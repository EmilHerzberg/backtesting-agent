"""Zhipu GLM AI Provider — includes free GLM-4.7-Flash."""
from __future__ import annotations

from decimal import Decimal

from src.backend.ai.models import ModelInfo
from src.backend.ai.providers.base import OpenAICompatibleProvider

ZHIPU_MODELS: list[ModelInfo] = [
    ModelInfo(model_id="glm-4.7-flash", display_name="GLM-4.7 Flash (GRATIS)", provider="zhipu",
              description="Completely FREE. 128K context. Good for simple tasks and pre-filtering.",
              context_window=128000, input_price_per_m=Decimal("0"), output_price_per_m=Decimal("0"),
              supports_streaming=True, supports_tools=True),
    ModelInfo(model_id="glm-5", display_name="GLM-5", provider="zhipu",
              description="200K context, reasoning. GPQA: 86%, SWE-bench: 77.8%",
              context_window=200000, input_price_per_m=Decimal("1.00"), output_price_per_m=Decimal("3.20"),
              supports_streaming=True, supports_tools=True, supports_reasoning=True),
    ModelInfo(model_id="glm-5-plus", display_name="GLM-5 Plus", provider="zhipu",
              description="Enhanced GLM-5 with better reasoning",
              context_window=200000, input_price_per_m=Decimal("1.50"), output_price_per_m=Decimal("4.80"),
              supports_streaming=True, supports_tools=True, supports_reasoning=True),
]


class ZhipuProvider(OpenAICompatibleProvider):
    PROVIDER_TYPE = "zhipu"
    DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
    MODELS = ZHIPU_MODELS
