"""Phase 3 / cluster 3A (cache) — H21 (adjusted-basis merge) + H23 (tz dedup).

- H23: `_store_cache` keyed the dedup check on naive-LOCAL bar time but stored naive-UTC, so on real
  (tz-aware) yfinance data every overlapping bar was re-inserted → IntegrityError / duplicate rows.
- H21: `get_or_fetch` incrementally appended an auto-adjusted (re-based) tail onto the stale cached
  head, so after any split/dividend the cached window carried a price discontinuity at the seam.
  The refresh now refetches the full window and REPLACES it as a single-basis snapshot.
"""
from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.backend.db.models import PriceCacheDB
from src.backend.marketdata.cache import CacheManager
from src.backend.shared.types import BarInterval


class _FakeProvider:
    def __init__(self, df):
        self.df = df

    def fetch_ohlcv(self, symbol, interval, start, end):
        return self.df


def _ohlcv(index, base=100.0):
    n = len(index)
    return pd.DataFrame(
        {"Open": [base] * n, "High": [base * 1.01] * n, "Low": [base * 0.99] * n,
         "Close": [base] * n, "Volume": [1000] * n},
        index=index,
    )


def _count(cm, symbol):
    with Session(cm._engine) as s:
        return s.execute(
            select(func.count()).select_from(PriceCacheDB).where(PriceCacheDB.symbol == symbol)
        ).scalar()


@pytest.mark.finding("H23")
def test_store_twice_tzaware_does_not_duplicate_or_crash():
    idx = pd.date_range("2020-01-01", periods=5, freq="B", tz="America/New_York")
    df = _ohlcv(idx)
    cm = CacheManager(provider=_FakeProvider(df), db_url="sqlite:///:memory:")
    cm._store_cache("AAPL", BarInterval.ONE_DAY, df)
    cm._store_cache("AAPL", BarInterval.ONE_DAY, df)   # pre-fix: dedup misses → IntegrityError / dupes
    assert _count(cm, "AAPL") == 5


@pytest.mark.finding("H21")
def test_stale_refresh_replaces_window_with_new_basis():
    idx = pd.date_range("2020-01-01", periods=8, freq="B")   # 2020 → always stale vs "now"
    cm = CacheManager(provider=_FakeProvider(_ohlcv(idx, base=100.0)), db_url="sqlite:///:memory:")
    start, end = idx[0].to_pydatetime(), idx[-1].to_pydatetime()

    first = cm.get_or_fetch("AAPL", BarInterval.ONE_DAY, start, end)
    assert first["Close"].iloc[0] == pytest.approx(100.0)

    # The provider now returns the SAME bars re-based (auto-adjusted after a split) — half the price.
    cm._provider = _FakeProvider(_ohlcv(idx, base=50.0))
    refreshed = cm.get_or_fetch("AAPL", BarInterval.ONE_DAY, start, end)

    # H21: the stale window is REPLACED on one basis (not a re-based tail appended / silently skipped).
    assert refreshed["Close"].iloc[0] == pytest.approx(50.0)
    assert _count(cm, "AAPL") == 8      # replaced in place, not duplicated
