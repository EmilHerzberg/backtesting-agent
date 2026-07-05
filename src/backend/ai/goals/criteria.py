"""Free-text -> structured criteria parser (V3).

Parses a user goal into structured numeric criteria using regex heuristics (no LLM needed), so the
research loop can count only candidates that actually satisfy what the user asked for (C3/M50). Metric
names are the canonical Candidate keys (``sharpe_annual``, ``n_trades``, ``max_drawdown``, …) so a
criterion can be evaluated against a candidate directly (H30).
"""
from __future__ import annotations

import re
from typing import Any

# Aliases map user words -> the canonical Candidate metric keys.
METRIC_ALIASES = {
    "sharpe": "sharpe_annual",
    "sharpe ratio": "sharpe_annual",
    "sharperatio": "sharpe_annual",
    "drawdown": "max_drawdown",
    "max drawdown": "max_drawdown",
    "max dd": "max_drawdown",
    "maxdd": "max_drawdown",
    "return": "total_return",
    "rendite": "total_return",
    "win rate": "win_rate",
    "winrate": "win_rate",
    "profit factor": "profit_factor",
    "pf": "profit_factor",
    "trades": "n_trades",
    "trade count": "n_trades",
    "regime": "regime_pass_count",
    "regimes": "regime_pass_count",
}


def _normalize_metric(name: str) -> str:
    return METRIC_ALIASES.get(name.lower().strip(), name.lower().replace(" ", "_"))


def parse_criteria(text: str) -> dict[str, Any]:
    """Parse a free-text goal into criteria + target_count.

    Returns:
        ``{"criteria": [{"metric", "op", "value", "label", ["abs"]}, ...], "target_count": int}``.
        Metrics use the canonical Candidate keys. Drawdown is a POSITIVE limit with op ``<=`` compared
        on the absolute value (``abs=True``), so it works regardless of the candidate's DD sign (H30).
    """
    text_lower = text.lower()

    # Target count: "Finde 3" / "3 Strategien"
    target = 1
    m = re.search(r"\b(\d+)\s*(strateg|kandidat|setup)", text_lower)
    if m:
        target = int(m.group(1))
    elif re.search(r"\bfinde?\s+(\d+)", text_lower):
        target = int(re.search(r"\bfinde?\s+(\d+)", text_lower).group(1))

    criteria: list[dict[str, Any]] = []

    # Sharpe >= X
    for m in re.finditer(
        r"(sharpe[-\s]?ratio|sharpe)\s*(>=|>|ueber|hoeher als|min(?:destens|\.)?)\s*(-?\d+(?:[.,]\d+)?)",
        text_lower,
    ):
        v = float(m.group(3).replace(",", "."))
        criteria.append({"metric": "sharpe_annual", "op": ">=", "value": v, "label": f"Sharpe ≥ {v}"})

    # Max drawdown < X% / "besser als -X%" / "nicht schlechter als X%"
    for m in re.finditer(
        r"(max[\-\s]*dd|drawdown)\s*(<=|<|>|>=|besser als|nicht schlechter als|unter)\s*(-?\d+(?:[.,]\d+)?)\s*%?",
        text_lower,
    ):
        v = abs(float(m.group(3).replace(",", ".")))  # a 20% limit, sign-agnostic
        criteria.append(
            {"metric": "max_drawdown", "op": "<=", "value": v / 100.0, "abs": True,
             "label": f"Max DD ≤ {v}%"}
        )

    # Return >= X% (L22)
    for m in re.finditer(r"(return|rendite)\s*(>=|>|ueber|min(?:destens|\.)?)\s*(-?\d+(?:[.,]\d+)?)\s*%?", text_lower):
        v = float(m.group(3).replace(",", "."))
        criteria.append({"metric": "total_return", "op": ">=", "value": v / 100.0, "label": f"Return ≥ {v}%"})

    # Win rate >= X% (L22)
    for m in re.finditer(r"(win[-\s]?rate)\s*(>=|>|ueber|min(?:destens|\.)?)\s*(-?\d+(?:[.,]\d+)?)\s*%?", text_lower):
        v = float(m.group(3).replace(",", "."))
        criteria.append({"metric": "win_rate", "op": ">=", "value": v / 100.0, "label": f"Win rate ≥ {v}%"})

    # Profit factor >= X (L22)
    for m in re.finditer(r"(profit[-\s]?factor|pf)\s*(>=|>|ueber|min(?:destens|\.)?)\s*(-?\d+(?:[.,]\d+)?)", text_lower):
        v = float(m.group(3).replace(",", "."))
        criteria.append({"metric": "profit_factor", "op": ">=", "value": v, "label": f"Profit factor ≥ {v}"})

    # "in allen X Regimes" / "X von 5 Regimes"
    for m in re.finditer(r"(\d+)\s*(?:von\s*\d+\s*)?regim", text_lower):
        v = int(m.group(1))
        criteria.append(
            {"metric": "regime_pass_count", "op": ">=", "value": v, "label": f"Zeitraum-Stabilitaet >= {v}/5"}
        )
    if "in allen" in text_lower and "regime" in text_lower:
        criteria.append(
            {"metric": "regime_pass_count", "op": ">=", "value": 5, "label": "Stabil in allen 5 Zeitabschnitten"}
        )

    # Mindestens X Trades
    for m in re.finditer(r"min(?:destens|\.)?\s*(\d+)\s*trades", text_lower):
        v = int(m.group(1))
        criteria.append({"metric": "n_trades", "op": ">=", "value": v, "label": f"≥ {v} Trades"})

    # Default if nothing matched
    if not criteria:
        criteria.append(
            {"metric": "sharpe_annual", "op": ">=", "value": 1.0, "label": "Sharpe ≥ 1.0 (default)"}
        )

    return {"criteria": criteria, "target_count": target}


def candidate_meets_criteria(
    candidate: dict[str, Any], criteria: list[dict[str, Any]]
) -> bool:
    """Check whether a single candidate (a metrics dict with canonical keys) satisfies all criteria.

    Criteria whose metric is not present on the candidate (e.g. a regime criterion on a robustness
    candidate) are skipped rather than treated as a failure.
    """
    for c in criteria:
        val = candidate.get(c["metric"])
        if val is None:
            continue  # not applicable to this candidate — don't fail on it
        target = c["value"]
        if c.get("abs"):
            val = abs(val)
        op = c["op"]
        if op == ">=" and not (val >= target):
            return False
        if op == ">" and not (val > target):
            return False
        if op == "<=" and not (val <= target):
            return False
        if op == "<" and not (val < target):
            return False
    return True
