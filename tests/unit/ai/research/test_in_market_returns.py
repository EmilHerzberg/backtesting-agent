"""valconf in-market masking — the executor reconstructs the daily returns on the bars a position was
actually HELD (from the trades), which powers the 'edge when deployed' Sharpe + CI shown beside the
full-period figure. This locks the mask reconstruction + its alignment/degeneracy guards."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from src.backend.ai.research.executor import _in_market_returns


def _data(n: int) -> pd.DataFrame:
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    return pd.DataFrame({"Close": np.linspace(100.0, 100.0 + n, n)}, index=idx)


@pytest.mark.finding("valconf-inmarket")
def test_masks_returns_to_the_held_bars_only():
    data = _data(6)                                   # bars d0..d5 → returns has len 5 (bar j+1)
    idx = data.index
    returns = np.array([0.01, 0.011, 0.012, 0.013, 0.014])
    # a position open on [d1, d3): held bars = d1, d2. held[1:] aligned to returns → [T,T,F,F,F]
    trades = [SimpleNamespace(entry_time=idx[1], exit_time=idx[3], side="long")]
    im = _in_market_returns(data, trades, warmup_bars=0, returns=returns)
    assert list(np.round(im, 6)) == [0.01, 0.011]     # only the two in-market days


@pytest.mark.finding("valconf-inmarket")
def test_short_side_still_counts_as_in_market():
    data = _data(6)
    idx = data.index
    returns = np.array([0.01, 0.011, 0.012, 0.013, 0.014])
    trades = [SimpleNamespace(entry_time=idx[2], exit_time=idx[4], side="short")]  # held d2, d3
    im = _in_market_returns(data, trades, warmup_bars=0, returns=returns)
    assert list(np.round(im, 6)) == [0.011, 0.012]    # held-or-not, not direction


@pytest.mark.finding("valconf-inmarket")
def test_empty_on_no_trades_or_misalignment():
    data = _data(6)
    idx = data.index
    returns = np.array([0.01, 0.011, 0.012, 0.013, 0.014])
    assert _in_market_returns(data, [], 0, returns).size == 0                       # no trades → empty
    # a returns array that doesn't align with the reconstructed mask → empty (never a mis-sliced mask)
    trades = [SimpleNamespace(entry_time=idx[1], exit_time=idx[3], side="long")]
    assert _in_market_returns(data, trades, 0, np.array([0.01, 0.02])).size == 0    # len 2 != 5 → empty


@pytest.mark.finding("valconf-inmarket")
def test_bad_trade_timestamps_are_skipped_not_fatal():
    data = _data(6)
    idx = data.index
    returns = np.array([0.01, 0.011, 0.012, 0.013, 0.014])
    trades = [
        SimpleNamespace(entry_time="not-a-date", exit_time="also-bad", side="long"),  # skipped
        SimpleNamespace(entry_time=idx[1], exit_time=idx[3], side="long"),            # counts
    ]
    im = _in_market_returns(data, trades, warmup_bars=0, returns=returns)
    assert list(np.round(im, 6)) == [0.01, 0.011]     # the good trade still masks correctly
