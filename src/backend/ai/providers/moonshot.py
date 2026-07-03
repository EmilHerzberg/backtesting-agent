"""Moonshot/Kimi AI Provider — Agent-Swarm Deep Research."""
from __future__ import annotations

from decimal import Decimal

from src.backend.ai.models import ModelInfo
from src.backend.ai.providers.base import OpenAICompatibleProvider

MOONSHOT_MODELS: list[ModelInfo] = [
    ModelInfo(model_id="kimi-k2.5", display_name="Kimi K2.5", provider="moonshot",
              description="256K context. Agent-Swarm: 100 parallel sub-agents. HLE: 50.2%",
              context_window=256000, input_price_per_m=Decimal("0.50"), output_price_per_m=Decimal("2.80"),
              supports_streaming=True, supports_tools=True, supports_reasoning=True),
    ModelInfo(model_id="kimi-k2.5-thinking", display_name="Kimi K2.5 Thinking", provider="moonshot",
              description="Extended reasoning mode with visible Chain-of-Thought",
              context_window=256000, input_price_per_m=Decimal("0.50"), output_price_per_m=Decimal("2.80"),
              supports_streaming=True, supports_tools=True, supports_reasoning=True),
]


class MoonshotProvider(OpenAICompatibleProvider):
    PROVIDER_TYPE = "moonshot"
    DEFAULT_BASE_URL = "https://api.moonshot.cn/v1"
    MODELS = MOONSHOT_MODELS
