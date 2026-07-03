"""Tests for ATS-1771/1772/1773 — Agent trial budgets."""

import pytest

from src.backend.ai.research.budgets import (
    AgentBudgetController,
    BudgetExceededError,
    BudgetLimits,
)


class TestAgentBudgetController:
    def test_allows_within_limit(self):
        ctrl = AgentBudgetController(BudgetLimits(max_trials_per_hypothesis=5))
        for i in range(5):
            ctrl.check_and_consume("agent_1", "hyp_1", "lin_1")

    def test_blocks_at_hypothesis_limit(self):
        ctrl = AgentBudgetController(BudgetLimits(max_trials_per_hypothesis=3))
        for i in range(3):
            ctrl.check_and_consume("agent_1", "hyp_1", "lin_1")
        with pytest.raises(BudgetExceededError, match="Hypothesis budget"):
            ctrl.check_and_consume("agent_1", "hyp_1", "lin_1")

    def test_new_hypothesis_resets_counter(self):
        ctrl = AgentBudgetController(BudgetLimits(max_trials_per_hypothesis=3))
        for i in range(3):
            ctrl.check_and_consume("agent_1", "hyp_1", "lin_1")
        # New hypothesis resets.
        ctrl.check_and_consume("agent_1", "hyp_2", "lin_1")

    def test_daily_lineage_limit(self):
        ctrl = AgentBudgetController(BudgetLimits(max_trials_per_lineage_per_day=5))
        for i in range(5):
            ctrl.check_and_consume("agent_1", f"hyp_{i}", "lin_1")
        with pytest.raises(BudgetExceededError, match="Daily lineage"):
            ctrl.check_and_consume("agent_1", "hyp_99", "lin_1")

    def test_mutation_limit(self):
        ctrl = AgentBudgetController(BudgetLimits(max_mutations_after_failed_gate=2))
        ctrl.check_and_consume("agent_1", "hyp_1", "lin_1", is_mutation_after_failure=True)
        ctrl.check_and_consume("agent_1", "hyp_1", "lin_1", is_mutation_after_failure=True)
        with pytest.raises(BudgetExceededError, match="Mutation budget"):
            ctrl.check_and_consume("agent_1", "hyp_1", "lin_1", is_mutation_after_failure=True)

    def test_remaining_budget(self):
        ctrl = AgentBudgetController(BudgetLimits(max_trials_per_hypothesis=10))
        ctrl.check_and_consume("agent_1", "hyp_1", "lin_1")
        rem = ctrl.remaining("agent_1")
        assert rem["hypothesis_remaining"] == 9

    def test_denial_reason_clear(self):
        ctrl = AgentBudgetController(BudgetLimits(max_trials_per_hypothesis=1))
        ctrl.check_and_consume("agent_1", "hyp_1", "lin_1")
        with pytest.raises(BudgetExceededError) as exc_info:
            ctrl.check_and_consume("agent_1", "hyp_1", "lin_1")
        assert "hyp_1" in str(exc_info.value)
