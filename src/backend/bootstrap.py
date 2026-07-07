"""Application composition root — database schema bootstrap (standalone research agent).

Side-effect-imports the ORM model modules so they register on ``Base.metadata``, then creates
tables + runs idempotent column migrations. Legacy owner modules (broker / trading / event_context /
data_providers) were trimmed from the standalone agent, so only the keep-set is registered here.
"""
from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine

from src.backend.db.base import Base

# Register the keep-set owner tables on Base.metadata (auth / backtesting / marketdata / ai / research).
from src.backend.auth import db_models as _auth_models  # noqa: F401
from src.backend.backtesting import db_models as _bt_models  # noqa: F401
from src.backend.marketdata import db_models as _md_models  # noqa: F401
from src.backend.ai import db_models as _ai_models  # noqa: F401
from src.backend.ai.research import db_models as _research_models  # noqa: F401

logger = logging.getLogger(__name__)

# Idempotent column adds for existing DBs (kept for the research + ai_providers tables only).
_MIGRATIONS = [
    ("ai_providers", "user_id", "INTEGER"),
    ("research_runs", "report_json", "TEXT DEFAULT '{}'"),
    ("research_candidates", "artifacts_json", "TEXT DEFAULT '{}'"),
    ("research_failures", "hypothesis_id", "VARCHAR(64) DEFAULT ''"),
    ("research_failures", "params_json", "TEXT DEFAULT '{}'"),
    ("research_candidates", "hypothesis_id", "VARCHAR(64) DEFAULT ''"),
    ("research_candidates", "params_json", "TEXT DEFAULT '{}'"),
    ("research_runs", "agent_mode", "VARCHAR(20) DEFAULT 'rule_based'"),
    ("research_runs", "provider", "VARCHAR(60) DEFAULT ''"),
    ("research_runs", "model", "VARCHAR(80) DEFAULT ''"),
    ("research_runs", "seed", "INTEGER DEFAULT 0"),
    ("research_runs", "rigor", "VARCHAR(20) DEFAULT ''"),
    ("research_runs", "enable_oos", "BOOLEAN DEFAULT 0"),
    ("research_runs", "mode", "VARCHAR(20) DEFAULT 'robustness'"),
    ("research_runs", "window_start", "VARCHAR(20) DEFAULT ''"),
    ("research_runs", "window_end", "VARCHAR(20) DEFAULT ''"),
    ("research_candidates", "validation_status", "VARCHAR(20) DEFAULT ''"),
    ("research_candidates", "confidence", "VARCHAR(20) DEFAULT ''"),
    ("research_candidates", "decay_json", "TEXT DEFAULT '{}'"),
    ("research_candidates", "weaknesses_json", "TEXT DEFAULT '[]'"),
    ("research_candidates", "holdout_json", "TEXT DEFAULT '{}'"),
    ("research_runs", "train_end", "VARCHAR(20) DEFAULT ''"),
    ("research_runs", "provider_type", "VARCHAR(30) DEFAULT ''"),
    # H31 (Phase 4B): the per-model leakage badge column. Was added to the ResearchRunDB ORM model but
    # left out of this idempotent auto-migration list, so on a PRESERVED prod DB the column was absent
    # after deploy and every full-entity `select(ResearchRunDB)` (GET /runs, /stats, load_report,
    # load_run_for_state) raised "no such column: research_runs.model_id" → hard 500, while
    # persist_snapshot silently no-op'd inside its swallow-all try/except. Adding it here auto-migrates
    # at next boot (matching provider_type) — no manual ALTER TABLE needed.
    ("research_runs", "model_id", "VARCHAR(60) DEFAULT ''"),
]


async def create_tables(engine: AsyncEngine) -> None:
    """Create all tables if they don't exist, then run migrations."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_run_migrations)


def _run_migrations(conn, **kwargs) -> None:
    """Add missing columns to existing tables (idempotent)."""
    insp = inspect(conn)
    for table, column, col_type in _MIGRATIONS:
        if not insp.has_table(table):
            continue
        existing = {c["name"] for c in insp.get_columns(table)}
        if column not in existing:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
            logger.info("Migration: added %s.%s", table, column)


async def drop_tables(engine: AsyncEngine) -> None:
    """Drop all tables. Use only in tests."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
