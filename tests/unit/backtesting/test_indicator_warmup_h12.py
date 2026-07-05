"""H12 — pandas indicators must be NaN (not directional) during warm-up.

Review finding H12: the ewm chains set no ``min_periods``, and ``ewm(adjust=False)`` never yields NaN,
so RSI/EMA/MACD/ADX/ATR emitted converged-looking values (and BUY/SELL signals) from bar 1 on
unwarmed averages. Every generated strategy then traded on garbage indicator values during warm-up.
(Also gives the previously-untested pandas ``BacktestIndicator`` library its first coverage — M18.)
"""
from __future__ import annotations

import pytest

from src.backend.backtesting.indicators.base import Signal
from src.backend.backtesting.indicators.momentum import RSIIndicator
from src.backend.backtesting.indicators.trend import ADXIndicator, EMAIndicator, MACDIndicator
from src.backend.backtesting.indicators.volatility import ATRIndicator, KeltnerChannelsIndicator
from tests.support.frozen_data import make_ohlcv

_DF = make_ohlcv(days=300, seed=11)


@pytest.mark.finding("H12")
@pytest.mark.parametrize(
    "indicator",
    [
        RSIIndicator(period=14),
        EMAIndicator(period=20),
        MACDIndicator(fast=12, slow=26, signal_period=9),
        ADXIndicator(period=14),
        ATRIndicator(period=14),
        KeltnerChannelsIndicator(ema_period=20, atr_period=14),
    ],
)
def test_indicator_is_nan_during_warmup_then_converges(indicator):
    vals = indicator.compute(_DF)
    # The first bars are NaN (not a converged-looking value) …
    assert vals.iloc[:10].isna().all()
    # … and past a generous warm-up it produces real values.
    assert vals.iloc[80:].notna().any()


@pytest.mark.finding("H12")
@pytest.mark.parametrize(
    "indicator",
    [
        RSIIndicator(period=14),
        EMAIndicator(period=20),
        MACDIndicator(fast=12, slow=26, signal_period=9),
        ADXIndicator(period=14),
        KeltnerChannelsIndicator(ema_period=20, atr_period=14),
    ],
)
def test_signal_is_hold_during_warmup(indicator):
    sig = indicator.signal(_DF)
    # No BUY/SELL emitted while the indicator is still warming up.
    assert (sig.iloc[:10] == Signal.HOLD).all()


@pytest.mark.finding("H12")
def test_generated_strategy_does_not_trade_during_warmup():
    """P1-04/P1-05: a generated DynamicStrategy must not open trades before its indicators warm up.
    The generator has to register each indicator as a strategy attribute so backtesting.py's warm-up
    detection skips the leading region — without that, indicators live only in a list, backtesting.py
    finds 0, and the strategy trades from bar ~1 despite the _signal_fn NaN mask."""
    from backtesting import Backtest
    from optuna.trial import FixedTrial

    from src.backend.backtesting.strategies.generator import generate_strategy

    period = 30
    trial = FixedTrial({
        "n_indicators": 1, "indicator_0": "EMA", "ind_0_period": period,
        "weight_0": 1.0, "buy_threshold": 0.5, "sell_threshold": -0.5,
    })
    strat_cls = generate_strategy(trial, max_indicators=1)
    # Strong uptrend so the EMA "close > ema" BUY reliably fires (otherwise the test is vacuous).
    data = make_ohlcv(days=400, seed=1, drift=0.003, vol=0.008)
    stats = Backtest(data, strat_cls, cash=10_000, commission=0.0, finalize_trades=True).run()
    trades = stats["_trades"]
    assert len(trades) > 0
    assert int(trades["EntryBar"].min()) >= period - 1    # no entry before the EMA(30) warmed up
