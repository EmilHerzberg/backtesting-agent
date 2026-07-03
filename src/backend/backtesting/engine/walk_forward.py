"""Walk-forward validation: optimize on train windows, evaluate on test windows."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

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
            means less over-fitting.
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


@dataclass
class WalkForwardResult:
    """Aggregated walk-forward validation result.

    Attributes:
        windows: Per-window results.
        avg_test_sharpe: Mean Sharpe ratio across all test windows.
        avg_overfitting_score: Mean overfitting score across windows.
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
        )

        try:
            opt_result = optimize(opt_config)
        except BacktestError as exc:
            logger.warning("Window %d optimisation failed: %s", i, exc)
            continue

        best_params = opt_result.best_params
        train_result = opt_result.best_result

        # ---- Evaluate on test data ------------------------------------ #
        strategy_cls = config.strategy_class.create_with_params(**best_params)
        test_bt_config = BacktestConfig(
            symbol="WF",
            strategy_class=strategy_cls,
            data=test_df,
            cash=config.cash,
            commission=config.commission,
        )

        try:
            test_result = run_backtest(test_bt_config)
        except BacktestError as exc:
            logger.warning("Window %d test evaluation failed: %s", i, exc)
            continue

        # ---- Overfitting score ---------------------------------------- #
        train_sharpe = train_result.sharpe_ratio if train_result.sharpe_ratio else 0.001
        test_sharpe = test_result.sharpe_ratio if test_result.sharpe_ratio else 0.0

        if train_sharpe > 0:
            overfitting_score = test_sharpe / train_sharpe
        else:
            overfitting_score = 0.0

        is_valid = test_sharpe >= config.validation_threshold

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
                is_valid=is_valid,
            )
        )

        # Append test equity to combined curve
        if test_result.equity_curve:
            combined_equity.extend(test_result.equity_curve)

    return _build_wf_result(wf_windows, combined_equity)


def _build_wf_result(
    windows: list[WalkForwardWindow],
    combined_equity: list[float],
) -> WalkForwardResult:
    """Aggregate per-window results into a :class:`WalkForwardResult`."""
    if not windows:
        return WalkForwardResult()

    test_sharpes = [w.test_result.sharpe_ratio for w in windows]
    overfitting_scores = [w.overfitting_score for w in windows]
    valid_count = sum(1 for w in windows if w.is_valid)
    pct_valid = (valid_count / len(windows)) * 100.0

    return WalkForwardResult(
        windows=windows,
        avg_test_sharpe=sum(test_sharpes) / len(test_sharpes),
        avg_overfitting_score=sum(overfitting_scores) / len(overfitting_scores),
        pct_valid_windows=pct_valid,
        is_strategy_validated=pct_valid > 50.0,
        combined_equity=combined_equity,
    )
