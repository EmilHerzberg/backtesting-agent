"""ATS-1780/1781 — OOS Lockbox service.

Separate evaluation that returns PASS/FAIL only. No metrics leaked.
Budget consumed per evaluation. Terminal outcome cannot be overwritten.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Session


class OOSOutcome(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


class LockboxBase(DeclarativeBase):
    pass


class OOSBudgetRow(LockboxBase):
    __tablename__ = "oos_budget"
    lineage_id = Column(String(64), primary_key=True)
    budget_total = Column(Integer, nullable=False, default=3)
    budget_used = Column(Integer, nullable=False, default=0)


class OOSResultRow(LockboxBase):
    __tablename__ = "oos_results"
    strategy_hash = Column(String(64), primary_key=True)
    lineage_id = Column(String(64), nullable=False)
    outcome = Column(String(4), nullable=False)  # PASS or FAIL
    evaluated_at = Column(String(32), nullable=False)


class PromotionToken:
    """Human approval token for OOS evaluation."""

    def __init__(self, approver: str, strategy_hash: str, lineage_id: str):
        self.token_id = f"promo_{uuid.uuid4().hex[:12]}"
        self.approver = approver
        self.strategy_hash = strategy_hash
        self.lineage_id = lineage_id
        self.approved_at = datetime.now(timezone.utc)


class BudgetExhaustedError(Exception):
    pass


class AlreadyEvaluatedError(Exception):
    pass


class OOSLockboxService:
    """OOS evaluation service.

    Uses a SEPARATE SQLite database file (oos_lockbox.db).
    Returns PASS or FAIL only. No metrics.
    """

    def __init__(self, db_path: str = "oos_lockbox.db"):
        self._engine = create_engine(f"sqlite:///{db_path}")
        LockboxBase.metadata.create_all(self._engine)

    def ensure_budget(self, lineage_id: str, total: int = 3) -> None:
        """Create a budget entry if it doesn't exist."""
        with Session(self._engine) as session:
            existing = session.get(OOSBudgetRow, lineage_id)
            if not existing:
                session.add(OOSBudgetRow(
                    lineage_id=lineage_id, budget_total=total, budget_used=0,
                ))
                session.commit()

    def remaining_budget(self, lineage_id: str) -> int:
        with Session(self._engine) as session:
            row = session.get(OOSBudgetRow, lineage_id)
            if not row:
                return 0
            return row.budget_total - row.budget_used

    def evaluate(
        self,
        token: PromotionToken,
        *,
        run_oos_backtest: Any = None,  # callable that returns bool (pass/fail)
    ) -> OOSOutcome:
        """Run the OOS evaluation.

        Args:
            token: Promotion token from human approval.
            run_oos_backtest: Callable that runs the actual OOS backtest
                internally and returns True (pass) or False (fail).
                The lockbox calls this but NEVER exposes its internals.

        Returns:
            OOSOutcome.PASS or OOSOutcome.FAIL — nothing else.

        Raises:
            BudgetExhaustedError: No remaining OOS budget for this lineage.
            AlreadyEvaluatedError: This strategy_hash already has a terminal result.
        """
        with Session(self._engine) as session:
            # Check for existing terminal result.
            existing = session.get(OOSResultRow, token.strategy_hash)
            if existing:
                raise AlreadyEvaluatedError(
                    f"Strategy {token.strategy_hash[:16]}... already evaluated: {existing.outcome}"
                )

            # Check and consume budget.
            budget = session.get(OOSBudgetRow, token.lineage_id)
            if not budget or budget.budget_used >= budget.budget_total:
                raise BudgetExhaustedError(
                    f"OOS budget exhausted for lineage {token.lineage_id}"
                )

            budget.budget_used += 1

            # Run the actual OOS evaluation (opaque to caller).
            # CRITICAL: catch ALL exceptions from the callable to prevent
            # metrics leaking via exception messages. Convert to FAIL.
            try:
                if run_oos_backtest is not None:
                    passed = run_oos_backtest()
                else:
                    passed = False
            except Exception:
                # Exception may contain OOS metrics in its message —
                # swallow it completely. The lockbox returns PASS/FAIL only.
                passed = False

            outcome = OOSOutcome.PASS if passed else OOSOutcome.FAIL

            # Record terminal result (atomic with budget consume).
            session.add(OOSResultRow(
                strategy_hash=token.strategy_hash,
                lineage_id=token.lineage_id,
                outcome=outcome.value,
                evaluated_at=datetime.now(timezone.utc).isoformat(),
            ))
            session.commit()

        return outcome
