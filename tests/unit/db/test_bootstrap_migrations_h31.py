"""Phase 4-review — H31-1: the model_id column is auto-migrated onto a preserved research_runs table.

H31 added `model_id` to the ResearchRunDB ORM model but omitted it from bootstrap._MIGRATIONS, so on a
PRESERVED prod DB (table already exists without the column) `create_all` never adds it and every
full-entity `select(ResearchRunDB)` raised "no such column: research_runs.model_id" → GET /runs, /stats
etc. hard-500, and persist_snapshot silently no-op'd. This test locks the auto-migration in.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect, text

from src.backend.bootstrap import _MIGRATIONS, _run_migrations


@pytest.mark.finding("H31")
def test_model_id_is_in_the_migration_list():
    # Guard: the sibling per-run leakage/identity columns must all be auto-migrated (not just some).
    research_cols = {col for (tbl, col, _type) in _MIGRATIONS if tbl == "research_runs"}
    assert "model_id" in research_cols          # pre-fix: absent → preserved DBs miss the column
    assert "provider_type" in research_cols     # its P2 sibling, which WAS present


@pytest.mark.finding("H31")
def test_model_id_column_is_auto_migrated_onto_an_existing_research_runs_table():
    engine = create_engine("sqlite://")   # in-memory
    # Simulate a preserved prod DB: research_runs already exists but predates the model_id column.
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE research_runs (id INTEGER PRIMARY KEY, provider_type VARCHAR(30))"
        ))
    with engine.begin() as conn:
        _run_migrations(conn)                                   # the idempotent boot migrator
        cols = {c["name"] for c in inspect(conn).get_columns("research_runs")}
    assert "model_id" in cols                                   # pre-fix: never added → read-path 500s

    # Idempotent: running it again is a no-op (no duplicate-column error).
    with engine.begin() as conn:
        _run_migrations(conn)
        cols2 = {c["name"] for c in inspect(conn).get_columns("research_runs")}
    assert "model_id" in cols2
