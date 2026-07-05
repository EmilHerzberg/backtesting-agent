"""Gap 1: ResearchExecutor — wraps the backtesting engine for the research loop.

Translates between the research loop's spec dict and the engine's BacktestConfig.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Template registry — maps template_id to strategy class.
_TEMPLATE_REGISTRY: dict[str, type] = {}


def _ensure_registry() -> dict[str, type]:
    """Lazy-load strategy classes to avoid circular imports."""
    if _TEMPLATE_REGISTRY:
        return _TEMPLATE_REGISTRY

    from src.backend.backtesting.strategies.sma_crossover import SMACrossover
    from src.backend.backtesting.strategies.rsi_reversion import RSIMeanReversion
    from src.backend.backtesting.strategies.bollinger_breakout import BollingerBreakout
    from src.backend.backtesting.strategies.macd_cross import MACDSignalCross
    from src.backend.backtesting.strategies.multi_indicator import MultiIndicator

    _TEMPLATE_REGISTRY.update({
        "sma_crossover": SMACrossover,
        "rsi_reversion": RSIMeanReversion,
        "bollinger_breakout": BollingerBreakout,
        "macd_cross": MACDSignalCross,
        "multi_indicator": MultiIndicator,
    })
    return _TEMPLATE_REGISTRY


def _lagged_sharpe_annual(
    data: pd.DataFrame, trades: list, warmup_bars: int, sharpe_annual: float
) -> float | None:
    """M23 — Sharpe under +1 bar of execution lag (the LagFragilityGate's missing producer).

    Reconstructs the per-bar position the strategy actually held (from its trades), then re-derives the
    P&L with every fill delayed by one bar (position established one bar later: ``pos.shift(1)·ret``).
    The reconstructed base and lagged Sharpe share one estimator, so their RATIO is a clean
    execution-lag fragility measure; that ratio is mapped onto the reported (backtesting.py) Sharpe
    scale the gate compares against. Returns ``None`` when there is no reconstructable position (the
    gate then stays honestly provisional) — it never fabricates a pass. Cheap: no second backtest.
    """
    from src.backend.backtesting.engine.metrics import annualized_sharpe, periods_per_year

    try:
        if not trades or "Close" not in data.columns:
            return None
        idx = data.index[warmup_bars:] if warmup_bars > 0 else data.index
        close = (data["Close"].iloc[warmup_bars:] if warmup_bars > 0 else data["Close"]).to_numpy(dtype=np.float64)
        if len(idx) < 3 or len(close) != len(idx):
            return None

        ts = pd.DatetimeIndex(idx).values
        pos = np.zeros(len(idx), dtype=np.float64)
        for t in trades:
            side = 1.0 if str(getattr(t, "side", "long")).lower() == "long" else -1.0
            try:
                e = np.datetime64(pd.Timestamp(t.entry_time))
                x = np.datetime64(pd.Timestamp(t.exit_time))
            except Exception:
                continue
            pos[(ts >= e) & (ts < x)] = side        # position held on bars in [entry, exit)

        ret = np.diff(close) / close[:-1]            # ret[j] = return of bar j+1
        base_r = pos[1:] * ret                       # position held during bar j+1 earns its return
        lag_r = pos[:-1] * ret                       # one extra bar of execution delay
        ppy = periods_per_year(idx)
        base_s = annualized_sharpe(base_r, ppy)
        lag_s = annualized_sharpe(lag_r, ppy)
        if not np.isfinite(base_s) or abs(base_s) < 1e-9:
            return None                              # no reconstructable edge → provisional (honest)
        return float(sharpe_annual) * (lag_s / base_s)
    except Exception:
        return None


class ResearchExecutor:
    """Wraps the backtesting engine for the research loop.

    Converts spec dict → BacktestConfig → run_backtest() → metrics dict.
    """

    def __init__(self, cash: float = 10_000.0, commission: float = 0.001):
        self._cash = cash
        self._commission = commission

    def run(self, spec: dict[str, Any], data: pd.DataFrame, *, warmup_bars: int = 0) -> dict[str, Any]:
        """Execute a backtest and return a flat metrics dict.

        Args:
            spec: Strategy spec with template_id, params, etc.
            data: OHLCV DataFrame.
            warmup_bars: M26/C1 — number of leading rows that are a warm-up prefix (indicators
                converge on them, no trades open, and the reported metrics are windowed past them).
                Used for the short OOS / hold-out / decay slices so they aren't scored on cold
                indicators.

        Returns:
            Dict with sharpe_annual, total_return, max_drawdown, n_trades,
            exposure_time, buy_hold_return, returns (numpy array), etc.
        """
        from src.backend.backtesting.engine.runner import BacktestConfig, run_backtest

        template_id = spec.get("template_id", "")
        params = spec.get("params", {})

        registry = _ensure_registry()
        strategy_cls = registry.get(template_id)
        if strategy_cls is None:
            raise ValueError(f"Unknown template_id: {template_id!r}. Available: {sorted(registry.keys())}")

        # Create parameterized strategy subclass.
        parameterized = strategy_cls.create_with_params(**params)

        config = BacktestConfig(
            symbol=spec.get("security_id", "UNKNOWN"),
            strategy_class=parameterized,
            data=data,
            cash=self._cash,
            commission=self._commission,
            exclusive_orders=True,
            trade_on_close=False,
            warmup_bars=warmup_bars,
        )

        result = run_backtest(config)

        # Compute daily returns from equity curve for gates.
        returns = np.array([], dtype=np.float64)
        if result.equity_curve and len(result.equity_curve) > 1:
            eq = np.array(result.equity_curve, dtype=np.float64)
            returns = np.diff(eq) / eq[:-1]

        # Buy-and-hold benchmark metrics.
        bh_sharpe = 0.0
        bh_max_dd = 0.0
        if len(returns) > 1:
            # M6/C2: single benchmark source — compute_buy_hold uses the interval-aware, strategy-
            # matched Sharpe estimator (no ad-hoc ddof=0 * sqrt(252) duplicate). Window past warm-up.
            from src.backend.backtesting.benchmarks.buy_hold import compute_buy_hold
            bh_df = data.iloc[warmup_bars:] if warmup_bars > 0 else data
            _bh = compute_buy_hold(bh_df)
            bh_sharpe = _bh.annualized_sharpe
            bh_max_dd = _bh.max_drawdown

        # M23: produce the +1-bar lag-fragility Sharpe the LagFragilityGate needs (it silently
        # provisional-passed without it). Windowed past warm-up, same as the reported metrics.
        lagged_sharpe = _lagged_sharpe_annual(data, result.trades or [], warmup_bars, result.sharpe_ratio)

        return {
            "sharpe_annual": result.sharpe_ratio,
            "lagged_sharpe_annual": lagged_sharpe,   # M23 — None when unreconstructable (gate stays provisional)
            "total_return": result.total_return,
            "max_drawdown": -abs(result.max_drawdown),
            "n_trades": result.trade_count,
            "trade_returns": [t.pnl_pct / 100.0 for t in (result.trades or [])],  # smart-activity per-trade edge
            "exposure_time": result.exposure_time,
            "win_rate": result.win_rate,
            "profit_factor": result.profit_factor,
            "buy_hold_return": result.buy_hold_return,
            "buy_hold_sharpe": bh_sharpe,
            "buy_hold_max_drawdown": bh_max_dd,
            "returns": returns,
            "equity_curve": result.equity_curve,
            "strategy_hash": spec.get("strategy_hash", ""),
            "template_id": template_id,
            "params": params,
            "commission": self._commission,
            "ohlcv_df": data.iloc[warmup_bars:] if warmup_bars > 0 else data,
        }
