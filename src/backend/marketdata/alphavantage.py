"""ATS-68: Alpha Vantage data provider with DB caching."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.db.models import PriceCacheDB
from src.backend.shared.config import settings
from src.backend.shared.types import BarInterval

logger = logging.getLogger(__name__)

SOURCE = "alphavantage"

_INTERVAL_MAP: dict[BarInterval, str] = {
    BarInterval.ONE_MIN: "1min",
    BarInterval.FIVE_MIN: "5min",
    BarInterval.FIFTEEN_MIN: "15min",
    BarInterval.ONE_HOUR: "60min",
    BarInterval.ONE_DAY: "daily",
}


async def fetch_and_cache(
    session: AsyncSession,
    symbol: str,
    interval: BarInterval = BarInterval.ONE_DAY,
    api_key: str | None = None,
) -> list[PriceCacheDB]:
    """Download data from Alpha Vantage and cache in DB.

    Requires ALPHA_VANTAGE_API_KEY in environment or passed directly.
    Free tier: 25 requests/day.
    """
    key = api_key or getattr(settings, "alpha_vantage_api_key", "")
    if not key:
        logger.warning("No Alpha Vantage API key configured")
        return await get_cached_bars(session, symbol, interval)

    df = await asyncio.to_thread(_download_av, symbol, interval, key)

    if df is None or len(df) == 0:
        logger.warning("No data from Alpha Vantage for %s", symbol)
        return await get_cached_bars(session, symbol, interval)

    # Find existing to avoid duplicates
    existing = await get_cached_bars(session, symbol, interval)
    existing_timestamps = {
        row.timestamp.replace(tzinfo=None)
        if row.timestamp and row.timestamp.tzinfo
        else row.timestamp
        for row in existing
    }

    new_rows = []
    for ts_key, row in df.items():
        # Alpha Vantage JSON returns date strings like "2024-01-05"
        if isinstance(ts_key, str):
            dt = datetime.fromisoformat(ts_key).replace(tzinfo=timezone.utc)
        elif hasattr(ts_key, "to_pydatetime"):
            dt = ts_key.to_pydatetime()
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
        else:
            dt = ts_key
            if hasattr(dt, "tzinfo") and dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)

        dt_naive = dt.replace(tzinfo=None)
        if dt_naive in existing_timestamps:
            continue

        new_rows.append(PriceCacheDB(
            symbol=symbol,
            timestamp=dt,
            interval=interval.value,
            open=Decimal(str(row["1. open"])),
            high=Decimal(str(row["2. high"])),
            low=Decimal(str(row["3. low"])),
            close=Decimal(str(row["4. close"])),
            volume=int(row["5. volume"]),
            source=SOURCE,
        ))

    if new_rows:
        session.add_all(new_rows)
        await session.commit()
        logger.info(
            "Cached %d new bars for %s from Alpha Vantage",
            len(new_rows), symbol,
        )

    return await get_cached_bars(session, symbol, interval)


def _download_av(symbol: str, interval: BarInterval, api_key: str):
    """Synchronous Alpha Vantage download."""
    try:
        from alpha_vantage.timeseries import TimeSeries
        ts = TimeSeries(key=api_key, output_format="json")

        av_interval = _INTERVAL_MAP.get(interval, "daily")
        if av_interval == "daily":
            data, _ = ts.get_daily(symbol=symbol, outputsize="compact")
        else:
            data, _ = ts.get_intraday(
                symbol=symbol, interval=av_interval, outputsize="compact"
            )
        return data
    except Exception as e:
        logger.error("Alpha Vantage download failed for %s: %s", symbol, e)
        return None


async def get_cached_bars(
    session: AsyncSession,
    symbol: str,
    interval: BarInterval,
) -> list[PriceCacheDB]:
    """Fetch cached Alpha Vantage bars from DB."""
    result = await session.execute(
        select(PriceCacheDB)
        .where(
            PriceCacheDB.symbol == symbol,
            PriceCacheDB.interval == interval.value,
            PriceCacheDB.source == SOURCE,
        )
        .order_by(PriceCacheDB.timestamp.asc())
    )
    return list(result.scalars().all())
