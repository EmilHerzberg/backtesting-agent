"""Walk-forward validation: optimize on train windows, evaluate on test windows."""

from __future__ import annotations

import logging
import math
import statistics
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover -- typing only
    from src.backend.backtesting.config.schema import EventGateConfig

# M11: the test/train overfitting ratio is only meaningful above a materially-positive train Sharpe.
_MIN_TRAIN_SHARPE_FOR_RATIO = 0.2

import numpy as np
import pandas as pd

from src.backend.marketdata.windows import rolling_windows
from src.backend.backtesting.engine.exceptions import BacktestError
from src.backend.backtesting.engine.optimizer import (
    OptimizationConfig,
    optimize,
)
from src.backend.backtesting.engine.runner import (
    BacktestConfig,
    BacktestResult,
    run_backtest,
)

logger = logging.getLogger(__name__)


@dataclass
class WalkForwardConfig:
    """Configuration for walk-forward validation.

    Attributes:
        strategy_class: A :class:`StrategyBase` subclass.
        data: Full OHLCV DataFrame spanning the entire validation period.
        train_size: Training window size (e.g. ``"12m"``, ``"1y"``).
        test_size: Test window size (e.g. ``"3m"``).
        step: Step between consecutive windows (e.g. ``"3m"``).
        n_trials_per_window: Optuna trials per training window.
        cash: Starting cash for each window.
        commission: Per-trade commission fraction.
        validation_threshold: Minimum test-window Sharpe ratio to count a
            window as "valid".
    """

    strategy_class: type
    data: pd.DataFrame
    train_size: str = "12m"
    test_size: str = "3m"
    step: str = "3m"
    n_trials_per_window: int = 50
    cash: float = 10_000.0
    commission: float = 0.001
    validation_threshold: float = 0.0
    # M10: forward the user's optuna settings to per-window optimization (was default composite/TPE only,
    # while windows were then SCORED on test Sharpe — an internal inconsistency).
    objective_metric: str = "composite"
    composite_weights: dict | None = None
    seed: int | None = None
    # F1 (QUANT-REVIEW): the real asset symbol + optional event-gate config, forwarded into BOTH the
    # per-window optimization and the out-of-sample test backtest so a YAML-configured gate is honoured
    # consistently across walk-forward (was inert — the inner configs were built without it).
    symbol: str = "WF"
    event_gate: "EventGateConfig | None" = None  # noqa: F821 -- forward ref (schema.EventGateConfig)


@dataclass
class WalkForwardWindow:
    """Results for a single walk-forward window.

    Attributes:
        window_index: Zero-based index of the window.
        train_start: First date in the training set.
        train_end: Last date in the training set.
        test_start: First date in the test set.
        test_end: Last date in the test set.
        best_params: Best parameters found during train-phase optimisation.
        train_result: Backtest result on the training data with best params.
        test_result: Backtest result on the out-of-sample test data.
        overfitting_score: ``test_sharpe / train_sharpe`` -- closer to 1.0
            means less over-fitting. M11: ``NaN`` when the train Sharpe is not
            materially positive (the ratio is meaningless there); such windows
            are excluded from the aggregate median.
        is_valid: Whether the test Sharpe exceeds the validation threshold.
    """

    window_index: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    best_params: dict
    train_result: BacktestResult
    test_result: BacktestResult
    overfitting_score: float
    is_valid: bool
    # R10 (valconf): the graded confidence tier + block-bootstrap Sharpe CI for this test window
    # (additive; `is_valid` now means "tier is strong/moderate" — a real frequency-aware significance
    # decision — instead of the old `test_sharpe > threshold`). Defaults keep direct constructors working.
    confidence_tier: str = ""
    ci_low: float | None = None
    ci_high: float | None = None


@dataclass
class WalkForwardResult:
    """Aggregated walk-forward validation result.

    Attributes:
        windows: Per-window results.
        avg_test_sharpe: Mean Sharpe ratio across all test windows.
        avg_overfitting_score: M11 — MEDIAN overfitting score across the *measurable* windows only
            (those with a materially-positive train Sharpe; degenerate-train windows are NaN and
            excluded). The ``avg_`` prefix is retained for backward-compat of the field name; the value
            is a median, not a mean.
        pct_valid_windows: Percentage of windows that passed validation.
        is_strategy_validated: ``True`` when more than 50% of windows pass.
        combined_equity: Concatenated equity curve from all test windows.
    """

    windows: list[WalkForwardWindow] = field(default_factory=list)
    avg_test_sharpe: float = 0.0
    avg_overfitting_score: float = 0.0
    pct_valid_windows: float = 0.0
    is_strategy_validated: bool = False
    combined_equity: list[float] = field(default_factory=list)
    crashed_windows: int = 0  # H6: windows that failed to optimise/evaluate — kept in the denominator


def _assess_window(train_result, test_result, train_df, test_df, *, seed):
    """R10 (valconf) — assess a test window's out-of-sample edge with the frequency-aware, graded
    confidence machinery instead of the old binary `test_sharpe > threshold`.

    A window is *valid* (``assessment.validates``) only when a real per-trade significance test clears the
    bar (tier strong/moderate) — the trade bar scales to the strategy's tempo × the test length, so a slow
    strategy isn't punished for being slow, and a lucky few-trade window can't certify. The H6 guarantee is
    preserved: a zero-trade window has no per-trade sample and ~0 in-market bars → tier ``inconclusive`` →
    not valid. Defensive ``getattr`` keeps it working with the partial result stubs some tests use.
    """
    from src.backend.backtesting.engine.confidence import (
        REGIME_FLOOR,
        VALIDATE_T,
        assess_confidence,
    )
    from src.backend.backtesting.engine.metrics import periods_per_year

    eq = np.asarray(getattr(test_result, "equity_curve", None) or [], dtype=np.float64)
    daily = (np.diff(eq) / eq[:-1]) if eq.size > 1 else np.array([], dtype=np.float64)
    idx = getattr(test_df, "index", None)
    ppy = periods_per_year(idx) if (idx is not None and len(idx) >= 2) else 252.0

    def _span_days(df) -> int:
        i = getattr(df, "index", None)
        return max((i[-1] - i[0]).days, 1) if (i is not None and len(i) >= 2) else 1

    trade_returns = [getattr(t, "pnl_pct", 0.0) / 100.0 for t in (getattr(test_result, "trades", None) or [])]
    return assess_confidence(
        train_trades=int(getattr(train_result, "trade_count", 0)),
        train_days=_span_days(train_df),
        holdout_days=_span_days(test_df),
        test_trades=int(getattr(test_result, "trade_count", 0)),
        trade_returns=trade_returns,
        daily_returns=daily,
        exposure_time=float(getattr(test_result, "exposure_time", 0.0) or 0.0),
        observed_sharpe=float(getattr(test_result, "sharpe_ratio", 0.0) or 0.0),
        ppy=ppy, t_star=VALIDATE_T, floor=REGIME_FLOOR, seed=int(seed or 0),
    )


def walk_forward_validate(config: WalkForwardConfig) -> WalkForwardResult:
    """Run walk-forward validation with per-window optimization.

    For each rolling window pair (train, test):
    1. Optimize the strategy on the training data.
    2. Evaluate the best parameters on the test data.
    3. Compute an overfitting score (``test_sharpe / train_sharpe``).

    Args:
        config: Walk-forward configuration.

    Returns:
        A :class:`WalkForwardResult` summarising all windows.
    """
    windows = rolling_windows(
        config.data,
        train_size=config.train_size,
        test_size=config.test_size,
        step=config.step,
    )

    if not windows:
        logger.warning("No walk-forward windows generated from the data.")
        return WalkForwardResult()

    wf_windows: list[WalkForwardWindow] = []
    combined_equity: list[float] = []
    crashed = 0  # H6: optimise/evaluate failures still count against the valid-window denominator

    for i, (train_df, test_df) in enumerate(windows):
        logger.info(
            "Walk-forward window %d/%d: train %s -> %s, test %s -> %s",
            i + 1,
            len(windows),
            train_df.index.min().date(),
            train_df.index.max().date(),
            test_df.index.min().date(),
            test_df.index.max().date(),
        )

        # ---- Optimize on training data -------------------------------- #
        opt_config = OptimizationConfig(
            strategy_class=config.strategy_class,
            data=train_df,
            n_trials=config.n_trials_per_window,
            cash=config.cash,
            commission=config.commission,
            objective_metric=config.objective_metric,     # M10: honor the user's optuna settings per window
            composite_weights=config.composite_weights,
            seed=config.seed,
            symbol=config.symbol,                          # F1: gate the per-window optimization too
            event_gate=config.event_gate,
        )

        try:
            opt_result = optimize(opt_config)
        except BacktestError as exc:
            logger.warning("Window %d optimisation failed: %s", i, exc)
            crashed += 1
            continue

        best_params = opt_result.best_params
        train_result = opt_result.best_result

        # ---- Evaluate on test data (C1: warm indicators on a prefix; trade only in-window) ---- #
        strategy_cls = config.strategy_class.create_with_params(**best_params)
        test_start = test_df.index[0]
        prefix = config.data.loc[config.data.index < test_start]
        # Warm-up length = the strategy's largest integer lookback (bounded by available prior data).
        max_lookback = int(max(
            (v for v in best_params.values() if isinstance(v, (int, float)) and v > 1),
            default=0,
        ))
        warmup_bars = min(max_lookback, len(prefix))
        eval_df = pd.concat([prefix.iloc[-warmup_bars:], test_df]) if warmup_bars > 0 else test_df
        test_bt_config = BacktestConfig(
            symbol=config.symbol,
            strategy_class=strategy_cls,
            data=eval_df,
            cash=config.cash,
            commission=config.commission,
            warmup_bars=warmup_bars,
            event_gate=config.event_gate,   # F1: honour the gate on the out-of-sample test too
        )

        try:
            test_result = run_backtest(test_bt_config)
        except BacktestError as exc:
            logger.warning("Window %d test evaluation failed: %s", i, exc)
            crashed += 1
            continue

        # ---- Overfitting score ---------------------------------------- #
        train_sharpe = train_result.sharpe_ratio or 0.0
        test_sharpe = test_result.sharpe_ratio if test_result.sharpe_ratio else 0.0

        # M11: the test/train ratio is only meaningful above a materially-positive train Sharpe. The old
        # 0.001 floor mapped a ~0 train Sharpe to ratio=300, and averaging made "closer to 1.0 = less
        # overfitting" meaningless. Non-measurable windows are NaN and excluded from the aggregate.
        if train_sharpe >= _MIN_TRAIN_SHARPE_FOR_RATIO:
            overfitting_score = test_sharpe / train_sharpe
        else:
            overfitting_score = float("nan")

        # R10: frequency-aware, graded validity (replaces `test_sharpe > threshold`).
        assess = _assess_window(train_result, test_result, train_df, test_df, seed=config.seed)

        wf_windows.append(
            WalkForwardWindow(
                window_index=i,
                train_start=str(train_df.index.min()),
                train_end=str(train_df.index.max()),
                test_start=str(test_df.index.min()),
                test_end=str(test_df.index.max()),
                best_params=best_params,
                train_result=train_result,
                test_result=test_result,
                overfitting_score=overfitting_score,
                is_valid=assess.validates,
                confidence_tier=assess.tier,
                ci_low=assess.ci_low,
                ci_high=assess.ci_high,
            )
        )

        # Append test equity to combined curve
        if test_result.equity_curve:
            combined_equity.extend(test_result.equity_curve)

    return _build_wf_result(wf_windows, combined_equity, crashed)


def _build_wf_result(
    windows: list[WalkForwardWindow],
    combined_equity: list[float],
    crashed_windows: int = 0,
) -> WalkForwardResult:
    """Aggregate per-window results into a :class:`WalkForwardResult`.

    H6: the valid-window percentage is over *attempted* windows (evaluated + crashed), so a run where
    most windows crashed and one passed does not report 100% valid.
    """
    total = len(windows) + crashed_windows
    if total == 0:
        return WalkForwardResult()

    test_sharpes = [w.test_result.sharpe_ratio for w in windows]
    # M11: aggregate only the MEASURABLE (finite) overfitting scores, and report the MEDIAN — robust to
    # the residual ratio outliers a mean would let a single weak-train window dominate.
    _finite_of = [w.overfitting_score for w in windows if math.isfinite(w.overfitting_score)]
    valid_count = sum(1 for w in windows if w.is_valid)
    pct_valid = (valid_count / total) * 100.0

    return WalkForwardResult(
        windows=windows,
        avg_test_sharpe=(sum(test_sharpes) / len(test_sharpes)) if test_sharpes else 0.0,
        avg_overfitting_score=(statistics.median(_finite_of) if _finite_of else 0.0),
        pct_valid_windows=pct_valid,
        is_strategy_validated=pct_valid > 50.0,
        combined_equity=combined_equity,
        crashed_windows=crashed_windows,
    )
