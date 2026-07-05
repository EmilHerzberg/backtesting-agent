"""H7 — open-at-end trades must be counted (finalize_trades).

Review finding H7 (docs/reviews/QUANT-REVIEW-2026-07-03.md): `Backtest(...)` never set
`finalize_trades`, so under backtesting.py's default (False) any trade still open on the last bar is
dropped from `# Trades` / `Win Rate` / profit factor, while its unrealized PnL stays in the equity
curve and `Return [%]`. Result: `trade_count` contradicts `total_return`, and a fully-invested
buy-and-hold run reports zero trades.

This test pins the corrected behavior: a position held to the last bar counts as one trade and the
trade stats are consistent with the return. It FAILS on the pre-fix code (trade_count == 0) and passes
once the runner sets `finalize_trades=True`.
"""
from __future__ import annotations

import pytest
from backtesting import Strategy

from src.backend.backtesting.engine.runner import BacktestConfig, run_backtest
from tests.support.frozen_data import make_ohlcv


class _BuyAndHoldOnce(Strategy):
    """Buy on the first bar, never sell → exactly one trade, still OPEN at the last bar."""

    def init(self) -> None:  # noqa: D401 — backtesting.py hook
        pass

    def next(self) -> None:  # noqa: D401 — backtesting.py hook
        if not self.position:
            self.buy()


@pytest.mark.finding("H7")
def test_open_at_end_trade_is_counted_and_consistent_with_return():
    """A position held to the last bar is counted as a trade, consistent with the (non-zero) return."""
    # Gently rising, offline, deterministic series → the held long ends in profit.
    data = make_ohlcv(days=300, seed=1, drift=0.001, vol=0.010)

    result = run_backtest(BacktestConfig(symbol="TEST", strategy_class=_BuyAndHoldOnce, data=data))

    # It was invested for essentially the whole window and moved the equity …
    assert result.exposure_time > 0.5
    assert result.total_return != 0.0
    # … so the open-at-end position must be reflected in the trade stats.
    # Pre-fix (finalize_trades unset) this is 0 → the return/trade-count contradiction H7 describes.
    assert result.trade_count == 1
    assert len(result.trades) == 1
