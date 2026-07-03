"""OpenAI (ChatGPT) provider. Training-rich — flagged as a backtest-selection leakage risk (F-11).

Prices are approximate (per 1M tokens, EUR-ish) and only drive the UI cost estimate — verify against
OpenAI's current pricing at deploy. Reasoning (o-series) models have API quirks handled in _build_kwargs.
"""
from __future__ import annotations

from decimal import Decimal

from src.backend.ai.models import ChatRequest, ModelInfo
from src.backend.ai.providers.base import OpenAICompatibleProvider

OPENAI_MODELS: list[ModelInfo] = [
    ModelInfo(model_id="gpt-5", display_name="GPT-5", provider="openai",
              description="OpenAI flagship. Assumed leakage risk — NOT tested in our research; flagged as "
                          "training-rich by analogy. Prefer a validated mechanism-only model for selection.",
              context_window=400000, input_price_per_m=Decimal("1.25"), output_price_per_m=Decimal("10.0"),
              supports_streaming=True, supports_tools=True, supports_json_mode=True, leakage="risk"),
    ModelInfo(model_id="o3", display_name="OpenAI o3 (reasoning)", provider="openai",
              description="Reasoning model (hidden CoT). Assumed leakage risk — not tested in our research.",
              context_window=200000, input_price_per_m=Decimal("2.0"), output_price_per_m=Decimal("8.0"),
              supports_streaming=True, supports_tools=True, supports_reasoning=True, supports_json_mode=True,
              leakage="risk"),
]

_REASONING_IDS = {m.model_id for m in OPENAI_MODELS if m.supports_reasoning}


class OpenAIProvider(OpenAICompatibleProvider):
    PROVIDER_TYPE = "openai"
    DEFAULT_BASE_URL = "https://api.openai.com/v1"
    MODELS = OPENAI_MODELS

    def _build_kwargs(self, request: ChatRequest) -> dict:
        kwargs = super()._build_kwargs(request)
        # o-series reasoning models reject custom temperature/top_p and use max_completion_tokens;
        # their chain-of-thought is hidden (no <think> tags → reasoning_content stays empty).
        if request.model in _REASONING_IDS:
            kwargs.pop("temperature", None)
            kwargs.pop("top_p", None)
            if "max_tokens" in kwargs:
                kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
        return kwargs
