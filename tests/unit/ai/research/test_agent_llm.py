"""W0 unit tests — provider plumbing + token ledger (agent-layer wiring)."""

import inspect

import pytest

from src.backend.ai.models import ModelInfo, TokenUsage
from src.backend.ai.research import agent_llm
from src.backend.ai.research.agent_llm import LLMHandle, TokenLedger, resolve_agent_llm
from src.backend.ai.research.state import Budget


def _handle(in_p=1.0, out_p=2.0):
    return LLMHandle(provider=object(), model="m", input_price_per_m=in_p, output_price_per_m=out_p)


class TestTokenLedger:
    def test_records_cost_and_feeds_budget(self):
        b = Budget(max_runs=10, max_eur=5.0)
        led = TokenLedger(budget=b)
        led.record(
            TokenUsage(prompt_tokens=1_000_000, completion_tokens=500_000, total_tokens=1_500_000),
            _handle(in_p=2.0, out_p=4.0),
        )
        # cost = 2.0*(1M/1M) + 4.0*(0.5M/1M) = 2.0 + 2.0 = 4.0
        assert led.cost_eur == pytest.approx(4.0)
        assert b.used_eur == pytest.approx(4.0)  # ← feeds the Director's max_eur cap
        assert led.prompt_tokens == 1_000_000
        assert led.completion_tokens == 500_000
        assert led.n_calls == 1

    def test_record_none_is_neutral(self):
        b = Budget(max_runs=10)
        led = TokenLedger(budget=b)
        led.record(None, _handle())
        assert led.n_calls == 1
        assert led.cost_eur == 0.0
        assert b.used_eur == 0.0
        assert led.prompt_tokens == 0

    def test_accumulates_across_calls(self):
        b = Budget(max_runs=10)
        led = TokenLedger(budget=b)
        u = TokenUsage(prompt_tokens=1_000_000, completion_tokens=0, total_tokens=1_000_000)
        led.record(u, _handle(in_p=1.0, out_p=0.0))
        led.record(u, _handle(in_p=1.0, out_p=0.0))
        assert led.cost_eur == pytest.approx(2.0)
        assert b.used_eur == pytest.approx(2.0)
        assert led.n_calls == 2

    def test_null_pricing_counts_tokens_no_cost(self):
        b = Budget(max_runs=10)
        led = TokenLedger(budget=b)
        led.record(
            TokenUsage(prompt_tokens=1000, completion_tokens=1000, total_tokens=2000),
            _handle(in_p=0.0, out_p=0.0),
        )
        assert led.cost_eur == 0.0
        assert led.prompt_tokens == 1000 and led.completion_tokens == 1000


class _FakeProvider:
    is_active = True

    def __init__(self, models):
        self._models = models

    def list_models(self):
        return self._models


class TestResolveAgentLLM:
    def test_returns_handle_with_pricing(self, monkeypatch):
        reg = pytest.importorskip("src.backend.ai.registry")
        mi = ModelInfo(
            model_id="deepseek-reasoner", display_name="DS", provider="deepseek",
            input_price_per_m=1.5, output_price_per_m=3.0, supports_tools=True,
        )
        monkeypatch.setattr(reg, "get_provider", lambda name: _FakeProvider([mi]))
        h = resolve_agent_llm("DeepSeek", "deepseek-reasoner")
        assert h is not None
        assert h.model == "deepseek-reasoner"
        assert h.input_price_per_m == 1.5
        assert h.output_price_per_m == 3.0
        assert h.supports_tools is True

    def test_none_when_no_provider(self, monkeypatch):
        reg = pytest.importorskip("src.backend.ai.registry")
        monkeypatch.setattr(reg, "get_provider", lambda name: None)
        assert resolve_agent_llm("nope", "m") is None

    def test_none_when_no_models(self, monkeypatch):
        reg = pytest.importorskip("src.backend.ai.registry")
        monkeypatch.setattr(reg, "get_provider", lambda name: _FakeProvider([]))
        assert resolve_agent_llm("p", "m") is None

    def test_falls_back_to_first_model_when_requested_missing(self, monkeypatch):
        reg = pytest.importorskip("src.backend.ai.registry")
        mi = ModelInfo(model_id="only-model", display_name="X", provider="p",
                       input_price_per_m=1.0, output_price_per_m=1.0)
        monkeypatch.setattr(reg, "get_provider", lambda name: _FakeProvider([mi]))
        h = resolve_agent_llm("p", "does-not-exist")
        assert h is not None and h.model == "only-model"


class TestW0Inertness:
    def test_no_llm_call_in_w0_module(self):
        # W0 must never invoke an LLM — no chat_completion *call* in agent_llm
        # (the string may appear in a docstring; we forbid the call syntax).
        assert ".chat_completion(" not in inspect.getsource(agent_llm)
        assert "chat_completion(" not in inspect.getsource(agent_llm)

    def test_state_has_effective_agent_mode(self):
        from src.backend.ai.research.state import GoalBrief, ResearchState
        st = ResearchState(goal=GoalBrief(goal_text="t"), budget=Budget(max_runs=1))
        assert st.agent_mode == "rule_based"  # honest default
