"""Data-leakage classification of AI models — grounded in the research, per-model (not per-provider).

See `docs/bt-agent/LEAKAGE-CLASSIFICATION-GROUNDED.md` + `docs/event-factor-gate-system/02-architecture/
LLM-DATA-LEAKAGE-AND-MODEL-SELECTION.md`. Three states — the classification lives on each `ModelInfo.leakage`:

  mechanism_only  validated clean (reasons from the prompt, not memorised outcomes) — recommended for selection
  risk            leakage risk (measured for Gemini; assumed/untested for OpenAI/Anthropic)
  unvalidated     no claim either way (tested only as verifier / skipped / never evaluated) — NOT "clean"

Only three models are evidence-validated mechanism-only (deepseek-reasoner, byteplus seed-2-0-pro; gemini is the
measured risk). The rest default to `unvalidated` so the UI never implies untested models are safe.
"""

from __future__ import annotations

MECHANISM_ONLY = "mechanism_only"
RISK = "risk"
UNVALIDATED = "unvalidated"


def _iter_catalog_models():
    """All ModelInfo across every registered provider class (static catalog, no instances needed)."""
    from src.backend.ai.registry import _PROVIDER_TYPES

    for cls in _PROVIDER_TYPES.values():
        for m in getattr(cls, "MODELS", []) or []:
            yield m


def model_leakage(model_id: str | None) -> str:
    """The leakage state of a specific model id (default `unvalidated` if unknown)."""
    if not model_id:
        return UNVALIDATED
    for m in _iter_catalog_models():
        if m.model_id == model_id:
            return getattr(m, "leakage", UNVALIDATED) or UNVALIDATED
    return UNVALIDATED


def provider_leakage(provider_type: str | None) -> str:
    """Summary state for a provider, from its models: `mechanism_only` if it offers a validated model, else
    `risk` if any model is risk, else `unvalidated`. Drives the per-provider (key-management) chip."""
    from src.backend.ai.registry import _PROVIDER_TYPES

    cls = _PROVIDER_TYPES.get((provider_type or "").lower())
    if cls is None:
        return UNVALIDATED
    states = {getattr(m, "leakage", UNVALIDATED) for m in getattr(cls, "MODELS", []) or []}
    if MECHANISM_ONLY in states:
        return MECHANISM_ONLY
    if RISK in states:
        return RISK
    return UNVALIDATED


def is_leakage_risk(provider_type: str | None) -> bool:
    """Back-compat: True when the provider's summary state is `risk`."""
    return provider_leakage(provider_type) == RISK
