"""Derive the FROZEN per-template effective-count ratios for the coverage-v2 N wire (RT1).

Input: the primary calibration panel's per-asset FAMILY return-correlation matrices
(strategy daily-return streams across the sweep's settings, FULL window, emitted by
calibrate_coverage_grid_v3.py phase A into data/calibration_v3_shards/full/).

Estimator (reconciled plan §2a, RT1 — replaces the retired Kish/rho-bar reduction,
which goes inert for banded correlation): Marčenko–Pastur-denoise each correlation
matrix (eigenvalue clipping, trace-preserving, sigma^2=1, q = n_settings/T_obs),
then the participation-ratio effective count Meff = (Σλ)² / Σλ².

The per-template ratios recorded here are REFERENCE VALUES (sweep-family LOWER
bounds), NOT a sanctioned N-reduction: (a) sweep families are one-dial-at-a-time
neighbors — near-clones — while the sampler visits far-apart cells; (b) the
families are market-mode dominated (off-diagonal correlations floor ~0.55 at any
grid distance), so Meff collapses to ~1.1-1.75 regardless of spread and a naive
reduction would nullify cross-run accumulation (a loosening). The v1 wire applies
NO reduction (raw visited count, B5 conservative upper bound); the PF2/PF3 phase
must count independence on the market-mode-stripped structure first.

Output (write-once, timestamp-free): docs/design/calibration-v3-effective-counts.json

Run:  python scripts/derive_family_effective_counts.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parent.parent
PANEL_PATH = _REPO / "docs" / "design" / "calibration-v3-panel.json"
SHARD_DIR = _REPO.parent / "data" / "calibration_v3_shards" / "full"
OUT_PATH = _REPO / "docs" / "design" / "calibration-v3-effective-counts.json"

FROZEN_QUANTILE = 75          # conservative aggregate: p75 of Meff/n over assets
MIN_SETTINGS = 8              # a family this small can't support the estimator


def mp_denoised_effective_count(corr: np.ndarray, t_obs: int) -> float:
    """RT1: participation ratio on the MP-denoised correlation spectrum."""
    n = corr.shape[0]
    if n < 2 or t_obs < n + 1:
        return float(n)
    ev = np.linalg.eigvalsh((corr + corr.T) / 2.0)
    ev = np.clip(ev, 0.0, None)                 # rounding in the shards can dent PSD
    q = n / float(t_obs)
    lam_plus = (1.0 + np.sqrt(q)) ** 2
    noise = ev < lam_plus
    if noise.any() and not noise.all():
        ev = ev.copy()
        ev[noise] = ev[noise].mean()            # clip-to-mean, trace preserved
    s1, s2 = float(ev.sum()), float((ev ** 2).sum())
    return (s1 * s1) / s2 if s2 > 0 else 1.0


def main():
    if OUT_PATH.exists():
        print(f"REFUSED: {OUT_PATH.name} already exists (write-once).")
        sys.exit(3)
    manifest = json.loads(PANEL_PATH.read_text())
    bars = {e["ticker_id"]: e["bars_inwindow"] for e in manifest["panel"]}

    per_template: dict[str, list] = {}
    used_assets = 0
    for tid, t_bars in sorted(bars.items()):
        f = SHARD_DIR / f"{tid}.json"
        if not f.exists():
            continue
        sh = json.loads(f.read_text())
        if sh.get("excluded"):
            continue
        used_assets += 1
        for template, fam in sh.get("correlations", {}).items():
            m = np.array(fam["matrix"], dtype=float)
            if m.shape[0] < MIN_SETTINGS:
                continue
            meff = mp_denoised_effective_count(m, int(t_bars) - 1)
            per_template.setdefault(template, []).append(
                {"ticker_id": tid, "n_settings": int(m.shape[0]),
                 "meff": round(meff, 3),
                 "ratio": round(meff / m.shape[0], 4)})

    out = {"method": {
        "estimator": "participation ratio (sum(ev))^2/sum(ev^2) on the "
                     "MP-clipped (sigma^2=1, trace-preserving) correlation "
                     "spectrum; q = n_settings/(bars_inwindow-1)",
        "reference_quantile": FROZEN_QUANTILE,
        "min_settings": MIN_SETTINGS,
        "direction_note": ("REFERENCE VALUES, not a sanctioned reduction: for a "
                           "reduction ratio the safe aggregate is max/1.0, and "
                           "p75 under-covers the top quartile — recorded as the "
                           "sweep-family LOWER bound alongside ratio_max. The "
                           "v1 wire applies NO reduction (raw visited count)."),
        "beta_mode_caveat": ("families are market-mode dominated (off-diag corr "
                             "floors ~0.55 even at max grid distance); the MP "
                             "clip folds the bulk into that mode, so Meff "
                             "~1.1-1.75 regardless of spread. The PF2/PF3 phase "
                             "must count independence on the market-mode-"
                             "stripped structure before any measured reduction "
                             "may reach the gate's N."),
        "panel_sha256": manifest["panel_sha256"],
    }, "templates": {}}
    for template, rows in sorted(per_template.items()):
        ratios = np.array([r["ratio"] for r in rows])
        meffs = np.array([r["meff"] for r in rows])
        out["templates"][template] = {
            "n_assets": len(rows),
            "n_settings_median": float(np.median([r["n_settings"] for r in rows])),
            "meff_p25": round(float(np.percentile(meffs, 25)), 3),
            "meff_median": round(float(np.median(meffs)), 3),
            "meff_p75": round(float(np.percentile(meffs, 75)), 3),
            "ratio_p25": round(float(np.percentile(ratios, 25)), 4),
            "ratio_median": round(float(np.median(ratios)), 4),
            "reference_ratio_p75": round(float(np.percentile(ratios,
                                                             FROZEN_QUANTILE)), 4),
            "ratio_max": round(float(ratios.max()), 4),
        }
        t = out["templates"][template]
        print(f"{template:20} assets={t['n_assets']:3}  Meff median="
              f"{t['meff_median']:6.2f} / settings~{t['n_settings_median']:.0f}"
              f"  ref_ratio_p75={t['reference_ratio_p75']} max={t['ratio_max']}")
    blob = json.dumps(out, indent=1, sort_keys=True)
    OUT_PATH.write_text(blob)
    print(f"\nwrote {OUT_PATH.name} (from {used_assets} panel assets) sha256="
          f"{hashlib.sha256(blob.encode()).hexdigest()[:16]}...")


if __name__ == "__main__":
    main()
