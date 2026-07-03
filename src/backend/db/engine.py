from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Default SQLite path: project root / data / trading.db
_DEFAULT_DB_PATH = Path(__file__).resolve().parents[3] / "data" / "trading.db"


def get_database_url(path: Path | None = None) -> str:
    db_path = path or _DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{db_path}"


engine = create_async_engine(
    get_database_url(),
    echo=False,
    connect_args={"check_same_thread": False},
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Sync engine for background workers (non-async context)
sync_engine = create_engine(
    f"sqlite:///{_DEFAULT_DB_PATH}",
    echo=False,
    connect_args={"check_same_thread": False},
)


async def get_session():
    """Dependency for FastAPI routes."""
    async with async_session() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
