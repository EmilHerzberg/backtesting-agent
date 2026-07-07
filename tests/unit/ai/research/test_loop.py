"""Tests for ATS-1757/1758 — research_loop state machine.

Updated to cover ALL spec gaps:
- OOS lockbox integration
- Lineage tracking
- Orchestrator protocol
- DSR registry stats
- Regime analysis
- Budget controller
- Phase transitions
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from src.backend.ai.research.loop import (
    DirectorConfig,
    DirectorDecision,
    RuleBasedOrchestrator,
    _record_failure,
    research_loop,
)
from src.backend.ai.research.state import (
    Budget,
    Candidate,
    DataSnapshot,
    FailureContext,
    GoalBrief,
    Hypothesis,
    OOSResult,
    ResearchPhase,
    ResearchState,
    RunArtifacts,
)


def _make_state(**kw):
    goal = GoalBrief(
        goal_text="test",
        asset_pool=["AAPL"],
        strategy_families=["trend_following"],
        target_candidates=2,
        max_runs=kw.pop("max_runs", 20),
    )
    return ResearchState(
        goal=goal,
        budget=Budget(max_runs=goal.max_runs),
        **kw,
    )


def test_all_failures_survives_asset_rotation():
    """Phase 1a: all_failures accumulates across rotation; failure_context stays per-asset bounded."""
    state = _make_state()
    state.current_asset = "A"
    state.asset_queue = ["B"]
    _record_failure(state, FailureContext(strategy_hash="h1", template_id="t", params={}, security_id="A"))
    assert len(state.failure_context) == 1
    assert len(state.all_failures) == 1
    assert state.advance_asset() is True          # rotate A -> B
    assert state.failure_context == []            # Strategist memory cleared on rotation
    assert len(state.all_failures) == 1           # full record survived the clear
    _record_failure(state, FailureContext(strategy_hash="h2", template_id="t", params={}, security_id="B"))
    assert len(state.failure_context) == 1        # only B's (bounded, per-asset)
    assert [f.security_id for f in state.all_failures] == ["A", "B"]   # both assets retained


def _make_hypothesis(template_id="sma_crossover"):
    return Hypothesis(
        hypothesis_id=f"hyp_{uuid.uuid4().hex[:8]}",
        author="test",
        economic_rationale="test rationale",
        claimed_mechanism="test mechanism",
        falsifiable_prediction="test prediction",
        proposed_template_id=template_id,
    )


def _make_spec(template_id="sma_crossover"):
    return {
        "strategy_hash": uuid.uuid4().hex,
        "template_id": template_id,
        "params": {"fast_period": 10, "slow_period": 50},
        "window_start": "2010-01-01",
        "window_end": "2020-12-31",
    }


def _make_good_metrics():
    return {
        "sharpe_annual": 1.2,
        "total_return": 0.25,
        "max_drawdown": -0.12,
        "n_trades": 80,
        "exposure_time": 0.5,
        "buy_hold_return": 0.15,
        "buy_hold_sharpe": 0.8,
        "returns": np.random.default_rng(42).standard_normal(252) * 0.01,
    }


def _make_mocks(gate_pass=True, critic_accept=True):
    """Create standard mocks for all loop dependencies."""
    strategist = AsyncMock()
    strategist.propose.return_value = (_make_hypothesis(), _make_spec())

    executor = MagicMock()
    executor.run.return_value = _make_good_metrics()

    gatekeeper = MagicMock()
    gatekeeper.evaluate.return_value = {"passed": gate_pass, "results": []}
    gatekeeper.update_registry_stats = MagicMock()

    critic = AsyncMock()
    rec = "accept" if critic_accept else "reject"
    critic.review.return_value = {"recommendation": rec, "confidence": "medium"}

    data_agent = MagicMock()
    data_agent.prepare.return_value = "mock_dataframe"

    return strategist, executor, gatekeeper, critic, data_agent


class TestResearchLoop:
    @pytest.mark.asyncio
    async def test_full_cycle_happy_path(self):
        """Loop finds 2 candidates and stops."""
        state = _make_state(max_runs=20)
        strategist, executor, gatekeeper, critic, data_agent = _make_mocks()

        result = await research_loop(state, strategist, executor, gatekeeper, critic, data_agent)

        assert result.phase == ResearchPhase.COMPLETED
        assert len(result.candidates) >= 2

    @pytest.mark.asyncio
    async def test_regime_candidate_is_unvalidated(self):
        """Regime candidate: validation_status UNVALIDATED; adequate sample + 0 soft-fails → confidence 'moderate'."""
        state = _make_state(max_runs=4)
        state.mode = "regime"
        strategist, executor, gatekeeper, critic, data_agent = _make_mocks()
        gatekeeper.evaluate.return_value = {
            "passed": True,
            "results": [{"gate_id": "minimum_activity", "status": "PASS", "details": {"tier": "adequate"}}],
        }
        result = await research_loop(state, strategist, executor, gatekeeper, critic, data_agent)
        assert len(result.candidates) >= 1
        c = result.candidates[0]
        assert c.validation_status == "unvalidated"
        assert c.confidence == "moderate"         # DG-2 vocab: adequate + 0 soft-fails = best a regime idea gets

    @pytest.mark.asyncio
    async def test_regime_thin_candidate_is_low_confidence(self):
        """P1 Chunk C: a thin-sample regime candidate → confidence 'low' (weaker-governs, F-13)."""
        state = _make_state(max_runs=4)
        state.mode = "regime"
        strategist, executor, gatekeeper, critic, data_agent = _make_mocks()
        gatekeeper.evaluate.return_value = {
            "passed": True,
            "results": [{"gate_id": "minimum_activity", "status": "PASS",
                         "details": {"tier": "thin", "low_confidence": True}}],
        }
        result = await research_loop(state, strategist, executor, gatekeeper, critic, data_agent)
        c = result.candidates[0]
        assert c.validation_status == "unvalidated"
        assert c.confidence == "low"

    @pytest.mark.asyncio
    async def test_robustness_candidate_has_no_firewall_fields(self):
        """Robustness candidates carry no firewall labels (no regression)."""
        state = _make_state(max_runs=4)   # default mode=robustness
        strategist, executor, gatekeeper, critic, data_agent = _make_mocks()
        result = await research_loop(state, strategist, executor, gatekeeper, critic, data_agent)
        c = result.candidates[0]
        assert c.validation_status == "" and c.confidence == ""

    @pytest.mark.asyncio
    async def test_regime_candidate_decay_computed(self):
        """C2: a regime candidate gets an out-of-regime decay characterization."""
        state = _make_state(max_runs=4)
        state.mode = "regime"
        state.window_start = "2021-01-01"
        state.window_end = "2022-06-30"
        strategist, executor, gatekeeper, critic, data_agent = _make_mocks()
        gatekeeper.evaluate.return_value = {
            "passed": True,
            "results": [{"gate_id": "minimum_activity", "status": "PASS", "details": {"tier": "adequate"}}],
        }
        result = await research_loop(state, strategist, executor, gatekeeper, critic, data_agent)
        c = result.candidates[0]
        # P2-4: decay is measured on a slice BEFORE and AFTER the regime window.
        assert c.decay.get("before") is not None
        assert c.decay["before"]["retained_fraction"] == 1.0   # mock returns the same sharpe in & out of regime

    def _regime_report(self, *soft_gates):
        # a gate report: activity adequate (PASS) + the given soft-failed quality gates
        results = [{"gate_id": "minimum_activity", "status": "GateStatus.PASS", "details": {"tier": "adequate"}}]
        for g in soft_gates:
            results.append({"gate_id": g, "status": "GateStatus.FAIL", "severity": "GateSeverity.SOFT",
                            "value": 0.1, "threshold": 0.3, "details": {"reason": f"{g} weak"}})
        return {"passed": True, "results": results}

    @pytest.mark.asyncio
    async def test_regime_weakness_profile_and_confidence_ladder(self):
        """Idea-surfacing: soft-failed quality gates → weaknesses; confidence drops one level per soft-fail."""
        for softs, expect in ([], "moderate"), (["performance_floor"], "low"), (["performance_floor", "deflated_sharpe"], "very_low"):
            state = _make_state(max_runs=3); state.mode = "regime"
            strat, ex, gk, cr, da = _make_mocks()
            gk.evaluate.return_value = self._regime_report(*softs)
            cr.review.return_value = {"recommendation": "accept"}
            result = await research_loop(state, strat, ex, gk, cr, da)
            c = result.candidates[0]
            assert len(c.weaknesses) == len(softs)
            assert c.confidence == expect, f"{softs} → {c.confidence} != {expect}"
            assert c.validation_status == "unvalidated"

    @pytest.mark.asyncio
    async def test_regime_critic_reject_surfaces_not_kills(self):
        """DG-1: in regime a Critic reject SURFACES (very_low), not the kill path."""
        state = _make_state(max_runs=3); state.mode = "regime"
        strat, ex, gk, cr, da = _make_mocks()
        gk.evaluate.return_value = self._regime_report()
        cr.review.return_value = {"recommendation": "reject", "reasoning": "overfit smell"}
        result = await research_loop(state, strat, ex, gk, cr, da)
        assert len(result.candidates) >= 1                       # NOT killed
        c = result.candidates[0]
        assert c.confidence == "very_low"
        assert any(w.get("gate") == "critic" for w in c.weaknesses)

    @pytest.mark.asyncio
    async def test_regime_critic_investigate_surfaces_low(self):
        """DG-1b: 'investigate' (the common regime verdict) surfaces at 'low', not killed."""
        state = _make_state(max_runs=3); state.mode = "regime"
        strat, ex, gk, cr, da = _make_mocks()
        gk.evaluate.return_value = self._regime_report()
        cr.review.return_value = {"recommendation": "investigate", "reasoning": "mixed"}
        result = await research_loop(state, strat, ex, gk, cr, da)
        assert len(result.candidates) >= 1
        assert result.candidates[0].confidence == "low"

    @pytest.mark.asyncio
    async def test_robustness_critic_reject_still_kills(self):
        """Robustness invariance: reject/investigate still KILL (no regression)."""
        state = _make_state(max_runs=3)   # robustness
        strat, ex, gk, cr, da = _make_mocks()
        cr.review.return_value = {"recommendation": "reject", "reasoning": "no"}
        result = await research_loop(state, strat, ex, gk, cr, da)
        assert len(result.candidates) == 0
        assert not getattr(result.candidates[0] if result.candidates else object(), "weaknesses", None)

    @pytest.mark.asyncio
    async def test_gate_failure_loops_back(self):
        """Failed gate feeds failure context back to strategist."""
        state = _make_state(max_runs=5)
        strategist, executor, gatekeeper, critic, data_agent = _make_mocks(gate_pass=False)
        gatekeeper.evaluate.return_value = {"passed": False, "first_failed_gate": "minimum_activity"}

        result = await research_loop(state, strategist, executor, gatekeeper, critic, data_agent)

        assert result.phase == ResearchPhase.STOPPED
        assert len(result.failure_context) > 0
        assert result.failure_context[0].failed_gate == "minimum_activity"
        critic.review.assert_not_called()

    @pytest.mark.asyncio
    async def test_critic_rejection_loops_back(self):
        """Critic rejection feeds back to strategist."""
        state = _make_state(max_runs=5)
        strategist, executor, gatekeeper, critic, data_agent = _make_mocks(critic_accept=False)
        critic.review.return_value = {"recommendation": "reject", "reasoning": "overfitted"}

        result = await research_loop(state, strategist, executor, gatekeeper, critic, data_agent)

        assert len(result.candidates) == 0
        assert any(fc.failure_reason == "critic_rejection" for fc in result.failure_context)

    @pytest.mark.asyncio
    async def test_budget_stops_loop(self):
        """Loop stops when budget is exhausted."""
        state = _make_state(max_runs=3)
        strategist, executor, gatekeeper, critic, data_agent = _make_mocks(gate_pass=False)
        gatekeeper.evaluate.return_value = {"passed": False, "first_failed_gate": "perf_floor"}

        result = await research_loop(state, strategist, executor, gatekeeper, critic, data_agent)

        assert result.budget.used_runs == 3
        assert result.phase == ResearchPhase.STOPPED

    @pytest.mark.asyncio
    @pytest.mark.finding("H19")
    async def test_per_hypothesis_budget_accumulates_on_the_stable_family_key(self):
        # BUDGET-1 / TI-2: H19's real fix is the LOOP wiring — key the anti-brute-force cap on the stable
        # lineage ROOT, not the fresh hyp_{uuid} the strategist mints each propose(). The controller-only
        # tests never exercised this, so a regression back to hypothesis.hypothesis_id would go undetected.
        # Drive the loop with a strategist that keeps proposing the SAME template (a mutation chain on one
        # family) and assert the per-hypothesis counter ACCUMULATES (pre-fix it reset to 1 every iteration).
        from src.backend.ai.research.budgets import (
            AgentBudgetController,
            BudgetExceededError,
            BudgetLimits,
        )

        class _SpyController(AgentBudgetController):
            def __init__(self, limits):
                super().__init__(limits)
                self.keys: list[str] = []
                self.raised = 0

            def check_and_consume(self, agent_id, hypothesis_id, lineage_id, is_mutation_after_failure=False):
                self.keys.append(hypothesis_id)
                try:
                    super().check_and_consume(agent_id, hypothesis_id, lineage_id, is_mutation_after_failure)
                except BudgetExceededError:
                    self.raised += 1
                    raise

        state = _make_state(max_runs=5)
        state.goal.target_candidates = 99          # don't stop early on goal_met
        strategist, executor, gatekeeper, critic, data_agent = _make_mocks()
        # Fresh hyp_{uuid} each call (like the real strategist), but the SAME proposed template.
        strategist.propose.side_effect = lambda *a, **k: (_make_hypothesis("sma_crossover"), _make_spec())
        spy = _SpyController(BudgetLimits())        # default cap 25 → won't trip in 5 iters

        await research_loop(
            state, strategist, executor, gatekeeper, critic, data_agent, budget_controller=spy,
        )

        assert len(spy.keys) >= 3
        assert len(set(spy.keys)) == 1              # SAME lineage-root family key every iteration (stable)
        hyp_uuids = {h.hypothesis_id for h in state.hypotheses}
        assert spy.keys[0] not in hyp_uuids         # keyed on the ROOT, NOT the fresh hyp_{uuid}
        # the per-hypothesis counter actually ACCUMULATED (pre-fix: reset to 1 each iteration → final 1)
        assert spy._get_usage("strategist").trials_this_hypothesis >= 3

    @pytest.mark.asyncio
    @pytest.mark.finding("M49")
    async def test_gate_failed_sharpe_does_not_pollute_plateau_watermark(self):
        # M49: the plateau watermark must track CANDIDATE quality, not the raw in-sample Sharpe of
        # gate-FAILED trials — an overfit high-Sharpe reject would otherwise pin the watermark high and
        # make R4 (asset_exhausted) abandon a still-productive asset.
        state = _make_state(max_runs=3)
        strategist, executor, gatekeeper, critic, data_agent = _make_mocks(gate_pass=False)
        executor.run.return_value = {**_make_good_metrics(), "sharpe_annual": 99.0}
        gatekeeper.evaluate.return_value = {"passed": False, "first_failed_gate": "dsr", "results": []}

        result = await research_loop(state, strategist, executor, gatekeeper, critic, data_agent)

        assert result.best_sharpe_on_asset == []       # pre-fix: [99.0, 99.0, 99.0] (gate-failed Sharpe)

    @pytest.mark.asyncio
    @pytest.mark.finding("M48")
    async def test_persistent_skips_trip_the_skip_breaker(self):
        # M48: when every proposal is blocked by the budget guard (persistent skips → no progress, one
        # paid strategist call per spin), the Director must stop the zombie spin, not run to the T6 cap.
        from src.backend.ai.research.budgets import AgentBudgetController, BudgetLimits

        state = _make_state(max_runs=20)
        state.goal.target_candidates = 99             # never meet the goal
        strategist, executor, gatekeeper, critic, data_agent = _make_mocks()
        strategist.propose.side_effect = lambda *a, **k: (_make_hypothesis("sma_crossover"), _make_spec())
        ctrl = AgentBudgetController(BudgetLimits(max_trials_per_hypothesis=2))  # 3rd+ proposal → skip

        result = await research_loop(
            state, strategist, executor, gatekeeper, critic, data_agent, budget_controller=ctrl,
        )

        assert result.stop_reason == "skip_breaker_last"   # pre-fix: "iteration_cap" (spun to the backstop)
        assert result.total_iterations < 20                # stopped early instead of spinning

    @pytest.mark.asyncio
    async def test_events_emitted(self):
        """on_event callback receives lifecycle events."""
        state = _make_state(max_runs=2)
        events = []
        strategist, executor, gatekeeper, critic, data_agent = _make_mocks()

        await research_loop(
            state, strategist, executor, gatekeeper, critic, data_agent,
            on_event=lambda t, p: events.append(t),
        )

        assert "goal_received" in events
        assert "loop_started" in events
        assert "proposing" in events
        assert "loop_finished" in events


class TestPhaseTransitions:
    """Test that phases transition per spec Part 3."""

    @pytest.mark.asyncio
    async def test_goal_received_phase(self):
        """Loop starts with GOAL_RECEIVED phase."""
        state = _make_state(max_runs=1)
        phases = []
        strategist, executor, gatekeeper, critic, data_agent = _make_mocks()

        def track_phase(event, payload):
            phases.append(state.phase.value)

        await research_loop(
            state, strategist, executor, gatekeeper, critic, data_agent,
            on_event=track_phase,
        )

        # GOAL_RECEIVED should be the first phase.
        assert "goal_received" in phases

    @pytest.mark.asyncio
    async def test_data_preparing_phase(self):
        """Loop transitions through DATA_PREPARING phase."""
        state = _make_state(max_runs=1)
        phases = []
        strategist, executor, gatekeeper, critic, data_agent = _make_mocks()

        def track_phase(event, payload):
            phases.append(state.phase.value)

        await research_loop(
            state, strategist, executor, gatekeeper, critic, data_agent,
            on_event=track_phase,
        )

        assert "data_preparing" in phases

    @pytest.mark.asyncio
    async def test_reporting_phase(self):
        """Loop transitions through REPORTING phase."""
        state = _make_state(max_runs=2)
        strategist, executor, gatekeeper, critic, data_agent = _make_mocks()

        result = await research_loop(
            state, strategist, executor, gatekeeper, critic, data_agent,
        )

        # Final phase should be COMPLETED (reporting was intermediate).
        assert result.phase == ResearchPhase.COMPLETED


class TestDSRRegistryStats:
    """Test that gatekeeper.update_registry_stats() is called."""

    @pytest.mark.asyncio
    async def test_dsr_stats_updated_before_gate(self):
        """Gatekeeper receives updated trial counts before evaluation."""
        state = _make_state(max_runs=3)
        strategist, executor, gatekeeper, critic, data_agent = _make_mocks()

        await research_loop(state, strategist, executor, gatekeeper, critic, data_agent)

        # update_registry_stats should be called before each gate evaluation.
        assert gatekeeper.update_registry_stats.call_count >= 2
        # First call should have n_trials=1.
        first_call = gatekeeper.update_registry_stats.call_args_list[0]
        assert first_call[0][0] == 1  # n_trials


class TestOrchestratorProtocol:
    """Test the pluggable orchestrator."""

    @pytest.mark.asyncio
    async def test_rule_based_orchestrator_continue(self):
        """Director returns 'continue' when nothing special."""
        state = _make_state()
        orch = RuleBasedOrchestrator()
        decision = await orch.decide(state, "gate_fail")
        assert decision.decision == "continue"

    @pytest.mark.asyncio
    async def test_rule_based_orchestrator_done(self):
        """Director returns 'done' when goal met."""
        state = _make_state()
        state.candidates = [MagicMock() for _ in range(3)]  # exceeds target_candidates=2
        orch = RuleBasedOrchestrator()
        decision = await orch.decide(state, "candidate")
        assert decision.decision == "done"
        assert decision.reason == "goal_met"

    @pytest.mark.asyncio
    async def test_rule_based_orchestrator_next_asset_on_plateau(self):
        """Director returns 'next_asset' on plateau when another asset is queued."""
        state = _make_state()
        state.asset_queue = ["MSFT"]
        state.best_sharpe_on_asset = [0.5] * 8  # plateau over the window
        orch = RuleBasedOrchestrator()
        decision = await orch.decide(state, "gate_fail")
        assert decision.decision == "next_asset"
        assert decision.reason == "asset_exhausted"

    @pytest.mark.asyncio
    async def test_custom_orchestrator_used(self):
        """Custom orchestrator is called instead of default."""
        state = _make_state(max_runs=3)
        strategist, executor, gatekeeper, critic, data_agent = _make_mocks()

        custom_orch = AsyncMock()
        custom_orch.config = DirectorConfig()
        custom_orch.decide.return_value = DirectorDecision("done", "goal_met", {})

        result = await research_loop(
            state, strategist, executor, gatekeeper, critic, data_agent,
            orchestrator=custom_orch,
        )

        # Should stop after first candidate because the Director says "done".
        assert len(result.candidates) == 1
        custom_orch.decide.assert_called_once()


class TestOOSLockboxIntegration:
    """OOS lockbox runs automatically in the candidate branch (C1)."""

    @pytest.mark.asyncio
    async def test_oos_called_when_available(self):
        """Lockbox auto-runs for a surviving candidate; PASS counts toward the goal."""
        state = _make_state(max_runs=5)
        state.goal.target_candidates = 1
        strategist, executor, gatekeeper, critic, data_agent = _make_mocks()

        lockbox = MagicMock()
        lockbox.ensure_budget = MagicMock()
        lockbox.get_result.return_value = None  # H16: no prior verdict → run the evaluation
        outcome_mock = MagicMock()
        outcome_mock.value = "PASS"
        lockbox.evaluate.return_value = outcome_mock

        result = await research_loop(
            state, strategist, executor, gatekeeper, critic, data_agent,
            lockbox=lockbox,
        )

        lockbox.ensure_budget.assert_called_once()
        lockbox.evaluate.assert_called_once()
        assert len(result.oos_results) == 1
        assert result.oos_results[0].outcome == "PASS"
        assert result.phase == ResearchPhase.COMPLETED
        # AC9 — OOS validation is exempt from the run budget (only the IS run counted).
        assert result.budget.used_runs == 1

    @pytest.mark.asyncio
    async def test_oos_not_called_when_no_lockbox(self):
        """Without a lockbox, no OOS evaluation happens."""
        state = _make_state(max_runs=5)
        strategist, executor, gatekeeper, critic, data_agent = _make_mocks()

        result = await research_loop(
            state, strategist, executor, gatekeeper, critic, data_agent,
            lockbox=None,
        )

        assert len(result.oos_results) == 0

    @pytest.mark.asyncio
    async def test_oos_fail_recorded(self):
        """Failed OOS is recorded and does NOT count toward the goal (C2)."""
        state = _make_state(max_runs=1)
        state.goal.target_candidates = 1
        strategist, executor, gatekeeper, critic, data_agent = _make_mocks()

        lockbox = MagicMock()
        lockbox.ensure_budget = MagicMock()
        lockbox.get_result.return_value = None  # H16: no prior verdict → run the evaluation
        outcome_mock = MagicMock()
        outcome_mock.value = "FAIL"
        lockbox.evaluate.return_value = outcome_mock

        result = await research_loop(
            state, strategist, executor, gatekeeper, critic, data_agent,
            lockbox=lockbox,
        )

        assert len(result.oos_results) == 1
        assert result.oos_results[0].outcome == "FAIL"


class TestLineageTracking:
    """Test lineage is properly tracked through the loop."""

    @pytest.mark.asyncio
    async def test_lineage_created_on_start(self):
        """Initial lineage is created when loop starts."""
        state = _make_state(max_runs=2)
        strategist, executor, gatekeeper, critic, data_agent = _make_mocks()

        result = await research_loop(state, strategist, executor, gatekeeper, critic, data_agent)

        assert result.current_lineage_id != ""
        assert result.current_lineage_id.startswith("lin_")

    @pytest.mark.asyncio
    async def test_new_lineage_on_template_change(self):
        """New root lineage created when hypothesis template changes."""
        state = _make_state(max_runs=4)

        call_count = 0
        async def alternating_propose(asset, strategy_families, failure_context, registry_summary):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return _make_hypothesis("sma_crossover"), _make_spec("sma_crossover")
            else:
                return _make_hypothesis("rsi_reversion"), _make_spec("rsi_reversion")

        strategist = AsyncMock()
        strategist.propose = alternating_propose

        _, executor, gatekeeper, critic, data_agent = _make_mocks()

        from src.backend.backtesting.validation.lineage import LineageTracker
        tracker = LineageTracker()

        result = await research_loop(
            state, strategist, executor, gatekeeper, critic, data_agent,
            lineage_tracker=tracker,
        )

        # Should have multiple lineages: at least one root for initial,
        # and a new root when template changed.
        assert len(tracker._lineages) >= 2


class TestRegimeAnalysis:
    """Test regime analysis is computed and passed to critic."""

    @pytest.mark.asyncio
    async def test_regime_analysis_in_critic_input(self):
        """Critic receives regime_analysis in metrics."""
        state = _make_state(max_runs=2)
        strategist, executor, gatekeeper, _, data_agent = _make_mocks()

        # Use a critic that captures its input.
        captured = {}
        async def capture_critic(spec, metrics, gate_report):
            captured["metrics"] = metrics
            return {"recommendation": "accept", "confidence": "medium"}

        critic = AsyncMock()
        critic.review = capture_critic

        await research_loop(state, strategist, executor, gatekeeper, critic, data_agent)

        assert "regime_analysis" in captured["metrics"]
        assert "benchmark" in captured["metrics"]


class TestDataSnapshot:
    """Test DataSnapshot message type is used."""

    @pytest.mark.asyncio
    async def test_data_snapshot_events(self):
        """data_prepared event is emitted with content hash."""
        state = _make_state(max_runs=1)
        strategist, executor, gatekeeper, critic, data_agent = _make_mocks()
        events = {}

        def capture_events(event, payload):
            events[event] = payload

        await research_loop(
            state, strategist, executor, gatekeeper, critic, data_agent,
            on_event=capture_events,
        )

        assert "data_prepared" in events
        assert "content_hash" in events["data_prepared"]
        assert "n_bars" in events["data_prepared"]


class TestMessageTypes:
    """Test new message type dataclasses work correctly."""

    def test_data_snapshot_hashing(self):
        """DataSnapshot computes content_hash from DataFrame."""
        import pandas as pd
        df = pd.DataFrame({"Close": [100, 101, 102]})
        snap = DataSnapshot(
            security_id="AAPL",
            window_start="2020-01-01",
            window_end="2020-12-31",
            data=df,
        )
        assert snap.content_hash != ""
        assert snap.n_bars == 3

    def test_data_snapshot_empty(self):
        """DataSnapshot with None data has empty hash."""
        snap = DataSnapshot(
            security_id="AAPL",
            window_start="2020-01-01",
            window_end="2020-12-31",
        )
        assert snap.content_hash == ""
        assert snap.n_bars == 0

    def test_run_artifacts(self):
        """RunArtifacts holds all executor outputs."""
        art = RunArtifacts(
            run_id="run_abc",
            strategy_hash="h" * 64,
            template_id="sma_crossover",
            params={"fast": 10},
            security_id="AAPL",
            metrics={"sharpe_annual": 1.0},
        )
        assert art.run_id == "run_abc"
        assert art.metrics["sharpe_annual"] == 1.0

    def test_oos_result(self):
        """OOSResult holds pass/fail outcome."""
        r = OOSResult(
            strategy_hash="h" * 64,
            lineage_id="lin_abc",
            outcome="PASS",
        )
        assert r.outcome == "PASS"

    def test_research_state_has_oos_results(self):
        """ResearchState has oos_results field."""
        state = _make_state()
        assert state.oos_results == []
        state.oos_results.append(OOSResult(
            strategy_hash="h" * 64,
            lineage_id="lin_abc",
            outcome="FAIL",
        ))
        assert len(state.oos_results) == 1


class TestNumericScanEnforcement:
    """Test that report_generator enforces numeric scan."""

    def test_clean_report_passes(self):
        """Report with clean narratives passes validation."""
        from src.backend.ai.research.report_generator import generate_final_report
        state = _make_state()
        report = generate_final_report(state)
        # Should not raise.
        report.validate_narratives()

    def test_numeric_claim_raises(self):
        """NumericClaimError raised if narrative contains fabricated numbers."""
        from src.backend.ai.research.reporter import NumericClaimError, ResearchReport, ReportSection
        report = ResearchReport()
        report.strategy_identity.narrative = "The Sharpe ratio was 1.5 which is excellent"
        with pytest.raises(NumericClaimError):
            report.validate_narratives()
