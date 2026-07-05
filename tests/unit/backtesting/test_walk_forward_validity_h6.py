"""H6 — walk-forward window validity must require real trades and count crashed windows.

Review finding H6: a zero-trade test window (runner maps NaN Sharpe -> 0.0) passed
`test_sharpe >= threshold` at the default threshold 0.0, so a strategy that never traded
out-of-sample reported `is_strategy_validated=True`; and crashed windows were `continue`d, shrinking
the denominator so 9 crashed + 1 valid read as 100% valid.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.backend.backtesting.engine.walk_forward import (
    WalkForwardWindow,
    _build_wf_result,
    _window_is_valid,
)


@pytest.mark.finding("H6")
def test_zero_trade_or_losing_window_is_not_valid():
    # Zero-trade window: runner defaulted Sharpe to 0.0 → must NOT be valid at threshold 0.0.
    assert _window_is_valid(SimpleNamespace(trade_count=0, sharpe_ratio=0.0), 0.0) is False
    # Traded and positive → valid.
    assert _window_is_valid(SimpleNamespace(trade_count=5, sharpe_ratio=0.4), 0.0) is True
    # Traded but Sharpe below threshold → not valid.
    assert _window_is_valid(SimpleNamespace(trade_count=5, sharpe_ratio=-0.1), 0.0) is False


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
