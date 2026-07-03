"""ATS-1713 — Event-sourced trial registry.

Append-only lifecycle tracking.  Current status is *derived* from events,
never stored as a mutable field.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.backend.backtesting.registry.models import (
    MetricsIndexRow,
    RunEventRow,
    RunRow,
    RunSpecRow,
    StrategyDefinitionRow,
)


class EventType(StrEnum):
    RUN_QUEUED = "RUN_QUEUED"
    RUN_STARTED = "RUN_STARTED"
    RUN_COMPLETED = "RUN_COMPLETED"
    RUN_FAILED_INFRA = "RUN_FAILED_INFRA"
    GATE_EVALUATED = "GATE_EVALUATED"
    GATE_FAILED = "GATE_FAILED"
    PASSED_IS = "PASSED_IS"
    PASSED_VALIDATION = "PASSED_VALIDATION"
    PROMOTION_APPROVED = "PROMOTION_APPROVED"
    OOS_EVALUATED = "OOS_EVALUATED"
    REPORT_RENDERED = "REPORT_RENDERED"


# Priority order for deriving current status from events.
_STATUS_PRIORITY = {
    EventType.OOS_EVALUATED: 10,
    EventType.PROMOTION_APPROVED: 9,
    EventType.PASSED_VALIDATION: 8,
    EventType.PASSED_IS: 7,
    EventType.GATE_FAILED: 6,
    EventType.RUN_FAILED_INFRA: 5,
    EventType.GATE_EVALUATED: 4,
    EventType.RUN_COMPLETED: 3,
    EventType.RUN_STARTED: 2,
    EventType.RUN_QUEUED: 1,
}

Scope = Literal["global", "lineage", "family"]


class TrialEventRegistry:
    """Append-only, event-sourced trial registry.

    All writes go through :meth:`append_event`.  Status is derived,
    never mutated.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    # ── writes ────────────────────────────────────────────────────

    def register_strategy(self, definition_json: str, **fields) -> None:
        """Insert a StrategyDefinitionRow if it doesn't already exist."""
        existing = self._session.get(
            StrategyDefinitionRow, fields["strategy_hash"]
        )
        if existing:
            return
        row = StrategyDefinitionRow(definition_json=definition_json, **fields)
        self._session.add(row)
        self._session.flush()

    def register_run_spec(self, run_spec_json: str, **fields) -> None:
        """Insert a RunSpecRow if it doesn't already exist."""
        existing = self._session.get(RunSpecRow, fields["run_spec_hash"])
        if existing:
            return
        row = RunSpecRow(run_spec_json=run_spec_json, **fields)
        self._session.add(row)
        self._session.flush()

    def register_run(self, **fields) -> str:
        """Insert a RunRow and return the run_id."""
        run_id = fields.get("run_id") or f"run_{uuid.uuid4().hex[:12]}"
        fields["run_id"] = run_id
        row = RunRow(**fields)
        self._session.add(row)
        self._session.flush()
        return run_id

    def append_event(
        self,
        run_id: str,
        event_type: EventType | str,
        payload_json: str = "{}",
    ) -> str:
        """Append an immutable lifecycle event. Returns the event_id."""
        event_id = f"evt_{uuid.uuid4().hex[:12]}"
        row = RunEventRow(
            event_id=event_id,
            run_id=run_id,
            event_type=str(event_type),
            payload_json=payload_json,
            created_at=datetime.now(timezone.utc),
        )
        self._session.add(row)
        self._session.flush()
        return event_id

    def record_metrics(self, run_id: str, **fields) -> None:
        """Insert a MetricsIndexRow for fast aggregation queries."""
        row = MetricsIndexRow(run_id=run_id, **fields)
        self._session.add(row)
        self._session.flush()

    # ── reads ─────────────────────────────────────────────────────

    def get_current_status(self, run_id: str) -> str | None:
        """Derive the current status from the highest-priority event."""
        stmt = select(RunEventRow.event_type).where(
            RunEventRow.run_id == run_id
        )
        event_types = [row[0] for row in self._session.execute(stmt)]
        if not event_types:
            return None
        return max(event_types, key=lambda et: _STATUS_PRIORITY.get(et, 0))

    def run_exists(self, run_spec_hash: str) -> bool:
        """Check if a run with this run_spec_hash already exists."""
        stmt = select(func.count()).select_from(RunRow).where(
            RunRow.run_spec_hash == run_spec_hash
        )
        return self._session.execute(stmt).scalar_one() > 0

    def audit_trial_count(self, scope: Scope = "global", key: str | None = None) -> int:
        """Count everything attempted — includes infra failures."""
        stmt = select(func.count()).select_from(RunRow)
        if scope == "lineage" and key:
            stmt = stmt.where(RunRow.lineage_id == key)
        return self._session.execute(stmt).scalar_one()

    def valid_research_trial_count(
        self, scope: Scope = "global", key: str | None = None
    ) -> int:
        """Count only trials that produced a return series (entered gate pipeline)."""
        stmt = select(func.count()).select_from(MetricsIndexRow)
        if scope == "lineage" and key:
            stmt = stmt.join(RunRow, RunRow.run_id == MetricsIndexRow.run_id)
            stmt = stmt.where(RunRow.lineage_id == key)
        return self._session.execute(stmt).scalar_one()

    def sharpe_distribution(
        self, scope: Scope = "global", key: str | None = None
    ) -> np.ndarray:
        """Return array of per-bar Sharpe ratios for DSR computation."""
        stmt = select(MetricsIndexRow.sharpe_perbar).where(
            MetricsIndexRow.sharpe_perbar.isnot(None)
        )
        if scope == "lineage" and key:
            stmt = stmt.join(RunRow, RunRow.run_id == MetricsIndexRow.run_id)
            stmt = stmt.where(RunRow.lineage_id == key)
        values = [row[0] for row in self._session.execute(stmt)]
        return np.array(values, dtype=np.float64)
