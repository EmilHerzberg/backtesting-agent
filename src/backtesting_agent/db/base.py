from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import DeclarativeBase


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Single declarative base shared by every module's ORM models.

    Lives here (not in db/models.py) so a module's table models can
    ``from backtesting_agent.db.base import Base`` without importing the
    aggregate db/models.py — which lets tables live in their owner module
    (marketdata, results, ...) without circular imports.
    """

    pass
