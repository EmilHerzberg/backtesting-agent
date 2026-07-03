"""Anthropic (Claude) provider — dedicated adapter for the Messages API (not OpenAI-shaped).

Training-rich → flagged as a backtest-selection leakage risk (F-11). Handles the two behaviours the
research Critic/Strategist rely on (LV2-2): json_mode (no response_format on Anthropic → system instruction
+ assistant "{" prefill) and extended thinking (budget_tokens < max_tokens, temperature=1). Prices approximate
(UI estimate only) — verify at deploy.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal

from src.backend.ai.interface import IAIProvider
from src.backend.ai.models import (
    ChatRequest,
    ChatResponse,
    ModelInfo,
    ProviderConfig,
    TokenUsage,
)

ANTHROPIC_MODELS: list[ModelInfo] = [
    ModelInfo(model_id="claude-opus-4-8", display_name="Claude Opus 4.8", provider="anthropic",
              description="Anthropic flagship, extended thinking. Assumed leakage risk — NOT tested in our "
                          "research; flagged as training-rich by analogy.",
              context_window=200000, input_price_per_m=Decimal("15.0"), output_price_per_m=Decimal("75.0"),
              supports_streaming=True, supports_tools=True, supports_reasoning=True, leakage="risk"),
    ModelInfo(model_id="claude-sonnet-4-6", display_name="Claude Sonnet 4.6", provider="anthropic",
              description="Balanced, extended thinking. Assumed leakage risk — not tested in our research.",
              context_window=200000, input_price_per_m=Decimal("3.0"), output_price_per_m=Decimal("15.0"),
              supports_streaming=True, supports_tools=True, supports_reasoning=True, leakage="risk"),
    ModelInfo(model_id="claude-haiku-4-5-20251001", display_name="Claude Haiku 4.5", provider="anthropic",
              description="Fast + cheap. Assumed leakage risk — not tested in our research.",
              context_window=200000, input_price_per_m=Decimal("1.0"), output_price_per_m=Decimal("5.0"),
              supports_streaming=True, supports_tools=True, leakage="risk"),
]

_JSON_INSTRUCTION = " Respond with ONLY a single valid JSON object and nothing else."


class AnthropicProvider(IAIProvider):
    PROVIDER_TYPE = "anthropic"
    DEFAULT_BASE_URL = ""
    MODELS = ANTHROPIC_MODELS

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic(api_key=config.api_key)
        self._api_key = config.api_key

    @property
    def provider_type(self) -> str:
        return "anthropic"

    def list_models(self) -> list[ModelInfo]:
        return list(self.MODELS)

    def _build(self, request: ChatRequest) -> tuple[dict, str]:
        """Map a ChatRequest → messages.create kwargs. Returns (kwargs, prefill)."""
        system_parts: list[str] = []
        messages: list[dict] = []
        for m in request.messages:
            if m.role == "system":
                if m.content:
                    system_parts.append(m.content)
            elif m.role in ("user", "assistant"):
                messages.append({"role": m.role, "content": m.content or ""})
            # tool turns unused by the research agents (text turns only) — skip.
        system = " ".join(system_parts).strip()
        if request.json_mode:
            system = (system + _JSON_INSTRUCTION).strip()

        kwargs: dict = {"model": request.model, "max_tokens": request.max_tokens, "messages": messages}
        if system:
            kwargs["system"] = system

        prefill = ""
        # Extended thinking requires temperature=1 + budget < max_tokens, and forbids assistant prefill.
        if request.reasoning and request.max_tokens >= 2048:
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": max(1024, request.max_tokens // 2)}
            kwargs["temperature"] = 1.0
        else:
            kwargs["temperature"] = min(float(request.temperature), 1.0)  # Anthropic caps at 1.0
            if request.json_mode:
                prefill = "{"
                kwargs["messages"] = messages + [{"role": "assistant", "content": prefill}]
        return kwargs, prefill

    async def chat_completion(self, request: ChatRequest) -> ChatResponse:
        kwargs, prefill = self._build(request)
        resp = await self._client.messages.create(**kwargs)

        text_parts: list[str] = []
        thinking_parts: list[str] = []
        for block in resp.content:
            btype = getattr(block, "type", "")
            if btype == "text":
                text_parts.append(getattr(block, "text", ""))
            elif btype == "thinking":
                thinking_parts.append(getattr(block, "thinking", ""))
        content = (prefill + "".join(text_parts)) if prefill else "".join(text_parts)

        usage = None
        u = getattr(resp, "usage", None)
        if u is not None:
            usage = TokenUsage(
                prompt_tokens=getattr(u, "input_tokens", 0),
                completion_tokens=getattr(u, "output_tokens", 0),
                total_tokens=getattr(u, "input_tokens", 0) + getattr(u, "output_tokens", 0),
            )
        return ChatResponse(
            model=getattr(resp, "model", request.model), provider="anthropic",
            content=content.strip(), finish_reason=getattr(resp, "stop_reason", None),
            usage=usage, reasoning_content=("".join(thinking_parts).strip() or None),
        )

    async def chat_completion_stream(self, request: ChatRequest) -> AsyncIterator[str]:
        kwargs, prefill = self._build(request)
        if prefill:
            yield prefill
        async with self._client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield text
