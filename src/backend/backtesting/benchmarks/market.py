"""ATS-1719 — Market benchmark (SPY) comparison.

Fetches SPY data for the same window and computes alpha/beta via OLS regression.
Graceful fallback if data unavailable.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MarketBenchmarkResult:
    """Market benchmark comparison metrics."""

    market_return: float | None = None
    market_sharpe: float | None = None
    alpha_vs_market: float | None = None
    beta_vs_market: float | None = None
    alpha_vs_asset: float | None = None
    beta_vs_asset: float | None = None
    residual_sharpe: float | None = None
    available: bool = False


def compute_alpha_beta(
    strategy_returns: np.ndarray,
    benchmark_returns: np.ndarray,
) -> tuple[float, float]:
    """OLS regression: strategy = alpha + beta * benchmark.

    Returns (alpha, beta). Both per-period (daily).
    """
    if len(strategy_returns) != len(benchmark_returns):
        n = min(len(strategy_returns), len(benchmark_returns))
        strategy_returns = strategy_returns[:n]
        benchmark_returns = benchmark_returns[:n]

    if len(strategy_returns) < 10:
        return 0.0, 0.0

    # OLS via normal equations: beta = cov(s,b)/var(b), alpha = mean(s) - beta*mean(b)
    cov = np.cov(strategy_returns, benchmark_returns)
    var_b = cov[1, 1]
    if var_b == 0:
        return 0.0, 0.0

    beta = float(cov[0, 1] / var_b)
    alpha = float(np.mean(strategy_returns) - beta * np.mean(benchmark_returns))
    return alpha, beta


def compute_market_benchmark(
    strategy_returns: np.ndarray,
    asset_returns: np.ndarray,
    market_returns: np.ndarray | None = None,
) -> MarketBenchmarkResult:
    """Compute market benchmark metrics.

    Args:
        strategy_returns: Per-bar strategy returns.
        asset_returns: Per-bar buy-and-hold asset returns.
        market_returns: Per-bar market (SPY) returns, or None if unavailable.

    Returns:
        MarketBenchmarkResult with alpha/beta vs asset and market.
    """
    # Alpha/beta vs the traded asset (always available).
    alpha_asset, beta_asset = compute_alpha_beta(strategy_returns, asset_returns)

    # Residual Sharpe: Sharpe of the residual (strategy - beta * asset).
    n = min(len(strategy_returns), len(asset_returns))
    residuals = strategy_returns[:n] - beta_asset * asset_returns[:n]
    residual_std = np.std(residuals, ddof=1) if len(residuals) > 1 else 0
    residual_sharpe = float(np.mean(residuals) / residual_std * math.sqrt(252)) if residual_std > 0 else 0.0

    if market_returns is None or len(market_returns) == 0:
        return MarketBenchmarkResult(
            alpha_vs_asset=alpha_asset,
            beta_vs_asset=beta_asset,
            residual_sharpe=residual_sharpe,
            available=False,
        )

    # Market metrics.
    market_total = float(np.prod(1 + market_returns) - 1) if len(market_returns) > 0 else 0.0
    market_std = np.std(market_returns, ddof=1) if len(market_returns) > 1 else 0
    market_sharpe = float(np.mean(market_returns) / market_std * math.sqrt(252)) if market_std > 0 else 0.0

    alpha_market, beta_market = compute_alpha_beta(strategy_returns, market_returns)

    return MarketBenchmarkResult(
        market_return=market_total,
        market_sharpe=market_sharpe,
        alpha_vs_market=alpha_market,
        beta_vs_market=beta_market,
        alpha_vs_asset=alpha_asset,
        beta_vs_asset=beta_asset,
        residual_sharpe=residual_sharpe,
        available=True,
    )
