"""Gap 3: RuleBasedStrategist — proposes strategies without LLM.

Cycles through templates, samples params within bounds, adapts from failures.
Works out of the box without any API key. LLM mode is an upgrade.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from typing import TYPE_CHECKING, Any

import numpy as np

from src.backend.ai.models import ChatMessage, ChatRequest
from src.backend.ai.research.agent_llm import extract_json_object
from src.backend.ai.research.state import FailureContext, Hypothesis

if TYPE_CHECKING:
    from src.backend.ai.research.agent_llm import LLMHandle, TokenLedger

logger = logging.getLogger(__name__)

# System-fixed backtest window (C-6: the LLM Strategist must NOT choose the period).
WINDOW_START, WINDOW_END, BAR_SIZE = "2015-01-01", "2023-12-31", "1d"

# Template registry with parameter spaces.
TEMPLATES: dict[str, dict[str, dict[str, Any]]] = {
    "sma_crossover": {
        "fast_period": {"type": "int", "low": 5, "high": 50},
        "slow_period": {"type": "int", "low": 20, "high": 200},
    },
    "rsi_reversion": {
        "period": {"type": "int", "low": 5, "high": 30},
        "buy_threshold": {"type": "float", "low": 15.0, "high": 40.0},
        "sell_threshold": {"type": "float", "low": 60.0, "high": 85.0},
    },
    "bollinger_breakout": {
        "period": {"type": "int", "low": 10, "high": 50},
        "std_dev": {"type": "float", "low": 1.0, "high": 3.0},  # F8: class param is std_dev (was num_std)
    },
    "macd_cross": {
        # F8: class wants fast/slow (was fast_period/slow_period); ranges keep slow > fast+5 (validate_params)
        "fast": {"type": "int", "low": 5, "high": 15},
        "slow": {"type": "int", "low": 26, "high": 50},
        "signal_period": {"type": "int", "low": 5, "high": 15},
    },
    "multi_indicator": {
        # F8: class wants sma_period/rsi_period/rsi_buy/rsi_sell (was bb_period, no thresholds);
        # ranges keep rsi_sell > rsi_buy+10 (validate_params)
        "sma_period": {"type": "int", "low": 20, "high": 50},
        "rsi_period": {"type": "int", "low": 10, "high": 20},
        "rsi_buy": {"type": "float", "low": 15.0, "high": 40.0},
        "rsi_sell": {"type": "float", "low": 60.0, "high": 85.0},
    },
}

# Strategy family mapping.
FAMILY_MAP: dict[str, list[str]] = {
    "trend_following": ["sma_crossover", "macd_cross"],
    "mean_reversion": ["rsi_reversion", "bollinger_breakout"],
    "multi_factor": ["multi_indicator"],
}


def _sample_params(param_space: dict, rng: np.random.Generator) -> dict[str, Any]:
    """Sample random parameters within bounds."""
    params = {}
    for name, spec in param_space.items():
        if spec["type"] == "int":
            params[name] = int(rng.integers(spec["low"], spec["high"] + 1))
        elif spec["type"] == "float":
            params[name] = round(float(rng.uniform(spec["low"], spec["high"])), 2)
    return params


def _compute_strategy_hash(template_id: str, params: dict, security_id: str) -> str:
    """Quick hash for dedup without full StrategyDefinition overhead."""
    payload = json.dumps(
        {"t": template_id, "p": params, "s": security_id},
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _repair_params(template_id: str, params: dict) -> dict:
    """Enforce cross-parameter constraints the strategy classes require (avoids execution errors).
    sma_crossover needs fast_period + 5 <= slow_period — the class raises otherwise (the LLM/random can
    propose fast >= slow). slow's high (200) >> fast's max (50)+5, so the bump is always in-bounds."""
    fp, sp = params.get("fast_period"), params.get("slow_period")
    if fp is not None and sp is not None and sp < fp + 5:
        params["slow_period"] = fp + 5
    return params


class RuleBasedStrategist:
    """Proposes strategies by cycling templates and sampling params.

    Adapts from failure context:
    - Avoids templates that failed on the same gate repeatedly
    - Adjusts param ranges based on failure details
    - Rotates to unexplored templates first

    No LLM required. Works fully offline.
    """

    def __init__(self, seed: int = 42, window_start: str = WINDOW_START, window_end: str = WINDOW_END):
        self._rng = np.random.default_rng(seed)
        self._tried_hashes: set[str] = set()
        self._template_failures: dict[str, int] = {}  # template_id → failure count
        self._call_count = 0
        # P1: the effective backtest window — robustness = the fixed default, regime = the run's window.
        # The strategist only STAMPS it (the run config sets it); the LLM never chooses it (C-6).
        self.window_start = window_start
        self.window_end = window_end

    async def propose(
        self,
        asset: str,
        strategy_families: list[str],
        failure_context: list[FailureContext],
        registry_summary: dict[str, Any],
    ) -> tuple[Hypothesis, dict[str, Any]]:
        """Propose a strategy spec with hypothesis."""
        self._call_count += 1

        # Learn from failures.
        for fc in failure_context:
            tid = fc.template_id
            if tid:
                self._template_failures[tid] = self._template_failures.get(tid, 0) + 1

        # Determine available templates.
        available = self._get_available_templates(strategy_families)
        if not available:
            available = list(TEMPLATES.keys())

        # Sort: least-failed templates first, then unexplored.
        available.sort(key=lambda t: self._template_failures.get(t, 0))

        # Try to find a spec we haven't tried yet (max 10 attempts).
        for attempt in range(10):
            template_id = available[attempt % len(available)]
            param_space = TEMPLATES[template_id]
            params = _repair_params(template_id, _sample_params(param_space, self._rng))

            strategy_hash = _compute_strategy_hash(template_id, params, asset)
            if strategy_hash not in self._tried_hashes:
                break
        else:
            # All attempts were duplicates — force random.
            template_id = self._rng.choice(available)
            params = _repair_params(template_id, _sample_params(TEMPLATES[template_id], self._rng))
            strategy_hash = _compute_strategy_hash(template_id, params, asset)

        self._tried_hashes.add(strategy_hash)

        # Build hypothesis.
        family = "unknown"
        for fam, templates in FAMILY_MAP.items():
            if template_id in templates:
                family = fam
                break

        recent_failures = [fc for fc in failure_context[-5:] if fc.template_id == template_id]
        adaptation_note = ""
        if recent_failures:
            gates = [fc.failed_gate for fc in recent_failures if fc.failed_gate]
            adaptation_note = f" Adapting from {len(recent_failures)} recent failures on gates: {gates}."

        hypothesis = Hypothesis(
            hypothesis_id=f"hyp_{uuid.uuid4().hex[:12]}",
            author="rule_based_strategist",
            economic_rationale=f"Testing {template_id} ({family}) on {asset}.{adaptation_note}",
            claimed_mechanism=f"{family} strategy exploiting {template_id} signals",
            falsifiable_prediction=f"Expects positive risk-adjusted return with Sharpe > 0.5 on {asset}",
            proposed_template_id=template_id,
            proposed_param_ranges={k: [v["low"], v["high"]] for k, v in TEMPLATES[template_id].items()},
            prior_strength="low",
            linked_specs=[strategy_hash],
        )

        spec = {
            "strategy_hash": strategy_hash,
            "template_id": template_id,
            "params": params,
            "security_id": asset,
            "bar_size": BAR_SIZE,
            "strategy_family": family,
            "window_start": self.window_start,
            "window_end": self.window_end,
        }

        return hypothesis, spec

    def _get_available_templates(self, families: list[str]) -> list[str]:
        """Get templates matching requested families."""
        if not families:
            return list(TEMPLATES.keys())

        available = []
        for fam in families:
            available.extend(FAMILY_MAP.get(fam, []))

        return available if available else list(TEMPLATES.keys())


# ── W2: LLM Strategist ────────────────────────────────────────────────

def _family_of(template_id: str) -> str:
    for fam, tids in FAMILY_MAP.items():
        if template_id in tids:
            return fam
    return "unknown"


STRATEGIST_SYSTEM_PROMPT = """You are a quantitative trading researcher. Propose ONE strategy to backtest.

Given: the asset; the allowed strategy families and their templates (each with parameters and [low, high]
bounds); recent FAILED attempts (template, params, why they were killed); and a registry summary.

Your job:
1. Form a SPECIFIC ECONOMIC HYPOTHESIS — a market mechanism you believe yields risk-adjusted return on this
   asset. Lead with the mechanism, not the parameters.
2. Choose ONE template (from the allowed list) and EXACT parameter values WITHIN the given bounds that
   express that mechanism.
3. LEARN from the failures: never repeat a killed attempt; if prior tries died on low activity, trade more;
   if they died because they merely tracked the market, change the MECHANISM, not just the numbers.

You do NOT choose the data window, time period, bar size, or asset — the system fixes those. Only the
template and its parameters.

Output ONLY a JSON object:
{"template_id": "...", "params": {"<name>": <number>, ...},
 "economic_rationale": "...", "claimed_mechanism": "...", "falsifiable_prediction": "..."}

Rules: every param within its [low, high]; allowed templates only; be specific and numeric about the mechanism."""


def _window_months(start: str, end: str) -> int:
    """Window length in months — the leakage-safe regime context (DURATION, not calendar dates)."""
    from datetime import date
    try:
        return max(1, round((date.fromisoformat(end) - date.fromisoformat(start)).days / 30.44))
    except Exception:
        return 0


# P1 Chunk B — regime-fit Strategist prompt (mode="regime"). ANTI-LEAKAGE: the LLM gets the window DURATION
# (months), NOT the calendar dates — so it reasons from MECHANISM, not memory of a period. The regime's
# character comes from the GOAL + the asset(s), not recalled dates. Doubled braces for .format().
REGIME_STRATEGIST_PROMPT = """You are a quantitative trading researcher fitting a strategy to ONE SPECIFIC
MARKET REGIME — a single window of ~{months} months. Its exact calendar dates are deliberately WITHHELD so you
reason from MECHANISM, not from memory of what happened in any period.

Given: the research GOAL (the user's regime hypothesis); the asset(s); the allowed templates + [low, high]
bounds; recent FAILED attempts; a registry summary.

Your job:
1. Form a SPECIFIC HYPOTHESIS about what works in THIS regime — read the GOAL + the asset(s) for its character
   (trend, volatility, theme) and lead with the market mechanism you expect to pay off. Do NOT guess the dates.
2. Choose ONE template and EXACT parameter values WITHIN bounds expressing it. The window is SHORT (~{months}
   months), so favor parameters that trade OFTEN ENOUGH to be statistically meaningful (higher frequency).
3. LEARN from the failures: never repeat a killed attempt; if prior tries died on low activity, trade more.

This is REGIME-FIT research, NOT a search for a robust all-weather strategy; you are NOT claiming it generalizes
beyond this window.

You do NOT choose the window, dates, bar size, or asset — only the template and its parameters.

Output ONLY a JSON object:
{{"template_id": "...", "params": {{"<name>": <number>, ...}},
 "economic_rationale": "...", "claimed_mechanism": "...", "falsifiable_prediction": "..."}}
Rules: every param within its [low, high]; allowed templates only; be specific and numeric about the mechanism."""


class LLMStrategist:
    """LLM Strategist (W2). Proposes an economic hypothesis + template + params via the LLM, falling back to
    the rule-based Strategist (its persistent fallback, shared `_tried_hashes`) on any failure. The LLM
    chooses `template_id` + `params` ONLY; window/bar_size are system-fixed (C-6)."""

    def __init__(self, llm: "LLMHandle", ledger: "TokenLedger | None", fallback: "RuleBasedStrategist",
                 window_start: str = WINDOW_START, window_end: str = WINDOW_END, mode: str = "robustness",
                 goal: str = ""):
        self._llm = llm
        self._ledger = ledger
        self._fb = fallback
        self.llm_calls = 0              # H25: LLM proposals attempted (billed)
        self.fallback_after_bill = 0    # H25: of those, how many were unparseable → rule-based fallback
        # P1: effective window (stamped onto the spec; the LLM still chooses template+params ONLY, C-6).
        self.window_start = window_start
        self.window_end = window_end
        self.mode = mode
        self.goal = goal   # user's regime hypothesis (regime mode) — supplies the regime character, NOT dates

    def _system_prompt(self) -> str:
        # P1 / anti-leakage: regime mode gives the LLM the window DURATION (months), never the calendar dates.
        if self.mode == "regime":
            return REGIME_STRATEGIST_PROMPT.format(months=_window_months(self.window_start, self.window_end))
        return STRATEGIST_SYSTEM_PROMPT

    def _over_budget(self) -> bool:
        if not self._ledger:
            return False
        b = self._ledger.budget
        return b.max_eur > 0 and b.used_eur >= b.max_eur

    async def propose(
        self,
        asset: str,
        strategy_families: list[str],
        failure_context: list[FailureContext],
        registry_summary: dict[str, Any],
    ) -> tuple[Hypothesis, dict[str, Any]]:
        if self._over_budget():
            return await self._fb.propose(asset, strategy_families, failure_context, registry_summary)
        try:
            templates = self._fb._get_available_templates(strategy_families)  # empty -> all (S-1)
            req = ChatRequest(
                model=self._llm.model,
                messages=[
                    ChatMessage(role="system", content=self._system_prompt()),
                    ChatMessage(
                        role="user",
                        content=self._render(asset, templates, failure_context, registry_summary),
                    ),
                ],
                temperature=0.4,
                # H25: reasoning models spend tokens on chain-of-thought BEFORE the JSON verdict; a
                # 700-token cap truncated them → extract_json_object returned None → silent fallback to
                # rule-based AFTER billing. The two production-recommended mechanism-only models
                # (deepseek-reasoner, byteplus seed) are reasoners, so full_ai was ~100% heuristic while
                # billing. Give reasoners the Critic's headroom (a higher cap is free for non-reasoners —
                # billing is on tokens actually generated, and they stop when the JSON is done).
                max_tokens=4000 if self._llm.supports_reasoning else 700,
                json_mode=self._llm.supports_json_mode,
            )
            resp = await self._llm.provider.chat_completion(req)
            if self._ledger is not None:
                self._ledger.record(resp.usage, self._llm)   # billed even if _build discards (S-4)
            built = self._build(resp.content, asset, templates)
            if built is None:
                # H25: we PAID for this call and could not use it — count + log distinctly so a silent
                # LLM→heuristic degradation is visible (surfaced as the llm-vs-fallback ratio).
                self.llm_calls += 1
                self.fallback_after_bill += 1
                logger.warning("Strategist LLM billed but unparseable — fell back to rule-based "
                               "(fallbacks %d/%d)", self.fallback_after_bill, self.llm_calls)
                return await self._fb.propose(asset, strategy_families, failure_context, registry_summary)
            self.llm_calls += 1
            return built
        except Exception as exc:  # noqa: BLE001 — any LLM failure -> rule-based, never stall
            # M57: record the HARD failure so a silently-degraded AI run (e.g. 401/400 on an unfunded key)
            # surfaces as such instead of a clean "completed full_ai" with used_eur=0.
            if self._ledger is not None:
                self._ledger.record_failure(exc)
            logger.warning("Strategist LLM failed (%s) — rule-based", exc)
            return await self._fb.propose(asset, strategy_families, failure_context, registry_summary)

    def _render(self, asset, templates, failure_context, registry_summary) -> str:
        allowed = [
            {"id": t, "family": _family_of(t),
             "params": {k: [v["low"], v["high"]] for k, v in TEMPLATES[t].items()}}
            for t in templates
        ]
        recent = [
            {"template_id": fc.template_id, "params": fc.params,
             "killed_by": fc.failed_gate or fc.failure_reason,
             # M37: a critic kill sets killed_by="critic_rejection" with the substance in critic_notes;
             # pass a bounded excerpt so the strategist can actually follow "change the MECHANISM if they
             # merely tracked the market" instead of seeing only the opaque literal.
             "critic_note": (getattr(fc, "critic_notes", "") or "")[:200]}
            for fc in failure_context[-5:]
        ]
        payload = {
            "asset": asset,
            "allowed_templates": allowed,
            "recent_failures": recent,
            "registry": {
                "total_iterations": registry_summary.get("total_iterations"),
                "candidates_found": registry_summary.get("candidates_found"),
                "sharpe_distribution": (registry_summary.get("sharpe_distribution") or [])[-10:],
            },
        }
        if self.mode == "regime" and self.goal:
            payload["research_goal"] = self.goal   # user's regime hypothesis (character, not dates)
        return json.dumps(payload, default=str)

    def _build(self, content, asset, templates):
        data = extract_json_object(content)
        if data is None:
            return None
        template_id = data.get("template_id")
        if template_id not in templates:                 # in requested families (C-2)
            return None
        space = TEMPLATES[template_id]
        raw = data.get("params", {})
        if not isinstance(raw, dict):     # malformed params -> keep the template, midpoint-fill
            raw = {}
        params: dict[str, Any] = {}
        repaired: list[str] = []                          # M38: provenance of system-invented values
        for name, ps in space.items():                   # exactly the template's param set
            lo, hi = ps["low"], ps["high"]
            v = raw.get(name)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                val = min(max(v, lo), hi)                 # clamp into bounds (Q3)
                if val != v:
                    repaired.append(f"{name}: clamped {v}->{val}")
            else:
                val = (lo + hi) / 2                       # midpoint fill (S-6)
                repaired.append(f"{name}: midpoint-filled (missing/non-numeric)")
            params[name] = int(round(val)) if ps.get("type") == "int" else float(val)

        # M38: if the system invented MORE THAN HALF the params, the LLM's stored rationale can't honestly
        # describe the executed spec — fall back to rule-based rather than run invented params under the
        # LLM narrative (worst case: a string `params` → every value a midpoint).
        if len(repaired) > max(1, len(space) // 2):
            return None

        _pre_repair = dict(params)
        params = _repair_params(template_id, params)
        if params != _pre_repair:
            repaired.append("constraint repair (e.g. fast<slow)")
        strategy_hash = _compute_strategy_hash(template_id, params, asset)
        if strategy_hash in self._fb._tried_hashes:       # dedup vs shared set (F-2)
            return None
        self._fb._tried_hashes.add(strategy_hash)

        family = _family_of(template_id)
        hypothesis = Hypothesis(
            hypothesis_id=f"hyp_{uuid.uuid4().hex[:12]}",
            author="llm_strategist",
            economic_rationale=data.get("economic_rationale", ""),      # S-3: thin prose OK
            claimed_mechanism=data.get("claimed_mechanism", ""),
            falsifiable_prediction=data.get("falsifiable_prediction", ""),
            proposed_template_id=template_id,                           # == spec.template_id (F-5)
            proposed_param_ranges={k: [v["low"], v["high"]] for k, v in space.items()},
            prior_strength="low",
            linked_specs=[strategy_hash],
        )
        spec = {
            "strategy_hash": strategy_hash,
            "template_id": template_id,
            "params": params,
            "repaired": repaired,   # M38: provenance — which values the system clamped/filled/repaired
            "security_id": asset,
            "bar_size": BAR_SIZE,
            "strategy_family": family,
            "window_start": self.window_start,      # from run config; LLM never chooses it (C-6)
            "window_end": self.window_end,
        }
        return hypothesis, spec
