"""Confidence-surfacing (CONFIDENCE-SURFACING-SPEC v2) — the statistical-quality summary.

Surfacing ONLY: reads the already-persisted gate report + candidate fields; no recompute, no
re-gating, ~€0 (C-2/C-3). Headlines the RELIABLE per-run signals — the per-trade edge t-stat
(smart-activity) + the benchmark margin + OOS. The DSR is a *caveated* multiple-testing overlay,
provisional on our run sizes (F-1b/CS-1). Every gate field is nullable (absent on some code path,
CF-3/CF-4) → None-safe, falls back to the tier, never fabricates.
"""

from __future__ import annotations

from typing import Any

# Mirror of DeflatedSharpeGate.PROVISIONAL_BELOW (deflated_sharpe.py). The gate now emits an explicit
# ``sr_variance_defaulted`` flag, so we no longer sniff the magic default variance value (M24).
_PROVISIONAL_BELOW = 20


def _gate(gate_report: dict[str, Any] | None, gate_id: str) -> dict[str, Any]:
    """The flat ``details`` of one gate result, or ``{}`` if the gate is absent (CF-3/CF-4)."""
    for r in (gate_report or {}).get("results", []) or []:
        if r.get("gate_id") == gate_id:
            return r.get("details") or {}
    return {}


def _num(x: Any, n: int = 3) -> float | None:
    try:
        return round(float(x), n)
    except (TypeError, ValueError):
        return None


def quality_summary(
    gate_report: dict[str, Any] | None,
    *,
    oos: str = "",
    mode: str = "robustness",
    confidence: str = "",
    validation_status: str = "",
    weaknesses: list | None = None,
) -> dict[str, Any]:
    """A statistical-quality summary for one *surviving* strategy (both modes).

    Returns a dict: ``tier`` (the headline grade), ``headline`` (plain-language words, digit-free
    for the ambiguous magnitudes — F-5), the component numbers (t/excess/dsr) for the tooltip +
    dossier, ``oos``, and ``mode`` (so the UI can keep robust vs UNVALIDATED unmissable — C-5).
    """
    act = _gate(gate_report, "minimum_activity")
    bench = _gate(gate_report, "benchmark_relative")
    dsr_d = _gate(gate_report, "deflated_sharpe")

    per_trade_t = _num(act.get("t_stat"))              # absent on floor-only / plumbing passes
    per_trade_tier = act.get("tier", "") or ""
    benchmark_excess = _num(bench.get("excess_return"))  # absent on a benchmark FAIL (pass-path only)
    oos_state = (oos or "").upper() or "OFF"           # "" → OFF (OOS disabled / not run) — neutral

    # DSR overlay — a real value only when present; provisional otherwise (F-1b / CS-4).
    dsr: dict[str, Any] | None = None
    if "dsr" in dsr_d and dsr_d.get("dsr") is not None:
        trials = int(dsr_d.get("n_trials", 0) or 0)
        sr_var = dsr_d.get("sr_variance")
        provisional = (
            bool(dsr_d.get("provisional"))
            or trials < _PROVISIONAL_BELOW
            or sr_var is None
            or bool(dsr_d.get("sr_variance_defaulted"))  # M24: explicit flag, not a magic-value sniff
        )
        dsr = {"value": _num(dsr_d.get("dsr"), 2), "trials": trials, "provisional": provisional}

    if mode == "regime":
        tier, headline = _regime_tier(validation_status, confidence, weaknesses or [])
    else:
        tier, headline = _robustness_tier(per_trade_t, per_trade_tier, benchmark_excess, oos_state, dsr)

    return {
        "tier": tier,
        "headline": headline,
        "per_trade_t": per_trade_t,
        "per_trade_tier": per_trade_tier,
        "benchmark_excess": benchmark_excess,
        "oos": oos_state,
        "dsr": dsr,
        "mode": mode,
    }


def _robustness_tier(
    t: float | None, tier: str, excess: float | None, oos: str, dsr: dict | None
) -> tuple[str, str]:
    """CS-1: the tier is built from the RELIABLE per-run signals — NOT the DSR (which is censored
    for survivors, CF-6). OOS FAIL is dispositive. D9/H5: only a real held-out PASS earns "strong" —
    an in-sample-only run (OOS OFF), a still-pending one, or an inconclusive one (UNEVALUATED) is
    capped at "moderate", never "strong" (no hold-out proof ⇒ no top badge)."""
    exc = excess or 0.0
    adequate = tier == "adequate"

    if oos == "FAIL":                                   # failed the held-out test
        grade = "weak"
    elif tier == "" and excess is None:                 # no gradeable signal at all → honest "provisional"
        grade = "provisional"
    elif adequate and exc > 0 and oos == "PASS":        # D9/H5: "strong" REQUIRES a held-out PASS
        grade = "strong"
    elif tier in ("adequate", "thin") and exc > 0:
        grade = "moderate"
    else:
        grade = "weak"

    parts: list[str] = []
    if t is not None:
        parts.append(f"per-trade edge t={t}" + (" (significant)" if adequate else " (thin)"))
    if excess is not None:
        parts.append("beat buy-and-hold" if exc > 0 else "did not beat buy-and-hold")
    if oos == "PASS":
        parts.append("passed out-of-sample")
    elif oos == "FAIL":
        parts.append("FAILED out-of-sample")
    elif oos == "OFF":
        parts.append("in-sample only (no hold-out)")
    elif oos == "UNEVALUATED":
        parts.append("out-of-sample inconclusive (too few trades)")
    if dsr is not None:
        parts.append(
            f"multiple-testing check: provisional ({dsr['trials']} trials)"
            if dsr["provisional"]
            else "multiple-testing check: passed"
        )
    return grade, ("; ".join(parts) if parts else "insufficient signal to grade")


def _regime_tier(validation_status: str, confidence: str, weaknesses: list) -> tuple[str, str]:
    """C-5: the regime context DOMINATES — the headline always carries the regime framing so an
    UNVALIDATED idea can never read as a robustness grade. P2's verdict upgrades the framing."""
    if validation_status == "regime_validated":
        tier, frame = "validated", "regime-fit · VALIDATED"
    elif validation_status == "regime_failed":
        tier, frame = "failed", "regime-fit · FAILED hold-out"
    else:
        tier, frame = (confidence or "low"), "regime-fit · UNVALIDATED"
    n = len(weaknesses or [])
    wk = f"; {n} weakness{'es' if n != 1 else ''} flagged" if n else ""
    return tier, f"{frame}{wk}"
