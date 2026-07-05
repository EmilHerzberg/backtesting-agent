"""Smoke test proving the Phase 0 verification harness itself works (ATS-1794).

If these pass, the harness is trustworthy and every later remediation regression test can build on it:
  1. a rule_based run is offline, completes, and makes ZERO LLM calls (€0 / RUN-7);
  2. same seed + same frozen data → identical report numbers (determinism / RUN-6);
  3. full_ai routes LLM calls to the MockProvider and stays offline (AI-path wiring / AIR-3).
"""
from __future__ import annotations

import pytest

from src.backend.ai.research.run import run_research

pytestmark = pytest.mark.asyncio


async def test_rule_based_is_offline_and_zero_llm_calls(frozen_ohlcv, mock_provider):
    """A rule_based run on frozen data completes and never touches the LLM (cost invariant)."""
    report = await run_research(
        goal="harness smoke — rule_based",
        assets=["AAPL"],
        max_runs=3,
        target_candidates=1,
        agent_mode="rule_based",
        seed=42,
        fetch_fn=frozen_ohlcv,
    )
    # The loop actually ran at least one trial…
    assert report.strategy_identity.numeric_fields["total_trials"] >= 1
    # …and made ZERO LLM calls even though a provider is registered (rule_based is €0).
    assert mock_provider.call_count == 0


async def test_same_seed_is_deterministic(frozen_ohlcv):
    """Same seed + same frozen data → identical report numbers across two independent runs."""
    common = dict(
        goal="harness smoke — determinism",
        assets=["AAPL"],
        max_runs=4,
        target_candidates=2,
        agent_mode="rule_based",
        fetch_fn=frozen_ohlcv,
    )
    a = await run_research(seed=123, **common)
    b = await run_research(seed=123, **common)
    assert a.strategy_identity.numeric_fields == b.strategy_identity.numeric_fields
    assert a.benchmark_comparison.numeric_fields == b.benchmark_comparison.numeric_fields
    assert a.hypothesis.numeric_fields == b.hypothesis.numeric_fields


async def test_full_ai_routes_to_mock_provider(frozen_ohlcv, mock_provider):
    """full_ai wiring: the loop invokes the registered MockProvider (recorded), fully offline / €0."""
    await run_research(
        goal="harness smoke — full_ai wiring",
        assets=["AAPL"],
        max_runs=2,
        target_candidates=1,
        agent_mode="full_ai",
        provider="mock-provider",
        model="mock-reason",
        seed=42,
        fetch_fn=frozen_ohlcv,
    )
    # The Strategist (and Critic) went through our mock rather than a real provider/network.
    assert mock_provider.call_count > 0
