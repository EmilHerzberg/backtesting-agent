"""ATS-2002 — add ``available_at`` columns to ``ec_events``.

This migration is idempotent: rerunning it on a schema that already has
the columns is a no-op. It also adds ``ec_event_sources.published_at`` so
the Source-Verifier (writeback in ATS-2003) can persist the publication
timestamp it extracts from URL responses.

Run automatically as part of :func:`src.backend.db.init_db.create_tables`
via the ``_run_migrations`` hook. Callers that want to invoke it
explicitly (e.g. an ad-hoc migration of an existing prod DB) can::

    from sqlalchemy.ext.asyncio import create_async_engine
    from src.backend.db.migrations.v3_2_001_available_at import (
        upgrade_async,
    )

    engine = create_async_engine("sqlite+aiosqlite:///path/to/db")
    await upgrade_async(engine)

Down-migration is provided for symmetry but only useful on databases
where the rest of the V3.2 schema can also be rolled back — see the
ticket DoD.
"""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


# Columns to add. (table, column, ddl-spec). The DDL must be SQLite-compatible
# because that is the only backend the Event-Context-System supports today.
_ADDITIONS: list[tuple[str, str, str]] = [
    ("ec_events", "available_at", "TIMESTAMP"),
    ("ec_events", "available_at_method", "VARCHAR(40) DEFAULT 'unknown'"),
    ("ec_events", "available_at_region", "VARCHAR(20) DEFAULT 'GLOBAL'"),
    ("ec_event_sources", "published_at", "TIMESTAMP"),
]

# Indexes to add (idempotent via IF NOT EXISTS, which SQLite supports).
_INDEXES: list[tuple[str, str, str]] = [
    ("ix_ec_events_available_at", "ec_events", "available_at"),
]


def upgrade(conn: Connection) -> None:
    """Apply the migration on a sync SQLAlchemy Connection.

    Idempotent: missing columns/indexes are added, existing ones skipped.
    """
    insp = inspect(conn)
    for table, column, ddl in _ADDITIONS:
        if not insp.has_table(table):
            logger.warning(
                "Migration v3_2_001: table %s does not exist, skipping %s",
                table, column,
            )
            continue
        existing = {c["name"] for c in insp.get_columns(table)}
        if column in existing:
            continue
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
        logger.info("Migration v3_2_001: added %s.%s", table, column)

    for index_name, table, column in _INDEXES:
        if not insp.has_table(table):
            continue
        conn.execute(
            text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table}({column})")
        )


def downgrade(conn: Connection) -> None:
    """Reverse the migration.

    SQLite's ``ALTER TABLE DROP COLUMN`` is only supported on >= 3.35.
    For older deployments the index is at least dropped so a subsequent
    upgrade re-creates it cleanly.
    """
    insp = inspect(conn)

    for index_name, _table, _column in _INDEXES:
        conn.execute(text(f"DROP INDEX IF EXISTS {index_name}"))

    for table, column, _ddl in reversed(_ADDITIONS):
        if not insp.has_table(table):
            continue
        existing = {c["name"] for c in insp.get_columns(table)}
        if column not in existing:
            continue
        try:
            conn.execute(text(f"ALTER TABLE {table} DROP COLUMN {column}"))
            logger.info("Migration v3_2_001 downgrade: dropped %s.%s", table, column)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Migration v3_2_001 downgrade: cannot drop %s.%s: %s",
                table, column, exc,
            )


async def upgrade_async(engine: AsyncEngine) -> None:
    """Convenience wrapper to apply :func:`upgrade` via an AsyncEngine."""
    async with engine.begin() as conn:
        await conn.run_sync(upgrade)


async def downgrade_async(engine: AsyncEngine) -> None:
    """Convenience wrapper for :func:`downgrade`."""
    async with engine.begin() as conn:
        await conn.run_sync(downgrade)
