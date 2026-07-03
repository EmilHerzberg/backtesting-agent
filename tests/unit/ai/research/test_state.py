"""Tests for ATS-1750/1751 — ResearchState model."""

from src.backend.ai.research.state import (
    Budget,
    Candidate,
    FailureContext,
    GoalBrief,
    OOSResult,
    ResearchPhase,
    ResearchState,
)


class TestBudget:
    def test_remaining_runs(self):
        b = Budget(max_runs=10, used_runs=3)
        assert b.remaining_runs() == 7

    def test_has_remaining_true(self):
        b = Budget(max_runs=10, used_runs=5)
        assert b.has_remaining() is True

    def test_has_remaining_false_at_limit(self):
        b = Budget(max_runs=10, used_runs=10)
        assert b.has_remaining() is False

    def test_consume_run(self):
        b = Budget(max_runs=10)
        b.consume_run(cost_eur=0.5)
        assert b.used_runs == 1
        assert b.used_eur == 0.5


class TestResearchState:
    def _make_state(self, **kw):
        goal = GoalBrief(
            goal_text="test", asset_pool=["AAPL", "MSFT"],
            target_candidates=2,
        )
        return ResearchState(
            goal=goal,
            budget=Budget(max_runs=100),
            **kw,
        )

    def test_goal_met_when_enough_candidates(self):
        state = self._make_state()
        state.candidates = [Candidate(
            strategy_hash=f"h{i}", run_id=f"r{i}", template_id="sma",
            params={}, security_id="AAPL",
        ) for i in range(2)]
        assert state.goal_met() is True

    def test_goal_not_met(self):
        state = self._make_state()
        assert state.goal_met() is False

    def test_advance_asset(self):
        state = self._make_state(asset_queue=["GOOGL", "TSLA"])
        assert state.advance_asset() is True
        assert state.current_asset == "GOOGL"
        assert state.advance_asset() is True
        assert state.current_asset == "TSLA"
        assert state.advance_asset() is False  # exhausted

    def test_advance_clears_failure_context(self):
        state = self._make_state(asset_queue=["GOOGL"])
        state.failure_context = [FailureContext(
            strategy_hash="x", template_id="sma", params={}, security_id="AAPL",
        )]
        state.advance_asset()
        assert len(state.failure_context) == 0

    def _cands(self, *hashes):
        return [Candidate(strategy_hash=h, run_id="r", template_id="sma",
                          params={}, security_id="AAPL") for h in hashes]

    def test_validated_count_oos_off(self):
        state = self._make_state()
        state.candidates = self._cands("h1", "h2")
        assert state.validated_count(oos_enabled=False) == 2

    def test_validated_count_oos_on_counts_pass_only(self):
        state = self._make_state()
        state.candidates = self._cands("h1", "h2")
        state.oos_results = [
            OOSResult(strategy_hash="h1", lineage_id="l", outcome="PASS"),
            OOSResult(strategy_hash="h2", lineage_id="l", outcome="FAIL"),
        ]
        assert state.validated_count(oos_enabled=True) == 1

    def test_advance_asset_resets_director_counters(self):
        state = self._make_state(asset_queue=["GOOGL"])
        state.consecutive_errors = 3
        state.attempts_on_current_asset = 7
        state.best_sharpe_on_asset = [0.5, 0.6]
        state.advance_asset()
        assert state.consecutive_errors == 0
        assert state.attempts_on_current_asset == 0
        assert state.best_sharpe_on_asset == []
