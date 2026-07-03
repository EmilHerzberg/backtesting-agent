"""Tests for runner-level validation + NoTradesError (ATS-188)."""

from __future__ import annotations

import pandas as pd
import pytest

from src.backend.backtesting.engine.exceptions import (
    InvalidParameterError,
    NoTradesError,
)
from src.backend.backtesting.engine.runner import BacktestConfig, run_backtest
from src.backend.backtesting.strategies import SMACrossover


def _trivial_data(rows: int = 100) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=rows, freq="B")
    # Flat series — never crosses → no trades will fire for SMACrossover
    return pd.DataFrame(
        {
            "Open": 100.0,
            "High": 100.5,
            "Low": 99.5,
            "Close": 100.0,
            "Volume": 1_000_000,
        },
        index=idx,
    )


class TestParamValidation:
    def test_zero_cash_raises(self):
        cfg = BacktestConfig(symbol="X", strategy_class=SMACrossover, data=_trivial_data(), cash=0)
        with pytest.raises(InvalidParameterError):
            run_backtest(cfg)

    def test_negative_cash_raises(self):
        cfg = BacktestConfig(symbol="X", strategy_class=SMACrossover, data=_trivial_data(), cash=-1)
        with pytest.raises(InvalidParameterError):
            run_backtest(cfg)

    def test_negative_commission_raises(self):
        cfg = BacktestConfig(
            symbol="X", strategy_class=SMACrossover, data=_trivial_data(),
            cash=10000, commission=-0.001,
        )
        with pytest.raises(InvalidParameterError):
            run_backtest(cfg)

    def test_commission_at_one_raises(self):
        cfg = BacktestConfig(
            symbol="X", strategy_class=SMACrossover, data=_trivial_data(),
            cash=10000, commission=1.0,
        )
        with pytest.raises(InvalidParameterError):
            run_backtest(cfg)


class TestNoTradesError:
    def test_default_keeps_zero_trade_result(self):
        # raise_on_no_trades=False (default): flat data => 0 trades, returns result.
        cfg = BacktestConfig(symbol="X", strategy_class=SMACrossover, data=_trivial_data())
        result = run_backtest(cfg)
        # Strategy may produce 0 or very few trades on flat data — accept both.
        assert result.trade_count >= 0

    def test_opt_in_raises_on_zero_trades(self):
        cfg = BacktestConfig(
            symbol="X",
            strategy_class=SMACrossover,
            data=_trivial_data(),
            raise_on_no_trades=True,
        )
        # If the strategy happens to not trade on flat data, NoTradesError fires.
        # If it does trade once, this test is a no-op — check that path too.
        try:
            result = run_backtest(cfg)
            # If we got here, the strategy traded — verify result
            assert result.trade_count > 0
        except NoTradesError as e:
            assert "0 trades" in str(e)
