"""Alibaba Qwen AI Provider — EU deployment available."""
from __future__ import annotations

from decimal import Decimal

from src.backend.ai.models import ModelInfo
from src.backend.ai.providers.base import OpenAICompatibleProvider

QWEN_MODELS: list[ModelInfo] = [
    ModelInfo(model_id="qwen-plus", display_name="Qwen Plus", provider="qwen",
              description="1M context, strong all-rounder. EU deployment (Frankfurt) available.",
              context_window=1000000, input_price_per_m=Decimal("0.40"), output_price_per_m=Decimal("1.20"),
              supports_streaming=True, supports_tools=True, supports_json_mode=True),
    ModelInfo(model_id="qwen3.5-plus", display_name="Qwen 3.5 Plus", provider="qwen",
              description="Latest Qwen, 1M context. GPQA ~88%, AIME 2026: 91.3%",
              context_window=1000000, input_price_per_m=Decimal("0.40"), output_price_per_m=Decimal("2.40"),
              supports_streaming=True, supports_tools=True, supports_reasoning=True),
    ModelInfo(model_id="qwen-turbo", display_name="Qwen Turbo", provider="qwen",
              description="Fast and cheap, 1M context",
              context_window=1000000, input_price_per_m=Decimal("0.05"), output_price_per_m=Decimal("0.40"),
              supports_streaming=True, supports_tools=True),
    ModelInfo(model_id="qwq-plus", display_name="QwQ Plus (Reasoning)", provider="qwen",
              description="Dedicated reasoning model with Chain-of-Thought",
              context_window=131000, input_price_per_m=Decimal("0.80"), output_price_per_m=Decimal("2.40"),
              supports_streaming=True, supports_reasoning=True),
]


class QwenProvider(OpenAICompatibleProvider):
    PROVIDER_TYPE = "qwen"
    DEFAULT_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    MODELS = QWEN_MODELS
