"""Gap 6: Report generator — produces the final research report.

Populates numeric fields from state, generates qualitative narrative,
validates with numeric-token scan.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from typing import TYPE_CHECKING

from src.backend.ai.models import ChatMessage, ChatRequest
from src.backend.ai.research.agent_llm import extract_json_object
from src.backend.ai.research.reporter import (
    NumericClaimError,
    ResearchReport,
    assert_no_numeric_claims,
)
from src.backend.ai.research.state import ResearchState

if TYPE_CHECKING:
    from src.backend.ai.research.agent_llm import LLMHandle, TokenLedger

logger = logging.getLogger(__name__)

# Section order for serialization (matches ResearchReport field order).
_REPORT_SECTIONS = [
    "strategy_identity", "hypothesis", "benchmark_comparison", "gate_outcomes",
    "dsr_analysis", "critic_notes", "limitations", "oos_status",
]


def serialize_report(report: ResearchReport) -> dict:
    """Flatten a ResearchReport into a JSON-safe dict (ordered section list)."""
    sections = []
    for name in _REPORT_SECTIONS:
        sec = getattr(report, name, None)
        if sec is None:
            continue
        sections.append({
            "key": name,
            "title": sec.title,
            "numeric_fields": sec.numeric_fields,
            "narrative": sec.narrative,
        })
    return {"sections": sections}


# Confidence-surfacing F-9 — the survivors' statistical quality, in WORDS (digit-free Reporter).
_CONFIDENCE_WORDS = {
    "strong": "a strong statistical confidence",
    "moderate": "a moderate statistical confidence",
    "weak": "a weak statistical confidence",
    "provisional": "only a provisional statistical confidence",
    "validated": "a regime-fit edge validated on held-out data (not robustness-proven)",
    "failed": "an edge that did not hold on a held-out slice",
    "low": "a low, unvalidated regime-fit confidence",
    "very_low": "a very low, unvalidated regime-fit confidence",
}


def _survivor_confidence_phrase(state: ResearchState) -> str:
    """F-9: the best survivor's statistical-quality tier as a digit-free phrase (or "" if none)."""
    if not state.candidates:
        return ""
    from src.backend.ai.research.quality import quality_summary

    b = max(state.candidates, key=lambda c: c.sharpe_annual)
    oos_map = {o.strategy_hash: o.outcome for o in state.oos_results}
    vs = getattr(b, "validation_status", "")
    q = quality_summary(
        getattr(b, "gate_report_summary", {}) or {},
        oos=oos_map.get(b.strategy_hash, ""),
        mode="regime" if vs else "robustness",
        confidence=getattr(b, "confidence", ""),
        validation_status=vs,
        weaknesses=getattr(b, "weaknesses", []) or [],
    )
    return _CONFIDENCE_WORDS.get(q["tier"], "a provisional statistical confidence")


def generate_final_report(state: ResearchState) -> ResearchReport:
    """Generate the final research report from loop state.

    All numbers come from state (the data store). Qualitative narrative
    is rule-based for MVP. LLM-based generation is an upgrade.
    """
    report = ResearchReport()

    # ── Strategy Identity ──────────────────────────────────────
    n_candidates = len(state.candidates)
    n_trials = state.total_iterations
    n_failures = len(state.all_failures)

    report.strategy_identity.numeric_fields = {
        "candidates_found": n_candidates,
        "total_trials": n_trials,
        "total_failures": n_failures,
        "budget_used_runs": state.budget.used_runs,
    }
    report.strategy_identity.narrative = (
        "The autonomous research process evaluated multiple strategy templates "
        "across the requested asset pool, systematically testing hypotheses and "
        "filtering through quality gates."
    )
    # M57 (model-honesty): if an AI run had hard LLM-call failures, the proposals and/or this narrative
    # silently fell back to the rule-based engine. Say so plainly (digit-free — the count lives in
    # numeric_fields; a run whose every call failed still reports status=completed/full_ai otherwise).
    if state.llm_degraded():
        report.strategy_identity.numeric_fields["llm_call_failures"] = state.budget.llm_failures
        report.strategy_identity.narrative = (
            "NOTE — DEGRADED AI RUN: this run was configured for AI mode, but one or more model calls "
            "failed (for example an authentication or credit error), so the strategy proposals and/or "
            "this narrative fell back to the built-in rule-based engine. Read these results as "
            "rule-based, not AI-driven. " + report.strategy_identity.narrative
        )

    # ── Hypothesis ─────────────────────────────────────────────
    templates_tried = set()
    for h in state.hypotheses:
        templates_tried.add(h.proposed_template_id)

    report.hypothesis.numeric_fields = {
        "hypotheses_generated": len(state.hypotheses),
        "unique_templates_tried": len(templates_tried),
    }
    report.hypothesis.narrative = (
        "Strategy hypotheses were generated systematically, rotating through "
        "available templates and adapting parameters based on prior failure context."
    )

    # ── Benchmark Comparison ───────────────────────────────────
    if state.candidates:
        best = max(state.candidates, key=lambda c: c.sharpe_annual)
        report.benchmark_comparison.numeric_fields = {
            "best_sharpe": best.sharpe_annual,
            "best_return": best.total_return,
            "best_drawdown": best.max_drawdown,
            "best_trades": best.n_trades,
            "best_asset": best.security_id,
            "best_template": best.template_id,
        }
    report.benchmark_comparison.narrative = (
        "Candidates were evaluated against buy-and-hold benchmarks. "
        "Only strategies demonstrating edge beyond passive holding survived."
    )

    # ── Gate Outcomes ──────────────────────────────────────────
    gate_failures = {}
    for fc in state.all_failures:
        if fc.failed_gate:
            gate_failures[fc.failed_gate] = gate_failures.get(fc.failed_gate, 0) + 1

    report.gate_outcomes.numeric_fields = {
        "gate_failure_distribution": gate_failures,
        "total_gate_failures": sum(gate_failures.values()),
    }
    report.gate_outcomes.narrative = (
        "The quality gate pipeline filtered candidates through multiple stages "
        "including minimum activity, performance floor, benchmark comparison, "
        "cost stress, and deflated Sharpe ratio checks."
    )

    # ── DSR Analysis ───────────────────────────────────────────
    report.dsr_analysis.numeric_fields = {
        "total_valid_trials": n_trials,
    }
    report.dsr_analysis.narrative = (
        "The Deflated Sharpe Ratio penalizes for multiple testing. "
        "Every trial raises the acceptance bar for future candidates."
    )
    _conf_phrase = _survivor_confidence_phrase(state)
    if _conf_phrase:  # F-9: headline the survivors' quality via the reliable per-run signals, in words
        report.dsr_analysis.narrative += (
            f" The surviving strategies carry {_conf_phrase}, judged mainly on their per-trade edge, "
            "benchmark margin, and out-of-sample result rather than the multiple-testing number alone."
        )

    # ── Critic Notes ───────────────────────────────────────────
    critic_rejections = [fc for fc in state.all_failures if fc.failure_reason == "critic_rejection"]
    report.critic_notes.numeric_fields = {
        "critic_rejections": len(critic_rejections),
    }
    report.critic_notes.narrative = (
        "An adversarial critic reviewed candidates that passed quality gates, "
        "challenging them for overfitting, regime dependence, and beta masking."
    )

    # ── Limitations ────────────────────────────────────────────
    report.limitations.narrative = (
        "This system is a research falsification engine. Passing all gates means "
        "not yet falsified, not proven profitable. Historical edges decay. "
        "Daily-bar technical signals on liquid equities have low prior alpha. "
        "Cost modeling is simplified. Backtest does not equal live performance."
    )

    # ── OOS Status ─────────────────────────────────────────────
    # Review fix (h16/oos dedup): count UNIQUE strategies (last verdict wins per hash), not raw append
    # attempts — the H16 recovery re-appends a terminal verdict on every re-find, and a repeatedly
    # re-proposed UNEVALUATED strategy (which writes no lockbox row) is re-evaluated and re-appended,
    # so the raw list is per-attempt. Mirror validated_count / the confidence-phrase last-wins map.
    _oos_by_hash = {r.strategy_hash: r.outcome for r in state.oos_results}
    oos_passed = sum(1 for o in _oos_by_hash.values() if o == "PASS")
    oos_failed = sum(1 for o in _oos_by_hash.values() if o == "FAIL")
    # UNEVALUATED (thin sample / data outage — H17) is NOT a terminal verdict: it is not counted as
    # "evaluated", so the pass/fail denominator stays honest.
    oos_unevaluated = sum(1 for o in _oos_by_hash.values() if o == "UNEVALUATED")
    report.oos_status.numeric_fields = {
        "oos_evaluated": oos_passed + oos_failed,
        "oos_passed": oos_passed,
        "oos_failed": oos_failed,
        "oos_unevaluated": oos_unevaluated,
    }
    report.oos_status.narrative = (
        "Out-of-sample evaluation provides the final test. "
        "Results are terminal and cannot be revised."
    )

    # ── Validate narratives (no numeric leakage) ───────────────
    # Per spec Part 5: "if the Reporter writes 'Sharpe of 1.2' in a prose
    # slot, rendering fails." This is enforced, not silently passed.
    report.validate_narratives()

    return report


# ── W3: LLM Reporter (narration) ──────────────────────────────────────

_KILL_PHRASE = {
    "benchmark_relative": "failing to beat buy-and-hold",
    "minimum_activity": "trading too rarely",
    "performance_floor": "weak risk-adjusted return",
    "cost_stress": "fragility under higher costs",
    "deflated_sharpe": "not surviving the multiple-testing penalty",
    "data_integrity": "data-quality issues",
    "lag_fragility": "fragility to execution lag",
    "spec_validation": "an invalid specification",
    "provider_capability": "provider-capability limits",
}


def _kill_phrase(gate_id: str) -> str:
    return _KILL_PHRASE.get(gate_id, gate_id)


def _descriptors(state: ResearchState) -> dict:
    """Digit-free qualitative descriptors of the run — the ONLY thing the LLM sees (W3-2)."""
    n_cand = len(state.candidates)
    n_trials = state.total_iterations
    gates = Counter(fc.failed_gate for fc in state.all_failures if fc.failed_gate)
    crit = sum(1 for fc in state.all_failures if fc.failure_reason == "critic_rejection")
    _oos = {r.strategy_hash: r.outcome for r in state.oos_results}   # dedup per hash
    oos_pass = sum(1 for o in _oos.values() if o == "PASS")
    oos_fail = sum(1 for o in _oos.values() if o == "FAIL")
    d = {
        "outcome": (
            "nothing survived" if n_cand == 0
            else "a few strategies survived" if n_cand <= 2
            else "several strategies survived"
        ),
        "effort": (
            "an extensive search" if n_trials >= 30
            else "a moderate search" if n_trials >= 10
            else "a brief search"
        ),
        "dominant_kill_reason": _kill_phrase(gates.most_common(1)[0][0]) if gates else "none",
        "critic": "the critic rejected some survivors" if crit else "the critic rejected nothing",
        # M46: honest tri-state — a single candidate PASS is NOT "the run passed out-of-sample", and an
        # all-UNEVALUATED list (thin sample / data outage; H17 appends UNEVALUATED to oos_results) is NOT a
        # failure. Only terminal PASS/FAIL verdicts drive the phrasing. All phrases stay digit-free.
        "oos": (
            "no out-of-sample evaluation" if not state.oos_results
            else "out-of-sample inconclusive (too few trades)" if (oos_pass + oos_fail) == 0
            else "mixed out-of-sample results (some passed, some failed)" if oos_pass and oos_fail
            else "passed out-of-sample" if oos_pass
            else "failed out-of-sample"
        ),
    }
    if state.candidates:
        b = max(state.candidates, key=lambda c: c.sharpe_annual)
        sh, dd, nt = b.sharpe_annual, b.max_drawdown, b.n_trades
        d["best_sharpe"] = (
            "suspiciously high" if sh > 2 else "strong" if sh > 1 else "moderate" if sh > 0.5 else "weak"
        )
        # M46: a MISSING / UNCOMPUTABLE benchmark must not read as "beat buy-and-hold". The runner coalesces
        # an uncomputable buy-and-hold to the float 0.0 (indistinguishable from a genuinely-flat benchmark),
        # so we key on the explicit `benchmark_available` flag (set by the executor when >1 return bar
        # existed), not on the 0.0 sentinel; `_bh is None` covers the reload/empty-dict path too.
        # HONEST SCOPE (re-review M46-1): for a candidate that CLEARED the gates the benchmark is in practice
        # always computable (the min-activity HARD floor forces ≥5 trades → a multi-bar equity curve), so the
        # `benchmark_available` branch is defensive; the reachable "unavailable" path is the empty-dict/reload
        # (`_bh is None`) case. Kept because it is honest and harmless.
        _bm = b.benchmark or {}
        _bh = _bm.get("buy_hold_return")
        if _bh is None or not _bm.get("benchmark_available", True):
            d["vs_benchmark"] = "benchmark unavailable"
        else:
            d["vs_benchmark"] = "beat buy-and-hold" if (b.total_return - _bh) > 0 else "underperformed buy-and-hold"
        d["drawdown"] = "severe" if dd < -0.3 else "moderate" if dd < -0.1 else "shallow"
        d["trades"] = "many" if nt > 100 else "a moderate number" if nt >= 30 else "few (low significance)"
        d["statistical_confidence"] = _survivor_confidence_phrase(state)  # F-9
    return d


REPORTER_SYSTEM_PROMPT = """You write the narrative for an autonomous trading-strategy research report.

You are given QUALITATIVE descriptors of the run (no numbers). Write a SHORT (1-2 sentence), honest,
qualitative narrative for each section listed. Describe magnitudes in WORDS.

ABSOLUTE RULE: never write any number, digit, year, percentage, or specific figure — the numbers are shown
separately. Use words ("a strong Sharpe", "few trades", "underperformed the benchmark").

HONESTY: the run's outcome sets the tone. This is a FALSIFICATION engine — finding nothing is a good,
expected result. If the outcome says nothing survived, say so plainly; do NOT call a 0-survivor run
"promising" or "successful".

Output ONLY a JSON object: {"<section_key>": "<narrative>", ...} for exactly these sections: {keys}."""


# P1 Chunk B — regime-fit Reporter prompt (state.mode="regime"). Same digit-free rule, but the honesty framing
# forbids "robust"/"generalizes" and frames survivors as regime-fit / unvalidated. (Uses .replace for {keys}.)
REGIME_REPORTER_SYSTEM_PROMPT = """You write the narrative for a REGIME-FIT trading-strategy research run —
strategies fitted to ONE specific market window, NOT validated as robust across regimes.

You are given QUALITATIVE descriptors (no numbers). Write a SHORT (1-2 sentence), honest, qualitative
narrative for each section listed. Describe magnitudes in WORDS.

ABSOLUTE RULE: never write any number, digit, year, percentage, or specific figure — the numbers are shown
separately.

HONESTY (critical for regime mode): these results are REGIME-FIT and NOT robustness-validated. NEVER call a
strategy "robust", "all-weather", or say it "generalizes". Frame survivors as fitting THIS regime / working
WITHIN this window, explicitly caveated as unvalidated beyond it. This is a FALSIFICATION engine — finding
nothing is a good, expected result; do NOT call a 0-survivor run "promising" or "successful".

Output ONLY a JSON object: {"<section_key>": "<narrative>", ...} for exactly these sections: {keys}."""


async def llm_narrate_report(
    report: ResearchReport,
    state: ResearchState,
    llm: "LLMHandle",
    ledger: "TokenLedger | None" = None,
) -> None:
    """W3: rewrite each section's narrative with LLM prose (qualitative, digit-free). Mutates `report`
    in place; any failure / digit-leak / missing section keeps that section's template narrative."""
    if ledger is not None:
        b = ledger.budget
        if b.max_eur > 0 and b.used_eur >= b.max_eur:
            return  # over budget -> keep templated narratives
    try:
        base = (REGIME_REPORTER_SYSTEM_PROMPT
                if getattr(state, "mode", "robustness") == "regime" else REPORTER_SYSTEM_PROMPT)
        prompt = base.replace("{keys}", ", ".join(_REPORT_SECTIONS))
        req = ChatRequest(
            model=llm.model,
            messages=[
                ChatMessage(role="system", content=prompt),
                ChatMessage(role="user", content=json.dumps({
                    "descriptors": _descriptors(state),
                    "sections": _REPORT_SECTIONS,
                })),
            ],
            temperature=0.3,
            max_tokens=900,
            json_mode=llm.supports_json_mode,
        )
        resp = await llm.provider.chat_completion(req)
        if ledger is not None:
            ledger.record(resp.usage, llm)
        data = extract_json_object(resp.content) or {}
        for key in _REPORT_SECTIONS:
            sec = getattr(report, key, None)
            text = data.get(key)
            if sec is None or not isinstance(text, str) or not text.strip():
                continue  # missing/malformed -> keep template (W3-4)
            try:
                assert_no_numeric_claims(text, key)  # digit leak -> keep template (C-3)
                sec.narrative = text.strip()
            except NumericClaimError:
                continue
    except Exception as exc:  # noqa: BLE001 — any failure -> all templated
        if ledger is not None:   # M57: a templated-instead-of-LLM report is a silent degradation
            ledger.record_failure(exc)
        logger.warning("Reporter LLM failed (%s) — templated narratives", exc)
    # belt-and-suspenders (W3S-1): narratives are all clean -> never raises; wrapped defensively.
    try:
        report.validate_narratives()
    except Exception:  # noqa: BLE001
        pass
