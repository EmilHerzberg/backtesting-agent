"""Phase 5 / 5B — pandas BacktestIndicator coverage (M18) + the bugs it would have caught (M16, H11).

M18: not a single test imported the pandas indicator library the engine actually uses, so the RSI
zero-loss bug (M16) and the ADX direction-agnostic signal (H11) shipped uncaught.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.backend.backtesting.indicators.base import Signal
from src.backend.backtesting.indicators.momentum import RSIIndicator
from src.backend.backtesting.indicators.trend import ADXIndicator


@pytest.mark.finding("M16")
def test_rsi_perfect_uptrend_is_overbought_not_nan_hold():
    close = pd.Series([100.0 + i for i in range(40)])       # monotonic up → zero losses
    df = pd.DataFrame({"Close": close})
    rsi = RSIIndicator(period=14).compute(df)
    assert rsi.iloc[-1] == pytest.approx(100.0)             # pre-fix: NaN (avg_loss=0 → NaN → HOLD)
    sig = RSIIndicator(period=14, overbought=70.0, oversold=30.0).signal(df)
    assert sig.iloc[-1] == Signal.SELL                      # a perfect uptrend registers as overbought


@pytest.mark.finding("M16")
def test_rsi_warmup_stays_hold():
    df = pd.DataFrame({"Close": pd.Series([100.0 + i for i in range(40)])})
    sig = RSIIndicator(period=14).signal(df)
    assert (sig.iloc[:10] == Signal.HOLD).all()             # warm-up NaN still masked to HOLD


def _trend_df(step, n=90):
    close = pd.Series([100.0 + step * i for i in range(n)])
    return pd.DataFrame({"Open": close, "High": close + 0.5, "Low": close - 0.5,
                         "Close": close, "Volume": [1000] * n})


@pytest.mark.finding("H11")
def test_adx_downtrend_does_not_vote_buy():
    sig = ADXIndicator(period=14).signal(_trend_df(step=-1.0))    # strong persistent downtrend
    post = sig.iloc[40:]
    assert (post == Signal.BUY).sum() == 0                  # pre-fix: BUY on every bar (ADX>25)
    assert (post == Signal.SELL).any()                      # −DI > +DI → SELL


@pytest.mark.finding("H11")
def test_adx_uptrend_signals_buy():
    sig = ADXIndicator(period=14).signal(_trend_df(step=1.0))
    post = sig.iloc[40:]
    assert (post == Signal.BUY).any() and (post == Signal.SELL).sum() == 0
