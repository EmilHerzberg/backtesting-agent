"""ATS-1746/1749 + H8/M22 — Leakage test suite: reference strategies vs the canary gate.

CI regression guard: if this test breaks, a refactor introduced look-ahead. H8: the positive control
(`LeakyFuturePeek`) genuinely leaks (peeks at the next bar via shift(-1)), so the canary's ability to
detect leakage is actually exercised — the old `LeakyClosePeek` filled next-open and did not leak, and
the discrimination test asserted nothing.
"""

from __future__ import annotations

import inspect

import numpy as np
import pandas as pd
import pytest
from backtesting import Backtest

from src.backend.backtesting.gates.canary import LeakageCanaryGate
from src.backend.backtesting.gates.pipeline import GateContext, GateStatus
from src.backend.backtesting.strategies.reference.clean_sma import CleanSMACross
from src.backend.backtesting.strategies.reference.leaky_future_peek import LeakyFuturePeek


def _make_trending_ohlcv(n=500, seed=42):
    """Create OHLCV data with a mild uptrend for meaningful strategy signals."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2018-01-01", periods=n, freq="B")
    returns = rng.normal(0.0003, 0.015, n)
    close = 100 * np.exp(np.cumsum(returns))
    high = close * (1 + np.abs(rng.normal(0, 0.005, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.005, n)))
    open_ = np.roll(close, 1) * (1 + rng.normal(0, 0.002, n))
    open_[0] = close[0]
    return pd.DataFrame({
        "Open": open_,
        "High": np.maximum(high, np.maximum(open_, close)),
        "Low": np.minimum(low, np.minimum(open_, close)),
        "Close": close,
        "Volume": rng.integers(100000, 1000000, n),
    }, index=idx)


def _run_strategy_returns(strategy_class, data):
    """Run a strategy and extract per-bar returns."""
    bt = Backtest(data, strategy_class, cash=10000, commission=0.001, finalize_trades=True)
    stats = bt.run()
    eq = stats["_equity_curve"]["Equity"]
    returns = eq.pct_change().dropna().values
    return returns, stats


def _run_fn(strategy_cls):
    def run(df):
        r, _ = _run_strategy_returns(strategy_cls, df)
        return r
    return run


class TestLeakyStrategy:
    def test_leaky_strategy_runs_and_trades(self):
        data = _make_trending_ohlcv()
        returns, stats = _run_strategy_returns(LeakyFuturePeek, data)
        assert len(returns) > 0
        assert int(stats.get("# Trades", 0)) > 0

    @pytest.mark.finding("H8")
    def test_leaky_actually_peeks_at_the_future(self):
        # The genuine leak is a shift(-1) indicator (tomorrow's bar known today), not a same-bar close read.
        source = inspect.getsource(LeakyFuturePeek.init)
        assert "shift(-1)" in source


class TestCleanStrategy:
    def test_clean_strategy_runs(self):
        data = _make_trending_ohlcv()
        returns, _ = _run_strategy_returns(CleanSMACross, data)
        assert len(returns) > 0

    def test_clean_uses_only_indicators(self):
        source = inspect.getsource(CleanSMACross.next)
        assert "self.fast" in source and "self.slow" in source


class TestCanaryDiscrimination:
    """H8/M22 — the canary must FAIL the genuinely-leaky control and clear the clean one."""

    @pytest.mark.finding("H8")
    def test_canary_catches_the_leaky_control_and_clears_clean(self):
        real = _make_trending_ohlcv(300, seed=99)
        leaky_real, _ = _run_strategy_returns(LeakyFuturePeek, real)
        clean_real, _ = _run_strategy_returns(CleanSMACross, real)

        r_leaky = LeakageCanaryGate(run_strategy_fn=_run_fn(LeakyFuturePeek), n_paths=25).check(
            GateContext(metrics={"ohlcv_df": real}, trades=[], returns=leaky_real, equity_curve=[]))
        r_clean = LeakageCanaryGate(run_strategy_fn=_run_fn(CleanSMACross), n_paths=25).check(
            GateContext(metrics={"ohlcv_df": real}, trades=[], returns=clean_real, equity_curve=[]))

        # The leaky control profits on PURE NOISE → the canary FAILs it (the positive control now leaks).
        assert r_leaky.status == GateStatus.FAIL
        assert r_leaky.details["noise_mean_sr"] > 0.02
        # The clean control has no edge on noise → its noise distribution is ~centered at zero.
        assert r_clean.details["noise_mean_sr"] < r_leaky.details["noise_mean_sr"] / 2

    @pytest.mark.finding("M22")
    def test_canary_is_provisional_without_a_run_fn(self):
        # M22 wiring: with no run function (gate inert until the loop supplies one) it provisional-passes,
        # never fabricates a verdict.
        r = LeakageCanaryGate().check(GateContext(metrics={}, trades=[], returns=np.zeros(50), equity_curve=[]))
        assert r.status == GateStatus.PASS
        assert r.details["details"]["provisional"] is True
