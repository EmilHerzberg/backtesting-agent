"""W1 unit tests — Critic LLM path (mock provider, €0; no real API call)."""

from unittest.mock import AsyncMock

import pytest

from src.backend.ai.models import ChatResponse, TokenUsage
from src.backend.ai.research.agent_llm import LLMHandle, TokenLedger
from src.backend.ai.research.critic import AdversarialCritic
from src.backend.ai.research.state import Budget


def _llm(supports_json=True, in_p=1.0, out_p=2.0):
    prov = AsyncMock()
    handle = LLMHandle(provider=prov, model="m", input_price_per_m=in_p,
                       output_price_per_m=out_p, supports_json_mode=supports_json)
    return handle, prov


def _resp(content, prompt=1000, completion=200):
    return ChatResponse(
        model="m", provider="p", content=content,
        usage=TokenUsage(prompt_tokens=prompt, completion_tokens=completion,
                         total_tokens=prompt + completion),
    )


SPEC = {"template_id": "sma_crossover", "params": {"fast": 10}, "security_id": "AAPL"}
# n_trades 80, sharpe 1.1, beats buy&hold, shallow dd -> heuristic = "accept"
METRICS = {"sharpe_annual": 1.1, "total_return": 0.2, "max_drawdown": -0.1, "n_trades": 80,
           "benchmark": {"buy_hold_return": 0.15}, "regime_analysis": {}}
GATES = {"passed": True, "results": []}


async def test_llm_verdict_parsed_and_recorded():
    b = Budget(max_runs=10, max_eur=5.0)
    led = TokenLedger(budget=b)
    llm, prov = _llm(in_p=2.0, out_p=4.0)
    prov.chat_completion.return_value = _resp(
        '{"weaknesses": ["few trades"], "confidence": "medium", '
        '"recommendation": "reject", "reasoning": "overfit"}',
        prompt=1_000_000, completion=500_000)
    out = await AdversarialCritic(llm=llm, ledger=led).review(SPEC, METRICS, GATES)
    assert out["recommendation"] == "reject"
    assert out["confidence"] == "medium"
    assert out["weaknesses"] == ["few trades"]
    assert led.cost_eur == pytest.approx(4.0)   # 2.0*1 + 4.0*0.5
    assert b.used_eur == pytest.approx(4.0)
    prov.chat_completion.assert_awaited_once()


async def test_over_budget_skips_llm():
    b = Budget(max_runs=10, max_eur=1.0)
    b.used_eur = 1.0  # at the cap
    led = TokenLedger(budget=b)
    llm, prov = _llm()
    out = await AdversarialCritic(llm=llm, ledger=led).review(SPEC, METRICS, GATES)
    prov.chat_completion.assert_not_awaited()    # pre-call guard
    assert out["recommendation"] == "accept"     # heuristic


async def test_api_error_falls_back_to_heuristic():
    led = TokenLedger(budget=Budget(max_runs=10, max_eur=5.0))
    llm, prov = _llm()
    prov.chat_completion.side_effect = RuntimeError("boom")
    out = await AdversarialCritic(llm=llm, ledger=led).review(SPEC, METRICS, GATES)
    assert out["recommendation"] == "accept"     # never a spurious accept from the LLM — heuristic


async def test_unparseable_falls_back():
    led = TokenLedger(budget=Budget(max_runs=10, max_eur=5.0))
    llm, prov = _llm()
    prov.chat_completion.return_value = _resp("sorry, no json here")
    out = await AdversarialCritic(llm=llm, ledger=led).review(SPEC, METRICS, GATES)
    assert out["recommendation"] == "accept"     # heuristic


async def test_isolation_allowlist_excludes_leak():
    led = TokenLedger(budget=Budget(max_runs=10, max_eur=5.0))
    llm, prov = _llm()
    prov.chat_completion.return_value = _resp('{"recommendation": "accept", "confidence": "high"}')
    leaky = {**METRICS, "economic_rationale": "SECRET-LEAK", "hypothesis": "SECRET-LEAK"}
    await AdversarialCritic(llm=llm, ledger=led).review(SPEC, leaky, GATES)
    req = prov.chat_completion.call_args.args[0]
    user_msg = next(m.content for m in req.messages if m.role == "user")
    assert "SECRET-LEAK" not in user_msg         # the allowlist kept it out
    assert req.max_tokens <= 4000                 # bounded (4000 accommodates deepseek-reasoner's pre-answer tokens)
    assert req.json_mode is True


async def test_json_mode_gated_on_support():
    led = TokenLedger(budget=Budget(max_runs=10, max_eur=5.0))
    llm, prov = _llm(supports_json=False)
    prov.chat_completion.return_value = _resp('{"recommendation": "accept", "confidence": "high"}')
    await AdversarialCritic(llm=llm, ledger=led).review(SPEC, METRICS, GATES)
    req = prov.chat_completion.call_args.args[0]
    assert req.json_mode is False


async def test_rule_based_no_provider_uses_heuristic():
    out = await AdversarialCritic().review(SPEC, METRICS, GATES)   # no llm
    assert out["recommendation"] == "accept"
