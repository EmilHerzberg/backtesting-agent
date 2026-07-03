"""Tests for ATS-1717 — BuyHoldBenchmark computation."""

import math

import numpy as np
import pandas as pd
import pytest

from src.backend.backtesting.benchmarks.buy_hold import BenchmarkResult, compute_buy_hold


def _make_ohlcv(closes, start="2020-01-01"):
    """Build minimal OHLCV DataFrame from a list of Close prices."""
    n = len(closes)
    idx = pd.date_range(start, periods=n, freq="B")
    return pd.DataFrame(
        {
            "Open": closes,
            "High": [c * 1.01 for c in closes],
            "Low": [c * 0.99 for c in closes],
            "Close": closes,
            "Volume": [10000] * n,
        },
        index=idx,
    )


class TestBuyHoldBenchmark:
    def test_known_values(self):
        """100 → 110 over 100 days = 10% return."""
        closes = [100 + i * 0.1 for i in range(101)]  # 100 to 110
        df = _make_ohlcv(closes)
        result = compute_buy_hold(df)

        assert isinstance(result, BenchmarkResult)
        assert abs(result.total_return - 0.10) < 0.001
        assert result.annualized_sharpe > 0  # uptrend → positive Sharpe
        assert result.max_drawdown <= 0  # drawdown is always <= 0

    def test_flat_prices(self):
        """All Close = 100 → return 0, Sharpe 0, DD 0."""
        df = _make_ohlcv([100.0] * 50)
        result = compute_buy_hold(df)

        assert result.total_return == 0.0
        assert result.annualized_sharpe == 0.0
        assert result.max_drawdown == 0.0

    def test_single_row(self):
        """1 bar → return 0, empty returns array."""
        df = _make_ohlcv([100.0])
        result = compute_buy_hold(df)

        assert result.total_return == 0.0
        assert len(result.daily_returns) == 0

    def test_downtrend(self):
        """Prices decline → negative return, negative Sharpe."""
        closes = [100 - i * 0.5 for i in range(50)]  # 100 to 75.5
        df = _make_ohlcv(closes)
        result = compute_buy_hold(df)

        assert result.total_return < 0
        assert result.annualized_sharpe < 0
        assert result.max_drawdown < 0

    def test_daily_returns_length(self):
        """N close prices → N-1 daily returns."""
        df = _make_ohlcv([100, 101, 102, 103, 104])
        result = compute_buy_hold(df)
        assert len(result.daily_returns) == 4

    def test_with_nan(self):
        """NaN in Close is dropped, doesn't crash."""
        closes = [100.0, 101.0, float("nan"), 103.0, 104.0]
        df = _make_ohlcv(closes)
        result = compute_buy_hold(df)
        assert not math.isnan(result.total_return)

    def test_max_drawdown_value(self):
        """V-shape: 100 → 80 → 100. DD should be ~-20%."""
        closes = list(range(100, 80, -1)) + list(range(80, 101))
        df = _make_ohlcv(closes)
        result = compute_buy_hold(df)

        assert result.max_drawdown < -0.15  # at least 15% drawdown
        assert result.total_return == pytest.approx(0.0, abs=0.01)  # back to 100
