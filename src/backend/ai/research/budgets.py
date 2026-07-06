"""ATS-1771/1772/1773 — Agent trial budgets.

Prevents brute-force parameter mutation and fake discovery.
Enforced before execution by the tool interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone


class BudgetExceededError(Exception):
    """Raised when an agent exceeds its trial budget."""
    pass


@dataclass
class BudgetLimits:
    """Configurable budget limits per agent."""

    max_trials_per_hypothesis: int = 25
    max_trials_per_lineage_per_day: int = 100
    max_mutations_after_failed_gate: int = 10
    max_batch_size: int = 250


@dataclass
class BudgetUsage:
    """Tracks usage against limits."""

    trials_this_hypothesis: int = 0
    trials_this_lineage_today: int = 0
    mutations_after_failure: int = 0
    current_hypothesis_id: str = ""
    current_lineage_id: str = ""
    current_date: date = field(default_factory=lambda: datetime.now(timezone.utc).date())

    def _maybe_reset_daily(self) -> None:
        today = datetime.now(timezone.utc).date()
        if today != self.current_date:
            self.trials_this_lineage_today = 0
            self.current_date = today


class AgentBudgetController:
    """Enforces trial budgets before allowing a run submission."""

    def __init__(self, limits: BudgetLimits | None = None):
        self.limits = limits or BudgetLimits()
        self._usage: dict[str, BudgetUsage] = {}  # agent_id → usage

    def _get_usage(self, agent_id: str) -> BudgetUsage:
        if agent_id not in self._usage:
            self._usage[agent_id] = BudgetUsage()
        usage = self._usage[agent_id]
        usage._maybe_reset_daily()
        return usage

    def check_and_consume(
        self,
        agent_id: str,
        hypothesis_id: str,
        lineage_id: str,
        is_mutation_after_failure: bool = False,
    ) -> None:
        """Check budget and consume one trial.

        Raises BudgetExceededError with a clear reason if any limit is hit.
        """
        usage = self._get_usage(agent_id)

        # Track hypothesis switches.
        if usage.current_hypothesis_id != hypothesis_id:
            usage.current_hypothesis_id = hypothesis_id
            usage.trials_this_hypothesis = 0
            usage.mutations_after_failure = 0

        if usage.current_lineage_id != lineage_id:
            usage.current_lineage_id = lineage_id
            usage.trials_this_lineage_today = 0   # H20: reset per-lineage — the counter never reset on a
            # lineage switch, so with the loop minting a new lineage nearly every iteration it acted as a
            # GLOBAL ~100/day kill switch that silently terminated long runs. (Keyed on the lineage ROOT
            # by the caller, so it now counts per hypothesis-family, not per per-call uuid.)

        # Check limits.
        if usage.trials_this_hypothesis >= self.limits.max_trials_per_hypothesis:
            raise BudgetExceededError(
                f"Hypothesis budget exhausted: {usage.trials_this_hypothesis}/"
                f"{self.limits.max_trials_per_hypothesis} trials for hypothesis {hypothesis_id}"
            )

        if usage.trials_this_lineage_today >= self.limits.max_trials_per_lineage_per_day:
            raise BudgetExceededError(
                f"Daily lineage budget exhausted: {usage.trials_this_lineage_today}/"
                f"{self.limits.max_trials_per_lineage_per_day} trials today for lineage {lineage_id}"
            )

        if is_mutation_after_failure and usage.mutations_after_failure >= self.limits.max_mutations_after_failed_gate:
            raise BudgetExceededError(
                f"Mutation budget exhausted: {usage.mutations_after_failure}/"
                f"{self.limits.max_mutations_after_failed_gate} mutations after gate failure"
            )

        # Consume.
        usage.trials_this_hypothesis += 1
        usage.trials_this_lineage_today += 1
        if is_mutation_after_failure:
            usage.mutations_after_failure += 1

    def remaining(self, agent_id: str) -> dict[str, int]:
        """Return remaining budget for an agent."""
        usage = self._get_usage(agent_id)
        return {
            "hypothesis_remaining": max(0, self.limits.max_trials_per_hypothesis - usage.trials_this_hypothesis),
            "lineage_daily_remaining": max(0, self.limits.max_trials_per_lineage_per_day - usage.trials_this_lineage_today),
            "mutation_remaining": max(0, self.limits.max_mutations_after_failed_gate - usage.mutations_after_failure),
        }
