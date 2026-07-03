"""BytePlus (ModelArk) provider — OpenAI-compatible. Seed 2.0 Pro is our research's validated mechanism-only
production model (LLM-DATA-LEAKAGE-AND-MODEL-SELECTION.md). Base URL + exact model ids/pricing — verify at deploy.
"""
from __future__ import annotations

from decimal import Decimal

from src.backend.ai.models import ModelInfo
from src.backend.ai.providers.base import OpenAICompatibleProvider

BYTEPLUS_MODELS: list[ModelInfo] = [
    ModelInfo(model_id="seed-2-0-pro-260328", display_name="BytePlus Seed 2.0 Pro", provider="byteplus",
              description="Validated mechanism-only — the cleanest / production enricher in our leakage research "
                          "(refuses when the mechanism is ambiguous; regressable error). Recommended for selection.",
              context_window=256000, input_price_per_m=Decimal("0.30"), output_price_per_m=Decimal("1.20"),
              supports_streaming=True, supports_tools=True, supports_reasoning=True, leakage="mechanism_only"),
    ModelInfo(model_id="seed-2-0-lite-260428", display_name="BytePlus Seed 2.0 Lite", provider="byteplus",
              description="Lighter Seed 2.0. Not evaluated for leakage.",
              context_window=256000, input_price_per_m=Decimal("0.15"), output_price_per_m=Decimal("0.60"),
              supports_streaming=True, supports_tools=True),  # leakage defaults to "unvalidated"
]


class BytePlusProvider(OpenAICompatibleProvider):
    PROVIDER_TYPE = "byteplus"
    DEFAULT_BASE_URL = "https://ark.ap-southeast.bytepluses.com/api/v3"
    MODELS = BYTEPLUS_MODELS
