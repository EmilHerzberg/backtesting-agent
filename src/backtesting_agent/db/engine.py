"""Sync + async SQLAlchemy engines, driven by ``Settings.database_url``.

The async engine backs FastAPI routes (Phase 3); the sync engine backs
background workers / the quality-check path that run outside an event loop.
Both point at the same SQLite file by default
(``sqlite+aiosqlite:///data/backtest_agent.db``).
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backtesting_agent.shared.config import settings


def _async_url() -> str:
    """Resolve the async DB URL, ensuring the SQLite directory exists."""
    url = settings.database_url
    # Best-effort: create the parent dir for file-based SQLite URLs.
    prefix = "sqlite+aiosqlite:///"
    if url.startswith(prefix):
        db_path = Path(url[len(prefix):])
        db_path.parent.mkdir(parents=True, exist_ok=True)
    return url


def _sync_url(async_url: str) -> str:
    """Derive the sync URL from the async one (drop the async driver)."""
    return async_url.replace("+aiosqlite", "").replace("+asyncpg", "")


_ASYNC_URL = _async_url()
_SYNC_URL = _sync_url(_ASYNC_URL)

_is_sqlite = _ASYNC_URL.startswith("sqlite")
_connect_args = {"check_same_thread": False} if _is_sqlite else {}

engine = create_async_engine(_ASYNC_URL, echo=False, connect_args=_connect_args)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Sync engine for background workers / non-async contexts (e.g. quality_check).
sync_engine = create_engine(_SYNC_URL, echo=False, connect_args=_connect_args)


async def get_session():
    """FastAPI dependency yielding an async session."""
    async with async_session() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
