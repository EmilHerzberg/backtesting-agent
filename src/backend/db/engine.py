from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.backend.shared.config import settings

# Default SQLite path: project root / data / trading.db
_DEFAULT_DB_PATH = Path(__file__).resolve().parents[3] / "data" / "trading.db"


def get_database_url(path: Path | None = None) -> str:
    """The async SQLAlchemy URL.

    Honors ``DATABASE_URL`` (via settings — env var or .env) so a deploy / the E2E harness can point at a
    different database; an explicit ``path`` still wins (tooling/migrations). Falls back to the project-root
    ``data/trading.db``. Previously this ignored ``DATABASE_URL`` entirely and hardcoded the default path, so
    the deploy's ``DATABASE_URL`` was dead config that only "worked" because its value matched the default.
    """
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite+aiosqlite:///{path}"
    url = (getattr(settings, "database_url", "") or "").strip()
    if url:
        return url
    _DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{_DEFAULT_DB_PATH}"


def _sync_url_from(async_url: str) -> str:
    """Strip the async driver marker so the sync engine talks to the SAME database."""
    return async_url.replace("+aiosqlite", "")


_async_url = get_database_url()
_is_sqlite = _async_url.startswith("sqlite")
_connect_args = {"check_same_thread": False} if _is_sqlite else {}

engine = create_async_engine(_async_url, echo=False, connect_args=_connect_args)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Sync engine for background workers (non-async context) — same database as the async engine.
sync_engine = create_engine(_sync_url_from(_async_url), echo=False, connect_args=_connect_args)


def _apply_sqlite_pragmas(dbapi_conn, _rec):
    """SQLite concurrency hardening. The default rollback journal locks the WHOLE database on every write, so a
    request that writes while a background research run is also writing raises ``database is locked`` (a 500).
    WAL lets readers and one writer proceed concurrently; ``busy_timeout`` makes a would-be writer WAIT for the
    lock instead of erroring; ``synchronous=NORMAL`` is durable enough under WAL and much faster.
    """
    try:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=10000")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()
    except Exception:  # non-SQLite backend or an unsupported connection → leave defaults
        pass


if _is_sqlite:
    event.listen(engine.sync_engine, "connect", _apply_sqlite_pragmas)
    event.listen(sync_engine, "connect", _apply_sqlite_pragmas)


async def get_session():
    """Dependency for FastAPI routes."""
    async with async_session() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
