"""C1 — warm-up buffer + trade-start mask so out-of-window backtests don't run indicators cold.

Review finding C1: walk-forward / OOS / hold-out backtests were bare window slices, so every indicator
recomputed from the first bar with no prior history — a slow lookback was NaN/unconverged for the whole
window and the "validated" strategy was not the one that traded. The fix warms indicators on a prefix,
masks entries until the window starts (no in-sample trades leak in), and reports metrics on the window.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.backend.backtesting.engine.runner import BacktestConfig, run_backtest
from src.backend.backtesting.strategies.base import StrategyBase
from tests.support.frozen_data import make_ohlcv


class _BuyFirstBar(StrategyBase):
    """Opens a long as soon as it is allowed, then holds → one trade whose entry timing reveals the mask."""

    def init(self) -> None:
        pass

    def next(self) -> None:
        if not self.position:
            self.buy()

    @classmethod
    def parameter_space(cls):
        return {}


@pytest.mark.finding("C1")
def test_warmup_mask_delays_entry_to_window_start():
    data = make_ohlcv(days=200, seed=3)
    warmup = 60
    trade_start = pd.Timestamp(data.index[warmup])

    cold = run_backtest(BacktestConfig(symbol="T", strategy_class=_BuyFirstBar, data=data))
    warm = run_backtest(
        BacktestConfig(symbol="T", strategy_class=_BuyFirstBar, data=data, warmup_bars=warmup)
    )

    assert cold.trade_count == 1 and warm.trade_count == 1
    # Cold: the position opens almost immediately — inside what would be the warm-up region.
    assert pd.Timestamp(cold.trades[0].entry_time) < trade_start
    # Warm: entries are suppressed until the window start (no in-sample trade leaks in).
    assert pd.Timestamp(warm.trades[0].entry_time) >= trade_start


@pytest.mark.finding("C1")
def test_warmup_reslices_metrics_to_window():
    data = make_ohlcv(days=200, seed=3)
    warmup = 60
    warm = run_backtest(
        BacktestConfig(symbol="T", strategy_class=_BuyFirstBar, data=data, warmup_bars=warmup)
    )
    # The reported equity curve excludes the flat warm-up prefix (~window length).
    assert abs(len(warm.equity_curve) - (len(data) - warmup)) <= 3


@pytest.mark.finding("C1")
def test_no_warmup_is_unchanged():
    """warmup_bars=0 must behave exactly as before — entry at the first bar, full-range equity."""
    data = make_ohlcv(days=120, seed=9)
    res = run_backtest(BacktestConfig(symbol="T", strategy_class=_BuyFirstBar, data=data))
    assert res.trade_count == 1
    assert pd.Timestamp(res.trades[0].entry_time) <= pd.Timestamp(data.index[3])
    assert abs(len(res.equity_curve) - len(data)) <= 1
