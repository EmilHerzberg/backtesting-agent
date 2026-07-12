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
    """Extract the FIRST balanced {...} JSON object from an LLM reply (markdown/code-fence tolerant).

    M42: the old "first { to last }" slice discarded billed LLM output whenever the reply had prose
    containing a stray '}', two JSON objects, or a raw newline inside a string. Now we strip code
    fences and try to ``raw_decode`` a JSON object starting at each '{' (``strict=False`` tolerates
    control chars in strings); the first that parses to a dict wins. None only when none is present.
    """
    if not content:
        return None
    text = content.strip()
    if "```" in text:                                  # unwrap ```json ... ``` / ``` ... ```
        import re
        m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if m:
            text = m.group(1).strip()
    decoder = json.JSONDecoder(strict=False)
    i = text.find("{")
    while i != -1:
        try:
            obj, _ = decoder.raw_decode(text, i)
            if isinstance(obj, dict):
                return obj
        except Exception:  # noqa: BLE001 — not a valid object at this '{', try the next
            pass
        i = text.find("{", i + 1)
    return None


@dataclass
class LLMHandle:
    """A ready-to-call provider+model bundle, with pricing for cost accounting."""

    provider: IAIProvider
    model: str
    input_price_per_m: float | None    # EUR per 1M prompt tokens (None = unknown, 0.0 = genuinely free)
    output_price_per_m: float | None   # EUR per 1M completion tokens (None = unknown)
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
    mi = next((m for m in models if m.model_id == model), None)
    if mi is None:
        if model:   # M43: don't silently swap — a mismatched id has different pricing AND leakage class
            logger.warning("Requested model %r not found for provider %s — substituting %s "
                           "(different pricing/leakage class)", model,
                           getattr(inst, "provider_type", "?"), models[0].model_id)
        mi = models[0]
    return LLMHandle(
        provider=inst,
        model=mi.model_id,
        # M44: preserve None (unknown pricing) distinctly from 0.0 (genuinely free) — do NOT fabricate 0,
        # which read €0.0000 in the HUD and let the € budget cap silently never bind for unpriced models.
        input_price_per_m=(float(mi.input_price_per_m) if mi.input_price_per_m is not None else None),
        output_price_per_m=(float(mi.output_price_per_m) if mi.output_price_per_m is not None else None),
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
    n_failures: int = 0       # M57: hard LLM-call failures (exceptions) that forced a rule-based fallback
    cost_eur: float = 0.0
    cost_known: bool = True   # M44: False once any call used a model with unknown pricing

    def record_failure(self, exc: BaseException | None = None) -> None:
        """M57: an LLM call raised (auth/credit/network/rate-limit) and the agent fell back to the
        rule-based/templated path. Count it AND propagate onto the Budget so the flag outlives this
        (per-run, discarded) ledger and reaches ResearchState → the API state + report banner. Without
        this a full_ai run whose every call 401s reports a clean 'completed full_ai' with used_eur=0."""
        self.n_failures += 1
        self.budget.llm_failures += 1

    def record(self, usage: TokenUsage | None, llm: LLMHandle) -> None:
        self.n_calls += 1
        if usage is None:
            return
        self.prompt_tokens += usage.prompt_tokens
        self.completion_tokens += usage.completion_tokens
        if llm.input_price_per_m is None or llm.output_price_per_m is None:
            # M44: pricing unknown — record the tokens but do NOT fabricate €0. cost_eur/used_eur stay
            # honest (the HUD should show "unknown (N tokens)"); the € cap genuinely cannot bind here.
            # Propagate onto the Budget so the flag OUTLIVES this (discarded) ledger and reaches the
            # ResearchState → API/report surface (the ledger itself is a per-run local).
            self.cost_known = False
            self.budget.cost_known = False
            return
        cost = (
            llm.input_price_per_m * usage.prompt_tokens
            + llm.output_price_per_m * usage.completion_tokens
        ) / 1_000_000
        self.cost_eur += cost
        self.budget.used_eur += cost
