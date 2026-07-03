"""Unit tests for the rule-based Director (DIRECTOR-REQUIREMENTS / -TECHNICAL-SPEC v2)."""

import inspect

import pytest

from src.backend.ai.research.loop import (
    DirectorConfig,
    RuleBasedOrchestrator,
    plateau,
)
from src.backend.ai.research.state import (
    Budget,
    Candidate,
    GoalBrief,
    OOSResult,
    ResearchState,
)


def _state(target=2, max_runs=20, max_seconds=3600, **kw):
    goal = GoalBrief(goal_text="t", asset_pool=["AAPL"], target_candidates=target, max_runs=max_runs)
    return ResearchState(goal=goal, budget=Budget(max_runs=max_runs, max_seconds=max_seconds), **kw)


def _cand(h):
    return Candidate(strategy_hash=h, run_id="r", template_id="sma", params={}, security_id="AAPL")


async def _decide(state, outcome="gate_fail", cfg=None):
    return await RuleBasedOrchestrator(cfg or DirectorConfig()).decide(state, outcome)


class TestPlateau:
    def test_few_samples_no_plateau(self):
        assert plateau([0.5, 0.5], window=4, eps=0.05) is False

    def test_flat_positive_plateau(self):
        assert plateau([0.5] * 4, window=4, eps=0.05) is True

    def test_flat_negative_plateau(self):
        # AC3 — sign-safe: a flat NEGATIVE streak is a plateau.
        assert plateau([-0.8] * 4, window=4, eps=0.05) is True

    def test_improving_not_plateau(self):
        assert plateau([0.1, 0.3, 0.6, 1.0], window=4, eps=0.05) is False


class TestDirectorRules:
    async def test_goal_met_before_budget(self):
        # T10 — goal+budget tie reports goal_met.
        state = _state(target=1, max_runs=1)
        state.candidates = [_cand("h1")]
        state.budget.used_runs = 1  # budget also exhausted
        d = await _decide(state, "candidate")
        assert (d.decision, d.reason) == ("done", "goal_met")

    async def test_budget_exhausted_runs(self):
        state = _state(target=5, max_runs=3)
        state.budget.used_runs = 3
        d = await _decide(state)
        assert (d.decision, d.reason) == ("done", "budget_exhausted")

    async def test_goal_met_oos_on_counts_pass_only(self):
        # C2/AC6 — with OOS on, only PASS counts.
        cfg = DirectorConfig(oos_enabled=True)
        state = _state(target=2)
        state.candidates = [_cand("h1"), _cand("h2")]
        state.oos_results = [OOSResult("h1", "l", "PASS")]
        d = await _decide(state, "candidate", cfg)
        assert d.decision != "done"  # only 1 PASS, need 2
        state.oos_results.append(OOSResult("h2", "l", "PASS"))
        d2 = await _decide(state, "candidate", cfg)
        assert (d2.decision, d2.reason) == ("done", "goal_met")

    async def test_circuit_breaker_next_asset(self):
        state = _state()
        state.asset_queue = ["MSFT"]
        state.consecutive_errors = 5
        d = await _decide(state, "error")
        assert (d.decision, d.reason) == ("next_asset", "circuit_breaker")

    async def test_circuit_breaker_last_asset_done(self):
        state = _state()  # queue empty
        state.consecutive_errors = 5
        d = await _decide(state, "error")
        assert (d.decision, d.reason) == ("done", "circuit_breaker_last")

    async def test_asset_exhausted_failures(self):
        state = _state()
        state.asset_queue = ["MSFT"]
        state.consecutive_failures = 12
        d = await _decide(state, "gate_fail")
        assert (d.decision, d.reason) == ("next_asset", "asset_exhausted")

    async def test_asset_exhausted_last_done(self):
        state = _state()  # single asset, no queue
        state.consecutive_failures = 12
        d = await _decide(state, "gate_fail")
        assert (d.decision, d.reason) == ("done", "asset_exhausted_last")

    async def test_fairness_cap_only_with_queue(self):
        # AC4/AC5/C3 — fairness cap fires only when another asset is queued.
        cfg = DirectorConfig(per_asset_cap=5)
        state = _state()
        state.attempts_on_current_asset = 5
        d_no = await _decide(state, "gate_fail", cfg)        # no queue → must NOT stop the only asset
        assert d_no.decision == "continue"
        state.asset_queue = ["MSFT"]
        d_yes = await _decide(state, "gate_fail", cfg)       # queue present → fairness cap
        assert (d_yes.decision, d_yes.reason) == ("next_asset", "fairness_cap")

    async def test_skipped_is_neutral(self):
        # T2 — 'skipped' yields the same decision as another neutral outcome.
        state = _state()
        d_skip = await _decide(state, "skipped")
        d_gate = await _decide(state, "gate_fail")
        assert d_skip.decision == d_gate.decision == "continue"

    async def test_continue_default(self):
        state = _state()
        d = await _decide(state, "gate_fail")
        assert d.decision == "continue"

    async def test_evidence_present(self):
        # AC7 — every decision carries a reason + evidence.
        state = _state()
        d = await _decide(state, "gate_fail")
        assert d.reason
        assert d.evidence and "remaining_runs" in d.evidence and "validated" in d.evidence


class TestThresholdsFromConfig:
    def test_thresholds_read_from_config(self):
        # AC10/T3 — thresholds come from DirectorConfig, not hardcoded literals in decide().
        src = inspect.getsource(RuleBasedOrchestrator.decide)
        for knob in ("cfg.per_asset_cap", "cfg.plateau_eps", "cfg.plateau_window",
                     "cfg.max_consecutive_failures", "cfg.error_breaker"):
            assert knob in src, f"{knob} not read from config in decide()"
        assert "0.05" not in src and "= 25" not in src and "= 12" not in src
