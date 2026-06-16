"""Metrics extraction and calculation for backtest results."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class TradeDetail:
    """Detailed information about a single trade."""

    entry_time: str
    exit_time: str
    side: str  # "long" or "short"
    entry_price: float
    exit_price: float
    size: float
    pnl: float
    pnl_pct: float
    duration: str


def extract_trades(stats: pd.Series) -> list[TradeDetail]:
    """Extract individual trades from backtesting.py stats._trades DataFrame.

    Args:
        stats: The ``pd.Series`` returned by ``Backtest.run()``.

    Returns:
        List of :class:`TradeDetail` objects.  Returns an empty list when
        the stats object contains no trade data.
    """
    try:
        trades_df: pd.DataFrame = stats["_trades"]
    except (KeyError, TypeError):
        return []

    if trades_df is None or trades_df.empty:
        return []

    details: list[TradeDetail] = []
    for _, row in trades_df.iterrows():
        entry_time = str(row.get("EntryTime", ""))
        exit_time = str(row.get("ExitTime", ""))
        size = float(row.get("Size", 0))
        side = "long" if size > 0 else "short"
        entry_price = float(row.get("EntryPrice", 0.0))
        exit_price = float(row.get("ExitPrice", 0.0))
        pnl = float(row.get("PnL", 0.0))

        # PnL percentage relative to entry value
        entry_value = abs(size) * entry_price
        pnl_pct = (pnl / entry_value * 100) if entry_value != 0 else 0.0

        # Duration
        try:
            dur = pd.Timestamp(exit_time) - pd.Timestamp(entry_time)
            duration = str(dur)
        except Exception:
            duration = ""

        details.append(
            TradeDetail(
                entry_time=entry_time,
                exit_time=exit_time,
                side=side,
                entry_price=entry_price,
                exit_price=exit_price,
                size=abs(size),
                pnl=pnl,
                pnl_pct=pnl_pct,
                duration=duration,
            )
        )

    return details


def calculate_sortino(
    equity_curve: pd.Series,
    risk_free_rate: float = 0.0,
    periods_per_year: float = 252.0,
) -> float:
    """Calculate the annualised Sortino ratio from an equity curve.

    Args:
        equity_curve: Series of portfolio equity values over time.
        risk_free_rate: Annualised risk-free rate (default 0).
        periods_per_year: Trading periods per year (252 for daily).

    Returns:
        Sortino ratio, or 0.0 when it cannot be computed.
    """
    if equity_curve is None or len(equity_curve) < 2:
        return 0.0

    returns = equity_curve.pct_change().dropna()
    if returns.empty:
        return 0.0

    excess = returns - risk_free_rate / periods_per_year
    mean_excess = float(excess.mean())

    # Downside deviation: std of negative returns only
    downside = returns[returns < 0]
    if downside.empty or downside.std() == 0:
        return 0.0 if mean_excess <= 0 else 999.99

    downside_std = float(downside.std())
    annualised_return = mean_excess * periods_per_year
    annualised_downside = downside_std * math.sqrt(periods_per_year)

    if annualised_downside == 0:
        return 0.0

    return annualised_return / annualised_downside


def calculate_calmar(
    total_return_pct: float,
    max_drawdown_pct: float,
    years: float,
) -> float:
    """Calculate the Calmar ratio.

    Args:
        total_return_pct: Total return as a percentage (e.g. 25.0 for 25%).
        max_drawdown_pct: Maximum drawdown as a positive percentage (e.g. 10.0).
        years: Duration of the backtest in years.

    Returns:
        Calmar ratio, or 0.0 when it cannot be computed.
    """
    if years <= 0 or max_drawdown_pct == 0:
        return 0.0

    annualised_return = total_return_pct / years
    return annualised_return / abs(max_drawdown_pct)


def calculate_profit_factor(trades: list[TradeDetail]) -> float:
    """Compute profit factor: gross profits / gross losses.

    Args:
        trades: List of :class:`TradeDetail` objects.

    Returns:
        Profit factor (>1 means profitable). Returns ``float('inf')`` when
        there are no losing trades, or 0.0 when there are no trades.
    """
    if not trades:
        return 0.0

    gross_profit = sum(t.pnl for t in trades if t.pnl > 0)
    gross_loss = abs(sum(t.pnl for t in trades if t.pnl < 0))

    if gross_loss == 0:
        return 999.99 if gross_profit > 0 else 0.0

    return gross_profit / gross_loss
