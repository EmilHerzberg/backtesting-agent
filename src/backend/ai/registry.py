"""AI Provider Registry — manages provider instances."""
from __future__ import annotations

import logging
from typing import Type

from src.backend.ai.interface import IAIProvider
from src.backend.ai.models import ModelInfo, ProviderConfig

logger = logging.getLogger(__name__)

_PROVIDER_TYPES: dict[str, Type[IAIProvider]] = {}


def _register_defaults() -> None:
    """Register built-in provider types."""
    from src.backend.ai.providers.minimax import MiniMaxProvider
    from src.backend.ai.providers.deepseek import DeepSeekProvider
    from src.backend.ai.providers.qwen import QwenProvider
    from src.backend.ai.providers.zhipu import ZhipuProvider
    from src.backend.ai.providers.moonshot import MoonshotProvider
    from src.backend.ai.providers.openai import OpenAIProvider
    from src.backend.ai.providers.gemini import GeminiProvider
    from src.backend.ai.providers.anthropic import AnthropicProvider
    from src.backend.ai.providers.byteplus import BytePlusProvider
    _PROVIDER_TYPES["minimax"] = MiniMaxProvider
    _PROVIDER_TYPES["deepseek"] = DeepSeekProvider
    _PROVIDER_TYPES["qwen"] = QwenProvider
    _PROVIDER_TYPES["zhipu"] = ZhipuProvider
    _PROVIDER_TYPES["moonshot"] = MoonshotProvider
    # Phase 2 — leakage classification is per-model now (grounded); providers just carry their models.
    _PROVIDER_TYPES["openai"] = OpenAIProvider
    _PROVIDER_TYPES["gemini"] = GeminiProvider
    _PROVIDER_TYPES["anthropic"] = AnthropicProvider
    _PROVIDER_TYPES["byteplus"] = BytePlusProvider   # research's validated mechanism-only production model


_register_defaults()
_INSTANCES: dict[str, IAIProvider] = {}


def register_provider_type(provider_type: str, cls: Type[IAIProvider]) -> None:
    """Register a provider class by type name."""
    _PROVIDER_TYPES[provider_type] = cls


def create_provider(config: ProviderConfig) -> IAIProvider:
    """Create and register a provider instance from config."""
    cls = _PROVIDER_TYPES.get(config.provider_type)
    if cls is None:
        raise ValueError(
            f"Unknown provider type '{config.provider_type}'. "
            f"Available: {', '.join(sorted(_PROVIDER_TYPES.keys()))}"
        )
    instance = cls(config)
    _INSTANCES[config.name] = instance
    logger.info("Registered AI provider: %s (%s)", config.name, config.provider_type)
    return instance


def get_provider(name: str) -> IAIProvider | None:
    """Get a registered provider by name."""
    return _INSTANCES.get(name)


def get_all_providers() -> dict[str, IAIProvider]:
    """Get all registered providers."""
    return dict(_INSTANCES)


def get_all_models() -> list[ModelInfo]:
    """Get all models from all active providers."""
    models = []
    for provider in _INSTANCES.values():
        if provider.is_active:
            models.extend(provider.list_models())
    return models


def remove_provider(name: str) -> None:
    """Remove a provider by name."""
    _INSTANCES.pop(name, None)


def available_provider_types() -> list[str]:
    """Return list of registered provider type names."""
    return sorted(_PROVIDER_TYPES.keys())
