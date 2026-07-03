"""P1 Chunk B — regime-aware prompts selected by mode (Strategist / Critic / Reporter). €0, no real LLM."""

from unittest.mock import AsyncMock

from src.backend.ai.research.agent_llm import LLMHandle
from src.backend.ai.research.strategist import (
    STRATEGIST_SYSTEM_PROMPT,
    LLMStrategist,
    RuleBasedStrategist,
)
from src.backend.ai.research.critic import AdversarialCritic, CRITIC_SYSTEM_PROMPT
from src.backend.ai.research.report_generator import (
    REGIME_REPORTER_SYSTEM_PROMPT,
    REPORTER_SYSTEM_PROMPT,
)


def _llm():
    prov = AsyncMock()
    return LLMHandle(provider=prov, model="m", input_price_per_m=1.0, output_price_per_m=1.0,
                     supports_json_mode=True)


# ── Strategist ──

def test_strategist_regime_prompt_uses_duration_not_dates():
    # Anti-leakage: the prompt injects the window DURATION (months), never the calendar dates.
    s = LLMStrategist(llm=_llm(), ledger=None, fallback=RuleBasedStrategist(),
                      window_start="2022-01-01", window_end="2023-06-30", mode="regime")
    p = s._system_prompt()
    assert "18 months" in p                                   # ~18-month duration injected
    assert "2022-01-01" not in p and "2022" not in p and "2023" not in p   # NO date leakage
    assert "{months}" not in p and "generalize" in p          # formatted; regime-fit framing


def test_strategist_render_passes_goal_in_regime_only():
    reg = LLMStrategist(llm=_llm(), ledger=None, fallback=RuleBasedStrategist(),
                        window_start="2022-01-01", window_end="2023-06-30", mode="regime",
                        goal="momentum in AI names")
    rendered = reg._render("QQQ", ["sma_crossover"], [], {})
    assert "momentum in AI names" in rendered and "2022-01-01" not in rendered   # goal yes, dates no
    rob = LLMStrategist(llm=_llm(), ledger=None, fallback=RuleBasedStrategist(), goal="x")
    assert "research_goal" not in rob._render("QQQ", ["sma_crossover"], [], {})    # robustness unchanged


def test_strategist_robustness_prompt_is_default():
    s = LLMStrategist(llm=_llm(), ledger=None, fallback=RuleBasedStrategist())
    assert s._system_prompt() == STRATEGIST_SYSTEM_PROMPT


# ── Critic ──

def test_critic_regime_prompt_uses_duration_not_dates():
    c = AdversarialCritic(mode="regime", window_start="2022-01-01", window_end="2023-06-30")
    p = c._system_prompt()
    assert "18-month" in p                                                 # ~18-month duration injected
    assert "2022-01-01" not in p and "2022" not in p and "2023" not in p   # no date leakage
    assert "{months}" not in p and "medium" in p and "OVERFIT" in p


def test_critic_robustness_prompt_is_default():
    assert AdversarialCritic()._system_prompt() == CRITIC_SYSTEM_PROMPT


# ── Reporter ──

def test_regime_reporter_prompt_forbids_robust_framing():
    p = REGIME_REPORTER_SYSTEM_PROMPT
    assert "REGIME-FIT" in p and "NOT robustness-validated" in p
    assert "robust" in p and "{keys}" in p                   # preserves the .replace placeholder
    assert p != REPORTER_SYSTEM_PROMPT


# ── Idea-surfacing: the SOFT-severity flip (regime only) ──

def test_build_pipeline_regime_softens_quality_gates():
    from src.backend.ai.research.gatekeeper import build_default_pipeline, RIGOR_PRESETS
    from src.backend.backtesting.gates.pipeline import GateSeverity
    p = build_default_pipeline(RIGOR_PRESETS["standard"], mode="regime")
    sev = {type(g).__name__: g.severity for g in p.gates}
    assert sev["PerformanceFloorGate"] == GateSeverity.SOFT
    assert sev["DeflatedSharpeGate"] == GateSeverity.SOFT
    assert sev["CostStressGate"] == GateSeverity.SOFT
    assert sev["BenchmarkRelativeGate"] == GateSeverity.HARD   # the anti-garbage floor stays HARD
    assert sev["MinimumActivityGate"] == GateSeverity.HARD


def test_build_pipeline_robustness_all_hard():
    from src.backend.ai.research.gatekeeper import build_default_pipeline, RIGOR_PRESETS
    from src.backend.backtesting.gates.pipeline import GateSeverity
    p = build_default_pipeline(RIGOR_PRESETS["standard"], mode="robustness")
    assert all(g.severity == GateSeverity.HARD for g in p.gates)   # robustness invariance
