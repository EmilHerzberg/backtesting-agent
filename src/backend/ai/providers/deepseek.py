"""DeepSeek AI Provider — V3.2 + Reasoner."""
from __future__ import annotations

from decimal import Decimal

from src.backend.ai.models import ModelInfo
from src.backend.ai.providers.base import OpenAICompatibleProvider

DEEPSEEK_MODELS: list[ModelInfo] = [
    ModelInfo(model_id="deepseek-chat", display_name="DeepSeek V3.2", provider="deepseek",
              description="Frontier-quality at 10-20x lower cost than GPT-4o. 128K context.",
              context_window=128000, input_price_per_m=Decimal("0.28"), output_price_per_m=Decimal("0.42"),
              supports_streaming=True, supports_tools=True, supports_json_mode=True),
    ModelInfo(model_id="deepseek-reasoner", display_name="DeepSeek Reasoner", provider="deepseek",
              description="Chain-of-Thought reasoning, 64K CoT tokens. Validated mechanism-only (reasons from "
                          "the prompt, not memorised outcomes) — recommended for strategy selection.",
              context_window=128000, input_price_per_m=Decimal("0.28"), output_price_per_m=Decimal("0.42"),
              supports_streaming=True, supports_tools=True, supports_reasoning=True, leakage="mechanism_only"),
]


class DeepSeekProvider(OpenAICompatibleProvider):
    PROVIDER_TYPE = "deepseek"
    DEFAULT_BASE_URL = "https://api.deepseek.com"
    MODELS = DEEPSEEK_MODELS
