from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.db.models import PriceCacheDB
from src.backend.shared.types import BarInterval

logger = logging.getLogger(__name__)

_INTERVAL_MAP: dict[BarInterval, str] = {
    BarInterval.ONE_MIN: "1m",
    BarInterval.FIVE_MIN: "5m",
    BarInterval.FIFTEEN_MIN: "15m",
    BarInterval.ONE_HOUR: "1h",
    BarInterval.ONE_DAY: "1d",
}

# yfinance max period per interval
_PERIOD_MAP: dict[BarInterval, str] = {
    BarInterval.ONE_MIN: "7d",
    BarInterval.FIVE_MIN: "60d",
    BarInterval.FIFTEEN_MIN: "60d",
    BarInterval.ONE_HOUR: "730d",
    BarInterval.ONE_DAY: "max",
}

SOURCE = "yahoo"


async def get_cached_bars(
    session: AsyncSession,
    symbol: str,
    interval: BarInterval,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[PriceCacheDB]:
    """Fetch cached price bars from DB."""
    stmt = (
        select(PriceCacheDB)
        .where(
            PriceCacheDB.symbol == symbol,
            PriceCacheDB.interval == interval.value,
            PriceCacheDB.source == SOURCE,
        )
        .order_by(PriceCacheDB.timestamp.asc())
    )
    if start:
        stmt = stmt.where(PriceCacheDB.timestamp >= start)
    if end:
        stmt = stmt.where(PriceCacheDB.timestamp <= end)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def fetch_and_cache(
    session: AsyncSession,
    symbol: str,
    interval: BarInterval = BarInterval.ONE_DAY,
    period: str | None = None,
) -> list[PriceCacheDB]:
    """Download historical data from Yahoo Finance and cache in DB.

    Only inserts bars that don't already exist (based on unique constraint).
    Returns all cached bars for the symbol/interval.
    """
    yf_interval = _INTERVAL_MAP.get(interval, "1d")
    yf_period = period or _PERIOD_MAP.get(interval, "1 Y")

    # yfinance is synchronous — run in thread pool
    df = await asyncio.to_thread(
        _download_yahoo, symbol, yf_interval, yf_period
    )

    if df is None or df.empty:
        logger.warning("No data from Yahoo for %s (interval=%s)", symbol, interval)
        return await get_cached_bars(session, symbol, interval)

    # Find existing timestamps to avoid duplicates
    # SQLite may return naive datetimes, so normalize to naive UTC for comparison
    existing = await get_cached_bars(session, symbol, interval)
    existing_timestamps = {
        row.timestamp.replace(tzinfo=None)
        if row.timestamp.tzinfo is not None
        else row.timestamp
        for row in existing
    }

    new_rows = []
    for ts, row in df.iterrows():
        # Ensure timezone-aware UTC
        if hasattr(ts, "tzinfo") and ts.tzinfo is not None:
            dt = ts.to_pydatetime().astimezone(timezone.utc)
        else:
            dt = ts.to_pydatetime().replace(tzinfo=timezone.utc)

        # Compare as naive UTC
        if dt.replace(tzinfo=None) in existing_timestamps:
            continue

        new_rows.append(PriceCacheDB(
            symbol=symbol,
            timestamp=dt,
            interval=interval.value,
            open=Decimal(str(round(row["Open"], 6))),
            high=Decimal(str(round(row["High"], 6))),
            low=Decimal(str(round(row["Low"], 6))),
            close=Decimal(str(round(row["Close"], 6))),
            volume=int(row["Volume"]),
            source=SOURCE,
        ))

    if new_rows:
        session.add_all(new_rows)
        await session.commit()
        logger.info(
            "Cached %d new bars for %s (interval=%s, source=yahoo)",
            len(new_rows), symbol, interval,
        )

    return await get_cached_bars(session, symbol, interval)


def _download_yahoo(symbol: str, interval: str, period: str):
    """Synchronous Yahoo download — called via asyncio.to_thread."""
    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period, interval=interval)
    return df


async def get_latest_timestamp(
    session: AsyncSession,
    symbol: str,
    interval: BarInterval,
) -> datetime | None:
    """Get the most recent cached timestamp for a symbol."""
    stmt = (
        select(PriceCacheDB.timestamp)
        .where(
            PriceCacheDB.symbol == symbol,
            PriceCacheDB.interval == interval.value,
            PriceCacheDB.source == SOURCE,
        )
        .order_by(PriceCacheDB.timestamp.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    return row
