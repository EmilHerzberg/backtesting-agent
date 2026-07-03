"""Account-settings Phase 2 — new providers, reasoning/leakage surfacing, Anthropic adapter."""

from __future__ import annotations

from src.backend.ai.leakage import is_leakage_risk, model_leakage, provider_leakage
from src.backend.ai.models import ChatMessage, ChatRequest, ProviderConfig
from src.backend.ai.providers.anthropic import AnthropicProvider
from src.backend.ai.registry import available_provider_types


def test_all_providers_registered():
    types = set(available_provider_types())
    assert {"deepseek", "minimax", "qwen", "zhipu", "moonshot",
            "openai", "gemini", "anthropic", "byteplus"} <= types


def test_model_leakage_states_grounded():
    # validated mechanism-only (the two clean exemplars + byteplus production model)
    assert model_leakage("deepseek-reasoner") == "mechanism_only"
    assert model_leakage("seed-2-0-pro-260328") == "mechanism_only"
    # measured / assumed risk
    assert model_leakage("gemini-3-pro") == "risk"
    assert model_leakage("gpt-5") == "risk"
    assert model_leakage("claude-opus-4-8") == "risk"
    # unvalidated — NOT cleared as clean (this is the honesty fix)
    assert model_leakage("deepseek-chat") == "unvalidated"
    assert model_leakage("MiniMax-M2.7") == "unvalidated"
    assert model_leakage("unknown-model") == "unvalidated"


def test_provider_leakage_summary():
    assert provider_leakage("deepseek") == "mechanism_only"   # offers a validated model
    assert provider_leakage("byteplus") == "mechanism_only"
    assert provider_leakage("gemini") == "risk"
    assert provider_leakage("openai") == "risk"
    assert provider_leakage("anthropic") == "risk"
    # never leakage-cleared → no claim (not "clean")
    for t in ("minimax", "qwen", "zhipu", "moonshot", ""):
        assert provider_leakage(t) == "unvalidated"


def test_is_leakage_risk_backcompat():
    for t in ("openai", "gemini", "anthropic"):
        assert is_leakage_risk(t) is True
    for t in ("deepseek", "byteplus", "minimax", "qwen", "zhipu", "moonshot", ""):
        assert is_leakage_risk(t) is False


def test_new_providers_expose_reasoning_models():
    from src.backend.ai.providers.openai import OPENAI_MODELS
    from src.backend.ai.providers.gemini import GEMINI_MODELS
    from src.backend.ai.providers.anthropic import ANTHROPIC_MODELS
    for models in (OPENAI_MODELS, GEMINI_MODELS, ANTHROPIC_MODELS):
        assert any(m.supports_reasoning for m in models)


def _anthropic():
    return AnthropicProvider(ProviderConfig(
        name="claude", provider_type="anthropic", api_key="sk-test-key", base_url=""))


def _req(**kw):
    base = dict(model="claude-opus-4-8", messages=[
        ChatMessage(role="system", content="You are a reviewer."),
        ChatMessage(role="user", content="Judge this."),
    ], max_tokens=4000, temperature=0.2)
    base.update(kw)
    return ChatRequest(**base)


def test_anthropic_pulls_system_and_sets_max_tokens():
    kwargs, prefill = _anthropic()._build(_req())
    assert kwargs["system"].startswith("You are a reviewer.")
    assert kwargs["max_tokens"] == 4000
    assert kwargs["messages"][0]["role"] == "user"  # system not left in messages


def test_anthropic_json_mode_prefill():
    kwargs, prefill = _anthropic()._build(_req(json_mode=True))
    assert "JSON" in kwargs["system"]
    assert prefill == "{"
    assert kwargs["messages"][-1] == {"role": "assistant", "content": "{"}
    assert "thinking" not in kwargs  # prefill only without thinking


def test_anthropic_thinking_budget_under_max():
    kwargs, prefill = _anthropic()._build(_req(reasoning=True, json_mode=True))
    assert kwargs["thinking"]["type"] == "enabled"
    assert kwargs["thinking"]["budget_tokens"] < kwargs["max_tokens"]
    assert kwargs["temperature"] == 1.0
    assert prefill == ""  # no prefill when thinking is on


def test_anthropic_temperature_clamped():
    kwargs, _ = _anthropic()._build(_req(temperature=1.8))
    assert kwargs["temperature"] <= 1.0
