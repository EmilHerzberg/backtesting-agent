"""Account-settings Phase 1 — hard account deletion with a Base-agnostic cascade (F-7 / AS-2 / PS-1).

Enumerates every table that has a ``user_id`` column from the **live DB schema** (not a single ORM
``Base.metadata``), so no metadata/Base gap can leave orphaned rows — and it stays correct after the
backend legacy trim. Research children are goal_id-scoped (no ``user_id``) → deleted via the user's runs first.
"""

from __future__ import annotations

import logging

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.ai.research.db_models import (
    ResearchCandidateDB,
    ResearchEventDB,
    ResearchFailureDB,
    ResearchHypothesisDB,
    ResearchLineageDB,
    ResearchRunDB,
)
from src.backend.auth.db_models import UserDB

logger = logging.getLogger(__name__)

_RESEARCH_CHILDREN = (
    ResearchCandidateDB, ResearchEventDB, ResearchFailureDB,
    ResearchHypothesisDB, ResearchLineageDB,
)


async def user_id_tables(session: AsyncSession) -> list[str]:
    """Every table in the DB with a ``user_id`` column (Base-agnostic, via the live schema)."""
    names = [r[0] for r in (await session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))).all()]
    out: list[str] = []
    for t in names:
        cols = (await session.execute(text(f'PRAGMA table_info("{t}")'))).all()
        if any(c[1] == "user_id" for c in cols):
            out.append(t)
    return out


async def purge_user(session: AsyncSession, user_id: int) -> None:
    """Hard-delete a user and ALL their data (F-7). No tombstone (Q2)."""
    # (0) evict the user's OWN runtime providers from the in-memory registry so their key can't linger
    #     (only their own — never the shared/global user_id IS NULL ones).
    from src.backend.db.models import AIProviderDB
    from src.backend.ai.registry import remove_provider
    prov_names = [r[0] for r in (await session.execute(
        select(AIProviderDB.name).where(AIProviderDB.user_id == user_id))).all()]
    for name in prov_names:
        try:
            remove_provider(name)
        except Exception:  # noqa: BLE001 — registry cleanup must not block the delete
            pass

    # (1) research_* children (goal_id-scoped) — before the generic pass removes research_runs.
    goal_ids = [r[0] for r in (await session.execute(
        select(ResearchRunDB.goal_id).where(ResearchRunDB.user_id == user_id))).all()]
    if goal_ids:
        for T in _RESEARCH_CHILDREN:
            await session.execute(delete(T).where(T.goal_id.in_(goal_ids)))

    # (2) generic: every table carrying a user_id column (research_runs, ai_providers, + any legacy/future).
    for t in await user_id_tables(session):
        await session.execute(text(f'DELETE FROM "{t}" WHERE user_id = :uid'), {"uid": user_id})

    # (3) the user row itself (users keys on `id`, not `user_id`, so the generic pass skipped it).
    await session.execute(delete(UserDB).where(UserDB.id == user_id))
    await session.commit()


async def count_user_rows(session: AsyncSession, user_id: int) -> int:
    """Test/verification helper: total rows still keyed to this user across all user_id tables."""
    total = 0
    for t in await user_id_tables(session):
        n = (await session.execute(
            text(f'SELECT COUNT(*) FROM "{t}" WHERE user_id = :uid'), {"uid": user_id})).scalar() or 0
        total += int(n)
    return total
