"""ATS-1785 — E2E integration test: full research loop pipeline.

Tests the complete flow: Strategist → Data → Executor → Gates → Critic → OOS
with mock LLM provider. No real API calls. Must complete in under 60s.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from src.backend.ai.research.loop import RuleBasedOrchestrator, research_loop
from src.backend.ai.research.state import (
    Budget,
    GoalBrief,
    Hypothesis,
    ResearchPhase,
    ResearchState,
)


def _make_hypothesis(template_id="sma_crossover"):
    return Hypothesis(
        hypothesis_id=f"hyp_{uuid.uuid4().hex[:8]}",
        author="e2e_test",
        economic_rationale="Testing the full pipeline",
        claimed_mechanism="Mock mechanism",
        falsifiable_prediction="Should find 2 candidates",
        proposed_template_id=template_id,
    )


def _make_spec(variant=0, template_id="sma_crossover"):
    return {
        "strategy_hash": f"{'a' * 60}{variant:04d}",
        "template_id": template_id,
        "params": {"fast_period": 10 + variant, "slow_period": 50},
        "window_start": "2018-01-01",
        "window_end": "2022-12-31",
    }


class TestResearchLoopE2E:
    @pytest.mark.asyncio
    async def test_e2e_happy_path(self):
        """Full loop: 2 candidates found from 5 runs."""
        state = ResearchState(
            goal=GoalBrief(
                goal_text="Find strategies for AAPL",
                asset_pool=["AAPL"],
                strategy_families=["trend_following"],
                target_candidates=2,
                max_runs=10,
            ),
            budget=Budget(max_runs=10),
        )

        call_count = 0

        async def mock_propose(asset, strategy_families, failure_context, registry_summary):
            nonlocal call_count
            call_count += 1
            return _make_hypothesis(), _make_spec(call_count)

        strategist = AsyncMock()
        strategist.propose = mock_propose

        executor = MagicMock()
        executor.run.return_value = {
            "sharpe_annual": 1.2,
            "total_return": 0.25,
            "max_drawdown": -0.12,
            "n_trades": 80,
            "exposure_time": 0.5,
            "buy_hold_return": 0.15,
            "returns": np.random.default_rng(42).standard_normal(252) * 0.01,
        }

        gatekeeper = MagicMock()
        gatekeeper.evaluate.return_value = {"passed": True, "results": []}
        gatekeeper.update_registry_stats = MagicMock()

        critic = AsyncMock()
        critic.review.return_value = {
            "recommendation": "accept",
            "confidence": "medium",
            "weaknesses": [],
        }

        data_agent = MagicMock()
        data_agent.prepare.return_value = "mock_df"

        events = []
        result = await research_loop(
            state, strategist, executor, gatekeeper, critic, data_agent,
            on_event=lambda t, p: events.append(t),
        )

        assert result.phase == ResearchPhase.COMPLETED
        assert len(result.candidates) == 2
        assert result.budget.used_runs == 2
        assert "goal_received" in events
        assert "loop_started" in events
        assert "candidate_found" in events
        assert "loop_finished" in events
        # DSR stats should be updated.
        assert gatekeeper.update_registry_stats.call_count == 2

    @pytest.mark.asyncio
    async def test_e2e_gate_failure_then_success(self):
        """First 3 runs fail gates, 4th and 5th pass."""
        state = ResearchState(
            goal=GoalBrief(
                goal_text="test",
                asset_pool=["MSFT"],
                target_candidates=2,
                max_runs=10,
            ),
            budget=Budget(max_runs=10),
        )

        propose_count = {"n": 0}

        async def mock_propose(asset, strategy_families, failure_context, registry_summary):
            propose_count["n"] += 1
            return _make_hypothesis(), _make_spec(propose_count["n"])

        strategist = MagicMock()
        strategist.propose = mock_propose

        executor = MagicMock()
        executor.run.return_value = {
            "sharpe_annual": 1.0, "total_return": 0.2, "n_trades": 60,
            "buy_hold_return": 0.1,
            "returns": np.random.default_rng(42).standard_normal(252) * 0.01,
        }

        gate_count = {"n": 0}
        def mock_gate(metrics, returns, context):
            gate_count["n"] += 1
            if gate_count["n"] <= 3:
                return {"passed": False, "first_failed_gate": "performance_floor"}
            return {"passed": True}

        gatekeeper = MagicMock()
        gatekeeper.evaluate = mock_gate
        gatekeeper.update_registry_stats = MagicMock()

        async def mock_review(spec, metrics, gate_report):
            return {"recommendation": "accept", "confidence": "medium"}

        critic = MagicMock()
        critic.review = mock_review

        data_agent = MagicMock()
        data_agent.prepare.return_value = "mock_df"

        result = await research_loop(
            state, strategist, executor, gatekeeper, critic, data_agent,
        )

        assert result.phase == ResearchPhase.COMPLETED
        assert len(result.candidates) == 2
        assert len(result.failure_context) == 3  # 3 gate failures
        assert result.budget.used_runs == 5  # 3 failed + 2 passed

    @pytest.mark.asyncio
    async def test_e2e_critic_rejection(self):
        """Critic rejects first candidate, accepts next two."""
        state = ResearchState(
            goal=GoalBrief(
                goal_text="test",
                asset_pool=["GOOGL"],
                target_candidates=2,
                max_runs=10,
            ),
            budget=Budget(max_runs=10),
        )

        call_count = 0
        async def mock_propose(asset, strategy_families, failure_context, registry_summary):
            nonlocal call_count
            call_count += 1
            return _make_hypothesis(), _make_spec(call_count)

        strategist = AsyncMock()
        strategist.propose = mock_propose

        executor = MagicMock()
        executor.run.return_value = {
            "sharpe_annual": 1.0, "total_return": 0.2, "n_trades": 60,
            "buy_hold_return": 0.1,
            "returns": np.random.default_rng(42).standard_normal(252) * 0.01,
        }

        gatekeeper = MagicMock()
        gatekeeper.evaluate.return_value = {"passed": True}
        gatekeeper.update_registry_stats = MagicMock()

        critic_call = 0
        async def mock_critic(spec, metrics, gate_report):
            nonlocal critic_call
            critic_call += 1
            if critic_call == 1:
                return {"recommendation": "reject", "reasoning": "overfitted"}
            return {"recommendation": "accept", "confidence": "medium"}

        critic = AsyncMock()
        critic.review = mock_critic

        data_agent = MagicMock()
        data_agent.prepare.return_value = "mock_df"

        result = await research_loop(
            state, strategist, executor, gatekeeper, critic, data_agent,
        )

        assert result.phase == ResearchPhase.COMPLETED
        assert len(result.candidates) == 2
        critic_rejections = [fc for fc in result.failure_context if fc.failure_reason == "critic_rejection"]
        assert len(critic_rejections) == 1

    @pytest.mark.asyncio
    async def test_e2e_budget_exhaustion(self):
        """Loop stops when budget runs out, even if goal not met."""
        state = ResearchState(
            goal=GoalBrief(
                goal_text="test",
                asset_pool=["TSLA"],
                target_candidates=10,  # unreachable
                max_runs=3,
            ),
            budget=Budget(max_runs=3),
        )

        async def mock_propose(asset, strategy_families, failure_context, registry_summary):
            return _make_hypothesis(), _make_spec()

        strategist = AsyncMock()
        strategist.propose = mock_propose

        executor = MagicMock()
        executor.run.return_value = {"sharpe_annual": 0.3, "total_return": 0.01, "n_trades": 20,
                                      "returns": np.zeros(100)}

        gatekeeper = MagicMock()
        gatekeeper.evaluate.return_value = {"passed": False, "first_failed_gate": "perf_floor"}
        gatekeeper.update_registry_stats = MagicMock()

        critic = AsyncMock()
        data_agent = MagicMock()
        data_agent.prepare.return_value = "mock_df"

        result = await research_loop(
            state, strategist, executor, gatekeeper, critic, data_agent,
        )

        assert result.phase == ResearchPhase.STOPPED
        assert result.budget.used_runs == 3
        assert result.stop_reason == "budget_exhausted"

    @pytest.mark.asyncio
    async def test_e2e_with_oos_lockbox(self):
        """Full pipeline with OOS lockbox integration."""
        state = ResearchState(
            goal=GoalBrief(
                goal_text="test with OOS",
                asset_pool=["AAPL"],
                target_candidates=1,
                max_runs=5,
            ),
            budget=Budget(max_runs=5),
        )

        async def mock_propose(asset, strategy_families, failure_context, registry_summary):
            return _make_hypothesis(), _make_spec(1)

        strategist = AsyncMock()
        strategist.propose = mock_propose

        executor = MagicMock()
        executor.run.return_value = {
            "sharpe_annual": 1.2, "total_return": 0.25, "n_trades": 80,
            "buy_hold_return": 0.1,
            "returns": np.random.default_rng(42).standard_normal(252) * 0.01,
        }

        gatekeeper = MagicMock()
        gatekeeper.evaluate.return_value = {"passed": True, "results": []}
        gatekeeper.update_registry_stats = MagicMock()

        critic = AsyncMock()
        critic.review.return_value = {"recommendation": "accept", "confidence": "high"}

        data_agent = MagicMock()
        data_agent.prepare.return_value = "mock_df"

        # OOS runs automatically in the candidate branch (C1); target=1 → done on first PASS.
        lockbox = MagicMock()
        lockbox.ensure_budget = MagicMock()
        outcome = MagicMock()
        outcome.value = "PASS"
        lockbox.evaluate.return_value = outcome

        events = []
        result = await research_loop(
            state, strategist, executor, gatekeeper, critic, data_agent,
            lockbox=lockbox,
            on_event=lambda t, p: events.append((t, p)),
        )

        assert result.phase == ResearchPhase.COMPLETED
        assert len(result.candidates) == 1
        assert len(result.oos_results) == 1
        assert result.oos_results[0].outcome == "PASS"
        assert any(t == "oos_result" for t, _ in events)

    @pytest.mark.asyncio
    async def test_e2e_lineage_tracked_across_iterations(self):
        """Lineage IDs are tracked and change on template switch."""
        state = ResearchState(
            goal=GoalBrief(
                goal_text="test lineage",
                asset_pool=["AAPL"],
                target_candidates=2,
                max_runs=10,
            ),
            budget=Budget(max_runs=10),
        )

        call_count = 0
        async def mock_propose(asset, strategy_families, failure_context, registry_summary):
            nonlocal call_count
            call_count += 1
            template = "sma_crossover" if call_count <= 1 else "rsi_reversion"
            return _make_hypothesis(template), _make_spec(call_count, template)

        strategist = AsyncMock()
        strategist.propose = mock_propose

        executor = MagicMock()
        executor.run.return_value = {
            "sharpe_annual": 1.0, "total_return": 0.2, "n_trades": 60,
            "buy_hold_return": 0.1,
            "returns": np.random.default_rng(42).standard_normal(252) * 0.01,
        }

        gatekeeper = MagicMock()
        gatekeeper.evaluate.return_value = {"passed": True}
        gatekeeper.update_registry_stats = MagicMock()

        critic = AsyncMock()
        critic.review.return_value = {"recommendation": "accept", "confidence": "medium"}

        data_agent = MagicMock()
        data_agent.prepare.return_value = "mock_df"

        from src.backend.backtesting.validation.lineage import LineageTracker
        tracker = LineageTracker()

        result = await research_loop(
            state, strategist, executor, gatekeeper, critic, data_agent,
            lineage_tracker=tracker,
        )

        assert result.current_lineage_id.startswith("lin_")
        # At least 2 lineages (one per template type).
        assert len(tracker._lineages) >= 2
