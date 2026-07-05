"""M23 — the LagFragilityGate finally has a producer of `lagged_sharpe_annual`.

Review finding M23: the gate reads `lagged_sharpe_annual`, which nothing computed, so the "+1 bar
execution-lag fragility" check always saw None → provisional PASS, yet displayed as a passed gate.
The executor now reconstructs the position the strategy actually held and re-derives the P&L with
every fill delayed one bar; a fragile edge (one that only works with instant fills) collapses / flips
sign, and the gate FAILs it. An unreconstructable run returns None → the gate stays honestly
provisional (never a fabricated pass).
"""
from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from src.backend.ai.research.executor import _lagged_sharpe_annual
from src.backend.backtesting.gates.lag_gate import LagFragilityGate
from src.backend.backtesting.gates.pipeline import GateContext, GateStatus

_N = 20


def _zigzag_df():
    """Bar returns alternate +3% / -3% (a pure microstructure zig-zag)."""
    rets = [0.03 if t % 2 == 1 else -0.03 for t in range(1, _N)]
    closes = [100.0]
    for r in rets:
        closes.append(closes[-1] * (1 + r))
    idx = pd.date_range("2020-01-01", periods=_N, freq="B")
    return pd.DataFrame({"Open": closes, "High": closes, "Low": closes, "Close": closes}, index=idx), idx


def _trade(idx, i, j, side="long"):
    return SimpleNamespace(entry_time=idx[i], exit_time=idx[j], side=side)


@pytest.mark.finding("M23")
def test_edge_that_needs_instant_fills_flips_sign_under_lag():
    df, idx = _zigzag_df()
    # Long for exactly the up-bars (odd t): captures every +3% move — but only with instant fills.
    trades = [_trade(idx, t, t + 1) for t in range(1, _N - 1) if t % 2 == 1]
    lagged = _lagged_sharpe_annual(df, trades, warmup_bars=0, sharpe_annual=1.0)
    assert lagged is not None
    assert lagged < 0                              # one bar late → long into the -3% bars → sign flip

    # And the gate now FAILs it (was a silent provisional pass).
    r = LagFragilityGate().check(_ctx({"sharpe_annual": 1.0, "lagged_sharpe_annual": lagged}))
    assert r.status == GateStatus.FAIL


@pytest.mark.finding("M23")
def test_robust_trend_edge_survives_one_bar_lag():
    closes = [100.0 * (1.01 ** i) for i in range(_N)]   # steady uptrend
    idx = pd.date_range("2020-01-01", periods=_N, freq="B")
    df = pd.DataFrame({"Open": closes, "High": closes, "Low": closes, "Close": closes}, index=idx)
    trades = [_trade(idx, 0, _N - 1)]                    # buy-and-hold long
    lagged = _lagged_sharpe_annual(df, trades, warmup_bars=0, sharpe_annual=1.0)
    assert lagged is not None and lagged > 0.5          # a real trend edge barely notices a 1-bar delay


@pytest.mark.finding("M23")
def test_no_trades_is_unreconstructable_none():
    df, _ = _zigzag_df()
    assert _lagged_sharpe_annual(df, [], warmup_bars=0, sharpe_annual=1.0) is None


def _ctx(metrics):
    return GateContext(metrics=metrics, trades=[], returns=[], equity_curve=[])


@pytest.mark.finding("M23")
def test_gate_evaluates_when_producer_present_and_stays_provisional_when_absent():
    healthy = LagFragilityGate().check(_ctx({"sharpe_annual": 1.0, "lagged_sharpe_annual": 0.9}))
    assert healthy.status == GateStatus.PASS

    fragile = LagFragilityGate().check(_ctx({"sharpe_annual": 1.0, "lagged_sharpe_annual": 0.3}))
    assert fragile.status == GateStatus.FAIL      # ratio 0.3 < 0.6 threshold

    absent = LagFragilityGate().check(_ctx({"sharpe_annual": 1.0, "lagged_sharpe_annual": None}))
    assert absent.status == GateStatus.PASS
    assert absent.details["details"]["provisional"] is True   # honest provisional when unreconstructable
