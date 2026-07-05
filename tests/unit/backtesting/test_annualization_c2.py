"""1C — interval-aware annualization (C2) + benchmark Sharpe matched to the strategy estimator (M5/M6).

Review C2: every benchmark/residual/market/buy-hold Sharpe hardcoded sqrt(252) regardless of bar
interval, so weekly/hourly benchmarks were inflated ~2.2x and the gate compared an interval-aware
strategy Sharpe against an interval-blind benchmark. M5/M6: the benchmark used a different estimator
(arithmetic, ddof=0) than the strategy (backtesting.py geometric/compounded).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.backend.backtesting.benchmarks.buy_hold import compute_buy_hold
from src.backend.backtesting.engine.metrics import benchmark_sharpe, periods_per_year
from src.backend.backtesting.engine.runner import BacktestConfig, run_backtest
from src.backend.backtesting.strategies.base import StrategyBase
from tests.support.frozen_data import make_ohlcv


@pytest.mark.finding("C2")
def test_periods_per_year_is_interval_aware():
    assert periods_per_year(make_ohlcv(days=300, seed=1).index) == 252.0       # business-day equity
    assert periods_per_year(pd.date_range("2015-01-01", periods=200, freq="W")) == 52.0
    assert periods_per_year(pd.date_range("2010-01-01", periods=120, freq="ME")) == 12.0
    assert periods_per_year(pd.date_range("2020-01-01", periods=300, freq="D")) == 365.0  # has weekends


@pytest.mark.finding("C2")
def test_weekly_benchmark_uses_weekly_factor_not_252():
    from src.backend.backtesting.engine.metrics import _geometric_mean

    widx = pd.date_range("2015-01-01", periods=250, freq="W")
    rets = np.random.default_rng(0).normal(0.001, 0.02, 250)
    close = pd.Series(100.0 * np.cumprod(1.0 + rets), index=widx)

    got = benchmark_sharpe(close)

    def _compounded(ann: float) -> float:
        dr = close.pct_change().dropna()
        g = _geometric_mean(dr.to_numpy())
        ret = (1 + g) ** ann - 1
        vol_sq = (dr.var(ddof=1) + (1 + g) ** 2) ** ann - (1 + g) ** (2 * ann)
        return ret / np.sqrt(vol_sq) if vol_sq > 0 else 0.0

    # The benchmark used the WEEKLY factor (52), not the daily 252 the old code hardcoded.
    assert got == pytest.approx(_compounded(52.0), rel=1e-6)
    assert got != pytest.approx(_compounded(252.0), rel=1e-3)


class _BuyHold(StrategyBase):
    def init(self) -> None:
        pass

    def next(self) -> None:
        if not self.position:
            self.buy()

    @classmethod
    def parameter_space(cls):
        return {}


@pytest.mark.finding("M5")
@pytest.mark.finding("M6")
def test_benchmark_sharpe_matches_strategy_estimator_scale():
    """A buy-and-hold strategy's backtesting.py Sharpe and the benchmark Sharpe are on the same scale
    (both geometric/compounded, interval-aware) — not off by a sqrt(252/ppy) or ddof mismatch.
    P1-06: tight tolerance so the pre-fix arithmetic-ddof0 estimator (~0.13 off here) would fail."""
    data = make_ohlcv(days=400, seed=2, drift=0.0006)
    res = run_backtest(BacktestConfig(symbol="T", strategy_class=_BuyHold, data=data, commission=0.0))
    bh = compute_buy_hold(data)
    assert res.sharpe_ratio == pytest.approx(bh.annualized_sharpe, abs=0.05)


@pytest.mark.finding("L17")
def test_market_benchmark_annualizes_by_interval():
    """P1-07/L17: compute_market_benchmark scales alpha and residual/market Sharpe by the interval
    factor, not a hardcoded 252. (NB: this helper is currently unwired — see M19; kept tested.)"""
    from src.backend.backtesting.benchmarks.market import compute_market_benchmark

    rng = np.random.default_rng(0)
    strat = rng.normal(0.001, 0.01, 200)
    asset = rng.normal(0.0008, 0.01, 200)
    daily = compute_market_benchmark(strat, asset, periods_per_year=252)
    weekly = compute_market_benchmark(strat, asset, periods_per_year=52)
    assert weekly.residual_sharpe == pytest.approx(daily.residual_sharpe * (52 / 252) ** 0.5, rel=1e-6)
    assert weekly.alpha_vs_asset == pytest.approx(daily.alpha_vs_asset * (52 / 252), rel=1e-6)


@pytest.mark.finding("M6")
def test_executor_benchmark_sharpe_is_single_source():
    from src.backend.ai.research.executor import ResearchExecutor

    data = make_ohlcv(days=300, seed=3)
    spec = {"template_id": "sma_crossover", "params": {"fast_period": 5, "slow_period": 20}, "security_id": "T"}
    m = ResearchExecutor().run(spec, data)
    # The executor's buy_hold_sharpe comes from compute_buy_hold (one source), not an ad-hoc formula.
    assert m["buy_hold_sharpe"] == pytest.approx(compute_buy_hold(data).annualized_sharpe)
