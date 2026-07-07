"""Phase 3 / cluster 3B — persistence integrity (H27, M47, M53).

- H27: `persist_snapshot` advanced the flush cursors BEFORE `session.commit()`; a failed commit rolled
  the rows back but left the cursors advanced → those events/candidates/failures were never retried
  and vanished from the durable audit trail. The cursors must advance only AFTER a successful commit.
- M47: a candidate was persisted with the RUN's flush-time lineage, so a candidate found just before a
  next-asset switch was attributed to the wrong lineage. It must carry its creation-time lineage.
- M53: `DateTime(timezone=True)` columns read back naive from SQLite; serialized without an offset the
  frontend parses them as LOCAL time. Every DB→JSON timestamp must be UTC-marked.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src.backend.ai.research import persistence
from src.backend.ai.research.db_models import ResearchCandidateDB
from src.backend.ai.research.persistence import _utc_iso
from src.backend.ai.research.router import RunRecord
from src.backend.ai.research.state import Candidate
from src.backend.db.init_db import create_tables, drop_tables

# (async tests run under asyncio_mode=auto — no module-wide mark, so the pure tests below stay sync)


# ── M53: pure unit — the UTC-marking helper ───────────────────────────

@pytest.mark.finding("M53")
def test_utc_iso_marks_naive_as_utc_and_passes_through_aware():
    naive = datetime(2026, 7, 5, 22, 0, 0)                      # SQLite round-trip strips tzinfo
    assert _utc_iso(naive).endswith("+00:00")
    aware = datetime(2026, 7, 5, 22, 0, 0, tzinfo=timezone.utc)
    assert _utc_iso(aware) == aware.isoformat()
    assert _utc_iso(None) is None


# ── M47: pure unit — a candidate carries its creation-time lineage ────

@pytest.mark.finding("M47")
def test_candidate_holds_creation_time_lineage():
    c = Candidate(strategy_hash="h", run_id="r", template_id="t", params={}, security_id="AAPL",
                  lineage_id="lin_created")
    assert c.lineage_id == "lin_created"


# ── H27 + M47 + M53: integration against a shared in-memory DB ────────

async def _shared_engine():
    # StaticPool → one connection, so the in-memory DB is visible across the separate sessions that
    # create_run_row / persist_snapshot / load_run_for_state each open.
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    await create_tables(engine)
    return engine


def _req():
    return SimpleNamespace(
        goal_text="g", asset_pool=["AAPL"], strategy_families=[], max_runs=5, max_eur=10.0,
        max_seconds=60, target_candidates=1, seed=42, rigor="standard", enable_oos=True,
    )


def _state_with_candidate():
    return SimpleNamespace(
        phase="executing", current_asset="AAPL",
        current_lineage_id="lin_flush",                        # the RUN's CURRENT lineage …
        budget=SimpleNamespace(used_runs=1, used_eur=0.0),
        train_end="", provider_type="",
        hypotheses=[], all_failures=[], oos_results=[], lineage_nodes=[],
        candidates=[Candidate(strategy_hash="h1", run_id="r1", template_id="sma", params={},
                              security_id="AAPL", lineage_id="lin_created")],  # … differs from the candidate's
    )


async def _raise_commit():
    raise RuntimeError("commit boom")


class _FailCommitCM:
    """Real session context manager with only `commit` overridden to raise (H27 injection)."""

    def __init__(self, real_factory):
        self._cm = real_factory()

    async def __aenter__(self):
        self._sess = await self._cm.__aenter__()
        self._sess.commit = _raise_commit
        return self._sess

    async def __aexit__(self, *a):
        return await self._cm.__aexit__(*a)


async def _candidate_rows(factory, goal_id):
    async with factory() as s:
        return (await s.execute(
            select(ResearchCandidateDB).where(ResearchCandidateDB.goal_id == goal_id)
        )).scalars().all()


@pytest.mark.finding("H27")
async def test_h27_failed_commit_does_not_advance_cursors_then_retry_persists(monkeypatch):
    engine = await _shared_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        monkeypatch.setattr(persistence, "async_session", factory)
        await persistence.create_run_row("g1", 1, _req())

        rec = RunRecord(goal_id="g1", user_id=1, state=_state_with_candidate(),
                        events=[{"kind": "execute", "payload": {"strategy_hash": "h1"}}])

        # 1) commit fails → cursors stay at 0, nothing durable (H27).
        monkeypatch.setattr(persistence, "async_session", lambda: _FailCommitCM(factory))
        await persistence.persist_snapshot(rec)
        assert rec.persisted_candidates == 0 and rec.persisted_events == 0
        assert await _candidate_rows(factory, "g1") == []

        # 2) retry with a working commit → cursors advance and the rows land (the lost rows are recovered).
        monkeypatch.setattr(persistence, "async_session", factory)
        await persistence.persist_snapshot(rec)
        assert rec.persisted_candidates == 1 and rec.persisted_events == 1
        rows = await _candidate_rows(factory, "g1")
        assert len(rows) == 1
        # M47: persisted with the candidate's CREATION lineage, not the run's flush-time lineage.
        assert rows[0].lineage_id == "lin_created"
    finally:
        await drop_tables(engine)
        await engine.dispose()


@pytest.mark.finding("M53")
async def test_m53_state_started_at_is_utc_marked(monkeypatch):
    engine = await _shared_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        monkeypatch.setattr(persistence, "async_session", factory)
        await persistence.create_run_row("g2", 7, _req())
        row = await persistence.load_run_for_state("g2", 7)
        assert isinstance(row["started_at"], str)
        assert row["started_at"].endswith("+00:00")            # not an offset-less local-looking string
    finally:
        await drop_tables(engine)
        await engine.dispose()


@pytest.mark.finding("M31")
async def test_train_end_round_trips_through_load_run_for_state(monkeypatch):
    # M31: regime candidate metrics are measured on the TRAIN slice [window_start, train_end], so the UI
    # needs train_end to label them (not the full window). Persist it and read it back through the DB row.
    engine = await _shared_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        monkeypatch.setattr(persistence, "async_session", factory)
        await persistence.create_run_row("g_m31", 3, _req())
        st = _state_with_candidate()
        st.train_end = "2022-06-01"                             # select-on-train split set by the loop
        await persistence.persist_snapshot(RunRecord(goal_id="g_m31", user_id=3, state=st, events=[]))
        row = await persistence.load_run_for_state("g_m31", 3)
        assert row["train_end"] == "2022-06-01"                 # pre-fix: KeyError (train_end absent)
    finally:
        await drop_tables(engine)
        await engine.dispose()
