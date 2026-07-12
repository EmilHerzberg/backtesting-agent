"""Google Gemini provider via the OpenAI-compatible endpoint. Training-rich — leakage risk (F-11).

Prices approximate (drive the UI estimate only) — verify at deploy. Reasoning ("thinking") on Gemini 3 may
not surface as <think> tags via the compat endpoint; the answer is what the agent needs.
"""
from __future__ import annotations

from decimal import Decimal

from src.backend.ai.models import ModelInfo
from src.backend.ai.providers.base import OpenAICompatibleProvider

GEMINI_MODELS: list[ModelInfo] = [
    # DEFAULT first: gemini-2.5-pro works on an AI Studio key (GOOGLE_API_KEY). gemini-3-pro below is
    # Vertex-only and 404s on AI Studio — keep the fallback (resolve_agent_llm substitutes models[0]) on a
    # model that actually resolves for the common key type.
    ModelInfo(model_id="gemini-2.5-pro", display_name="Gemini 2.5 Pro", provider="gemini",
              description="Balanced flagship, thinking. Available on AI Studio (GOOGLE_API_KEY). Measured "
                          "leakage risk (Gemini family = calibrated recall in our research).",
              context_window=1000000, input_price_per_m=Decimal("1.25"), output_price_per_m=Decimal("10.0"),
              supports_streaming=True, supports_tools=True, supports_reasoning=True, supports_json_mode=True,
              leakage="risk"),
    ModelInfo(model_id="gemini-3-pro", display_name="Gemini 3 Pro (Vertex)", provider="gemini",
              description="Google flagship, thinking. VERTEX-ONLY — 404s on an AI Studio key; needs Vertex AI "
                          "credentials. Measured leakage risk — use only as a research oracle, not for selection.",
              context_window=1000000, input_price_per_m=Decimal("2.0"), output_price_per_m=Decimal("12.0"),
              supports_streaming=True, supports_tools=True, supports_reasoning=True, supports_json_mode=True,
              leakage="risk"),
    ModelInfo(model_id="gemini-2.5-flash", display_name="Gemini 2.5 Flash", provider="gemini",
              description="Fast, cheap, 1M context. Measured leakage lean (Gemini family).",
              context_window=1000000, input_price_per_m=Decimal("0.30"), output_price_per_m=Decimal("2.50"),
              supports_streaming=True, supports_tools=True, supports_json_mode=True, leakage="risk"),
]


class GeminiProvider(OpenAICompatibleProvider):
    PROVIDER_TYPE = "gemini"
    DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
    MODELS = GEMINI_MODELS
