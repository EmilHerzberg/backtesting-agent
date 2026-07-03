from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import DeclarativeBase


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Single declarative base shared by every module's ORM models.

    Lives here (not in db/models.py) so that a module's table models can
    ``from src.backend.db.base import Base`` without importing the monolithic
    db/models.py — which is what lets tables move into their owner modules
    without circular imports (Modularisation Phase 2). db/models.py re-exports
    ``Base`` and ``_utc_now`` so the historical import path keeps working.
    """

    pass
