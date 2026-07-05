"""Core backtest runner -- thin wrapper around backtesting.py's Backtest class."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import pandas as pd
from backtesting import Backtest

from src.backend.backtesting.engine.exceptions import (
    BacktestError,
    InsufficientDataError,
    NoTradesError,
)
from src.backend.backtesting.engine.metrics import (
    TradeDetail,
    benchmark_sharpe,
    calculate_calmar,
    calculate_profit_factor,
    calculate_sortino,
    extract_trades,
    periods_per_year,
)

logger = logging.getLogger(__name__)

# Minimum number of rows required to run a backtest
_MIN_ROWS = 2


@dataclass
class BacktestConfig:
    """Configuration for a single backtest run.

    Attributes:
        symbol: Ticker symbol (used for labelling only).
        strategy_class: A ``backtesting.Strategy`` subclass.
        data: OHLCV DataFrame with DatetimeIndex and columns
            Open, High, Low, Close, Volume.
        cash: Starting cash.
        commission: Per-trade commission fraction (e.g. 0.001 = 0.1%).
        exclusive_orders: If ``True``, each new order cancels the previous one.
        trade_on_close: If ``True``, market orders fill at the current bar's
            close price instead of the next bar's open.
        raise_on_no_trades: If ``True``, raise :class:`NoTradesError` when the
            run produces zero trades. Default ``False`` to keep the optimizer
            and other batch callers from blowing up on no-signal trials —
            they want a result with trade_count=0 and a low score, not an
            exception. (ATS-188)
        seed: ATS-2004 — Optional RNG seed for stochastic strategies.  The
            built-in ``backtesting.py`` engine is deterministic given fixed
            input data, so this currently only feeds strategies that opt in
            via ``self.params.seed`` (none today, but kept for API stability).
    """

    symbol: str
    strategy_class: type
    data: pd.DataFrame
    cash: float = 10_000.0
    commission: float = 0.001
    exclusive_orders: bool = True
    trade_on_close: bool = False
    raise_on_no_trades: bool = False
    seed: int | None = None
    # ATS-2080 — optional Event-Gate consumer. ``None`` keeps the runner
    # behaviour-identical to pre-2080. When non-``None`` the runner
    # pre-loads gates for ``(symbol, data.index[0], data.index[-1])`` and
    # injects the resulting DataFrame onto the strategy instance via
    # ``strategy._gates_df`` so :meth:`StrategyBase._apply_event_gate` can
    # filter / size entry signals. See
    # :mod:`src.backend.backtesting.event_gate`.
    event_gate: "EventGateConfig | None" = None  # noqa: F821 -- forward ref
    # C1 (QUANT-REVIEW-2026-07-03) — warm-up prefix length. When > 0 the first ``warmup_bars`` rows
    # are a burn-in region: indicators converge on them, but the strategy is prevented from opening
    # positions until ``data.index[warmup_bars]`` (StrategyBase honours ``_trade_start``), and the
    # reported per-bar metrics are recomputed over the post-warm-up window so the flat burn-in does
    # not dilute them. Used by walk-forward / OOS / hold-out so a strategy isn't "validated" on cold,
    # unconverged indicators.
    warmup_bars: int = 0


# Forward-reference resolver (kept at module level so the dataclass annotation
# can stay a string literal — avoiding an import-cycle risk if EventGateConfig
# ever moves into a module that imports runner).
def _resolve_event_gate_forward_ref() -> None:  # pragma: no cover -- import shim
    from src.backend.backtesting.config.schema import EventGateConfig  # noqa: F401


@dataclass
class BacktestResult:
    """Structured result of a single backtest run.

    Contains core performance metrics, trade details, and the raw
    backtesting.py stats for advanced inspection.
    """

    # Core metrics
    total_return: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    sortino_ratio: float = 0.0
    win_rate: float = 0.0
    trade_count: int = 0
    profit_factor: float = 0.0
    calmar_ratio: float = 0.0

    # Additional
    equity_curve: list[float] = field(default_factory=list)
    trades: list[TradeDetail] = field(default_factory=list)
    buy_hold_return: float = 0.0
    exposure_time: float = 0.0

    # ATS-2080 — Event-Gate accounting. ``blocked_trades_count`` /
    # ``reduced_trades_count`` count per-bar gate decisions (one per
    # blocked or reduced entry signal). ``blocked_trades_log`` /
    # ``reduced_trades_log`` carry the per-event audit dicts produced by
    # :meth:`StrategyBase._apply_event_gate` — sufficient to reconstruct
    # which event drove each suppression. ``gate_opportunity_cost`` is
    # a placeholder for the ungated-vs-gated comparison (zero until the
    # external comparison runner fills it). ``gate_alpha`` is the inverse
    # — positive means gating helped, negative means it hurt.
    blocked_trades_count: int = 0
    reduced_trades_count: int = 0
    blocked_trades_log: list[dict] = field(default_factory=list)
    reduced_trades_log: list[dict] = field(default_factory=list)
    gate_opportunity_cost: float = 0.0
    gate_alpha: float = 0.0

    # ATS-1706 — strategy identity hash (from StrategyDefinition)
    strategy_hash: str | None = None

    # Raw backtesting.py stats (dict-ified pd.Series)
    raw_stats: dict = field(default_factory=dict)


def run_backtest(
    config: BacktestConfig,
    *,
    gates_df: pd.DataFrame | None = None,
    registry_session: "Session | None" = None,  # noqa: F821 — ATS-1714
    run_id: str | None = None,
) -> BacktestResult:
    """Run a single backtest and return structured results.

    Args:
        config: A :class:`BacktestConfig` describing the backtest.
        gates_df: ATS-2080 — optional pre-loaded gate DataFrame (schema
            per :func:`src.backend.backtesting.event_gate.load_gates_for_backtest`).
            When supplied, the runner SKIPS the async DB pre-load and uses
            this directly. Lets tests and async callers bypass
            :func:`_preload_gates_blocking` (which can't be called from
            inside a running event loop). Only consulted when
            ``config.event_gate`` is enabled — otherwise ignored.

    Returns:
        A :class:`BacktestResult` with extracted metrics.

    Raises:
        InvalidParameterError: If cash<=0 or commission<0 (ATS-188).
        InsufficientDataError: If the data has fewer than ``_MIN_ROWS`` rows.
        NoTradesError: If the run produces zero trades AND
            ``config.raise_on_no_trades`` is True (ATS-188).
        BacktestError: If backtesting.py raises an unexpected error.
    """
    # ATS-188 / E4-S1-T4 — runner-level parameter validation.
    # Strategies validate their own params via create_with_params(); here we
    # check the engine-level knobs that strategies have no say over.
    from src.backend.backtesting.engine.exceptions import InvalidParameterError
    if config.cash <= 0:
        raise InvalidParameterError(
            f"cash must be > 0 (got {config.cash})"
        )
    if config.commission < 0 or config.commission >= 1:
        raise InvalidParameterError(
            f"commission must be in [0, 1) (got {config.commission})"
        )

    if config.data is None or len(config.data) < _MIN_ROWS:
        row_count = 0 if config.data is None else len(config.data)
        raise InsufficientDataError(rows=row_count, minimum=_MIN_ROWS)

    # ATS-1714 — emit registry lifecycle events if a session is provided.
    _registry = None
    if registry_session is not None:
        try:
            from src.backend.backtesting.registry.event_registry import (
                EventType,
                TrialEventRegistry,
            )
            _registry = TrialEventRegistry(registry_session)
            if run_id:
                _registry.append_event(run_id, EventType.RUN_STARTED)
        except Exception:
            logger.debug("Registry event emission skipped (import or DB error)", exc_info=True)
            _registry = None

    # F-027 fix: validate OHLC for NaN BEFORE calling backtesting.py to avoid
    # cryptic library-internal crashes. Try to auto-fix simple gaps first.
    ohlc_cols = [c for c in ("Open", "High", "Low", "Close") if c in config.data.columns]
    nan_count = int(config.data[ohlc_cols].isna().sum().sum()) if ohlc_cols else 0
    if nan_count > 0:
        nan_per_col = config.data[ohlc_cols].isna().sum().to_dict()
        # Try to forward-fill, then drop remaining
        cleaned = config.data.copy()
        cleaned[ohlc_cols] = cleaned[ohlc_cols].ffill().bfill()
        remaining = int(cleaned[ohlc_cols].isna().sum().sum())
        if remaining > 0:
            raise BacktestError(
                f"OHLC-Daten enthalten {nan_count} NaN-Werte ({nan_per_col}) "
                "die nicht durch ffill/bfill fixierbar sind. Bitte mit "
                "src/backend/backtesting/data/quality.py auto_fix() vorbereiten "
                "oder den betroffenen Datenbereich vor dem Backtest entfernen."
            )
        logger.warning("F-027: Auto-filled %d NaN OHLC values via ffill/bfill", nan_count)
        # Use cleaned data downstream
        bt_data = cleaned
    else:
        bt_data = config.data

    # ATS-2080 — pre-load event-gate decisions (if configured) and attach
    # them to the strategy class so the strategy's ``next()`` can consult
    # the gate without paying for a DB round-trip per bar. The class-level
    # attribute assignment piggy-backs on backtesting.py's mechanism for
    # passing strategy parameters: parameters live as class attributes,
    # not instance attributes.
    strategy_class = config.strategy_class
    if config.event_gate is not None and getattr(config.event_gate, "enabled", False):
        # Prefer caller-supplied gates (tests / async contexts); otherwise
        # try the sync DB pre-load. Either way, an empty DataFrame is a
        # legitimate "no gates" answer — the strategy still runs.
        if gates_df is None:
            gates_df = _preload_gates_blocking(
                symbol=config.symbol,
                data=bt_data,
            )
        strategy_class._gates_df = gates_df  # type: ignore[attr-defined]
        strategy_class._event_gate_config = config.event_gate  # type: ignore[attr-defined]
        strategy_class._event_gate_symbol = config.symbol  # type: ignore[attr-defined]
    else:
        # Ensure stale state from a previous gated run doesn't leak into
        # an ungated one — defensive only; the same class object may be
        # reused across optimizer trials.
        strategy_class._gates_df = None  # type: ignore[attr-defined]
        strategy_class._event_gate_config = None  # type: ignore[attr-defined]
        strategy_class._event_gate_symbol = None  # type: ignore[attr-defined]

    # C1 — warm-up trade mask: suppress entries until the first post-warm-up bar so indicators
    # converge on the prefix without in-sample trades leaking into the evaluation window. Set on every
    # run (None when no warm-up) so a stale value can't leak across reused strategy classes.
    if config.warmup_bars > 0 and len(bt_data) > config.warmup_bars:
        strategy_class._trade_start = pd.Timestamp(bt_data.index[config.warmup_bars])  # type: ignore[attr-defined]
    else:
        strategy_class._trade_start = None  # type: ignore[attr-defined]

    try:
        bt = Backtest(
            bt_data,
            strategy_class,
            cash=config.cash,
            commission=config.commission,
            exclusive_orders=config.exclusive_orders,
            trade_on_close=config.trade_on_close,
            # H7 (QUANT-REVIEW-2026-07-03): close trades still open on the last bar so they are
            # included in # Trades / Win Rate / Profit Factor. Without this, a position held to the
            # end contributes its PnL to the equity/return but is dropped from every trade stat,
            # making trade_count inconsistent with total_return (and a fully-invested run report 0 trades).
            finalize_trades=True,
        )
        stats = bt.run()
    except Exception as exc:
        # ATS-1714 — record infrastructure failure.
        if _registry and run_id:
            try:
                from src.backend.backtesting.registry.event_registry import EventType
                _registry.append_event(run_id, EventType.RUN_FAILED_INFRA,
                                       f'{{"error": "{str(exc)[:200]}"}}')
                registry_session.commit()
            except Exception:
                pass
        raise BacktestError(f"Backtest execution failed: {exc}") from exc

    result = _parse_stats(stats)

    # C1/M3 — recompute per-bar metrics over the post-warm-up window only (the flat burn-in region
    # would otherwise dilute the Sharpe/Sortino and understate the window return/drawdown). Pass the
    # window DatetimeIndex so the reslice uses the interval-aware geometric estimator (P1-03/C2/M5).
    if config.warmup_bars > 0:
        result = _reslice_to_window(result, config.warmup_bars, bt_data.index)

    # ATS-1714 — record successful completion.
    if _registry and run_id:
        try:
            from src.backend.backtesting.registry.event_registry import EventType
            _registry.append_event(run_id, EventType.RUN_COMPLETED)
            registry_session.commit()
        except Exception:
            logger.debug("Registry RUN_COMPLETED event failed", exc_info=True)

    # ATS-1718 — auto-compute buy-and-hold benchmark for every run.
    try:
        from src.backend.backtesting.benchmarks.buy_hold import compute_buy_hold
        # C1 — benchmark the window, not the warm-up prefix, so strategy-vs-benchmark stays comparable.
        bh_data = bt_data.iloc[config.warmup_bars:] if config.warmup_bars > 0 else bt_data
        bh = compute_buy_hold(bh_data)
        result.buy_hold_return = bh.total_return
    except Exception:
        logger.debug("Buy-and-hold benchmark computation skipped", exc_info=True)

    # ATS-2080 — harvest event-gate logs from the strategy instance.
    # backtesting.py exposes the strategy instance on ``stats._strategy``.
    strategy_instance = stats.get("_strategy", None)
    if strategy_instance is not None:
        blocked = getattr(strategy_instance, "blocked_log", None) or []
        reduced = getattr(strategy_instance, "reduced_log", None) or []
        result.blocked_trades_log = list(blocked)
        result.reduced_trades_log = list(reduced)
        result.blocked_trades_count = len(blocked)
        result.reduced_trades_count = len(reduced)
    # ATS-188: opt-in zero-trade detection. Optimizers WANT trade_count=0
    # to be a valid (low-scoring) result; user-driven simulation runs may
    # prefer a hard error so the UI can show a clear "no trades" message.
    if config.raise_on_no_trades and result.trade_count == 0:
        raise NoTradesError(
            f"{config.symbol}/{config.strategy_class.__name__} produced 0 trades — "
            "the strategy never generated a signal in this date range. "
            "Try a wider window or different parameters."
        )
    return result


def _reslice_to_window(result: BacktestResult, warmup_bars: int, window_index=None) -> BacktestResult:
    """C1/M3 — recompute per-bar metrics over the post-warm-up window only.

    After a warm-up run (indicators converge on the prefix; ``StrategyBase`` suppresses entries until
    the window), the equity curve still carries a flat burn-in region that would dilute the per-bar
    Sharpe/Sortino and understate the window return/drawdown. Recompute those from the window slice.
    Trades are already window-only (entries were masked during the prefix), so trade-derived metrics
    (trade_count / win_rate / profit_factor) are left intact. P1-03/C2/M5: the windowed Sharpe uses the
    SAME geometric/compounded, interval-aware estimator (``benchmark_sharpe``) as the non-warm-up
    strategy Sharpe and the benchmark — not a separate arithmetic one — so all three stay on one scale.
    """
    eq_full = result.equity_curve
    if warmup_bars <= 0 or len(eq_full) <= warmup_bars + 2:
        return result
    win = eq_full[warmup_bars:]
    win_idx = window_index[warmup_bars:] if (window_index is not None and len(window_index) == len(eq_full)) else None
    eq = pd.Series(win, index=win_idx) if win_idx is not None else pd.Series(win, dtype=float).reset_index(drop=True)
    result.equity_curve = list(win)
    if eq.iloc[0] > 0:
        result.total_return = float(eq.iloc[-1] / eq.iloc[0] - 1.0)
    result.sharpe_ratio = benchmark_sharpe(eq)  # geometric, interval-aware — one scale with the benchmark
    ppy = periods_per_year(eq.index) if isinstance(eq.index, pd.DatetimeIndex) else 252.0
    run_max = eq.cummax()
    result.max_drawdown = float((1.0 - eq / run_max).max())
    result.sortino_ratio = calculate_sortino(eq, periods_per_year=ppy)
    # Keep Calmar consistent with the resliced window (was left on the full flat-diluted values).
    if isinstance(eq.index, pd.DatetimeIndex) and len(eq) >= 2:
        years = max((eq.index[-1] - eq.index[0]).days, 1) / 365.25
    else:
        years = len(eq) / ppy
    result.calmar_ratio = calculate_calmar(result.total_return, result.max_drawdown, years)
    return result


def _parse_stats(stats: pd.Series) -> BacktestResult:
    """Extract structured metrics from backtesting.py's stats Series.

    Args:
        stats: The ``pd.Series`` returned by ``Backtest.run()``.

    Returns:
        Populated :class:`BacktestResult`.
    """
    # --- Safe getters --------------------------------------------------- #
    def _get(key: str, default: float = 0.0) -> float:
        val = stats.get(key, default)
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return default
        return float(val)

    # --- Core metrics --------------------------------------------------- #
    # F-013 fix: backtesting.py liefert Return in PROZENT (z.B. 1.80 = 1.8%),
    # wir speichern ueberall als FRACTION (0.018) damit Frontend * 100 das
    # korrekte Prozent anzeigt. Vorher wurde 1.80 gespeichert und im UI
    # zu 180% multipliziert — reiner Unit-Bug.
    total_return = _get("Return [%]") / 100.0
    sharpe = _get("Sharpe Ratio")
    max_dd = abs(_get("Max. Drawdown [%]")) / 100.0  # fraction
    win_rate = _get("Win Rate [%]") / 100.0  # fraction
    trade_count = int(_get("# Trades"))
    buy_hold_return = _get("Buy & Hold Return [%]") / 100.0
    exposure_time = _get("Exposure Time [%]") / 100.0

    # --- Equity curve --------------------------------------------------- #
    equity_values: list[float] = []
    ppy = 252.0  # C2 — interval-aware annualization for the derived (Sortino) metrics
    try:
        eq_df: pd.DataFrame = stats["_equity_curve"]
        if eq_df is not None and "Equity" in eq_df.columns:
            equity_values = eq_df["Equity"].tolist()
            ppy = periods_per_year(eq_df.index)
    except (KeyError, TypeError):
        pass

    equity_series = pd.Series(equity_values) if equity_values else pd.Series(dtype=float)

    # --- Trades --------------------------------------------------------- #
    trade_details = extract_trades(stats)

    # --- Derived metrics ------------------------------------------------ #
    sortino = calculate_sortino(equity_series, periods_per_year=ppy)

    # Duration in years for Calmar
    try:
        eq_df = stats["_equity_curve"]
        if eq_df is not None and len(eq_df) >= 2:
            delta = eq_df.index[-1] - eq_df.index[0]
            years = delta.days / 365.25
        else:
            years = 0.0
    except Exception:
        years = 0.0

    calmar = calculate_calmar(total_return, max_dd, years)
    profit_factor = calculate_profit_factor(trade_details)

    # --- Raw stats dict ------------------------------------------------- #
    raw: dict = {}
    for key in stats.index:
        val = stats[key]
        # Skip non-serialisable objects (DataFrames, etc.)
        if isinstance(val, (int, float, str, bool, type(None))):
            raw[key] = val

    return BacktestResult(
        total_return=total_return,
        sharpe_ratio=sharpe,
        max_drawdown=max_dd,
        sortino_ratio=sortino,
        win_rate=win_rate,
        trade_count=trade_count,
        profit_factor=profit_factor,
        calmar_ratio=calmar,
        equity_curve=equity_values,
        trades=trade_details,
        buy_hold_return=buy_hold_return,
        exposure_time=exposure_time,
        raw_stats=raw,
    )


# --------------------------------------------------------------------------- #
# ATS-2080 — Event-Gate pre-loading helper
# --------------------------------------------------------------------------- #


def _preload_gates_blocking(
    symbol: str,
    data: pd.DataFrame,
) -> pd.DataFrame:
    """Synchronously pre-load event-gate rows for ``(symbol, date-range)``.

    :class:`BacktestConfig.event_gate` triggers the runner to attach a
    gate DataFrame to the strategy *before* :meth:`Backtest.run`. The
    underlying DB client is async (``EventDBClient``), but
    :func:`run_backtest` is intentionally sync — used from optimizers,
    CLI, and Jupyter notebooks where forcing an async event loop would
    surprise callers. We bridge with :func:`asyncio.run`.

    Tests / CI environments without an Event-Context DB are handled
    gracefully: any exception during DB setup or query is caught and
    logged, and an empty DataFrame is returned so the backtest still
    runs (gates simply never fire). This is the same conservative
    posture used elsewhere in the runner — never break a backtest on a
    missing optional dependency.

    Args:
        symbol: ticker symbol used to resolve ``assets.symbol``.
        data: OHLCV DataFrame — we read the first/last index to derive
            the date range for the gate query.

    Returns:
        A DataFrame with the columns documented in
        :func:`src.backend.backtesting.event_gate.load_gates_for_backtest`.
        Empty when no gates exist or when the DB is unreachable.
    """
    import asyncio

    from src.backend.backtesting.event_gate import (
        _empty_gates_df,
        load_gates_for_backtest,
    )

    try:
        start_ts = pd.Timestamp(data.index[0])
        end_ts = pd.Timestamp(data.index[-1])
        start_date = start_ts.date()
        end_date = end_ts.date()
    except (AttributeError, IndexError, ValueError):
        return _empty_gates_df()

    async def _load() -> pd.DataFrame:
        # Lazy import — keeps ``runner.py`` importable in environments
        # without the event-context package (e.g. some CI matrix cells).
        from src.backend.db.engine import async_session
        from src.backend.event_context import EventDBClient

        async with async_session() as session:
            client = EventDBClient(session)
            return await load_gates_for_backtest(
                client, symbol, start_date, end_date,
            )

    try:
        return asyncio.run(_load())
    except RuntimeError as exc:
        # Already inside an event loop (Jupyter, FastAPI test client) —
        # fall back to an empty df and warn. Callers that need gates in
        # an async context can call ``load_gates_for_backtest`` directly.
        logger.warning(
            "ATS-2080: cannot pre-load gates inside running event loop (%s) — "
            "backtest will run without gate filtering",
            exc,
        )
        return _empty_gates_df()
    except Exception as exc:  # noqa: BLE001 -- intentional broad catch
        logger.warning(
            "ATS-2080: event-gate pre-load failed (%s) — falling back to empty",
            exc,
        )
        return _empty_gates_df()
