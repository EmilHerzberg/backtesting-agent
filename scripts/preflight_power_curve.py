"""PF1 — the two-sided power/size curve of the (coverage-v2-wired) DSR gate.

Runs the REAL DeflatedSharpeGate on synthetic daily-return streams with PLANTED
true annualized Sharpe, across the operating points the coverage-v2 wire
creates, and measures:

- POWER: P(firm PASS | true edge = s) per edge and operating point — the curve
  D1's reference edge is finalized from ("the weakest edge the in-sample gate
  must reliably confirm", owner-locked band 0.9-1.0, strict-leaning).
- SIZE: P(firm PASS | true edge = 0) — the false-pass rate. The MON2 headline
  reframe is visible in the output: moving the campaign N 200 → 172,831 shifts
  power modestly (sr0 ∝ √(2 ln N)); T and V dominate.

Fixed operating conditions (pre-registered): T = 2265 daily bars (the research
window), sigma = 1%/day gaussian returns (skew/kurtosis stress is a recorded
extension, not v1), exposure 1.0, n_trials = 200 executed (firm-verdict regime),
measured per-period trial-Sharpe variance V = 0.005 (typical dispersion; the
PF4 floor v_null = 3/2264 ≈ 0.0013 does not bind at this point — a collapsed-V
point is included to show the floor holding the bar up).

Output (write-once, timestamp-free): docs/design/coverage-v2-power-curve.json

Run:  PYTHONPATH=. BROKER_MODE=mock python scripts/preflight_power_curve.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from src.backend.backtesting.gates.deflated_sharpe import DeflatedSharpeGate  # noqa: E402
from src.backend.backtesting.gates.pipeline import GateContext, GateStatus  # noqa: E402

OUT_PATH = _REPO / "docs" / "design" / "coverage-v2-power-curve.json"

SEED = 20260718
T_BARS = 2265
SIGMA_DAILY = 0.01
N_TRIALS = 200
V_MEASURED = 0.005
REPS = 400
EDGES = [0.0, 0.3, 0.5, 0.7, 0.9, 1.0, 1.2, 1.5, 2.0, 2.5, 3.0, 3.5]          # planted annualized Sharpe
POINTS = [("per_run", 0), ("campaign_5k", 5_000), ("campaign_full", 172_831)]
COLLAPSED_V_POINT = ("campaign_5k_collapsed_V", 5_000, 1e-9)  # PF4 floor showcase
POWER_FLOOR = 0.80  # IMPL, pre-registered: D1's reference edge must clear this


def _pass_rate(edge: float, search_size: int, v_measured: float,
               rng: np.random.Generator) -> float:
    gate = DeflatedSharpeGate()
    mu = edge / np.sqrt(252.0) * SIGMA_DAILY
    firm_passes = 0
    for _ in range(REPS):
        returns = rng.standard_normal(T_BARS) * SIGMA_DAILY + mu
        # the REALIZED sample Sharpe, not the planted edge — the gate derives sr_hat from the
        # returns itself, but any future metrics consumer must see the honest sample value
        realized = float(returns.mean() / returns.std(ddof=1) * np.sqrt(252.0))
        ctx = GateContext(
            metrics={"sharpe_annual": realized, "exposure_time": 1.0},
            trades=[], returns=returns, equity_curve=[],
            n_trials_global=N_TRIALS, trial_sr_variance=v_measured,
            search_size=search_size,
        )
        r = gate.check(ctx)
        if r.status == GateStatus.PASS and not r.details.get("provisional"):
            firm_passes += 1
    return firm_passes / REPS


def main():
    if OUT_PATH.exists():
        print(f"REFUSED: {OUT_PATH.name} already exists (write-once).")
        sys.exit(3)
    rng = np.random.default_rng(SEED)
    curve: dict = {}
    print(f"{'edge':>6} | " + " | ".join(f"{name:>22}" for name, _ in POINTS)
          + f" | {COLLAPSED_V_POINT[0]:>26}")
    for edge in EDGES:
        row = {}
        for name, ss in POINTS:
            row[name] = round(_pass_rate(edge, ss, V_MEASURED, rng), 4)
        row[COLLAPSED_V_POINT[0]] = round(
            _pass_rate(edge, COLLAPSED_V_POINT[1], COLLAPSED_V_POINT[2], rng), 4)
        curve[str(edge)] = row
        print(f"{edge:>6} | " + " | ".join(f"{row[name]:>22}" for name, _ in POINTS)
              + f" | {row[COLLAPSED_V_POINT[0]]:>26}")

    size = {k: curve["0.0"][k] for k in curve["0.0"]}
    # D1 recommendation: smallest edge in the owner-locked band whose power at the
    # FULL-campaign point clears the pre-registered floor.
    rec = next((e for e in (0.9, 1.0)
                if curve[str(e)]["campaign_full"] >= POWER_FLOOR), None)
    out = {"constants": {"seed": SEED, "t_bars": T_BARS, "sigma_daily": SIGMA_DAILY,
                         "n_trials": N_TRIALS, "v_measured": V_MEASURED,
                         "reps": REPS, "edges": EDGES,
                         "points": {n: s for n, s in POINTS},
                         "collapsed_v_point": list(COLLAPSED_V_POINT),
                         "power_floor_IMPL": POWER_FLOOR,
                         "scope_note": ("DSR gate only (the coverage-v2-changed "
                                        "gate); gaussian returns; skew/kurtosis "
                                        "stress recorded as an extension")},
           "power_curve": curve, "size_at_null": size,
           "d1_recommendation": {"reference_edge": rec,
                                 "rule": "smallest edge in {0.9, 1.0} with "
                                         "power(campaign_full) >= power_floor"}}
    blob = json.dumps(out, indent=1, sort_keys=True).encode()
    OUT_PATH.write_bytes(blob)   # bytes, not text: the printed sha must equal sha256sum(file)
    print(f"\nsize at null: {size}")
    print(f"D1 recommendation: reference_edge = {rec}")
    print(f"wrote {OUT_PATH.name} sha256="
          f"{hashlib.sha256(blob).hexdigest()[:16]}...")


if __name__ == "__main__":
    main()
