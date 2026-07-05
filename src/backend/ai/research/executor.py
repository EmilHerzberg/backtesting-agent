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
            # M26/C1 — benchmark the window, not the warm-up prefix, so strategy-vs-benchmark matches.
            close = data["Close"].values[warmup_bars:] if warmup_bars > 0 else data["Close"].values
            bh_returns = np.diff(close) / close[:-1]
            if len(bh_returns) > 0 and bh_returns.std() > 0:
                bh_sharpe = float(bh_returns.mean() / bh_returns.std() * np.sqrt(252))
                bh_cummax = np.maximum.accumulate(np.cumprod(1 + bh_returns))
                bh_drawdowns = (np.cumprod(1 + bh_returns) - bh_cummax) / bh_cummax
                bh_max_dd = float(bh_drawdowns.min()) if len(bh_drawdowns) > 0 else 0.0

        return {
            "sharpe_annual": result.sharpe_ratio,
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
