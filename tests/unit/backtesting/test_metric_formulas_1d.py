"""1D — metric formula fixes: Sortino (H9), sentinels (H10), Calmar CAGR (M2), composite weights (M4)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.backend.backtesting.engine.metrics import (
    TradeDetail,
    _CALMAR_CAP,
    _PROFIT_FACTOR_CAP,
    _SORTINO_CAP,
    calculate_calmar,
    calculate_profit_factor,
    calculate_sortino,
)
from src.backend.backtesting.engine.optimizer import _DEFAULT_COMPOSITE_WEIGHTS, _calculate_objective


def _trade(pnl: float) -> TradeDetail:
    return TradeDetail(
        entry_time="", exit_time="", side="long", entry_price=1.0, exit_price=1.0,
        size=1.0, pnl=pnl, pnl_pct=pnl, duration="",
    )


@pytest.mark.finding("H9")
def test_sortino_of_steady_loser_is_bounded_not_1e15():
    # A strategy losing a steady ~1%/period: the old centered-std denominator collapsed to ~0 and the
    # Sortino exploded to ~1e15. It must now be a bounded, negative value.
    equity = pd.Series(10_000 * (0.99 ** np.arange(60)))
    s = calculate_sortino(equity)
    assert s < 0
    assert abs(s) <= _SORTINO_CAP


@pytest.mark.finding("H9")
def test_sortino_single_negative_return_is_not_nan():
    # One negative return → old ddof=1 std was NaN. Uncentered downside deviation is well-defined.
    equity = pd.Series([100.0, 101.0, 102.0, 101.0, 103.0, 104.0])
    s = calculate_sortino(equity)
    assert np.isfinite(s)


@pytest.mark.finding("H10")
def test_sortino_no_downside_is_capped_not_999():
    equity = pd.Series([100.0, 101.0, 102.5, 104.0])  # monoting up → no downside
    assert calculate_sortino(equity) == _SORTINO_CAP


@pytest.mark.finding("H10")
def test_profit_factor_is_capped():
    assert calculate_profit_factor([_trade(50.0)]) == _PROFIT_FACTOR_CAP  # no losers → cap, not 999.99
    # 3 profit vs 1 loss → PF 3.0 (below the cap).
    assert calculate_profit_factor([_trade(3.0), _trade(-1.0)]) == pytest.approx(3.0)


@pytest.mark.finding("M2")
def test_calmar_uses_cagr_not_arithmetic():
    # +100% over 2 years: arithmetic gave 100%/2 = 50%; CAGR = sqrt(2)-1 ≈ 41.4%.
    calmar = calculate_calmar(total_return=1.0, max_drawdown=0.20, years=2.0)
    expected_cagr = (2.0 ** 0.5) - 1.0
    assert calmar == pytest.approx(min(expected_cagr / 0.20, _CALMAR_CAP))
    # Very short window is guarded (no wild ×N extrapolation).
    assert calculate_calmar(total_return=0.1, max_drawdown=0.1, years=0.02) == 0.0


@pytest.mark.finding("M4")
def test_composite_penalizes_drawdown():
    """A 50% drawdown must lower the composite score vs. the same Sharpe with no drawdown."""
    class _Cfg:
        objective_metric = "composite"
        composite_weights = _DEFAULT_COMPOSITE_WEIGHTS

    class _Res:
        def __init__(self, dd):
            self.sharpe_ratio = 1.0
            self.max_drawdown = dd
            self.total_return = 0.0
            self.sortino_ratio = 0.0
            self.win_rate = 0.0
            self.profit_factor = 0.0
            self.calmar_ratio = 0.0

    low = _calculate_objective(_Res(0.05), _Cfg())
    high = _calculate_objective(_Res(0.50), _Cfg())
    assert high < low
    assert (low - high) > 0.3  # a 50% DD is a materially larger penalty than a 5% DD
