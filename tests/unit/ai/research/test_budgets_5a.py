"""Phase 5 / cluster 5A — the anti-brute-force budget subsystem (H19, H20).

- H19: the per-hypothesis / mutation caps never fired — the loop keyed them on a fresh hyp_{uuid} every
  iteration (counter reset each call), and is_mutation was computed AFTER the prev-template update (always
  True). The loop now passes the stable lineage ROOT key, so the caps bind.
- H20: the per-lineage/day counter never reset on a lineage switch, so with a new lineage almost every
  iteration it acted as a GLOBAL ~100/day kill switch that silently terminated long runs.
"""
from __future__ import annotations

import pytest

from src.backend.ai.research.budgets import AgentBudgetController, BudgetExceededError, BudgetLimits


@pytest.mark.finding("H19")
def test_per_hypothesis_cap_fires_with_a_stable_key():
    # Staying on ONE family key (as the loop now passes the lineage root) → the per-hypothesis cap
    # actually binds. Pre-fix the loop passed a fresh uuid per call, resetting the counter every time.
    ctrl = AgentBudgetController(BudgetLimits(max_trials_per_hypothesis=3))
    for _ in range(3):
        ctrl.check_and_consume("strategist", "family1", "family1")
    with pytest.raises(BudgetExceededError):
        ctrl.check_and_consume("strategist", "family1", "family1")   # 4th exceeds the cap of 3


@pytest.mark.finding("H20")
def test_lineage_counter_resets_on_family_switch_no_global_kill():
    ctrl = AgentBudgetController(BudgetLimits(max_trials_per_lineage_per_day=3, max_trials_per_hypothesis=1000))
    for _ in range(3):
        ctrl.check_and_consume("strategist", "r1", "r1")     # fill family r1's daily-lineage budget
    # Switching to a new family resets the per-lineage counter → NOT a global kill switch.
    ctrl.check_and_consume("strategist", "r2", "r2")         # must not raise
    ctrl.check_and_consume("strategist", "r2", "r2")


@pytest.mark.finding("H20")
def test_same_family_still_hits_its_own_daily_lineage_cap():
    # The cap still binds WITHIN a family (it's a real cap, just not global).
    ctrl = AgentBudgetController(BudgetLimits(max_trials_per_lineage_per_day=3, max_trials_per_hypothesis=1000))
    with pytest.raises(BudgetExceededError):
        for _ in range(4):
            ctrl.check_and_consume("strategist", "r1", "r1")
