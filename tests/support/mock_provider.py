"""MockProvider — a €0 IAIProvider test double for the verification harness (ATS-1794).

Records every chat_completion call, returns canned JSON (a superset object that satisfies BOTH the
Strategist parser — template_id/params — and the Critic parser — recommendation/confidence/…), and
meters zero token cost. Used to:
  * assert ZERO LLM calls on the rule_based path (RUN-7 / cost invariant), and
  * exercise the ai_assisted/full_ai wiring at €0 without a real key or network (AIR-2/3/4).
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from decimal import Decimal
from typing import Any

from src.backend.ai.interface import IAIProvider
from src.backend.ai.models import ChatRequest, ChatResponse, ModelInfo, TokenUsage

# A superset response: the Strategist reads template_id/params; the Critic reads
# recommendation/confidence/weaknesses/reasoning. Both parsers use .get(), so extra keys are ignored.
# sma_crossover with fast+5<=slow is a valid, executable spec (see strategist.TEMPLATES).
DEFAULT_RESPONSE: dict[str, Any] = {
    "template_id": "sma_crossover",
    "params": {"fast_period": 10, "slow_period": 30},
    "recommendation": "accept",
    "confidence": "medium",
    "weaknesses": [],
    "reasoning": "Deterministic mock verdict for the zero-cost harness.",
}


def default_models() -> list[ModelInfo]:
    """One free, reasoning-capable, mechanism-only mock model (zero pricing)."""
    return [
        ModelInfo(
            model_id="mock-reason",
            display_name="Mock Reasoner",
            provider="mock",
            description="Zero-cost deterministic mock for the €0 harness.",
            input_price_per_m=Decimal("0"),
            output_price_per_m=Decimal("0"),
            supports_json_mode=True,
            supports_reasoning=True,
            leakage="mechanism_only",
        ),
    ]


class MockProvider(IAIProvider):
    """Zero-cost, deterministic provider double. Inspect `.calls` / `.call_count` after a run."""

    PROVIDER_TYPE = "mock"

    def __init__(
        self,
        config,
        *,
        response: dict | str | Callable[[ChatRequest], dict | str] | None = None,
        models: list[ModelInfo] | None = None,
    ) -> None:
        super().__init__(config)
        self._response = response if response is not None else DEFAULT_RESPONSE
        self._models = models if models is not None else default_models()
        self.calls: list[ChatRequest] = []  # every chat_completion request, in order

    @property
    def provider_type(self) -> str:
        return self.PROVIDER_TYPE

    def list_models(self) -> list[ModelInfo]:
        return list(self._models)

    def _content_for(self, request: ChatRequest) -> str:
        resp = self._response(request) if callable(self._response) else self._response
        return resp if isinstance(resp, str) else json.dumps(resp)

    async def chat_completion(self, request: ChatRequest) -> ChatResponse:
        self.calls.append(request)
        return ChatResponse(
            model=request.model,
            provider=self.PROVIDER_TYPE,
            content=self._content_for(request),
            finish_reason="stop",
            usage=TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        )

    async def chat_completion_stream(self, request: ChatRequest) -> AsyncIterator[str]:
        self.calls.append(request)
        yield self._content_for(request)

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def reset(self) -> None:
        self.calls.clear()
