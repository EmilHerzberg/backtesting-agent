"""ATS-1780/1781 — OOS Lockbox service.

Separate evaluation that returns PASS / FAIL / UNEVALUATED only. No metrics leaked.
Budget consumed per *terminal* evaluation (PASS/FAIL); an UNEVALUATED outcome (the
backtest could not be run, or the sample was too thin to judge) spends no budget and
writes no terminal row, so it can be retried. Terminal outcome cannot be overwritten.
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
    UNEVALUATED = "UNEVALUATED"  # H17: could not be evaluated / too few trades — NOT terminal, retryable


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


class OOSCampaignRow(LockboxBase):
    """FB4: the CAMPAIGN-wide fresh-data ledger. Per-lineage budgets stop one
    hypothesis from re-rolling its hold-out; this stops a campaign from doing
    the same across MANY lineages — every terminal OOS evaluation in a scope
    counts here, the count drives the Šidák-adjusted family bar, and the
    depletable cap turns volume into honest absence (UNEVALUATED), never into
    extra lottery tickets."""

    __tablename__ = "oos_campaign_ledger"
    scope_key = Column(String(64), primary_key=True)
    tests_terminal = Column(Integer, nullable=False, default=0)
    budget_total = Column(Integer, nullable=False, default=50)


# FB4 frozen constants (mirrored in docs/design/coverage-v2-gate-config.json +
# the tamper test): a campaign may spend at most CAMPAIGN_OOS_BUDGET terminal
# hold-out verdicts, and the family-wise false-PASS rate across the WHOLE budget
# is held at CAMPAIGN_ALPHA_FAMILY via the fixed budget-sized Šidák bar
# (every test faces t* ≈ 3.083 — see campaign_adjusted_t).
CAMPAIGN_OOS_BUDGET = 50
CAMPAIGN_ALPHA_FAMILY = 0.05


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

    def campaign_tests(self, scope_key: str) -> int:
        """FB4: how many terminal OOS verdicts this campaign scope has spent."""
        with Session(self._engine) as session:
            row = session.get(OOSCampaignRow, scope_key)
            return int(row.tests_terminal) if row else 0

    @staticmethod
    def campaign_adjusted_t(tests_so_far: int = 0) -> float:
        """FB4: the per-test one-sided t* holding the FAMILY-wise false-PASS rate
        across the campaign's ENTIRE budget at CAMPAIGN_ALPHA_FAMILY.

        Review fix (blocker): the earlier sequential scheme (m = spent+1) let
        early tests spend big alpha slices — measured FWER 20.6% at the 50-test
        budget, 4x the target. True control needs the FIXED budget-sized Šidák
        bar for EVERY test: alpha_i = 1-(1-alpha)^(1/BUDGET) → t* ≈ 3.083,
        giving FWER exactly ≤ alpha at full depletion and below it before.
        Constant by construction (also kills within-run order gaming); the
        ``tests_so_far`` arg is retained for interface stability and ignored."""
        import scipy.stats

        alpha_i = 1.0 - (1.0 - CAMPAIGN_ALPHA_FAMILY) ** (1.0 / CAMPAIGN_OOS_BUDGET)
        return float(max(scipy.stats.norm.ppf(1.0 - alpha_i), 1.645))

    def get_result(self, strategy_hash: str) -> OOSOutcome | None:
        """Return the stored *terminal* outcome for a strategy, or None if never evaluated.

        H16: lets a re-run recover the prior verdict instead of re-raising
        AlreadyEvaluatedError (which the caller swallowed, leaving the candidate PENDING
        forever). UNEVALUATED never persists a row, so it correctly reads back as None and
        is retried.
        """
        with Session(self._engine) as session:
            row = session.get(OOSResultRow, strategy_hash)
            return OOSOutcome(row.outcome) if row else None

    @staticmethod
    def _coerce(raw: Any) -> OOSOutcome:
        """Map the callable's return to an outcome. Accepts an OOSOutcome, its string value, or a
        bool for backward compatibility (True→PASS, False→FAIL)."""
        if isinstance(raw, OOSOutcome):
            return raw
        if isinstance(raw, str):
            return OOSOutcome(raw)
        return OOSOutcome.PASS if raw else OOSOutcome.FAIL

    def evaluate(
        self,
        token: PromotionToken,
        *,
        run_oos_backtest: Any = None,  # callable -> OOSOutcome (or bool for back-compat)
        campaign_scope: str | None = None,  # FB4: campaign ledger scope (None = layer inactive)
    ) -> OOSOutcome:
        """Run the OOS evaluation.

        Args:
            token: Promotion token from human approval.
            run_oos_backtest: Callable that runs the actual OOS backtest internally and returns
                an ``OOSOutcome`` (PASS / FAIL / UNEVALUATED) — or a bool for back-compat. The
                lockbox calls this but NEVER exposes its internals.

        Returns:
            OOSOutcome.PASS, .FAIL, or .UNEVALUATED — nothing else.

        Semantics:
            * PASS / FAIL are terminal: they consume one unit of budget and write a result row
              (atomic). A terminal result cannot be overwritten.
            * UNEVALUATED (callable returned UNEVALUATED, or raised — H17) is NOT terminal: no
              budget is spent and no row is written, so the candidate can be evaluated later once
              the data outage clears or a larger sample exists. An exception body is swallowed so
              no OOS metrics can leak through its message.

        Raises:
            BudgetExhaustedError: No remaining OOS budget for this lineage.
            AlreadyEvaluatedError: This strategy_hash already has a terminal result.
        """
        with Session(self._engine) as session:
            # A terminal result is final — never re-run it.
            existing = session.get(OOSResultRow, token.strategy_hash)
            if existing:
                raise AlreadyEvaluatedError(
                    f"Strategy {token.strategy_hash[:16]}... already evaluated: {existing.outcome}"
                )

            # Budget must be available up front (fail fast) — but is only *consumed* below on a
            # terminal outcome, so an infra failure never burns a scarce OOS evaluation.
            budget = session.get(OOSBudgetRow, token.lineage_id)
            if not budget or budget.budget_used >= budget.budget_total:
                raise BudgetExhaustedError(
                    f"OOS budget exhausted for lineage {token.lineage_id}"
                )

            # FB4: the CAMPAIGN cap, checked up front like the lineage budget. A depleted
            # campaign yields honest absence for every further candidate — more volume can
            # never buy more lottery tickets against the same hold-out data.
            campaign = None
            if campaign_scope is not None:
                campaign = session.get(OOSCampaignRow, campaign_scope)
                if campaign is None:
                    campaign = OOSCampaignRow(scope_key=campaign_scope,
                                              tests_terminal=0,
                                              budget_total=CAMPAIGN_OOS_BUDGET)
                    session.add(campaign)
                if campaign.tests_terminal >= campaign.budget_total:
                    raise BudgetExhaustedError(
                        f"FB4 campaign OOS budget exhausted for scope {campaign_scope}"
                    )

            # Run the actual OOS evaluation (opaque to caller).
            # H17: an exception means we COULD NOT evaluate — that is UNEVALUATED, never a terminal
            # FAIL. Swallow the body (it may embed OOS metrics) but do not consume budget or record.
            try:
                raw = run_oos_backtest() if run_oos_backtest is not None else OOSOutcome.FAIL
            except Exception:
                return OOSOutcome.UNEVALUATED

            outcome = self._coerce(raw)
            if outcome is OOSOutcome.UNEVALUATED:
                # Too thin to judge — not a failure. No budget, no row: retryable later.
                return OOSOutcome.UNEVALUATED

            # Terminal (PASS/FAIL): consume budget (lineage + FB4 campaign) and record the
            # result atomically.
            budget.budget_used += 1
            if campaign is not None:
                campaign.tests_terminal += 1
            session.add(OOSResultRow(
                strategy_hash=token.strategy_hash,
                lineage_id=token.lineage_id,
                outcome=outcome.value,
                evaluated_at=datetime.now(timezone.utc).isoformat(),
            ))
            session.commit()

        return outcome
