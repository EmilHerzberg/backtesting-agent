"""Phase 4 / cluster 4B — LLM degradation & honesty (H25, H26).

- H25: strategist max_tokens=700 truncated reasoning models before the JSON → extract_json_object
  returned None → silent fallback to rule-based AFTER billing. Reasoners now get the Critic's headroom,
  and a billed-but-unparseable call is counted so the degradation is visible.
- H26: the heuristic critic hard-rejected <30 trades ("insufficient" → reject), overriding the
  calibrated smart-activity gate the candidate already passed. Trade count is now a non-critical caveat.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.backend.ai.research.agent_llm import LLMHandle
from src.backend.ai.research.critic import AdversarialCritic
from src.backend.ai.research.strategist import LLMStrategist, RuleBasedStrategist


class _MockProvider:
    def __init__(self, content):
        self._content = content
        self.last_req = None

    async def chat_completion(self, req):
        self.last_req = req
        return SimpleNamespace(
            content=self._content,
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=10, total_tokens=20),
        )


def _handle(content, reasoning):
    return LLMHandle(provider=_MockProvider(content), model="m",
                     input_price_per_m=0.0, output_price_per_m=0.0, supports_reasoning=reasoning)


@pytest.mark.finding("H25")
async def test_reasoning_model_gets_critic_order_max_tokens_and_counts_fallback():
    h = _handle("not valid json", reasoning=True)
    strat = LLMStrategist(h, None, RuleBasedStrategist())
    await strat.propose("AAPL", [], [], {})
    assert h.provider.last_req.max_tokens == 4000            # reasoners are no longer truncated
    # billed but unparseable → counted (the silent LLM→heuristic degradation is now visible)
    assert strat.llm_calls == 1 and strat.fallback_after_bill == 1


@pytest.mark.finding("H25")
async def test_non_reasoning_model_keeps_small_cap():
    h = _handle("not valid json", reasoning=False)
    strat = LLMStrategist(h, None, RuleBasedStrategist())
    await strat.propose("AAPL", [], [], {})
    assert h.provider.last_req.max_tokens == 700


def _metrics(**over):
    m = {"sharpe_annual": 1.2, "n_trades": 15, "total_return": 0.20, "max_drawdown": -0.10,
         "buy_hold_return": 0.10}
    m.update(over)
    return m


@pytest.mark.finding("H26")
def test_critic_does_not_reject_a_gate_passed_thin_sample_on_trade_count():
    # 15 trades: below the old hardcoded 30, but the smart-activity gate already vetted trade count.
    r = AdversarialCritic()._heuristic_review({}, _metrics(n_trades=15), {})
    assert r["recommendation"] != "reject"


@pytest.mark.finding("H26")
def test_critic_still_rejects_overfit_sharpe():
    r = AdversarialCritic()._heuristic_review({}, _metrics(sharpe_annual=5.0, n_trades=50), {})
    assert r["recommendation"] == "reject"     # Sharpe>3 "overfit" is still a critical reject


@pytest.mark.finding("H31")
def test_run_leakage_badge_is_per_model_not_provider(monkeypatch):
    # The run badge must reflect the MODEL that ran, not the provider summary — a provider that ships
    # one validated model badged EVERY run on it clean, even a run on an unvalidated sibling model.
    import src.backend.ai.research.router as rt

    monkeypatch.setattr(rt, "model_leakage", lambda mid: "unvalidated")
    monkeypatch.setattr(rt, "provider_leakage", lambda pt: "mechanism_only")
    assert rt._run_leakage("deepseek", "deepseek-chat") == "unvalidated"     # the model wins
    assert rt._run_leakage("deepseek", "") == "mechanism_only"              # fall back only when unknown
