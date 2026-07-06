"""Cache manager for backtesting data, backed by the PriceCacheDB table."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pandas as pd
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from src.backend.db.models import Base, PriceCacheDB
from src.backend.shared.config import settings
from src.backend.shared.types import BarInterval
from src.backend.marketdata.provider import (
    DataProvider,
    OHLCV_COLUMNS,
    create_provider,
)

logger = logging.getLogger(__name__)

# Default source tag for backtesting cache entries
_SOURCE = "yahoo"


def _to_naive_utc(dt):
    """Normalise a bar timestamp to naive-UTC — the representation cached rows round-trip as (SQLite
    drops tzinfo). Shared by the dedup key and the H21 replace-range bounds so both agree."""
    if hasattr(dt, "to_pydatetime"):
        dt = dt.to_pydatetime()
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.astimezone(timezone.utc)
    elif hasattr(dt, "replace"):
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.replace(tzinfo=None) if hasattr(dt, "replace") else dt


def _sync_db_url() -> str:
    """Convert the async database URL to a synchronous one."""
    url = settings.database_url
    if "aiosqlite" in url:
        url = url.replace("sqlite+aiosqlite", "sqlite")
    return url


class CacheManager:
    """Manages OHLCV data caching for backtesting.

    Uses a synchronous SQLAlchemy engine (backtesting is offline batch
    processing) and the existing PriceCacheDB table.
    """

    def __init__(
        self,
        provider: DataProvider | None = None,
        db_url: str | None = None,
        source: str = _SOURCE,
    ) -> None:
        self._provider = provider or create_provider("yahoo")
        self._source = source
        self._engine = create_engine(db_url or _sync_db_url())
        # Ensure tables exist (safe no-op if they already do)
        Base.metadata.create_all(self._engine)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def get_or_fetch(
        self,
        symbol: str,
        interval: BarInterval = BarInterval.ONE_DAY,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        """Return OHLCV data, using cache when available and fetching missing ranges.

        The returned DataFrame has a DatetimeIndex and columns:
        Open, High, Low, Close, Volume (all float).
        """
        cached_df = self._load_cache(symbol, interval, start, end)

        # Determine what we still need to fetch
        need_fetch = cached_df.empty
        fetch_start = start

        if not cached_df.empty and start is not None:
            earliest_cached = cached_df.index.min().to_pydatetime()
            if hasattr(earliest_cached, "tzinfo") and earliest_cached.tzinfo:
                earliest_cached = earliest_cached.replace(tzinfo=None)
            start_naive = start.replace(tzinfo=None) if start.tzinfo else start
            if earliest_cached > start_naive + timedelta(days=1):
                need_fetch = True

        if not cached_df.empty:
            latest_cached = cached_df.index.max().to_pydatetime()
            if hasattr(latest_cached, "tzinfo") and latest_cached.tzinfo:
                latest_cached = latest_cached.replace(tzinfo=None)
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            # If the latest cached bar is more than ~1 interval old, the cache is stale.
            gap_threshold = _interval_to_timedelta(interval) * 2
            if now - latest_cached > gap_threshold:
                need_fetch = True
                # H21: refetch the FULL requested window (fetch_start stays = start), never just the
                # tail — an auto-adjusted refresh re-bases the whole series, so a tail-append would
                # leave the cached head on a stale basis.

        if need_fetch:
            fresh_df = self._provider.fetch_ohlcv(symbol, interval, fetch_start, end)
            if not fresh_df.empty:
                # H21: replace the window's bars so the cached series is a single-basis snapshot.
                self._store_cache(symbol, interval, fresh_df, replace=True)
                # Reload from cache for consistent result
                cached_df = self._load_cache(symbol, interval, start, end)

        if cached_df.empty:
            return pd.DataFrame(columns=OHLCV_COLUMNS)

        return cached_df

    def invalidate(
        self,
        symbol: str,
        interval: BarInterval,
        older_than_days: int | None = None,
    ) -> int:
        """Remove cached bars. Returns count of deleted rows.

        Args:
            symbol: Ticker symbol.
            interval: Bar interval.
            older_than_days: If set, only delete bars older than this many days.
        """
        with Session(self._engine) as session:
            stmt = delete(PriceCacheDB).where(
                PriceCacheDB.symbol == symbol,
                PriceCacheDB.interval == interval.value,
                PriceCacheDB.source == self._source,
            )
            if older_than_days is not None:
                cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
                stmt = stmt.where(PriceCacheDB.timestamp < cutoff)

            result = session.execute(stmt)
            session.commit()
            count = result.rowcount  # type: ignore[union-attr]
            logger.info(
                "Invalidated %d cached bars for %s (%s)", count, symbol, interval
            )
            return count

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _load_cache(
        self,
        symbol: str,
        interval: BarInterval,
        start: datetime | None,
        end: datetime | None,
    ) -> pd.DataFrame:
        """Load cached bars from DB and return as DataFrame."""
        with Session(self._engine) as session:
            stmt = (
                select(PriceCacheDB)
                .where(
                    PriceCacheDB.symbol == symbol,
                    PriceCacheDB.interval == interval.value,
                    PriceCacheDB.source == self._source,
                )
                .order_by(PriceCacheDB.timestamp.asc())
            )
            if start is not None:
                stmt = stmt.where(PriceCacheDB.timestamp >= start)
            if end is not None:
                stmt = stmt.where(PriceCacheDB.timestamp <= end)

            rows = session.execute(stmt).scalars().all()

        if not rows:
            return pd.DataFrame(columns=OHLCV_COLUMNS)

        records = []
        for r in rows:
            ts = r.timestamp
            if ts.tzinfo is not None:
                ts = ts.replace(tzinfo=None)
            records.append({
                "Date": ts,
                "Open": float(r.open),
                "High": float(r.high),
                "Low": float(r.low),
                "Close": float(r.close),
                "Volume": int(r.volume),
            })

        df = pd.DataFrame(records)
        df = df.set_index("Date")
        df.index = pd.to_datetime(df.index)
        df.index.name = "Date"
        # Remove duplicates, keep last
        df = df[~df.index.duplicated(keep="last")]
        return df

    def _store_cache(
        self,
        symbol: str,
        interval: BarInterval,
        df: pd.DataFrame,
        *,
        replace: bool = False,
    ) -> None:
        """Persist DataFrame rows into PriceCacheDB, skipping existing timestamps.

        H21: with ``replace=True``, existing bars spanning ``df``'s range are deleted first, so the
        window is re-stored as a single-adjustment-basis snapshot instead of appending a re-based
        (auto-adjusted) tail onto stale bars — which produced a price discontinuity at the seam after
        every split/dividend.
        """
        with Session(self._engine) as session:
            if replace and not df.empty:
                lo = _to_naive_utc(df.index.min())
                hi = _to_naive_utc(df.index.max())
                session.execute(
                    delete(PriceCacheDB).where(
                        PriceCacheDB.symbol == symbol,
                        PriceCacheDB.interval == interval.value,
                        PriceCacheDB.source == self._source,
                        PriceCacheDB.timestamp >= lo,
                        PriceCacheDB.timestamp <= hi,
                    )
                )
                session.commit()

            # Gather existing timestamps to avoid duplicates
            existing_stmt = (
                select(PriceCacheDB.timestamp)
                .where(
                    PriceCacheDB.symbol == symbol,
                    PriceCacheDB.interval == interval.value,
                    PriceCacheDB.source == self._source,
                )
            )
            result = session.execute(existing_stmt).scalars().all()
            # H23: the dedup key must be naive-UTC — the SAME representation the row round-trips as.
            # SQLite drops tzinfo, so a stored UTC bar reads back naive-UTC (e.g. 05:00). The old code
            # keyed new rows on naive-LOCAL time (00:00 NY), which never matched the stored 05:00, so
            # every overlapping bar was re-inserted (IntegrityError / duplicate rows) on real yfinance data.
            existing_ts = {
                (t.astimezone(timezone.utc) if t.tzinfo else t).replace(tzinfo=None) for t in result
            }

            new_rows = []
            for ts, row in df.iterrows():
                dt = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
                if hasattr(dt, "tzinfo") and dt.tzinfo is not None:
                    dt_utc = dt.astimezone(timezone.utc)
                else:
                    dt_utc = dt.replace(tzinfo=timezone.utc) if hasattr(dt, "replace") else dt
                dt_key = dt_utc.replace(tzinfo=None) if hasattr(dt_utc, "replace") else dt_utc

                if dt_key in existing_ts:
                    continue

                new_rows.append(PriceCacheDB(
                    symbol=symbol,
                    timestamp=dt_utc,
                    interval=interval.value,
                    open=Decimal(str(round(float(row["Open"]), 6))),
                    high=Decimal(str(round(float(row["High"]), 6))),
                    low=Decimal(str(round(float(row["Low"]), 6))),
                    close=Decimal(str(round(float(row["Close"]), 6))),
                    volume=int(row["Volume"]),
                    source=self._source,
                ))

            if new_rows:
                session.add_all(new_rows)
                session.commit()
                logger.info(
                    "Stored %d new bars for %s (%s) in cache",
                    len(new_rows), symbol, interval,
                )


def _interval_to_timedelta(interval: BarInterval) -> timedelta:
    """Convert a BarInterval to an approximate timedelta."""
    mapping = {
        BarInterval.ONE_MIN: timedelta(minutes=1),
        BarInterval.FIVE_MIN: timedelta(minutes=5),
        BarInterval.FIFTEEN_MIN: timedelta(minutes=15),
        BarInterval.ONE_HOUR: timedelta(hours=1),
        BarInterval.ONE_DAY: timedelta(days=1),
    }
    return mapping.get(interval, timedelta(days=1))
