"""ATS-1721 — Provider capability registry.

Loads per-provider capability flags from config/provider_capabilities.yaml.
Used by gates to block research conclusions on biased data.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel


_CONFIG_PATH = Path(__file__).resolve().parents[4] / "config" / "provider_capabilities.yaml"


class ProviderCapability(BaseModel):
    """Capability flags for a single data provider."""

    supports_delisted: bool = False
    supports_pit_membership: bool = False
    supports_corporate_actions: bool = False
    supports_dividends: bool = False
    supports_split_adjusted_ohlcv: bool = False
    supports_total_return_series: bool = False
    research_conclusion_allowed: bool = False
    survivorship_bias_risk: bool = True
    provider_class: str = "unknown"
    notes: str = ""


# Module-level cache.
_capabilities: dict[str, ProviderCapability] | None = None


def _load() -> dict[str, ProviderCapability]:
    global _capabilities
    if _capabilities is not None:
        return _capabilities

    if not _CONFIG_PATH.exists():
        _capabilities = {}
        return _capabilities

    with open(_CONFIG_PATH) as f:
        raw = yaml.safe_load(f)

    providers: dict[str, Any] = raw.get("providers", {})
    _capabilities = {
        name: ProviderCapability(**cfg)
        for name, cfg in providers.items()
    }
    return _capabilities


def get_capability(provider_name: str) -> ProviderCapability:
    """Return capability flags for a provider (falls back to _default)."""
    caps = _load()
    if provider_name in caps:
        return caps[provider_name]
    return caps.get("_default", ProviderCapability())


def get_bias_flags(provider_name: str) -> dict[str, bool]:
    """Return the bias_flags dict to attach to a DataSnapshot / BacktestResult."""
    cap = get_capability(provider_name)
    return {
        "survivorship_bias": cap.survivorship_bias_risk,
        "point_in_time": cap.supports_pit_membership,
        "research_conclusion_allowed": cap.research_conclusion_allowed,
    }


def reset_cache() -> None:
    """Clear the module-level cache (for testing)."""
    global _capabilities
    _capabilities = None
