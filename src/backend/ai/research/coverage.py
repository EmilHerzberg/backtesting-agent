"""Cross-run coverage memory (v1) — space-filling sampling over a domain-aware hyperparameter grid.

The strategist samples parameters i.i.d.-uniform with a fixed seed, so runs re-test the SAME strategies
(within-run dedup only). This module turns the continuous/integer parameter space into a discrete grid of
"meaningfully different" CELLS, remembers which cells have been visited ACROSS runs, and lets the strategist
pick the UNVISITED cell farthest from everything visited (greedy farthest-point / maximin) — so successive
runs dig where no prior run has dug, instead of re-sampling near-duplicates.

DESIGN: docs/design/COVERAGE-MEMORY-V1.md.

OVERFITTING-NEUTRAL (v1 quality gate): this module changes only WHERE we sample. It never reads a cell's
performance to steer sampling (that would be exploitation → overfitting), and nothing here feeds the
significance path (the deflated-Sharpe multiple-testing count stays per-run, untouched). v1 stores NO
per-cell performance at all — coverage is a pure spatial memory (visited cells + counts), so there is no
performance column for a future edit to accidentally wire into the sampler.

CROSS-RUN HONESTY (shipped caveat): coverage accumulates the visited set across runs, but each run's
significance still corrects only for THAT run's trials. So a campaign that fills the grid and then
cherry-picks the best surviving cell has an UNCORRECTED cumulative multiple-testing burden. v1 surfaces no
cross-run winner list, and `summary()` ships a plain-language caveat saying exactly this; the cross-run
correction itself is v2 (it needs the calibrated grid).

Grid resolution is a-priori for v1 (tagged grid_version) — a signal-flip calibration replaces it in v2.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from itertools import product

# ── Calibrated grid (v2) — PER-PARAMETER resolution from the signal-flip study ────────────────────────
# Each parameter's just-noticeable-difference (JND): the step at which ~5% of in-market days change position
# (= a meaningfully different strategy), measured on the REAL backtest engine over 6 diverse assets
# (AAPL/MSFT/NVDA/KO/PG/SPY, 2015-2023, target T=0.05). See docs/design/COVERAGE-CALIBRATION.md +
# scratchpad/calibrate_grid.py. Sensitivity is very non-uniform, so resolution is per-parameter, not per-kind.
# The GRID_VERSION bump means v1-persisted cells never collide with these v2 cells (namespaced in the store).
GRID_VERSION = "v2"

# PERIOD dims: log ratio r (one cell per multiplicative 1+r band). Short oscillators (rsi/bollinger period)
# flip on a ~5-8% change; sma fast is nearly inert (~30%).
_PERIOD_RATIO = {
    ("sma_crossover", "fast_period"): 0.30, ("sma_crossover", "slow_period"): 0.16,
    ("rsi_reversion", "period"): 0.08,
    ("bollinger_breakout", "period"): 0.06,
    ("macd_cross", "fast"): 0.20, ("macd_cross", "slow"): 0.22, ("macd_cross", "signal_period"): 0.20,
    ("multi_indicator", "sma_period"): 0.16, ("multi_indicator", "rsi_period"): 0.08,  # analogs (multi under-trades)
}
# THRESHOLD dims: absolute RSI points. MULTIPLIER dims: absolute std-dev units.
_THRESHOLD_STEP = {
    ("rsi_reversion", "buy_threshold"): 2.0, ("rsi_reversion", "sell_threshold"): 2.0,
    ("multi_indicator", "rsi_buy"): 2.0, ("multi_indicator", "rsi_sell"): 2.0,
}
_MULTIPLIER_STEP = {("bollinger_breakout", "std_dev"): 0.15}
# Per-kind medians — fallback for any (template, param) pair not individually calibrated.
_KIND_FALLBACK = {"period": 0.16, "threshold": 2.0, "multiplier": 0.15}


def _kind(param_name: str) -> str:
    """Classify a parameter by how "meaningfully different" scales for it."""
    if "std" in param_name:
        return "multiplier"
    if param_name.endswith("threshold") or param_name in ("rsi_buy", "rsi_sell"):
        return "threshold"
    return "period"        # every lookback window (fast/slow/period/signal/sma_period/rsi_period)


def _template_space(template_id: str) -> dict:
    """The template's param-space dict {name: {low, high, type}} (lazy import — avoids a strategist cycle)."""
    from src.backend.ai.research.strategist import TEMPLATES
    return TEMPLATES[template_id]


def _res(template_id: str, param_name: str) -> float:
    """Calibrated resolution for one parameter: a log RATIO (period) or an absolute STEP (threshold/
    multiplier). Falls back to the per-kind median when the pair was not individually calibrated."""
    kind = _kind(param_name)
    tbl = {"period": _PERIOD_RATIO, "threshold": _THRESHOLD_STEP, "multiplier": _MULTIPLIER_STEP}[kind]
    return tbl.get((template_id, param_name), _KIND_FALLBACK[kind])


def _dim_n(template_id: str, param_name: str, low: float, high: float) -> int:
    """Number of cells along one dimension."""
    r = _res(template_id, param_name)
    if _kind(param_name) == "period":
        return int(math.floor(math.log(high / low) / math.log(1 + r))) + 1
    return int(math.floor((high - low) / r)) + 1


def _dim_cell(template_id: str, param_name: str, low: float, high: float, v: float) -> int:
    """Cell index of value v along one dimension (v clamped into [low, high] first)."""
    v = min(max(v, low), high)
    r = _res(template_id, param_name)
    if _kind(param_name) == "period":
        c = int(math.floor(math.log(v / low) / math.log(1 + r)))
    else:
        c = int(math.floor((v - low) / r))
    return min(max(c, 0), _dim_n(template_id, param_name, low, high) - 1)


def _dim_center(template_id: str, param_name: str, low: float, high: float, c: int, is_int: bool) -> float:
    """Representative value at the center of cell index c."""
    r = _res(template_id, param_name)
    n = _dim_n(template_id, param_name, low, high)
    c = min(max(c, 0), n - 1)
    if _kind(param_name) == "period":
        val = low * (1 + r) ** (c + 0.5)
    else:
        val = low + (c + 0.5) * r
    val = min(val, high)
    return int(round(val)) if is_int else round(float(val), 2)


def _sorted_params(template_id: str) -> list[str]:
    """Canonical (name-sorted) parameter order — the cell-id axis order, stable across dict changes."""
    return sorted(_template_space(template_id).keys())


def bin_params(template_id: str, params: dict) -> str:
    """Map a concrete parameter point to its discrete cell id, e.g. 'v1:3-0-7'. Two points collapse to the
    same cell iff they are not meaningfully different (near-duplicates)."""
    space = _template_space(template_id)
    idxs = []
    for name in _sorted_params(template_id):
        spec = space[name]
        lo, hi = float(spec["low"]), float(spec["high"])
        v = params.get(name)
        if v is None:
            v = (lo + hi) / 2
        idxs.append(str(_dim_cell(template_id, name, lo, hi, float(v))))
    return f"{GRID_VERSION}:" + "-".join(idxs)


def cell_center(template_id: str, cell_id: str) -> dict:
    """The representative parameter point at the center of a cell (what the sampler hands to the backtest)."""
    space = _template_space(template_id)
    idxs = _cell_vec(cell_id)
    out: dict = {}
    for name, c in zip(_sorted_params(template_id), idxs):
        spec = space[name]
        lo, hi = float(spec["low"]), float(spec["high"])
        is_int = spec.get("type") == "int"
        out[name] = _dim_center(template_id, name, lo, hi, c, is_int)
    return out


def _cell_vec(cell_id: str) -> tuple[int, ...]:
    """Parse 'v1:3-0-7' → (3, 0, 7)."""
    body = cell_id.split(":", 1)[1] if ":" in cell_id else cell_id
    return tuple(int(x) for x in body.split("-")) if body else ()


def _dim_ns(template_id: str) -> list[int]:
    """Cells-per-dimension in canonical param order (for distance normalization + enumeration)."""
    space = _template_space(template_id)
    ns = []
    for name in _sorted_params(template_id):
        spec = space[name]
        ns.append(_dim_n(template_id, name, float(spec["low"]), float(spec["high"])))
    return ns


_FEASIBLE_CACHE: dict[tuple[str, str], frozenset[str]] = {}


def feasible_cells(template_id: str) -> frozenset[str]:
    """The DRAWABLE cells: the full per-dim product MINUS structurally-unreachable cells whose center is
    bumped by _repair_params onto a different cell (the SMA fast≥slow-5 'dead corner'). The sampler must
    draw only from here, else maximin (which loves box extremes) burns attempts on cells that repair-collapse
    onto an already-visited boundary cell. For the other 4 templates the constraints are structural (disjoint
    ranges), so every product cell is feasible and this is the full grid."""
    key = (template_id, GRID_VERSION)
    cached = _FEASIBLE_CACHE.get(key)
    if cached is not None:
        return cached
    from src.backend.ai.research.strategist import _repair_params

    ns = _dim_ns(template_id)
    keep: set[str] = set()
    for combo in product(*(range(n) for n in ns)):
        cid = f"{GRID_VERSION}:" + "-".join(str(c) for c in combo)
        center = cell_center(template_id, cid)
        repaired = _repair_params(template_id, dict(center))
        if bin_params(template_id, repaired) == cid:   # center stays in its own cell → drawable
            keep.add(cid)
    frozen = frozenset(keep)
    _FEASIBLE_CACHE[key] = frozen
    return frozen


def _dist(a: tuple[int, ...], b: tuple[int, ...], ns: list[int]) -> float:
    """Distance between two cells in per-dim-normalized index space (each axis scaled by its cell count, so
    period spread is relative and threshold spread absolute — 'farthest' means economically farthest)."""
    return math.sqrt(sum(((a[i] - b[i]) / ns[i]) ** 2 for i in range(len(ns))))


@dataclass
class CoverageMap:
    """In-memory coverage state for ONE (scope, window) loaded at run start. Pure geometry — never consults
    performance. The strategist holds one; the loop flushes newly-visited cells at run end."""

    visited: dict[tuple[str, str], set[str]] = field(default_factory=dict)      # (template, asset) → cell ids
    tried_hashes: set[str] = field(default_factory=set)                         # exact-hash dedup, cross-run
    newly_visited: dict[tuple[str, str], set[str]] = field(default_factory=dict)  # to persist at run end
    _recent: deque = field(default_factory=lambda: deque(maxlen=10))            # novelty over last-K marks
    _total_cells: dict[tuple[str, str], int] = field(default_factory=dict)

    def _feasible_count(self, template_id: str) -> int:
        return len(feasible_cells(template_id))

    def pick_cell(self, template_id: str, asset: str, rng) -> str | None:
        """The unvisited feasible cell FARTHEST (maximin) from everything visited for (template, asset).
        Returns None when the feasible space is saturated (v1 signals, never auto-stops)."""
        feas = feasible_cells(template_id)
        vis = self.visited.setdefault((template_id, asset), set())
        cand = feas - vis
        if not cand:
            return None                                     # saturated
        ns = _dim_ns(template_id)
        if not vis:                                         # first pick → cell nearest the box center
            center = [(n - 1) / 2 for n in ns]
            return min(sorted(cand), key=lambda c: _dist(_cell_vec(c), tuple(center), ns))
        vis_vecs = [_cell_vec(c) for c in vis]
        far_d = -1.0
        far: list[str] = []
        for c in cand:
            cv = _cell_vec(c)
            d = min(_dist(cv, vv, ns) for vv in vis_vecs)
            if d > far_d + 1e-12:
                far_d, far = d, [c]
            elif abs(d - far_d) <= 1e-12:
                far.append(c)
        far.sort()                                          # determinism given the visited set
        return far[int(rng.integers(0, len(far)))]          # rng only breaks ties (reproducible)

    def mark(self, template_id: str, asset: str, cell_id: str, strategy_hash: str | None = None) -> bool:
        """Record a visited cell. Returns True if it opened a NEW cell (feeds the novelty rate)."""
        vis = self.visited.setdefault((template_id, asset), set())
        is_new = cell_id not in vis
        vis.add(cell_id)
        if is_new:
            self.newly_visited.setdefault((template_id, asset), set()).add(cell_id)
        if strategy_hash:
            self.tried_hashes.add(strategy_hash)
        self._recent.append(1 if is_new else 0)
        return is_new

    def novelty_rate(self) -> float:
        """Fraction of the last K marks that opened a new cell — honest 'are we still finding new ground?'."""
        return (sum(self._recent) / len(self._recent)) if self._recent else 1.0

    def pct_covered(self, template_id: str, asset: str) -> float:
        feas = self._feasible_count(template_id)
        return (len(self.visited.get((template_id, asset), set())) / feas) if feas else 1.0

    def unexplored_regions(self, template_id: str, asset: str, k: int = 3) -> list[dict]:
        """A few unvisited cell CENTERS — the soft nudge fed to the LLM (regions, never performance)."""
        cand = sorted(feasible_cells(template_id) - self.visited.get((template_id, asset), set()))
        return [cell_center(template_id, c) for c in cand[:k]]

    # Digit-free honesty caveat shipped with every coverage summary (the review's "smallest honest guard"):
    # coverage % accumulates ACROSS runs but each run's significance corrects only for its own trials.
    CROSS_RUN_CAVEAT = (
        "Coverage percentage measures how much of the parameter space has been searched across all your "
        "runs. Each run's significance check (the deflated Sharpe) accounts only for that run's own trials — "
        "it does NOT correct for the cumulative search across many runs. If you pick the best-looking "
        "strategy across a long campaign, treat it as a fresh hypothesis to re-validate out-of-sample, not a "
        "proven edge."
    )

    def summary(self) -> dict:
        """Coverage stats for the report — SPREAD ONLY (novelty + per-template pct) plus the cross-run
        honesty caveat. Deliberately carries NO per-cell/per-strategy performance ranking (that would be a
        cherry-picking menu; the overfitting quality gate forbids it)."""
        by_t: dict[str, list[float]] = {}
        for (t, a) in self.visited:
            by_t.setdefault(t, []).append(self.pct_covered(t, a))
        per = {t: round(sum(v) / len(v), 3) for t, v in by_t.items() if v}
        return {
            "novelty_rate": round(self.novelty_rate(), 3),
            "cells_visited": sum(len(v) for v in self.visited.values()),
            "pct_covered_by_template": per,
            "grid_version": GRID_VERSION,
            "caveat": self.CROSS_RUN_CAVEAT,
        }


# ── Persistence (robustness-mode only in v1; window_key="" pools the fixed default window) ────────────

async def load_coverage(scope_key: str, assets: list[str], window_key: str = "") -> CoverageMap:
    """Load the persisted visited-cell set for (scope, assets, window) into a fresh CoverageMap."""
    from sqlalchemy import select

    from src.backend.ai.research.db_models import ResearchCoverageDB
    from src.backend.db.engine import async_session

    cov = CoverageMap()
    if not assets:
        return cov
    async with async_session() as session:
        rows = (await session.execute(
            select(ResearchCoverageDB).where(
                ResearchCoverageDB.scope_key == scope_key,
                ResearchCoverageDB.window_key == window_key,
                ResearchCoverageDB.grid_version == GRID_VERSION,
                ResearchCoverageDB.security_id.in_(assets),
            )
        )).scalars().all()
    for r in rows:
        cov.visited.setdefault((r.template_id, r.security_id), set()).add(r.cell_id)
        if r.exemplar_hash:
            cov.tried_hashes.add(r.exemplar_hash)
    return cov


async def persist_coverage(scope_key: str, window_key: str, cov: CoverageMap, goal_id: str = "") -> int:
    """Upsert the cells newly visited this run (visit_count++). Best-effort telemetry; the per-attempt
    detail already lives in research_candidates/failures, so a lost flush is reconstructable via backfill."""
    from sqlalchemy import select

    from src.backend.ai.research.db_models import ResearchCoverageDB
    from src.backend.ai.research.persistence import _write_lock
    from src.backend.db.engine import async_session

    n = 0
    async with _write_lock, async_session() as session:
        for (template_id, asset), cells in cov.newly_visited.items():
            for cid in cells:
                existing = (await session.execute(
                    select(ResearchCoverageDB).where(
                        ResearchCoverageDB.scope_key == scope_key,
                        ResearchCoverageDB.window_key == window_key,
                        ResearchCoverageDB.grid_version == GRID_VERSION,
                        ResearchCoverageDB.template_id == template_id,
                        ResearchCoverageDB.security_id == asset,
                        ResearchCoverageDB.cell_id == cid,
                    )
                )).scalar_one_or_none()
                if existing is None:
                    session.add(ResearchCoverageDB(
                        scope_key=scope_key, window_key=window_key, grid_version=GRID_VERSION,
                        template_id=template_id, security_id=asset, cell_id=cid,
                        exemplar_hash="", visit_count=1, last_goal_id=goal_id,
                    ))
                    n += 1
                else:
                    existing.visit_count += 1
                    if goal_id:
                        existing.last_goal_id = goal_id
        await session.commit()
    return n


async def backfill_coverage(scope_key: str, window_key: str = "") -> int:
    """Reconstruct robustness coverage cells from existing candidates + failures (idempotent). Makes the
    coverage table a pure, rebuildable accelerator; run once when it is empty for a scope."""
    import json

    from sqlalchemy import select

    from src.backend.ai.research.db_models import (
        ResearchCandidateDB, ResearchCoverageDB, ResearchFailureDB, ResearchRunDB,
    )
    from src.backend.ai.research.persistence import _write_lock
    from src.backend.db.engine import async_session

    n = 0
    async with _write_lock, async_session() as session:
        # only robustness runs (window_key "") for this scope's users
        run_rows = (await session.execute(
            select(ResearchRunDB.goal_id, ResearchRunDB.user_id, ResearchRunDB.mode)
        )).all()
        robustness_goals = {g for (g, uid, mode) in run_rows
                            if (mode or "robustness") == "robustness" and str(uid) == scope_key}
        seen: set[tuple] = set()
        for Model in (ResearchCandidateDB, ResearchFailureDB):
            rows = (await session.execute(select(Model))).scalars().all()
            for r in rows:
                if getattr(r, "goal_id", None) not in robustness_goals:
                    continue
                tmpl, asset = getattr(r, "template_id", ""), getattr(r, "security_id", "")
                params_raw = getattr(r, "params_json", "") or "{}"
                if not tmpl or not asset:
                    continue
                try:
                    params = json.loads(params_raw)
                    cid = bin_params(tmpl, params)
                except Exception:  # noqa: BLE001 — skip unparseable historical rows
                    continue
                key = (scope_key, window_key, tmpl, asset, cid)
                if key in seen:
                    continue
                seen.add(key)
                exists = (await session.execute(
                    select(ResearchCoverageDB.id).where(
                        ResearchCoverageDB.scope_key == scope_key,
                        ResearchCoverageDB.window_key == window_key,
                        ResearchCoverageDB.grid_version == GRID_VERSION,
                        ResearchCoverageDB.template_id == tmpl,
                        ResearchCoverageDB.security_id == asset,
                        ResearchCoverageDB.cell_id == cid,
                    )
                )).first()
                if exists is None:
                    session.add(ResearchCoverageDB(
                        scope_key=scope_key, window_key=window_key, grid_version=GRID_VERSION,
                        template_id=tmpl, security_id=asset, cell_id=cid,
                        exemplar_hash=getattr(r, "strategy_hash", "") or "", visit_count=1,
                    ))
                    n += 1
        await session.commit()
    return n
