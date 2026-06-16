"""Cache manager for backtesting data, backed by the PriceCacheDB table."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pandas as pd
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from backtesting_agent.db.models import Base, PriceCacheDB
from backtesting_agent.shared.config import settings
from backtesting_agent.shared.types import BarInterval
from backtesting_agent.marketdata.provider import (
    DataProvider,
    OHLCV_COLUMNS,
    create_provider,
)

logger = logging.getLogger(__name__)

# Default source tag for backtesting cache entries
_SOURCE = "yahoo"


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
            # Incremental update: only fetch data newer than latest cached bar
            latest_cached = cached_df.index.max().to_pydatetime()
            if hasattr(latest_cached, "tzinfo") and latest_cached.tzinfo:
                latest_cached = latest_cached.replace(tzinfo=None)
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            # If latest cached bar is more than 1 interval old, fetch new data
            gap_threshold = _interval_to_timedelta(interval) * 2
            if now - latest_cached > gap_threshold:
                incremental_start = latest_cached - timedelta(days=1)  # small overlap
                need_fetch = True
                fetch_start = incremental_start.replace(tzinfo=timezone.utc)

        if need_fetch:
            fresh_df = self._provider.fetch_ohlcv(symbol, interval, fetch_start, end)
            if not fresh_df.empty:
                self._store_cache(symbol, interval, fresh_df)
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
    ) -> None:
        """Persist DataFrame rows into PriceCacheDB, skipping existing timestamps."""
        with Session(self._engine) as session:
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
            existing_ts = {
                t.replace(tzinfo=None) if t.tzinfo else t for t in result
            }

            new_rows = []
            for ts, row in df.iterrows():
                dt = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
                if hasattr(dt, "tzinfo") and dt.tzinfo is not None:
                    dt_naive = dt.replace(tzinfo=None)
                    dt_utc = dt.astimezone(timezone.utc)
                else:
                    dt_naive = dt
                    dt_utc = dt.replace(tzinfo=timezone.utc) if hasattr(dt, "replace") else dt

                if dt_naive in existing_ts:
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
