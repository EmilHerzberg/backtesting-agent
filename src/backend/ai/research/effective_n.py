"""Coverage-v2 effective-N wire (RT1/B1/B2/B4/B5) — the campaign multiplicity size.

WHAT FEEDS THE GATE (v1 of the wire, pre-registered):
    search_size = max(N_visited_campaign, N_run)
where N_visited_campaign = the RAW count of VISITED grid cells summed over the
campaign's selection scope (every (template, asset) in the run's coverage map —
B1 realized-visited, B2 campaign pool), and N_run = the run's measured trial
count. The raw visited count is the B5-sanctioned CONSERVATIVE UPPER BOUND on
the campaign's independent-trial multiplicity.

WHY NO CORRELATION REDUCTION YET (the honest part): the calibration study
measured the sweep families' effective counts (calibration-v3-effective-counts
.json: Meff ~1.1-1.65 of ~38-55 settings, ratio ~0.03) — but sweep families are
one-dial-at-a-time NEIGHBORS (maximally correlated), while the maximin sampler
visits cells FAR APART (review-verified: correlation decays 0.97→0.60 with grid
distance). Applying the sweep-derived ratio to spread-out visited sets would
OVER-reduce N — the anti-conservative direction the plan forbids.

BETA-MODE CAVEAT (Track-4 review, load-bearing for the PF phase): even
maximally-distant cells of one (template, asset) family share the asset's
market mode — measured off-diagonal correlations floor at ~0.55, and the MP
clip folds the whole bulk into that mode, so ``mp_denoised_effective_count``
returns Meff ~1.4-1.75 on REAL families regardless of spread. Naively wiring
that as N_eff would collapse the campaign correction back to N_run — nullifying
cross-run accumulation (a loosening). The PF2/PF3 phase must therefore count
independence on the market-mode-STRIPPED (or beta-hedged) return structure, not
the raw correlation matrix; until then the raw visited count stands (its slack
is log-damped: a 6x over-count moves the hurdle only ~10-14%).

SCOPE NOTES: (1) the wire is INERT on run 1 by design — within a single run the
distinct visited cells never exceed the executed trials, so the correction only
binds once persisted cross-run coverage accumulates (run 2+). (2) The campaign
scope sums every (template, asset) the coverage store holds for the run's asset
pool — including templates outside the current run's allowed set (a superset =
over-strict = safe; the campaign's cherry-pick scope is everything it ever
searched on those assets, B2).

FIREWALL (PF6, output-side): this module consumes CELL COUNTS and frozen
calibration constants only — no performance data exists anywhere in its
inputs, so the multiplicity size cannot encode or steer selection.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np

_ARTIFACT = (Path(__file__).resolve().parents[4]
             / "docs" / "design" / "calibration-v3-effective-counts.json")


def participation_ratio(eigvals: np.ndarray) -> float:
    """Meff = (Σλ)² / Σλ² — the ONC/participation-ratio effective count."""
    ev = np.clip(np.asarray(eigvals, dtype=float), 0.0, None)
    s1, s2 = float(ev.sum()), float((ev ** 2).sum())
    return (s1 * s1) / s2 if s2 > 0 else 1.0


def mp_denoised_effective_count(corr: np.ndarray, t_obs: int) -> float:
    """RT1 estimator: participation ratio on the Marčenko–Pastur-clipped
    (sigma^2=1, trace-preserving) correlation spectrum. PF3-validated on
    known-K synthetics; the gate-time measured reduction applies it to the
    ACTUAL visited family once PF2/PF3 pass (not wired yet — see module doc)."""
    corr = np.asarray(corr, dtype=float)
    n = corr.shape[0]
    if n < 2 or t_obs < n + 1:
        return float(max(n, 1))
    ev = np.linalg.eigvalsh((corr + corr.T) / 2.0)
    ev = np.clip(ev, 0.0, None)
    lam_plus = (1.0 + np.sqrt(n / float(t_obs))) ** 2
    noise = ev < lam_plus
    if noise.any() and not noise.all():
        ev = ev.copy()
        ev[noise] = ev[noise].mean()
    return participation_ratio(ev)


def market_mode_stripped_effective_count(corr: np.ndarray, t_obs: int) -> float:
    """PF2/PF3 (Track-5): variance-share-weighted residual diversity count.

    Real strategy families share their asset's market mode (off-diagonal
    correlations floor ~0.55 at any grid distance), which collapses the raw
    participation ratio to ~1-2 regardless of true strategy diversity (the
    Track-4 pinned limitation). This estimator strips the TOP eigenvector
    (the family's common mode), counts the participation ratio of the
    RENORMALIZED residual, and WEIGHTS that count by the residual's share of
    total variance:  1 + residual_share × PR(residual).

    The weighting is load-bearing (caught by the anti-gaming test): without
    it, true near-clones' independent-but-TINY idiosyncratic noise renormalizes
    into full unit-scale diversity and 30 clones count as ~30. With it, clones
    → ~1 (residual share ≈ 0) while genuinely-distinct groups riding one beta
    retain their diversity in proportion to how much of their behaviour is
    actually their own. Semantics (honest): a CONSERVATIVE, lower-bound-leaning
    measure of independent-trial multiplicity — the shared mode genuinely
    couples the family's Sharpe estimators, so K distinct groups at high beta
    count as fewer than K. The PF-phase largest-within-tolerance rule composes
    estimator candidates; over-counting is the SAFE direction when this is
    used to reduce the raw visited N. Still NOT wired to the gate."""
    corr = np.asarray(corr, dtype=float)
    n = corr.shape[0]
    if n < 3 or t_obs < n + 1:
        return float(max(n, 1))
    sym = (corr + corr.T) / 2.0
    ev, vec = np.linalg.eigh(sym)
    ev = np.clip(ev, 0.0, None)
    total = float(ev.sum())
    resid_share = max(1.0 - float(ev[-1]) / total, 0.0) if total > 0 else 0.0
    resid = sym - ev[-1] * np.outer(vec[:, -1], vec[:, -1])
    d = np.sqrt(np.clip(np.diag(resid), 1e-12, None))
    resid = resid / np.outer(d, d)
    np.fill_diagonal(resid, 1.0)
    pr_resid = max(mp_denoised_effective_count(resid, t_obs) - 1.0, 0.0)
    return 1.0 + resid_share * pr_resid


@lru_cache(maxsize=1)
def _frozen() -> dict:
    try:
        return json.loads(_ARTIFACT.read_text()).get("templates", {})
    except (OSError, json.JSONDecodeError):
        return {}


def frozen_ratio(template_id: str) -> float:
    """The calibration-measured sweep-family Meff ratio (p75 over assets) — a
    LOWER-bound REFERENCE on the true ratio for spread-out visited sets.
    Telemetry/PF-phase input only; NOT a sanctioned reduction and NOT applied
    to the gate's N (see the beta-mode caveat in the module doc). Unknown
    templates report 1.0 (no reduction)."""
    t = _frozen().get(template_id)
    return float(t["reference_ratio_p75"]) if t else 1.0


def campaign_search_size(visited: dict, n_run: int) -> int:
    """B1/B2/B5: the campaign multiplicity size for the DSR's sr0.

    ``visited``: CoverageMap.visited — {(template, asset): set(cell_ids)} for
    the campaign's selection scope. Raw counts (the conservative upper bound);
    the max(., n_run) floor makes enabling the wire monotone-STRICTER vs the
    per-run status quo by construction.
    """
    n_campaign = sum(len(cells) for cells in (visited or {}).values())
    return max(int(n_campaign), int(n_run))
