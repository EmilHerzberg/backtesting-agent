"""Cost sensitivity analysis — test strategy robustness against varying transaction costs."""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

from backtesting_agent.engine.runner import BacktestConfig, BacktestResult, run_backtest

logger = logging.getLogger(__name__)


@dataclass
class CostTierResult:
    multiplier: float
    commission: float
    sharpe_ratio: float | None
    total_return: float | None
    max_drawdown: float | None
    trade_count: int | None
    profit_factor: float | None


@dataclass
class CostSensitivityReport:
    trial_strategy: str
    trial_symbol: str
    base_commission: float
    tiers: list[CostTierResult]
    breakeven_multiplier: float | None  # At what cost multiplier does sharpe drop below 0?
    robust: bool  # Still profitable at 2x costs?


def _safe(v: float | None) -> float | None:
    if v is None:
        return None
    if isinstance(v, float) and (math.isinf(v) or math.isnan(v)):
        return None
    return round(v, 4)


def run_cost_sweep(
    strategy_class: type,
    data,
    symbol: str = "",
    base_commission: float = 0.001,
    cash: float = 10_000.0,
    multipliers: list[float] | None = None,
) -> CostSensitivityReport:
    """Run a backtest at multiple cost tiers and analyze robustness.

    Args:
        strategy_class: Strategy class for backtesting.py
        data: OHLCV DataFrame
        symbol: Ticker symbol (for labeling)
        base_commission: Base commission rate (default 0.1%)
        cash: Starting capital
        multipliers: Cost multipliers to test (default: [0.5, 1.0, 1.5, 2.0, 3.0, 5.0])

    Returns:
        CostSensitivityReport with results per tier and breakeven analysis.
    """
    if multipliers is None:
        multipliers = [0.5, 1.0, 1.5, 2.0, 3.0, 5.0]

    tiers: list[CostTierResult] = []
    breakeven: float | None = None

    for mult in sorted(multipliers):
        commission = base_commission * mult
        try:
            config = BacktestConfig(
                symbol=symbol,
                strategy_class=strategy_class,
                data=data,
                cash=cash,
                commission=commission,
            )
            result = run_backtest(config)
            tier = CostTierResult(
                multiplier=mult,
                commission=round(commission, 6),
                sharpe_ratio=_safe(result.sharpe_ratio),
                total_return=_safe(result.total_return),
                max_drawdown=_safe(result.max_drawdown),
                trade_count=result.trade_count,
                profit_factor=_safe(result.profit_factor),
            )
            tiers.append(tier)

            # Track breakeven
            if breakeven is None and tier.sharpe_ratio is not None and tier.sharpe_ratio <= 0:
                breakeven = mult
        except Exception as exc:
            logger.warning("Cost sweep failed at %sx: %s", mult, exc)
            tiers.append(CostTierResult(
                multiplier=mult, commission=round(commission, 6),
                sharpe_ratio=None, total_return=None, max_drawdown=None,
                trade_count=None, profit_factor=None,
            ))

    # Check if robust at 2x costs
    tier_2x = next((t for t in tiers if t.multiplier == 2.0), None)
    robust = tier_2x is not None and tier_2x.sharpe_ratio is not None and tier_2x.sharpe_ratio > 0

    strategy_name = getattr(strategy_class, "__name__", str(strategy_class))

    return CostSensitivityReport(
        trial_strategy=strategy_name,
        trial_symbol=symbol,
        base_commission=base_commission,
        tiers=tiers,
        breakeven_multiplier=breakeven,
        robust=robust,
    )
