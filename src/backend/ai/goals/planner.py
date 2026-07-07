"""Goal Orchestrator planner — scope parsing, batch planning, dedupe.

F-034 v2: BE03 (_parse_goal_scope), BE04 (_plan_next_batch),
BE06 (_check_plateau_v2), BE07 (_dedupe_candidates).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from src.backend.ai.analysis.clustering import (
    ASSET_CLASS,
    ASSET_CLASS_LABELS,
    STRATEGY_FAMILY,
)


# ─── BE03: InterpretedScope dataclass ──────────────────────────────

@dataclass
class InterpretedScope:
    symbol_pool: list[str] = field(default_factory=list)
    strategy_pool: list[str] = field(default_factory=list)
    default_lookback: str = "2y"
    default_n_trials: int = 100
    walk_forward: bool = True
    source_annotations: dict[str, str] = field(default_factory=dict)

    def as_scope_dict(self) -> dict[str, Any]:
        return {
            "symbols": self.symbol_pool,
            "strategies": self.strategy_pool,
            "lookback": self.default_lookback,
            "n_trials": self.default_n_trials,
            "walk_forward": self.walk_forward,
            "train_size": "12m",
            "test_size": "3m",
        }


@dataclass
class BatchPlan:
    symbols: list[str]
    strategies: list[str]
    n_trials: int
    lookback: str
    walk_forward: bool
    rationale: str

    def as_scope_dict(self) -> dict[str, Any]:
        return {
            "symbols": self.symbols,
            "strategies": self.strategies,
            "lookback": self.lookback,
            "n_trials": self.n_trials,
            "walk_forward": self.walk_forward,
            "train_size": "12m",
            "test_size": "3m",
        }


# ─── Asset-class keyword map ──────────────────────────────────────

_ASSET_KEYWORDS: dict[str, list[str]] = {
    "us_tech": ["us-tech", "us tech", "tech", "nasdaq", "technologie"],
    "us_finance": ["us-finance", "finance", "finanz", "bank"],
    "us_consumer": ["us-consumer", "consumer", "konsum", "verbrauch"],
    "us_health": ["us-health", "health", "gesundheit", "pharma"],
    "us_energy": ["us-energy", "energy", "energie", "oel", "oil"],
    "us_industrial": ["us-industrial", "industrial", "industrie"],
    "us_telecom": ["us-telecom", "telecom", "telekom", "media"],
    "eu_large": ["eu", "europa", "dax", "dax-40", "dax40", "euro stoxx"],
    "crypto": ["crypto", "krypto", "bitcoin", "btc", "eth"],
    "etf_broad": ["etf", "index", "spy", "qqq", "breit"],
}

_STRATEGY_KEYWORDS: dict[str, list[str]] = {
    # M15: a "breakout" is a TREND-following concept (buy the break of resistance). It was routed to
    # mean_reversion, so a user asking for a breakout strategy silently got mean-reversion — compounded
    # by BollingerBreakout itself implementing mean-reversion (buy below the lower band). "bollinger"
    # stays under mean_reversion (that's what the class does); "breakout" now routes to trend_following.
    "trend_following": ["trend", "momentum", "sma", "macd", "moving average", "breakout"],
    "mean_reversion": ["mean-reversion", "reversion", "rsi", "bollinger"],
    "multi_factor": ["multi", "kombination", "combined"],
}

_STRATEGY_FAMILY_TO_CLASSES: dict[str, list[str]] = {
    "trend_following": ["SMACrossover", "MACDSignalCross"],
    "mean_reversion": ["RSIMeanReversion", "BollingerBreakout"],
    "multi_factor": ["MultiIndicator"],
}

_ALL_STRATEGIES = [
    "SMACrossover", "RSIMeanReversion", "MACDSignalCross",
    "BollingerBreakout", "MultiIndicator",
]


def _symbols_for_class(cls: str) -> list[str]:
    """Return all symbols belonging to an asset class."""
    return [sym for sym, c in ASSET_CLASS.items() if c == cls]


def _detect_direct_symbols(text: str) -> list[str]:
    """Find direct ticker mentions (e.g. 'AAPL', 'MSFT', 'BTC-USD').

    Also handles bare crypto symbols: 'BTC' -> 'BTC-USD', 'ETH' -> 'ETH-USD'
    since yfinance requires the -USD suffix for crypto pairs.
    """
    words = re.findall(r"\b[A-Z][A-Z0-9\.\-]{1,10}\b", text.upper())
    result = []
    for w in words:
        # Prefer -USD variant for crypto (yfinance needs BTC-USD, not BTC)
        if f"{w}-USD" in ASSET_CLASS:
            result.append(f"{w}-USD")
        elif w in ASSET_CLASS:
            result.append(w)
    return result


# ─── BE03: _parse_goal_scope ──────────────────────────────────────

def parse_goal_scope(text: str) -> InterpretedScope:
    """Parse free-text goal into a structured scope with source annotations.

    Konzept §5.1. Keyword-matching against clustering.py ASSET_CLASS keys
    and strategy families.
    """
    lower = text.lower()
    scope = InterpretedScope()
    annotations: dict[str, str] = {}

    # 1) Direct symbol mentions (e.g. "AAPL MSFT GOOGL")
    direct = _detect_direct_symbols(text)
    if direct:
        scope.symbol_pool = direct
        annotations["symbol_pool"] = f"direct_symbols ({', '.join(direct)})"
    else:
        # 2) Asset-class keyword matching
        matched_classes: list[str] = []
        matched_keywords: list[str] = []
        for cls, keywords in _ASSET_KEYWORDS.items():
            for kw in keywords:
                if kw in lower:
                    if cls not in matched_classes:
                        matched_classes.append(cls)
                        matched_keywords.append(kw)
                    break
        if matched_classes:
            syms: list[str] = []
            for cls in matched_classes:
                syms.extend(_symbols_for_class(cls))
            scope.symbol_pool = sorted(set(syms))
            labels = [ASSET_CLASS_LABELS.get(c, c) for c in matched_classes]
            annotations["symbol_pool"] = (
                f"keyword_{'+'.join(matched_keywords)} -> "
                f"{', '.join(labels)} ({len(scope.symbol_pool)} symbols)"
            )
        else:
            annotations["symbol_pool"] = "nothing_recognized"

    # 3) Strategy keyword matching
    matched_families: list[str] = []
    matched_strat_kw: list[str] = []
    for family, keywords in _STRATEGY_KEYWORDS.items():
        for kw in keywords:
            if kw in lower:
                if family not in matched_families:
                    matched_families.append(family)
                    matched_strat_kw.append(kw)
                break
    if matched_families:
        strats: list[str] = []
        for fam in matched_families:
            strats.extend(_STRATEGY_FAMILY_TO_CLASSES.get(fam, []))
        scope.strategy_pool = sorted(set(strats))
        annotations["strategy_pool"] = (
            f"keyword_{'+'.join(matched_strat_kw)} -> "
            f"{', '.join(matched_families)} ({len(scope.strategy_pool)} strategies)"
        )
    else:
        scope.strategy_pool = list(_ALL_STRATEGIES)
        annotations["strategy_pool"] = "default (all 5 strategies)"

    # 4) Defaults
    annotations["default_lookback"] = "default (2y)"
    annotations["default_n_trials"] = "default (100)"
    annotations["walk_forward"] = "default (True)"

    scope.source_annotations = annotations
    return scope


# ─── BE04: _plan_next_batch ───────────────────────────────────────

def plan_next_batch(
    scope: InterpretedScope,
    existing_candidates: list[dict[str, Any]],
) -> Optional[BatchPlan]:
    """Coverage-gap planner. Returns None if all combinations tested.

    Konzept §5.2. Phase A: pure gap analysis, no seed re-runs.
    """
    # All possible combos
    all_combos = set()
    for sym in scope.symbol_pool:
        for strat in scope.strategy_pool:
            all_combos.add((sym, strat))

    # Already tested
    tested = set()
    for c in existing_candidates:
        tested.add((c.get("symbol", ""), c.get("strategy", "")))

    gaps = all_combos - tested
    if not gaps:
        return None

    # Pick up to 5 symbols x 2 strategies (max 10 combos)
    gap_list = sorted(gaps)
    symbols_seen: set[str] = set()
    strategies_seen: set[str] = set()
    selected: list[tuple[str, str]] = []

    for sym, strat in gap_list:
        if len(selected) >= 10:
            break
        if len(symbols_seen) >= 5 and sym not in symbols_seen:
            continue
        if len(strategies_seen) >= 2 and strat not in strategies_seen:
            continue
        selected.append((sym, strat))
        symbols_seen.add(sym)
        strategies_seen.add(strat)

    if not selected:
        # Fallback: just take the first 10
        selected = gap_list[:10]
        symbols_seen = {s for s, _ in selected}
        strategies_seen = {st for _, st in selected}

    n_trials = min(scope.default_n_trials, max(50, 1000 // max(len(selected), 1)))

    return BatchPlan(
        symbols=sorted(symbols_seen),
        strategies=sorted(strategies_seen),
        n_trials=n_trials,
        lookback=scope.default_lookback,
        walk_forward=scope.walk_forward,
        rationale=(
            f"Coverage-Gap: {len(gaps)} von {len(all_combos)} Kombinationen noch nicht "
            f"getestet. Plane {len(selected)} Kombis: "
            f"{sorted(symbols_seen)} x {sorted(strategies_seen)}, "
            f"n_trials={n_trials}."
        ),
    )


# ─── BE06: Plateau v2 ────────────────────────────────────────────

def check_plateau_v2(plateau_history: list[list]) -> bool:
    """Check if sharpe has not improved across last N completed batches.

    Konzept §5.3. Counts completed batches, not scheduler ticks.
    plateau_history is a list of [batch_job_id, max_sharpe] pairs,
    appended only when a batch completes.
    """
    N = 3
    if len(plateau_history) < N:
        return False
    recent = [entry[1] for entry in plateau_history[-N:]]
    delta = max(recent) - min(recent)
    return delta < 0.1


# ─── BE07: Dedupe ────────────────────────────────────────────────

def dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep at most one candidate per (strategy, symbol), highest sharpe wins.

    Konzept §8. Prevents target_count being reached with 3 near-identical
    parameter variants of the same strategy on the same symbol.
    """
    groups: dict[tuple[str, str], list[dict]] = {}
    for c in candidates:
        key = (c.get("strategy", ""), c.get("symbol", ""))
        groups.setdefault(key, []).append(c)

    result: list[dict[str, Any]] = []
    for key, members in groups.items():
        members.sort(key=lambda m: m.get("sharpe_ratio", 0), reverse=True)
        result.append(members[0])
    return result


def check_target_reached(
    candidates: list[dict[str, Any]],
    criteria: list[dict[str, Any]],
    target_count: int,
) -> bool:
    """Target reached when enough DEDUPLICATED candidates meet criteria."""
    from src.backend.ai.goals.criteria import candidate_meets_criteria

    matching = [c for c in candidates if candidate_meets_criteria(c, criteria)]
    deduped = dedupe_candidates(matching)
    return len(deduped) >= target_count
