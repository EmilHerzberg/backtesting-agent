"""Free-text -> structured criteria parser (V3).

Tries to parse user goal text into structured criteria. Uses regex
heuristics so it works without LLM. The frontend shows the parsed
criteria for verification + editing.
"""
from __future__ import annotations

import re
from typing import Any

METRIC_ALIASES = {
    "sharpe": "sharpe_ratio",
    "sharpe ratio": "sharpe_ratio",
    "sharperatio": "sharpe_ratio",
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
    "regime": "regime_pass_count",
    "regimes": "regime_pass_count",
}


def _normalize_metric(name: str) -> str:
    return METRIC_ALIASES.get(name.lower().strip(), name.lower().replace(" ", "_"))


def parse_criteria(text: str) -> dict[str, Any]:
    """Parse a free-text goal into criteria + target_count.

    Returns:
        {"criteria": [...], "target_count": int}
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

    # Sharpe > X
    for m in re.finditer(
        r"(sharpe[-\s]?ratio|sharpe)\s*(>=|>|>=|ueber|ueber|hoeher als|min(?:destens|\.)?)\s*(-?\d+(?:[.,]\d+)?)",
        text_lower,
    ):
        v = float(m.group(3).replace(",", "."))
        criteria.append({"metric": "sharpe_ratio", "op": ">=", "value": v, "label": f"Sharpe ≥ {v}"})

    # Max DD > -X% / nicht schlechter als -X%
    for m in re.finditer(
        r"(max[\-\s]*dd|drawdown|drawdown)\s*(>|>=|besser als|nicht schlechter als)\s*(-?\d+(?:[.,]\d+)?)\s*%?",
        text_lower,
    ):
        v = float(m.group(3).replace(",", "."))
        if v > 0:
            v = -v
        criteria.append(
            {"metric": "max_drawdown", "op": ">=", "value": v / 100, "label": f"Max DD ≥ {v}%"}
        )

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
        criteria.append({"metric": "trade_count", "op": ">=", "value": v, "label": f"≥ {v} Trades"})

    # Default if nothing matched
    if not criteria:
        criteria.append(
            {"metric": "sharpe_ratio", "op": ">=", "value": 1.0, "label": "Sharpe ≥ 1.0 (default)"}
        )

    return {"criteria": criteria, "target_count": target}


def candidate_meets_criteria(
    candidate: dict[str, Any], criteria: list[dict[str, Any]]
) -> bool:
    """Check whether a single candidate satisfies all criteria."""
    for c in criteria:
        metric = c["metric"]
        op = c["op"]
        target = c["value"]
        val = candidate.get(metric)
        if val is None:
            return False
        if op == ">=" and not (val >= target):
            return False
        if op == ">" and not (val > target):
            return False
        if op == "<=" and not (val <= target):
            return False
        if op == "<" and not (val < target):
            return False
    return True
