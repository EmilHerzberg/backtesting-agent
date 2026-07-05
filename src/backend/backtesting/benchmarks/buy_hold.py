"""ATS-1717 — Buy-and-hold benchmark computation.

Given OHLCV data, compute what a simple buy-and-hold of the same asset
over the same window would have returned.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class BenchmarkResult:
    """Metrics for a buy-and-hold benchmark."""

    total_return: float
    annualized_sharpe: float
    max_drawdown: float
    daily_returns: np.ndarray


def compute_buy_hold(df: pd.DataFrame) -> BenchmarkResult:
    """Compute buy-and-hold metrics from an OHLCV DataFrame.

    Uses the Close column.  Assumes the DataFrame index is a
    DatetimeIndex sorted chronologically.

    Args:
        df: OHLCV DataFrame with at least a 'Close' column.

    Returns:
        BenchmarkResult with total return, Sharpe, max drawdown, and
        the daily returns series.
    """
    close = df["Close"].dropna()

    if len(close) < 2:
        return BenchmarkResult(
            total_return=0.0,
            annualized_sharpe=0.0,
            max_drawdown=0.0,
            daily_returns=np.array([], dtype=np.float64),
        )

    # Daily simple returns.
    returns = close.pct_change().dropna().to_numpy(dtype=np.float64)

    # Total return.
    total_return = float(close.iloc[-1] / close.iloc[0] - 1)

    # C2/M5/M6: annualized Sharpe computed the same way (interval-aware, geometric/compounded) that
    # backtesting.py computes the strategy Sharpe, so the two are comparable in the benchmark gate.
    from src.backend.backtesting.engine.metrics import benchmark_sharpe

    annualized_sharpe = benchmark_sharpe(close)

    # Max drawdown.
    cum = (1 + pd.Series(returns)).cumprod()
    running_max = cum.cummax()
    drawdowns = (cum - running_max) / running_max
    max_drawdown = float(drawdowns.min()) if len(drawdowns) > 0 else 0.0

    return BenchmarkResult(
        total_return=total_return,
        annualized_sharpe=annualized_sharpe,
        max_drawdown=max_drawdown,
        daily_returns=returns,
    )
