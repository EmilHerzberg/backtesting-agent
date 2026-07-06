"""W0 — provider plumbing + token accounting for the agent layer.

Rails the LLM agents (W1 Critic -> W2 Strategist -> W3 Reporter) ride on.
INERT until W1: nothing here calls an LLM. Resolution is registry-based (no DB
session), mirroring the /chat endpoint. See W0-PROVIDER-PLUMBING-SPEC.md (v2).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from src.backend.ai.interface import IAIProvider
from src.backend.ai.models import TokenUsage
from src.backend.ai.research.state import Budget

logger = logging.getLogger(__name__)


def extract_json_object(content: str | None) -> dict | None:
    """Extract the first {...} JSON object from an LLM reply (markdown-tolerant).

    Shared by the agent LLM paths (W1 Critic, W2 Strategist). Returns None on any failure.
    """
    if not content:
        return None
    start, end = content.find("{"), content.rfind("}")
    if start == -1 or end < start:
        return None
    try:
        obj = json.loads(content[start:end + 1])
    except Exception:  # noqa: BLE001
        return None
    return obj if isinstance(obj, dict) else None


@dataclass
class LLMHandle:
    """A ready-to-call provider+model bundle, with pricing for cost accounting."""

    provider: IAIProvider
    model: str
    input_price_per_m: float       # EUR per 1M prompt tokens (0.0 if unknown)
    output_price_per_m: float      # EUR per 1M completion tokens
    supports_tools: bool = False
    supports_json_mode: bool = False
    supports_reasoning: bool = False   # H25: reasoning models need a larger max_tokens (reason-before-JSON)


def _auto_pick() -> IAIProvider | None:
    """First active registry provider with a reasoning model (else first active)."""
    from src.backend.ai.registry import get_all_providers

    providers = [p for p in get_all_providers().values() if p.is_active]
    for p in providers:
        try:
            if any(getattr(m, "supports_reasoning", False) for m in p.list_models()):
                return p
        except Exception:  # noqa: BLE001 — a flaky provider shouldn't break selection
            continue
    return providers[0] if providers else None


def resolve_agent_llm(
    provider_name: str | None = None,
    model: str | None = None,
) -> LLMHandle | None:
    """Resolve a live provider+model+pricing from the in-memory registry.

    Registry-based (no DB session), like the /chat endpoint. Returns None if no
    usable provider is found -> the caller falls back to rule-based (never fakes AI).
    """
    from src.backend.ai.registry import get_provider

    inst = get_provider(provider_name) if provider_name else _auto_pick()
    if inst is None:
        return None
    models = inst.list_models()
    if not models:
        return None
    mi = next((m for m in models if m.model_id == model), None) or models[0]
    return LLMHandle(
        provider=inst,
        model=mi.model_id,
        input_price_per_m=float(mi.input_price_per_m or 0),
        output_price_per_m=float(mi.output_price_per_m or 0),
        supports_tools=bool(mi.supports_tools),
        supports_json_mode=bool(getattr(mi, "supports_json_mode", False)),
        supports_reasoning=bool(getattr(mi, "supports_reasoning", False)),
    )


@dataclass
class TokenLedger:
    """Per-run token + EUR accumulator.

    Cost flows into Budget.used_eur so the Director's max_eur cap (R2) enforces
    spend. Each W1+ agent calls record(response.usage, llm) after chat_completion.
    """

    budget: Budget
    prompt_tokens: int = 0
    completion_tokens: int = 0
    n_calls: int = 0
    cost_eur: float = 0.0

    def record(self, usage: TokenUsage | None, llm: LLMHandle) -> None:
        self.n_calls += 1
        if usage is None:
            return
        self.prompt_tokens += usage.prompt_tokens
        self.completion_tokens += usage.completion_tokens
        cost = (
            llm.input_price_per_m * usage.prompt_tokens
            + llm.output_price_per_m * usage.completion_tokens
        ) / 1_000_000
        self.cost_eur += cost
        self.budget.used_eur += cost
