"""Data providers for backtesting: ABC + Yahoo and AlphaVantage implementations."""
from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

from backtesting_agent.shared.config import settings
from backtesting_agent.shared.types import BarInterval

logger = logging.getLogger(__name__)

# Map BarInterval to yfinance interval strings
_YF_INTERVAL_MAP: dict[BarInterval, str] = {
    BarInterval.ONE_MIN: "1m",
    BarInterval.FIVE_MIN: "5m",
    BarInterval.FIFTEEN_MIN: "15m",
    BarInterval.ONE_HOUR: "1h",
    BarInterval.ONE_DAY: "1d",
    BarInterval.ONE_WEEK: "1wk",  # ATS-129
}

# Map BarInterval to Alpha Vantage interval strings
_AV_INTERVAL_MAP: dict[BarInterval, str] = {
    BarInterval.ONE_MIN: "1min",
    BarInterval.FIVE_MIN: "5min",
    BarInterval.FIFTEEN_MIN: "15min",
    BarInterval.ONE_HOUR: "60min",
    BarInterval.ONE_DAY: "daily",
    BarInterval.ONE_WEEK: "weekly",  # ATS-129 — TIME_SERIES_WEEKLY_ADJUSTED
}

# Standard column names for backtesting DataFrames
OHLCV_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


class DataProvider(ABC):
    """Abstract base class for backtesting data providers.

    All providers return pandas DataFrames with a DatetimeIndex and
    capitalized OHLCV columns: Open, High, Low, Close, Volume.
    """

    @abstractmethod
    def fetch_ohlcv(
        self,
        symbol: str,
        interval: BarInterval = BarInterval.ONE_DAY,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        """Fetch OHLCV data for a symbol.

        Args:
            symbol: Ticker symbol (e.g. "AAPL", "BTC-USD").
            interval: Bar interval.
            start: Start datetime (inclusive). None = provider default.
            end: End datetime (inclusive). None = now.

        Returns:
            DataFrame with DatetimeIndex and columns Open, High, Low, Close, Volume.

        Raises:
            DataProviderError: On network or API errors.
        """


class DataProviderError(Exception):
    """Raised when a data provider fails to fetch data."""


# ATS-2004 — Frozen-snapshot provider for deterministic golden runs.
# Project root, used to locate ``data/golden/`` regardless of CWD.
# This file lives at src/backend/marketdata/provider.py → parents[3] is the
# project root (Modularisation Phase 4: moved here from backtesting/data/).
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_GOLDEN_SNAPSHOT = (
    _PROJECT_ROOT / "data" / "golden" / "yfinance_snapshot_2026-05-21.parquet"
)


def _determinism_mode_active() -> bool:
    """Return True if BACKTEST_DETERMINISM_MODE env var is truthy."""
    return os.environ.get("BACKTEST_DETERMINISM_MODE", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


class FrozenSnapshotProvider(DataProvider):
    """Reads OHLCV from a pre-frozen parquet snapshot (ATS-2004).

    The snapshot is a long-format parquet file with columns
    ``symbol, interval, Date, Open, High, Low, Close, Volume`` produced by
    ``scripts/freeze_yfinance_snapshot.py``.  This makes backtests fully
    deterministic — yfinance occasionally revises historical bars and that
    silently changes results between runs.

    In determinism mode the YahooProvider transparently delegates to this
    class; the snapshot file path can be overridden via the
    ``BACKTEST_DATA_SNAPSHOT`` env var (handy for tests).
    """

    def __init__(self, snapshot_path: Path | None = None) -> None:
        env_path = os.environ.get("BACKTEST_DATA_SNAPSHOT")
        self._path = (
            Path(snapshot_path) if snapshot_path
            else Path(env_path) if env_path
            else _DEFAULT_GOLDEN_SNAPSHOT
        )
        self._cache: pd.DataFrame | None = None

    def _load(self) -> pd.DataFrame:
        if self._cache is not None:
            return self._cache
        if not self._path.exists():
            raise DataProviderError(
                f"Frozen snapshot missing at {self._path}. "
                "Run `python scripts/freeze_yfinance_snapshot.py` once to create it, "
                "or unset BACKTEST_DETERMINISM_MODE for live yfinance fetches."
            )
        try:
            df = pd.read_parquet(self._path)
        except Exception as exc:  # pragma: no cover — IO error path
            raise DataProviderError(
                f"Failed to read frozen snapshot {self._path}: {exc}"
            ) from exc
        # Strip tz to keep parity with YahooProvider's tz-naive output
        if "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"]).dt.tz_localize(None)
        self._cache = df
        return df

    def fetch_ohlcv(
        self,
        symbol: str,
        interval: BarInterval = BarInterval.ONE_DAY,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        df = self._load()
        # Filter symbol + interval
        iv_str = _YF_INTERVAL_MAP.get(interval, "1d")
        mask = (df["symbol"] == symbol) & (df["interval"] == iv_str)
        sub = df.loc[mask].copy()
        if sub.empty:
            logger.warning(
                "FrozenSnapshotProvider: no rows for %s/%s in %s",
                symbol, iv_str, self._path.name,
            )
            return pd.DataFrame(columns=OHLCV_COLUMNS)
        sub = sub.set_index("Date").sort_index()
        if start is not None:
            start_naive = pd.Timestamp(start).tz_localize(None) if (
                hasattr(start, "tzinfo") and start.tzinfo is not None
            ) else pd.Timestamp(start)
            sub = sub[sub.index >= start_naive]
        if end is not None:
            end_naive = pd.Timestamp(end).tz_localize(None) if (
                hasattr(end, "tzinfo") and end.tzinfo is not None
            ) else pd.Timestamp(end)
            sub = sub[sub.index <= end_naive]
        sub.index.name = "Date"
        return sub[OHLCV_COLUMNS].copy()


class YahooProvider(DataProvider):
    """Data provider using yfinance (synchronous, suitable for offline backtesting).

    In determinism mode (env ``BACKTEST_DETERMINISM_MODE=true``) requests are
    transparently routed to :class:`FrozenSnapshotProvider` so two runs of
    the same config produce identical bar data — yfinance occasionally
    revises historical values.
    """

    def __init__(self) -> None:
        # Lazy snapshot delegate, created on first call when in determinism mode.
        self._frozen: FrozenSnapshotProvider | None = None

    def fetch_ohlcv(
        self,
        symbol: str,
        interval: BarInterval = BarInterval.ONE_DAY,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        # ATS-2004: route to frozen snapshot when determinism mode is on.
        if _determinism_mode_active():
            if self._frozen is None:
                self._frozen = FrozenSnapshotProvider()
            return self._frozen.fetch_ohlcv(symbol, interval, start, end)

        yf_interval = _YF_INTERVAL_MAP.get(interval, "1d")
        try:
            ticker = yf.Ticker(symbol)
            kwargs: dict = {"interval": yf_interval}
            if start is not None:
                kwargs["start"] = start.strftime("%Y-%m-%d")
            if end is not None:
                kwargs["end"] = end.strftime("%Y-%m-%d")
            if start is None and end is None:
                kwargs["period"] = "max" if interval == BarInterval.ONE_DAY else "60d"

            df = ticker.history(**kwargs)
        except Exception as exc:
            raise DataProviderError(
                f"Yahoo Finance download failed for {symbol}: {exc}"
            ) from exc

        if df is None or df.empty:
            logger.warning("No data from Yahoo for %s (%s)", symbol, interval)
            return pd.DataFrame(columns=OHLCV_COLUMNS)

        return _normalize_ohlcv(df)


class AlphaVantageProvider(DataProvider):
    """Data provider using the Alpha Vantage API (synchronous)."""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or getattr(settings, "alpha_vantage_api_key", "")

    def fetch_ohlcv(
        self,
        symbol: str,
        interval: BarInterval = BarInterval.ONE_DAY,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        if not self._api_key:
            raise DataProviderError("No Alpha Vantage API key configured")

        try:
            from alpha_vantage.timeseries import TimeSeries

            ts = TimeSeries(key=self._api_key, output_format="pandas")
            av_interval = _AV_INTERVAL_MAP.get(interval, "daily")

            if av_interval == "daily":
                df, _ = ts.get_daily(symbol=symbol, outputsize="full")
            elif av_interval == "weekly":  # ATS-129
                df, _ = ts.get_weekly(symbol=symbol)
            else:
                df, _ = ts.get_intraday(
                    symbol=symbol, interval=av_interval, outputsize="full"
                )
        except DataProviderError:
            raise
        except Exception as exc:
            raise DataProviderError(
                f"Alpha Vantage download failed for {symbol}: {exc}"
            ) from exc

        if df is None or df.empty:
            logger.warning("No data from Alpha Vantage for %s", symbol)
            return pd.DataFrame(columns=OHLCV_COLUMNS)

        # Alpha Vantage pandas output uses numbered column names
        rename_map = {
            "1. open": "Open",
            "2. high": "High",
            "3. low": "Low",
            "4. close": "Close",
            "5. volume": "Volume",
        }
        df = df.rename(columns=rename_map)
        df.index = pd.to_datetime(df.index)
        df.index.name = "Date"
        df = df.sort_index()

        # Filter by date range if provided
        if start is not None:
            df = df[df.index >= pd.Timestamp(start)]
        if end is not None:
            df = df[df.index <= pd.Timestamp(end)]

        return df[OHLCV_COLUMNS].copy()


def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize a DataFrame to standard OHLCV format.

    Ensures DatetimeIndex, capitalized column names, and only OHLCV columns.
    """
    df = df.copy()
    df.index = pd.to_datetime(df.index)
    df.index.name = "Date"

    # yfinance may include Dividends, Stock Splits — keep only OHLCV
    available = [c for c in OHLCV_COLUMNS if c in df.columns]
    if len(available) < 5:
        # Try case-insensitive matching
        col_map = {c.lower(): c for c in df.columns}
        for target in OHLCV_COLUMNS:
            if target not in df.columns and target.lower() in col_map:
                df = df.rename(columns={col_map[target.lower()]: target})

    missing = [c for c in OHLCV_COLUMNS if c not in df.columns]
    if missing:
        raise DataProviderError(
            f"OHLCV normalization failed: missing columns {missing}. "
            f"Available columns: {list(df.columns)}"
        )

    return df[OHLCV_COLUMNS].copy()


# ── Broker-based providers ────────────────────────────────────────


class PolygonProvider(DataProvider):
    """Data provider using Polygon.io API. Free tier: 5 calls/min."""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or getattr(settings, "polygon_api_key", "")

    def fetch_ohlcv(
        self,
        symbol: str,
        interval: BarInterval = BarInterval.ONE_DAY,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        if not self._api_key:
            raise DataProviderError("No Polygon.io API key configured")
        import httpx
        multiplier_map = {
            BarInterval.ONE_MIN: (1, "minute"),
            BarInterval.FIVE_MIN: (5, "minute"),
            BarInterval.FIFTEEN_MIN: (15, "minute"),
            BarInterval.ONE_HOUR: (1, "hour"),
            BarInterval.ONE_DAY: (1, "day"),
            BarInterval.ONE_WEEK: (1, "week"),  # ATS-129
        }
        mult, span = multiplier_map.get(interval, (1, "day"))
        params: dict = {"adjusted": "true", "sort": "asc", "limit": "50000"}
        params["apiKey"] = self._api_key
        s = start.strftime("%Y-%m-%d") if start else "2020-01-01"
        e = end.strftime("%Y-%m-%d") if end else datetime.now().strftime("%Y-%m-%d")
        url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/{mult}/{span}/{s}/{e}"
        try:
            resp = httpx.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            raise DataProviderError(f"Polygon.io failed for {symbol}: {exc}") from exc
        results = data.get("results", [])
        if not results:
            return pd.DataFrame(columns=OHLCV_COLUMNS)
        df = pd.DataFrame(results)
        df["Date"] = pd.to_datetime(df["t"], unit="ms")
        df = df.rename(columns={"o": "Open", "h": "High", "l": "Low", "c": "Close", "v": "Volume"})
        df = df.set_index("Date").sort_index()
        return df[OHLCV_COLUMNS].copy()


class TwelveDataProvider(DataProvider):
    """Data provider using Twelve Data API. Free tier: 800 calls/day."""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or getattr(settings, "twelve_data_api_key", "")

    def fetch_ohlcv(
        self,
        symbol: str,
        interval: BarInterval = BarInterval.ONE_DAY,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        if not self._api_key:
            raise DataProviderError("No Twelve Data API key configured")
        import httpx
        iv_map = {
            BarInterval.ONE_MIN: "1min",
            BarInterval.FIVE_MIN: "5min",
            BarInterval.FIFTEEN_MIN: "15min",
            BarInterval.ONE_HOUR: "1h",
            BarInterval.ONE_DAY: "1day",
            BarInterval.ONE_WEEK: "1week",  # ATS-129
        }
        params: dict = {
            "symbol": symbol,
            "interval": iv_map.get(interval, "1day"),
            "apikey": self._api_key,
            "outputsize": "5000",
            "format": "JSON",
        }
        if start:
            params["start_date"] = start.strftime("%Y-%m-%d")
        if end:
            params["end_date"] = end.strftime("%Y-%m-%d")
        try:
            resp = httpx.get("https://api.twelvedata.com/time_series", params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            raise DataProviderError(f"Twelve Data failed for {symbol}: {exc}") from exc
        values = data.get("values", [])
        if not values:
            return pd.DataFrame(columns=OHLCV_COLUMNS)
        df = pd.DataFrame(values)
        df["Date"] = pd.to_datetime(df["datetime"])
        for col in ["open", "high", "low", "close"]:
            df[col] = df[col].astype(float)
        df["volume"] = df["volume"].astype(int)
        df = df.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"})
        df = df.set_index("Date").sort_index()
        return df[OHLCV_COLUMNS].copy()


class FinnhubProvider(DataProvider):
    """Data provider using Finnhub API. Free tier: 60 calls/min."""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or getattr(settings, "finnhub_api_key", "")

    def fetch_ohlcv(
        self,
        symbol: str,
        interval: BarInterval = BarInterval.ONE_DAY,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        if not self._api_key:
            raise DataProviderError("No Finnhub API key configured")
        import httpx
        res_map = {
            BarInterval.ONE_MIN: "1",
            BarInterval.FIVE_MIN: "5",
            BarInterval.FIFTEEN_MIN: "15",
            BarInterval.ONE_HOUR: "60",
            BarInterval.ONE_DAY: "D",
            BarInterval.ONE_WEEK: "W",  # ATS-129
        }
        s = int(start.timestamp()) if start else int((datetime.now().timestamp()) - 365 * 86400)
        e = int(end.timestamp()) if end else int(datetime.now().timestamp())
        params = {
            "symbol": symbol,
            "resolution": res_map.get(interval, "D"),
            "from": s,
            "to": e,
            "token": self._api_key,
        }
        try:
            resp = httpx.get("https://finnhub.io/api/v1/stock/candle", params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            raise DataProviderError(f"Finnhub failed for {symbol}: {exc}") from exc
        if data.get("s") != "ok" or "t" not in data:
            return pd.DataFrame(columns=OHLCV_COLUMNS)
        df = pd.DataFrame({
            "Date": pd.to_datetime(data["t"], unit="s"),
            "Open": data["o"], "High": data["h"], "Low": data["l"],
            "Close": data["c"], "Volume": data["v"],
        })
        df = df.set_index("Date").sort_index()
        return df[OHLCV_COLUMNS].copy()


class CoinGeckoProvider(DataProvider):
    """Data provider for crypto using CoinGecko (free, no API key)."""

    _SYMBOL_MAP = {
        "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
        "ADA": "cardano", "DOT": "polkadot", "AVAX": "avalanche-2",
        "MATIC": "matic-network", "LINK": "chainlink", "UNI": "uniswap",
        "DOGE": "dogecoin", "XRP": "ripple", "LTC": "litecoin",
        "BNB": "binancecoin", "ATOM": "cosmos", "NEAR": "near",
    }

    def fetch_ohlcv(
        self,
        symbol: str,
        interval: BarInterval = BarInterval.ONE_DAY,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        import httpx
        # Strip -USD suffix if present
        clean = symbol.replace("-USD", "").replace("USD", "").upper()
        coin_id = self._SYMBOL_MAP.get(clean, clean.lower())

        s = int(start.timestamp()) if start else int(datetime.now().timestamp() - 365 * 86400)
        e = int(end.timestamp()) if end else int(datetime.now().timestamp())
        url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc"
        # CoinGecko OHLC supports 1, 7, 14, 30, 90, 180, 365 days
        days = max(1, (e - s) // 86400)
        if days > 365:
            days = 365
        try:
            resp = httpx.get(url, params={"vs_currency": "usd", "days": str(days)}, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            raise DataProviderError(f"CoinGecko failed for {symbol}: {exc}") from exc
        if not data:
            return pd.DataFrame(columns=OHLCV_COLUMNS)
        df = pd.DataFrame(data, columns=["timestamp", "Open", "High", "Low", "Close"])
        df["Date"] = pd.to_datetime(df["timestamp"], unit="ms")
        df["Volume"] = 0  # CoinGecko OHLC doesn't include volume
        df = df.set_index("Date").sort_index()
        return df[OHLCV_COLUMNS].copy()


class TiingoProvider(DataProvider):
    """Data provider using Tiingo API. Free tier: 500 calls/hour."""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or getattr(settings, "tiingo_api_key", "")

    def fetch_ohlcv(
        self,
        symbol: str,
        interval: BarInterval = BarInterval.ONE_DAY,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        if not self._api_key:
            raise DataProviderError("No Tiingo API key configured")
        import httpx
        headers = {"Content-Type": "application/json", "Authorization": f"Token {self._api_key}"}
        params: dict = {}
        if start:
            params["startDate"] = start.strftime("%Y-%m-%d")
        if end:
            params["endDate"] = end.strftime("%Y-%m-%d")

        if interval == BarInterval.ONE_DAY:
            url = f"https://api.tiingo.com/tiingo/daily/{symbol}/prices"
        else:
            freq_map = {
                BarInterval.ONE_MIN: "1min",
                BarInterval.FIVE_MIN: "5min",
                BarInterval.FIFTEEN_MIN: "15min",
                BarInterval.ONE_HOUR: "1hour",
            }
            params["resampleFreq"] = freq_map.get(interval, "1day")
            url = f"https://api.tiingo.com/iex/{symbol}/prices"

        try:
            resp = httpx.get(url, headers=headers, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            raise DataProviderError(f"Tiingo failed for {symbol}: {exc}") from exc
        if not data:
            return pd.DataFrame(columns=OHLCV_COLUMNS)
        df = pd.DataFrame(data)
        date_col = "date" if "date" in df.columns else "Date"
        df["Date"] = pd.to_datetime(df[date_col])
        col_map = {
            "open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume",
            "adjOpen": "Open", "adjHigh": "High", "adjLow": "Low", "adjClose": "Close", "adjVolume": "Volume",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        df = df.set_index("Date").sort_index()
        available = [c for c in OHLCV_COLUMNS if c in df.columns]
        if len(available) < 5:
            for c in OHLCV_COLUMNS:
                if c not in df.columns:
                    df[c] = 0
        return df[OHLCV_COLUMNS].copy()


# ── Broker-based providers ────────────────────────────────────────


class AlpacaDataProvider(DataProvider):
    """Data provider using Alpaca Market Data API (no trading account needed)."""

    def __init__(self, api_key: str, secret_key: str) -> None:
        self._api_key = api_key
        self._secret_key = secret_key

    def fetch_ohlcv(
        self,
        symbol: str,
        interval: BarInterval = BarInterval.ONE_DAY,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        try:
            from alpaca.data.historical import StockHistoricalDataClient
            from alpaca.data.requests import StockBarsRequest
            from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

            tf_map = {
                BarInterval.ONE_MIN: TimeFrame.Minute,
                BarInterval.FIVE_MIN: TimeFrame(5, TimeFrameUnit.Minute),
                BarInterval.FIFTEEN_MIN: TimeFrame(15, TimeFrameUnit.Minute),
                BarInterval.ONE_HOUR: TimeFrame.Hour,
                BarInterval.ONE_DAY: TimeFrame.Day,
            }
            tf = tf_map.get(interval, TimeFrame.Day)

            client = StockHistoricalDataClient(
                api_key=self._api_key, secret_key=self._secret_key,
            )
            req = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=tf,
                start=start,
                end=end,
            )
            barset = client.get_stock_bars(req)
            bars = barset[symbol] if symbol in barset else []

            if not bars:
                return pd.DataFrame(columns=OHLCV_COLUMNS)

            data = [{
                "Date": b.timestamp,
                "Open": float(b.open),
                "High": float(b.high),
                "Low": float(b.low),
                "Close": float(b.close),
                "Volume": int(b.volume),
            } for b in bars]

            df = pd.DataFrame(data).set_index("Date")
            df.index = pd.to_datetime(df.index)
            return df[OHLCV_COLUMNS].copy()
        except Exception as exc:
            raise DataProviderError(f"Alpaca data fetch failed for {symbol}: {exc}") from exc


class AggregatedDataProvider(DataProvider):
    """Meta-provider that tries multiple sources and returns the best result.

    Priority: tries each provider in order, returns the one with the most
    data points. Falls back through the chain on errors.
    """

    def __init__(self, providers: list[DataProvider]) -> None:
        self._providers = providers

    @property
    def provider_count(self) -> int:
        return len(self._providers)

    @property
    def provider_names(self) -> list[str]:
        return [type(p).__name__ for p in self._providers]

    def fetch_ohlcv(
        self,
        symbol: str,
        interval: BarInterval = BarInterval.ONE_DAY,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        best_df: pd.DataFrame | None = None
        best_source: str = "none"

        for provider in self._providers:
            try:
                df = provider.fetch_ohlcv(symbol, interval, start, end)
                if df is not None and not df.empty:
                    if best_df is None or len(df) > len(best_df):
                        best_df = df
                        best_source = type(provider).__name__
            except Exception as exc:
                logger.debug(
                    "Provider %s failed for %s: %s",
                    type(provider).__name__, symbol, exc,
                )
                continue

        if best_df is None or best_df.empty:
            raise DataProviderError(
                f"No data available for {symbol} from any provider "
                f"({', '.join(self.provider_names)})"
            )

        logger.info(
            "Best data for %s: %s (%d rows) from %s",
            symbol, interval, len(best_df), best_source,
        )
        return best_df


def create_aggregated_provider(
    broker_accounts: list | None = None,
    *,
    api_keys: dict[str, str] | None = None,
) -> AggregatedDataProvider:
    """Create an AggregatedDataProvider with all available sources.

    Always includes Yahoo Finance + CoinGecko. Adds keyed providers
    based on *api_keys* if supplied (DB-resolved, see ATS-1592), with
    fallback to ``.env`` settings when a key is not provided.

    Args:
        broker_accounts: Optional list of BrokerAccountDB to add as
            broker-data providers (Alpaca).
        api_keys: Optional ``{provider_id: api_key}`` map. Empty values
            and missing keys fall through to the legacy ``.env``
            settings. To inject DB-resolved keys, use
            :func:`create_aggregated_provider_for_user` which awaits
            the resolver.
    """
    api_keys = api_keys or {}

    # ATS-2004 — in determinism mode, *only* the frozen snapshot is used so
    # network providers can never introduce nondeterminism.
    if _determinism_mode_active():
        logger.info(
            "BACKTEST_DETERMINISM_MODE active — using FrozenSnapshotProvider only."
        )
        return AggregatedDataProvider([FrozenSnapshotProvider()])

    def _key(provider_id: str, env_attr: str) -> str:
        # DB key (passed via api_keys) wins; otherwise read from .env-backed settings.
        return api_keys.get(provider_id) or getattr(settings, env_attr, "") or ""

    providers: list[DataProvider] = []

    # Always include Yahoo Finance (free, no key needed)
    providers.append(YahooProvider())

    # CoinGecko (free, crypto)
    providers.append(CoinGeckoProvider())

    # Alpha Vantage if key available (DB > env)
    av_key = _key("alpha_vantage", "alpha_vantage_api_key")
    if av_key:
        providers.append(AlphaVantageProvider(api_key=av_key))

    # Polygon.io
    poly_key = _key("polygon", "polygon_api_key")
    if poly_key:
        providers.append(PolygonProvider(api_key=poly_key))

    # Twelve Data
    td_key = _key("twelve_data", "twelve_data_api_key")
    if td_key:
        providers.append(TwelveDataProvider(api_key=td_key))

    # Finnhub
    fh_key = _key("finnhub", "finnhub_api_key")
    if fh_key:
        providers.append(FinnhubProvider(api_key=fh_key))

    # Tiingo
    tiingo_key = _key("tiingo", "tiingo_api_key")
    if tiingo_key:
        providers.append(TiingoProvider(api_key=tiingo_key))

    # Broker-based providers
    if broker_accounts:
        for acct in broker_accounts:
            if acct.broker_type == "alpaca" and acct.api_key and acct.api_secret:
                providers.append(AlpacaDataProvider(
                    api_key=acct.api_key,
                    secret_key=acct.api_secret,
                ))

    logger.info(
        "Created AggregatedDataProvider with %d sources: %s",
        len(providers),
        [type(p).__name__ for p in providers],
    )
    return AggregatedDataProvider(providers)


# NOTE (standalone backtesting-agent): the upstream
# ``create_aggregated_provider_for_user`` resolved per-user data-provider
# keys from the DB (DataProviderDB + key_resolver). The standalone has no
# users/auth — keys come from .env via Settings — so that async variant is
# omitted. Use ``create_aggregated_provider`` with explicit api_keys instead.


def create_provider(name: str = "yahoo", **kwargs) -> DataProvider:
    """Factory function to create a data provider by name.

    Args:
        name: Provider name — "yahoo" or "alphavantage".
        **kwargs: Extra arguments forwarded to the provider constructor.

    Returns:
        A DataProvider instance.

    Raises:
        ValueError: If the provider name is unknown.
    """
    name_lower = name.lower().strip()
    if name_lower == "yahoo":
        return YahooProvider()
    elif name_lower in ("alphavantage", "alpha_vantage"):
        return AlphaVantageProvider(**kwargs)
    elif name_lower in ("frozen", "snapshot", "frozen_snapshot"):
        # ATS-2004 — explicit frozen-snapshot provider for golden runs.
        return FrozenSnapshotProvider(**kwargs)
    else:
        raise ValueError(
            f"Unknown data provider '{name}'. Supported: yahoo, alphavantage, frozen"
        )
