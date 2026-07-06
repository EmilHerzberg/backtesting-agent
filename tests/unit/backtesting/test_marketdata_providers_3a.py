"""Phase 3 / cluster 3A (providers) — H22, M33, M34, M35.

- H22: AggregatedDataProvider picked whichever provider returned the MOST rows, silently blending
  adjustment conventions across a fallback. It must return the FIRST (priority) provider that answers.
- M33: TiingoProvider mapped both raw and adjusted fields to Open/Close/… → duplicate labels / crash.
- M34: CoinGeckoProvider used /ohlc (ignores the window → wrong period) and fabricated Volume=0.
- M35: AlphaVantageProvider fetched the raw (unadjusted) series despite claiming adjusted.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from src.backend.marketdata.provider import (
    AggregatedDataProvider,
    CoinGeckoProvider,
    DataProvider,
    TiingoProvider,
    _av_adjust,
)
from src.backend.shared.types import BarInterval


def _ohlcv(index, base=100.0):
    n = len(index)
    return pd.DataFrame(
        {"Open": [base] * n, "High": [base] * n, "Low": [base] * n, "Close": [base] * n,
         "Volume": [1] * n},
        index=index,
    )


class _FakeProvider(DataProvider):
    def __init__(self, df):
        self._df = df

    def fetch_ohlcv(self, symbol, interval=BarInterval.ONE_DAY, start=None, end=None):
        return self._df


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


# ── H22: aggregation by priority, not row count ───────────────────────

@pytest.mark.finding("H22")
def test_aggregation_returns_first_nonempty_not_the_biggest():
    first = _FakeProvider(_ohlcv(pd.date_range("2020-01-01", periods=3, freq="B"), base=1.0))
    second = _FakeProvider(_ohlcv(pd.date_range("2020-01-01", periods=10, freq="B"), base=2.0))
    out = AggregatedDataProvider([first, second]).fetch_ohlcv("X")
    # The higher-priority provider wins even though it has FEWER rows (no cross-provider basis mixing).
    assert len(out) == 3
    assert out["Close"].iloc[0] == pytest.approx(1.0)


# ── M35: Alpha Vantage adjusted-basis scaling ─────────────────────────

@pytest.mark.finding("M35")
def test_av_adjust_scales_whole_bar_to_adjusted_basis():
    raw = pd.DataFrame({
        "1. open": [10.0], "2. high": [11.0], "3. low": [9.0],
        "4. close": [10.0], "5. adjusted close": [5.0], "6. volume": [100],
    })
    out = _av_adjust(raw)
    assert list(out.columns).count("Close") == 1              # no duplicate labels
    assert out["Close"].iloc[0] == pytest.approx(5.0)         # close := adjusted close
    assert out["Open"].iloc[0] == pytest.approx(5.0)          # OHL scaled by 5/10
    assert out["High"].iloc[0] == pytest.approx(5.5)


# ── M33: Tiingo prefers adjusted, no duplicate columns ────────────────

@pytest.mark.finding("M33")
def test_tiingo_prefers_adjusted_and_dedupes_columns(monkeypatch):
    import httpx
    payload = [{
        "date": "2020-01-02", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100,
        "adjOpen": 5, "adjHigh": 5.5, "adjLow": 4.5, "adjClose": 5, "adjVolume": 200,
    }]
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp(payload))
    df = TiingoProvider(api_key="x").fetch_ohlcv("AAPL")
    assert list(df.columns).count("Close") == 1
    assert df["Close"].iloc[0] == pytest.approx(5.0)          # adjusted, not raw 10
    assert df["Volume"].iloc[0] == pytest.approx(200)         # adjVolume, not raw 100


# ── M34: CoinGecko honors the window + real volume ────────────────────

@pytest.mark.finding("M34")
def test_coingecko_uses_range_endpoint_and_real_volume(monkeypatch):
    import httpx
    t1 = int(datetime(2021, 1, 4).timestamp() * 1000)
    t2 = int(datetime(2021, 1, 5).timestamp() * 1000)
    captured: dict = {}

    def _get(url, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params or {}
        return _Resp({"prices": [[t1, 100.0], [t2, 110.0]],
                      "total_volumes": [[t1, 5.0], [t2, 6.0]]})

    monkeypatch.setattr(httpx, "get", _get)
    df = CoinGeckoProvider().fetch_ohlcv("BTC-USD", start=datetime(2021, 1, 1), end=datetime(2021, 1, 10))

    assert "market_chart/range" in captured["url"]            # honors [from,to], not the recent-N /ohlc
    assert "from" in captured["params"] and "to" in captured["params"]
    assert df["Close"].iloc[0] == pytest.approx(100.0)
    assert df["Volume"].iloc[0] == pytest.approx(5.0)         # real volume, not a fabricated 0
