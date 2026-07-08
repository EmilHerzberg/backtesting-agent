"""H6 + R10 — walk-forward window validity.

H6 (original): a zero-trade test window (runner maps NaN Sharpe -> 0.0) must NOT count as valid, and
crashed windows must stay in the denominator.

R10 (valconf): window validity is now FREQUENCY-AWARE and SIGNIFICANCE-BASED — a window is valid only when
a real per-trade significance test clears the bar (tier strong/moderate), with the trade bar scaled to the
strategy's tempo × the test length. The H6 zero-trade guarantee is preserved (no per-trade sample + ~0
in-market bars -> tier inconclusive -> not valid).
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from src.backend.backtesting.engine.walk_forward import (
    WalkForwardWindow,
    _assess_window,
    _build_wf_result,
)


def _df(n: int, start: str = "2020-01-01") -> pd.DataFrame:
    return pd.DataFrame({"x": range(n)}, index=pd.bdate_range(start, periods=n))


def _res(trade_count, *, pnls=(), sharpe=0.0, equity=None, exposure=0.5):
    return SimpleNamespace(
        trade_count=trade_count, sharpe_ratio=sharpe, exposure_time=exposure,
        equity_curve=list(equity) if equity is not None else [],
        trades=[SimpleNamespace(pnl_pct=p) for p in pnls],
    )


@pytest.mark.finding("H6")
def test_window_validity_is_frequency_aware_and_significance_based():
    train_df, test_df = _df(252), _df(63)                          # 1y train, ~3mo test
    rng = np.random.default_rng(0)
    up_eq = list(100 * np.cumprod(1 + rng.normal(0.004, 0.002, 63)))
    down_eq = list(100 * np.cumprod(1 + rng.normal(-0.003, 0.002, 63)))

    # Zero-trade window → no per-trade sample, ~0 in-market bars → not valid (H6 guarantee).
    zero = _assess_window(_res(60), _res(0, equity=up_eq, exposure=0.0), train_df, test_df, seed=1)
    assert zero.validates is False and zero.tier == "inconclusive"

    # Many significant, positive trades → valid (tier strong/moderate, per-trade basis).
    strong = _res(30, pnls=[1.0 + 0.05 * ((i % 3) - 1) for i in range(30)], sharpe=1.5, equity=up_eq)
    a = _assess_window(_res(60), strong, train_df, test_df, seed=1)
    assert a.validates and a.tier in ("strong", "moderate") and a.basis == "per_trade"

    # Traded but a losing/collapsed edge → tier failed → not valid.
    losing = _res(30, pnls=[-0.5 + 0.1 * ((i % 3) - 1) for i in range(30)], sharpe=-0.3, equity=down_eq)
    b = _assess_window(_res(60), losing, train_df, test_df, seed=1)
    assert b.validates is False and b.tier == "failed"


@pytest.mark.finding("H6")
def test_slow_strategy_with_few_trades_is_not_validated_but_gets_evidence():
    # R10/R6: a strategy too slow to produce enough trades stays NOT valid (per-bar never certifies), but
    # is enriched with a per-bar confidence signal (basis per_bar) rather than an outright zero.
    train_df, test_df = _df(252), _df(63)
    rng = np.random.default_rng(1)
    eq = list(100 * np.cumprod(1 + rng.normal(0.002, 0.004, 63)))
    slow = _res(2, pnls=[3.0, 4.0], sharpe=0.9, equity=eq, exposure=0.9)   # 2 trades, mostly in-market
    a = _assess_window(_res(8), slow, train_df, test_df, seed=1)
    assert a.validates is False                                     # per-bar can't validate
    assert a.basis == "per_bar" and a.tier in ("weak", "inconclusive")


def _win(is_valid: bool, sharpe: float = 0.4) -> WalkForwardWindow:
    return WalkForwardWindow(
        window_index=0, train_start="", train_end="", test_start="", test_end="",
        best_params={}, train_result=SimpleNamespace(sharpe_ratio=1.0),
        test_result=SimpleNamespace(sharpe_ratio=sharpe), overfitting_score=1.0, is_valid=is_valid,
    )


@pytest.mark.finding("H6")
def test_crashed_windows_count_against_the_denominator():
    # 1 valid evaluated window + 3 crashed → 25% valid, not 100%.
    res = _build_wf_result([_win(True)], [], crashed_windows=3)
    assert res.pct_valid_windows == pytest.approx(25.0)
    assert res.is_strategy_validated is False
    assert res.crashed_windows == 3


@pytest.mark.finding("H6")
def test_all_crashed_is_not_validated():
    res = _build_wf_result([], [], crashed_windows=4)
    assert res.pct_valid_windows == 0.0
    assert res.is_strategy_validated is False
