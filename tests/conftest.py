"""Shared pytest fixtures for the verification harness (Phase 0, ATS-1794).

The legacy broker `MockBroker` fixture was removed with the `broker` package. This root conftest now
provides the €0/offline/deterministic harness fixtures used across the remediation test suite:

- `db_session`     — ephemeral in-memory SQLite with all tables created (never touches prod).
- `frozen_ohlcv`   — a `fetch_fn` serving deterministic offline OHLCV (pass to `run_research`).
- `mock_provider`  — a registered MockProvider instance (inspect `.calls`); AI path routes to it.
- `_clean_registry`— autouse: isolates the module-level AI provider registry between tests.

Existing kept tests (ai/research, ai, auth, backtesting, db) may still bring their own fixtures.
"""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.backend.db.init_db import create_tables, drop_tables


@pytest.fixture(autouse=True)
def _clean_registry():
    """Snapshot and restore the module-level AI provider registry so a mock registered in one test
    never leaks into another."""
    from src.backend.ai import registry

    types_snap = dict(registry._PROVIDER_TYPES)  # noqa: SLF001
    inst_snap = dict(registry._INSTANCES)  # noqa: SLF001
    try:
        yield
    finally:
        registry._PROVIDER_TYPES.clear()  # noqa: SLF001
        registry._PROVIDER_TYPES.update(types_snap)  # noqa: SLF001
        registry._INSTANCES.clear()  # noqa: SLF001
        registry._INSTANCES.update(inst_snap)  # noqa: SLF001


@pytest.fixture
async def db_session():
    """Ephemeral in-memory DB with all tables; dropped and disposed after the test."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    await create_tables(engine)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await drop_tables(engine)
    await engine.dispose()


@pytest.fixture
def frozen_ohlcv():
    """A `fetch_fn(security_id, start, end)` serving deterministic offline OHLCV."""
    from tests.support.frozen_data import frozen_fetch

    return frozen_fetch()


@pytest.fixture
def mock_provider():
    """A registered MockProvider instance named 'mock-provider' (inspect `.calls`)."""
    from tests.support.factories import register_mock_provider

    return register_mock_provider()
