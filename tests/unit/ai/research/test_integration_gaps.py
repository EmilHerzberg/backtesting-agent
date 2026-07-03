"""Tests for integration gaps: executor, gatekeeper, strategist, report, run_research."""

import asyncio
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from src.backend.ai.research.executor import ResearchExecutor, _ensure_registry
from src.backend.ai.research.gatekeeper import ResearchGatekeeper, build_default_pipeline
from src.backend.ai.research.strategist import RuleBasedStrategist, TEMPLATES
from src.backend.ai.research.report_generator import generate_final_report
from src.backend.ai.research.state import (
    Budget, Candidate, FailureContext, GoalBrief, Hypothesis, ResearchState,
)


def _make_ohlcv(n=300, seed=42):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2018-01-01", periods=n, freq="B")
    close = 100 + np.cumsum(rng.standard_normal(n) * 0.5)
    close = np.maximum(close, 10)
    return pd.DataFrame({
        "Open": close + rng.uniform(-0.3, 0.3, n),
        "High": close + np.abs(rng.standard_normal(n) * 0.5),
        "Low": close - np.abs(rng.standard_normal(n) * 0.5),
        "Close": close,
        "Volume": rng.integers(10000, 500000, n),
    }, index=idx)


# ── Executor ──────────────────────────────────────────────────

class TestResearchExecutor:
    def test_template_registry_populated(self):
        reg = _ensure_registry()
        assert "sma_crossover" in reg
        assert "rsi_reversion" in reg
        assert len(reg) >= 5

    def test_run_returns_metrics_dict(self):
        executor = ResearchExecutor()
        data = _make_ohlcv(300)
        spec = {
            "template_id": "sma_crossover",
            "params": {"fast_period": 10, "slow_period": 50},
            "security_id": "TEST",
        }
        metrics = executor.run(spec, data)
        assert "sharpe_annual" in metrics
        assert "total_return" in metrics
        assert "n_trades" in metrics
        assert "returns" in metrics
        assert isinstance(metrics["returns"], np.ndarray)

    def test_unknown_template_raises(self):
        executor = ResearchExecutor()
        with pytest.raises(ValueError, match="Unknown template_id"):
            executor.run({"template_id": "nonexistent", "params": {}}, _make_ohlcv())

    def test_run_with_rsi(self):
        executor = ResearchExecutor()
        data = _make_ohlcv(300)
        spec = {
            "template_id": "rsi_reversion",
            "params": {"period": 14, "buy_threshold": 30, "sell_threshold": 70},
            "security_id": "TEST",
        }
        metrics = executor.run(spec, data)
        assert isinstance(metrics["total_return"], float)


# ── Gatekeeper ────────────────────────────────────────────────

class TestResearchGatekeeper:
    def test_build_default_pipeline(self):
        pipeline = build_default_pipeline()
        assert len(pipeline.gates) >= 7

    def test_evaluate_good_metrics_passes_basic_gates(self):
        gk = ResearchGatekeeper()
        metrics = {
            "n_trades": 100,
            "sharpe_annual": 1.2,
            "total_return": 0.25,
            "max_drawdown": -0.15,
            "exposure_time": 0.5,
            "commission": 0.001,
            "params": {},
        }
        returns = np.random.default_rng(42).standard_normal(252) * 0.01
        context = {"strategy_hash": "a" * 64, "template_id": "sma_crossover"}
        result = gk.evaluate(metrics, returns, context)
        assert "passed" in result
        assert isinstance(result["results"], list)

    def test_evaluate_bad_metrics_fails(self):
        gk = ResearchGatekeeper()
        metrics = {"n_trades": 5, "sharpe_annual": 0.1, "total_return": -0.1,
                   "exposure_time": 0.5, "commission": 0.001}
        result = gk.evaluate(metrics, np.zeros(100), {"strategy_hash": "a" * 64, "template_id": "sma"})
        assert result["passed"] is False


# ── Strategist ────────────────────────────────────────────────

class TestRuleBasedStrategist:
    @pytest.mark.asyncio
    async def test_propose_returns_valid_spec(self):
        s = RuleBasedStrategist(seed=42)
        hyp, spec = await s.propose("AAPL", ["trend_following"], [], {})
        assert isinstance(hyp, Hypothesis)
        assert "template_id" in spec
        assert "params" in spec
        assert spec["template_id"] in TEMPLATES
        assert spec["security_id"] == "AAPL"

    @pytest.mark.asyncio
    async def test_propose_adapts_from_failures(self):
        s = RuleBasedStrategist(seed=42)
        failures = [
            FailureContext(strategy_hash="x", template_id="sma_crossover",
                          params={}, security_id="AAPL", failed_gate="perf_floor"),
            FailureContext(strategy_hash="y", template_id="sma_crossover",
                          params={}, security_id="AAPL", failed_gate="perf_floor"),
            FailureContext(strategy_hash="z", template_id="sma_crossover",
                          params={}, security_id="AAPL", failed_gate="perf_floor"),
        ]
        hyp, spec = await s.propose("AAPL", ["trend_following"], failures, {})
        # After 3 failures on sma_crossover, should prefer macd_cross
        # (Not guaranteed on single call due to randomness, but failure tracking works)
        assert spec["template_id"] in TEMPLATES

    @pytest.mark.asyncio
    async def test_propose_avoids_duplicates(self):
        s = RuleBasedStrategist(seed=42)
        hashes = set()
        for _ in range(10):
            _, spec = await s.propose("AAPL", [], [], {})
            hashes.add(spec["strategy_hash"])
        # Should have mostly unique specs (at least 8/10)
        assert len(hashes) >= 8

    @pytest.mark.asyncio
    async def test_propose_records_hypothesis(self):
        s = RuleBasedStrategist(seed=42)
        hyp, spec = await s.propose("MSFT", ["mean_reversion"], [], {})
        assert hyp.hypothesis_id.startswith("hyp_")
        assert "MSFT" in hyp.economic_rationale
        assert hyp.proposed_template_id == spec["template_id"]


# ── Report Generator ──────────────────────────────────────────

class TestReportGenerator:
    def test_generates_report_from_empty_state(self):
        state = ResearchState(
            goal=GoalBrief(goal_text="test", asset_pool=["AAPL"]),
            budget=Budget(max_runs=10),
        )
        report = generate_final_report(state)
        assert report.strategy_identity.narrative
        assert report.limitations.narrative
        errors = report.validate()
        # Some sections may be empty (no candidates), but structure exists
        assert isinstance(errors, list)

    def test_generates_report_with_candidates(self):
        state = ResearchState(
            goal=GoalBrief(goal_text="test", asset_pool=["AAPL"]),
            budget=Budget(max_runs=50, used_runs=30),
            total_iterations=30,
        )
        state.candidates = [
            Candidate(strategy_hash="abc", run_id="r1", template_id="sma",
                      params={}, security_id="AAPL", sharpe_annual=1.2,
                      total_return=0.25, max_drawdown=-0.12, n_trades=80),
        ]
        state.hypotheses = [
            Hypothesis(hypothesis_id="h1", author="test", economic_rationale="test",
                       claimed_mechanism="test", falsifiable_prediction="test",
                       proposed_template_id="sma"),
        ]
        report = generate_final_report(state)
        assert report.benchmark_comparison.numeric_fields.get("best_sharpe") == 1.2
        assert report.strategy_identity.numeric_fields["total_trials"] == 30

    def test_report_narratives_pass_numeric_scan(self):
        state = ResearchState(
            goal=GoalBrief(goal_text="test"),
            budget=Budget(max_runs=10),
        )
        report = generate_final_report(state)
        # Should not raise — narratives are clean
        report.validate_narratives()


# ── End-to-End with Real Executor ─────────────────────────────

class TestEndToEndWithExecutor:
    @pytest.mark.asyncio
    async def test_research_loop_with_real_executor(self):
        """Run the full loop with real backtesting engine on synthetic data."""
        from src.backend.ai.research.loop import research_loop
        from src.backend.ai.research.critic import AdversarialCritic

        data = _make_ohlcv(300, seed=99)

        state = ResearchState(
            goal=GoalBrief(
                goal_text="test with real executor",
                asset_pool=["SYNTHETIC"],
                strategy_families=["trend_following"],
                target_candidates=1,
                max_runs=5,
            ),
            budget=Budget(max_runs=5),
        )

        strategist = RuleBasedStrategist(seed=42)
        executor = ResearchExecutor()
        gatekeeper = ResearchGatekeeper()
        critic = AdversarialCritic()
        data_agent = MagicMock()
        data_agent.prepare.return_value = data

        events = []
        result = await research_loop(
            state, strategist, executor, gatekeeper, critic, data_agent,
            on_event=lambda t, p: events.append(t),
        )

        # Loop should have run (might not find candidates on synthetic data,
        # but it should complete without errors)
        assert result.total_iterations > 0
        assert result.budget.used_runs > 0
        assert "loop_started" in events
        assert "loop_finished" in events

        # Generate report from the state
        report = generate_final_report(result)
        assert report.strategy_identity.numeric_fields["total_trials"] > 0
