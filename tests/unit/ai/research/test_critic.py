"""Tests for ATS-1764/1765/1766 — Adversarial Critic."""

import pytest

from src.backend.ai.research.critic import AdversarialCritic


@pytest.fixture
def critic():
    return AdversarialCritic()  # no LLM, uses heuristic


class TestHeuristicCritic:
    @pytest.mark.asyncio
    @pytest.mark.finding("H26")
    async def test_low_trade_count_is_a_caveat_not_a_reject(self, critic):
        # H26: the smart-activity gate already vetted trade count (calibrated floor) before the critic;
        # a thin sample is now a NON-critical caveat, not a hardcoded-30 reject that overrode calibration.
        result = await critic.review(
            spec={"template_id": "sma"},
            metrics={"sharpe_annual": 1.0, "n_trades": 10, "total_return": 0.2, "max_drawdown": -0.1},
            gate_report={"passed": True},
        )
        assert result["recommendation"] != "reject"
        assert any("trade count" in w.lower() for w in result["weaknesses"])

    @pytest.mark.asyncio
    async def test_rejects_suspicious_sharpe(self, critic):
        result = await critic.review(
            spec={},
            metrics={"sharpe_annual": 5.0, "n_trades": 100, "total_return": 0.5, "max_drawdown": -0.05},
            gate_report={"passed": True},
        )
        assert result["recommendation"] == "reject"
        assert any("overfit" in w.lower() for w in result["weaknesses"])

    @pytest.mark.asyncio
    async def test_accepts_strong_candidate(self, critic):
        result = await critic.review(
            spec={},
            metrics={
                "sharpe_annual": 1.2, "n_trades": 120, "total_return": 0.25,
                "max_drawdown": -0.12, "benchmark": {"buy_hold_return": 0.15},
            },
            gate_report={"passed": True},
        )
        assert result["recommendation"] == "accept"
        assert result["confidence"] == "high"

    @pytest.mark.asyncio
    async def test_flags_benchmark_underperformance(self, critic):
        result = await critic.review(
            spec={},
            metrics={
                "sharpe_annual": 0.8, "n_trades": 80, "total_return": 0.10,
                "max_drawdown": -0.15, "benchmark": {"buy_hold_return": 0.20},
            },
            gate_report={"passed": True},
        )
        assert any("underperforms" in w.lower() for w in result["weaknesses"])

    @pytest.mark.asyncio
    async def test_no_strategist_context(self, critic):
        """Critic never sees strategist reasoning — verified by interface."""
        # The review() method takes spec+metrics+gates but NOT hypothesis.
        # This is structural: the function signature prevents leaking context.
        import inspect
        sig = inspect.signature(critic.review)
        param_names = set(sig.parameters.keys())
        assert "hypothesis" not in param_names
        assert "rationale" not in param_names
        assert "chain_of_thought" not in param_names
