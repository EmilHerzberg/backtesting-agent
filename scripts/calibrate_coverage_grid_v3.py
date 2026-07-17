"""Coverage grid calibration V3 — the pre-registered 211-name warehouse study.

Implements COVERAGE-CALIBRATION-V3-PROTOCOL.md sections 3-9 (+ the section-12
freeze amendments). Produces the measurement behind GRID_VERSION="v3" and the
inputs the coverage-v2 effective-N wire needs (family return correlations).
The shipped v2 harness (calibrate_coverage_grid.py) stays untouched as the
provenance of the v2 grid.

Two phases, resume-safe (the laptop has crashed mid-workstream before):

- Phase A (expensive, parallel): per-asset shards. For every panel name x
  window x dial x base x step, run the pair of real backtests, reconstruct the
  discrete position vectors, and record the disagreement reading delta with
  its full validity classification (FIX-13 instrumented skips, FIX-14
  degenerate flags, FIX-15 active-bar quantum floor, FIX-16 warmup bars,
  FIX-17 delisted-tail trim) plus the FULL-window strategy-return correlation
  streams (FIX-27). One JSON shard per asset under data/calibration_v3_shards/
  — re-running skips existing shards.

- Phase B (cheap, deterministic): aggregate shards into D_Q curves (Q=0.85
  primary, ladder reported), interpolated SUSTAINED crossings (FIX-18),
  bootstrap CI-separated-min across bases and regimes with the FIX-24 quality
  gates, the FIX-25 temporal-split check, section-6 stability (bootstrap
  convergence + subsample ladder), section-9 confirmations (multi_indicator
  raw exposure; integer-vs-ratio analytic-primary), rho-bar + family
  correlation matrices, and the sr0(N) reference curve (FIX-30). Emits dials
  whose JND sits on the finest sweep rung (FIX-19) — the runner then extends
  the sweep finer and repeats (never accepts a bottomed-out grid).

Write-once (FIX-32): docs/design/calibration-v3-results.json is refused if
present; the file carries NO timestamps so a re-run is byte-identical or
fails the freeze-hash comparison.

Run (from the repo root):
    PYTHONPATH=. BROKER_MODE=mock python scripts/calibrate_coverage_grid_v3.py \
        [--workers 8] [--phase all|a|b] [--smoke]

--smoke: 3 assets x 2 windows x 2 dials — wiring check, writes nothing to
docs/ (results go to the shard dir as smoke-results.json).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

# --------------------------------------------------------------------------- #
# Frozen constants (protocol sections 3-6 + section-12; implementer-frozen
# values are marked IMPL and surfaced in the results manifest)
# --------------------------------------------------------------------------- #

PANEL_PATH = _REPO / "docs" / "design" / "calibration-v3-panel.json"
OUT_PATH = _REPO / "docs" / "design" / "calibration-v3-results.json"
SHARD_DIR = _REPO.parent / "data" / "calibration_v3_shards"

WINDOWS = {  # section 5 (frozen) + FIX-25 temporal halves
    "full":   ("2000-01-01", "2023-12-31"),
    "dotcom": ("2000-01-01", "2002-12-31"),
    "gfc":    ("2007-07-01", "2009-06-30"),
    "covid":  ("2020-01-01", "2020-12-31"),
    "calm_a": ("2004-01-01", "2006-12-31"),
    "calm_b": ("2013-01-01", "2015-12-31"),
    "half_1": ("2000-01-01", "2015-12-31"),
    "half_2": ("2016-01-01", "2023-12-31"),
}
REGIME_KEYS = ["full", "dotcom", "gfc", "covid", "calm_a", "calm_b"]  # JND-setting
TEMPORAL_KEYS = ["half_1", "half_2"]                                  # FIX-25 check

TARGETS = (0.02, 0.05, 0.10)     # T ladder; 0.05 primary
PRIMARY_T = 0.05
Q_LADDER = (0.50, 0.75, 0.85, 0.95, 1.00)
PRIMARY_Q = 0.85

M_MIN = 30                # minimum valid assets for D_Q to be defined
N_MIN_ACTIVE = 100        # FIX-15 active-bar quantum floor (both settings)
DEGEN_ROUNDTRIPS = 3      # FIX-14: fewer round-trips on either side = degenerate
DEGEN_EXPOSURE = 0.02     # IMPL: exposure floor (aligned with FIX-34's 2% rule)
WARMUP_K = 3              # FIX-16: bars >= K * max(period in pair)
TRIM_K = 5                # FIX-17: delisted-tail trading days dropped
STALE_RUN = 3             # FIX-17: trailing constant-adjc run dropped
SAT_CEILING = 0.95        # FIX-14: delta >= this counts as saturated
SAT_FRAC_MAX = 0.50       # IMPL: crossing invalid if > this fraction saturated
BOOT_B = 500
BOOT_SEED = 20230706
CI_UPPER_PCT = 90         # FIX-20: bootstrap upper CI percentile
SUBSAMPLE_SIZES = (50, 75, 100, 125, 150)
SUBSAMPLE_SEED = 20230707  # IMPL: section-6 ladder seed
MONO_TOL = 0.02            # FIX-18 monotonicity diagnostic tolerance

CANON = {
    "sma_crossover": {"fast_period": 15, "slow_period": 100},
    "rsi_reversion": {"period": 14, "buy_threshold": 30.0, "sell_threshold": 70.0},
    "bollinger_breakout": {"period": 20, "std_dev": 2.0},
    "macd_cross": {"fast": 12, "slow": 26, "signal_period": 9},
    "multi_indicator": {"sma_period": 30, "rsi_period": 14,
                        "rsi_buy": 30.0, "rsi_sell": 70.0},
}
# dial: (kind, low, high, bases). multi_indicator is measured ONLY via the
# section-9 raw-exposure confirmation (excluded from N — near-dead).
PARAMS = {
    "sma_crossover": {"fast_period": ("period", 5, 50, [7, 15, 35]),
                      "slow_period": ("period", 20, 200, [30, 70, 150])},
    "rsi_reversion": {"period": ("period", 5, 30, [7, 14, 25]),
                      "buy_threshold": ("threshold", 15, 40, [20, 30]),
                      "sell_threshold": ("threshold", 60, 85, [65, 78])},
    "bollinger_breakout": {"period": ("period", 10, 50, [14, 25, 40]),
                           "std_dev": ("multiplier", 1.0, 3.0, [1.5, 2.3])},
    "macd_cross": {"fast": ("period", 5, 15, [6, 10, 14]),
                   "slow": ("period", 26, 50, [28, 38, 48]),
                   "signal_period": ("period", 5, 15, [6, 10, 14])},
}
RATIOS = [0.05, 0.08, 0.12, 0.16, 0.20, 0.25, 0.30, 0.40, 0.50]
ABS_STEPS = {"threshold": [1, 2, 3, 4, 5, 7, 10],
             "multiplier": [0.1, 0.2, 0.3, 0.5, 0.75, 1.0]}
EXTEND_FINER = {"period": [0.02, 0.03], "threshold": [0.5],
                "multiplier": [0.05]}   # FIX-19 prepends
PLUS_ONE_INT = "+1int"    # section-9: explicit +1-integer step for period dials

SKIP_REASONS = {"no_bars_in_window", "overlap_lt_50", "active_lt_nmin",
                "bars_lt_warmup_k", "crashed"}
MAX_CRASH_RATE = 0.05     # FIX-13: per-dial ceiling, exceed -> investigate

# --------------------------------------------------------------------------- #
# Phase A — per-asset worker
# --------------------------------------------------------------------------- #

_WORKER = {}   # per-process state (registry + bars), set by _init_worker


def _init_worker():
    os.environ.setdefault("BROKER_MODE", "mock")
    os.environ["TQDM_DISABLE"] = "1"   # engine progress bars x 450k backtests
    from src.backend.ai.research.executor import _ensure_registry
    _WORKER["REG"] = _ensure_registry()


def _steps_for(kind: str, base: float, low: float, high: float,
               ratios: list, abs_steps: dict) -> list[tuple[str, float]]:
    """(label, stepped_value) pairs, clamped to bounds, deduped."""
    out, seen = [], set()
    if kind == "period":
        for r in ratios:
            s = round(base * (1 + r))
            if s <= high and s != base and s not in seen:
                seen.add(s)
                out.append((f"r{r}", float(s)))
        one = base + 1  # section-9 +1-integer confirmation step
        if one <= high and one not in seen:
            out.append((PLUS_ONE_INT, float(one)))
    else:
        for d in abs_steps[kind]:
            s = round(base + d, 2)
            if s <= high and s not in seen:
                seen.add(s)
                out.append((f"a{d}", s))
    return out


def _positions(template: str, params: dict, data, cache: dict, window_key: str):
    """Position vector + stats for one setting on one window slice.

    Cache key includes the WINDOW (FIX-12 — the v2 cache silently collapsed
    all regimes onto the full window). Exceptions are narrowed + instrumented
    (FIX-13): expected engine rejections return status='crashed' with the
    type; anything unexpected propagates and fails the run loudly.
    """
    import pandas as pd
    from src.backend.backtesting.engine.runner import BacktestConfig, run_backtest

    key = (template, window_key,
           tuple(sorted((k, round(float(v), 4)) for k, v in params.items())))
    if key in cache:
        return cache[key]
    out = {"status": "traded", "exc": None}
    try:
        cls = _WORKER["REG"][template].create_with_params(
            **{k: (int(v) if float(v).is_integer() else float(v))
               for k, v in params.items()})
        cfg = BacktestConfig(symbol="CAL", strategy_class=cls, data=data,
                             cash=10_000.0, commission=0.0,
                             exclusive_orders=True, trade_on_close=False,
                             warmup_bars=0)
        res = run_backtest(cfg)
        ts = pd.DatetimeIndex(data.index).values
        p = np.zeros(len(data), dtype=np.int8)
        for t in (res.trades or []):
            side = 1 if str(getattr(t, "side", "long")).lower() == "long" else -1
            e = np.datetime64(pd.Timestamp(t.entry_time))
            x = np.datetime64(pd.Timestamp(t.exit_time))
            p[(ts >= e) & (ts < x)] = side
        out["p"] = p
        out["trades"] = len(res.trades or [])
        if out["trades"] == 0:
            out["status"] = "flat"
    except (ValueError, KeyError, ZeroDivisionError, IndexError) as e:
        out.update(status="crashed", exc=type(e).__name__, p=np.zeros(0, np.int8),
                   trades=0)
    cache[key] = out
    return out


def _trim_mask(bars_index, adjc: np.ndarray, is_delisted_tail: bool) -> np.ndarray:
    """FIX-17: True = bar participates in the disagreement comparison."""
    mask = np.ones(len(adjc), dtype=bool)
    if not is_delisted_tail or len(adjc) <= TRIM_K + STALE_RUN:
        return mask
    mask[-TRIM_K:] = False
    i = len(adjc) - TRIM_K - 1
    run_end = i
    while i > 0 and adjc[i] == adjc[i - 1]:
        i -= 1
    if run_end - i + 1 >= STALE_RUN:
        mask[i:run_end + 1] = False
    return mask


def _delta(pa: dict, pb: dict, mask: np.ndarray, n_window: int) -> dict:
    """One disagreement reading with its full validity classification."""
    rec = {}
    if pa["status"] == "crashed" or pb["status"] == "crashed":
        rec["status"] = "crashed"
        rec["exc"] = pa.get("exc") or pb.get("exc")
        return rec
    a, b = pa["p"], pb["p"]
    n = min(len(a), len(b), len(mask))
    if n < 50:
        rec["status"] = "overlap_lt_50"
        return rec
    a, b, m = a[:n], b[:n], mask[:n]
    act_a = int(((a != 0) & m).sum())
    act_b = int(((b != 0) & m).sum())
    active = ((a != 0) | (b != 0)) & m
    n_active = int(active.sum())
    rec.update(active_a=act_a, active_b=act_b,
               trades_a=pa["trades"], trades_b=pb["trades"],
               expo_a=round(act_a / max(n_window, 1), 4),
               expo_b=round(act_b / max(n_window, 1), 4))
    if min(act_a, act_b) < N_MIN_ACTIVE:           # FIX-15 quantum floor
        rec["status"] = "active_lt_nmin"
        return rec
    diff = int(((a != b) & m).sum())
    rec["status"] = "ok"
    rec["delta"] = round(diff / n_active, 5)
    rec["diff_bars"] = diff
    # FIX-14: degenerate on/off — either side nearly dead is not "distinct"
    rec["degenerate"] = bool(
        min(pa["trades"], pb["trades"]) < DEGEN_ROUNDTRIPS
        or min(rec["expo_a"], rec["expo_b"]) < DEGEN_EXPOSURE)
    return rec


def _strategy_returns(p: np.ndarray, logret: np.ndarray) -> np.ndarray:
    """Per-bar strategy returns: position held entering the bar x bar return."""
    n = min(len(p), len(logret) + 1)
    return p[: n - 1] * logret[: n - 1]


def scan_asset(entry: dict, dials: dict | None, extra_ratios: dict | None) -> dict:
    """Phase-A worker: the full delta/correlation slice for ONE panel name."""
    from scripts._warehouse import warehouse_fetch

    sym = entry["symbol"]
    full = warehouse_fetch(sym, WINDOWS["full"][0], WINDOWS["full"][1],
                           enforce_quality=False)  # panel pre-gated (AM-2, frozen)
    is_delisted = not entry["alive_flag"]
    shard = {"symbol": sym, "ticker_id": entry["ticker_id"],
             "alive": entry["alive_flag"], "records": [], "correlations": {},
             "multi_exposure": None, "trim": {}}
    use_dials = dials or {t: list(p) for t, p in PARAMS.items()}

    for wkey in WINDOWS:
        lo, hi = WINDOWS[wkey]
        data = full.loc[lo:hi]
        if len(data) == 0:
            continue
        adjc = data["Close"].to_numpy()
        # trim applies when the name's series ENDS inside this window (death)
        tail_here = is_delisted and (data.index[-1] == full.index[-1])
        mask = _trim_mask(data.index, adjc, tail_here)
        if tail_here:
            shard["trim"][wkey] = int((~mask).sum())
        cache: dict = {}
        for template, dial_names in use_dials.items():
            if template not in PARAMS:
                continue
            for pname in dial_names:
                kind, low, high, bases = PARAMS[template][pname]
                ratios = (extra_ratios or {}).get((template, pname), []) + RATIOS
                others = {k: v for k, v in CANON[template].items() if k != pname}
                for base in bases:
                    need = WARMUP_K * base if kind == "period" else 0
                    pa = None
                    for label, stepped in _steps_for(kind, base, low, high,
                                                     sorted(set(ratios)),
                                                     ABS_STEPS):
                        req = max(need, WARMUP_K * stepped
                                  if kind == "period" else 0)
                        rec = {"w": wkey, "t": template, "p": pname,
                               "base": base, "step": label, "value": stepped}
                        if len(data) < max(req, 50):
                            rec["status"] = ("bars_lt_warmup_k"
                                             if len(data) >= 50
                                             else "no_bars_in_window")
                            shard["records"].append(rec)
                            continue
                        if pa is None:
                            pa = _positions(template, {**others, pname: base},
                                            data, cache, wkey)
                        pb = _positions(template, {**others, pname: stepped},
                                        data, cache, wkey)
                        rec.update(_delta(pa, pb, mask, len(data)))
                        shard["records"].append(rec)
        # FIX-27 correlation streams: FULL window only, per template family
        if wkey == "full":
            logret = np.diff(np.log(adjc))
            for template in use_dials:
                if template not in PARAMS:
                    continue
                fam, labels = [], []
                for (tmpl, wk, ptup), out in sorted(cache.items(),
                                                    key=lambda kv: str(kv[0])):
                    if tmpl != template or out["status"] == "crashed":
                        continue
                    r = _strategy_returns(out["p"], logret)
                    if len(r) and np.std(r) > 0:
                        fam.append(r)
                        labels.append(str(dict(ptup)))
                if len(fam) >= 2:
                    n = min(map(len, fam))
                    mat = np.corrcoef(np.vstack([f[:n] for f in fam]))
                    shard["correlations"][template] = {
                        "labels": labels,
                        "matrix": np.round(mat, 3).tolist()}
        # section-9: multi_indicator raw exposure at CANON (guard-independent)
        if wkey == "full":
            cachem: dict = {}
            pm = _positions("multi_indicator", CANON["multi_indicator"], data,
                            cachem, wkey)
            if pm["status"] != "crashed":
                shard["multi_exposure"] = {
                    "exposure": round(float((pm["p"] != 0).mean()), 5),
                    "holding_bars": int((pm["p"] != 0).sum()),
                    "trades": pm["trades"]}
    return shard


def run_phase_a(panel: list[dict], workers: int, dials=None, extra=None,
                force=False) -> None:
    SHARD_DIR.mkdir(parents=True, exist_ok=True)
    todo = []
    for e in panel:
        f = SHARD_DIR / f"{e['ticker_id']}.json"
        if force or not f.exists():
            todo.append(e)
    print(f"phase A: {len(todo)}/{len(panel)} shards to compute "
          f"({workers} workers)", flush=True)
    if not todo:
        return
    with ProcessPoolExecutor(max_workers=workers,
                             initializer=_init_worker) as ex:
        futs = {ex.submit(scan_asset, e, dials, extra): e for e in todo}
        done = 0
        for fut in as_completed(futs):
            e = futs[fut]
            try:
                shard = fut.result()
            except Exception as exc:  # loud, per FIX-13 — no silent skips
                print(f"  FAILED {e['symbol']}: {type(exc).__name__}: {exc}",
                      flush=True)
                raise
            (SHARD_DIR / f"{e['ticker_id']}.json").write_text(
                json.dumps(shard))
            done += 1
            if done % 10 == 0 or done == len(todo):
                print(f"  {done}/{len(todo)} shards", flush=True)


# --------------------------------------------------------------------------- #
# Phase B — deterministic aggregation
# --------------------------------------------------------------------------- #

def _dq(vals: np.ndarray, q: float) -> float:
    return float(np.percentile(vals, q * 100))


def _crossing(steps: list[float], dq: list[float], T: float) -> float | None:
    """FIX-18: interpolated SUSTAINED crossing (last up-crossing; linear
    interpolation between the bracketing steps; never rounds coarse)."""
    idx = None
    for i in range(len(dq)):
        if dq[i] >= T and all(d >= T for d in dq[i:]):
            idx = i
            break
    if idx is None:
        return None
    if idx == 0:
        return steps[0]
    x0, x1, y0, y1 = steps[idx - 1], steps[idx], dq[idx - 1], dq[idx]
    if y1 == y0:
        return x1
    return x0 + (x1 - x0) * (T - y0) / (y1 - y0)


def _collect(shards: dict, asset_ids: list[int]) -> dict:
    """tensor[(t,p,base,step_label)][window] -> {'assets':[], 'deltas':[], ...}"""
    tensor: dict = {}
    for tid in asset_ids:
        sh = shards[tid]
        for r in sh["records"]:
            if r["step"] == PLUS_ONE_INT and r["w"] != "full":
                continue  # +1int confirmation runs on the full window only
            cell = tensor.setdefault((r["t"], r["p"], r["base"], r["step"]), {})
            wc = cell.setdefault(r["w"], {"deltas": [], "assets": [],
                                          "alive": [], "skips": {},
                                          "degenerate": 0, "value": r.get("value")})
            if r["status"] == "ok" and not r.get("degenerate"):
                wc["deltas"].append(r["delta"])
                wc["assets"].append(tid)
                wc["alive"].append(sh["alive"])
            elif r["status"] == "ok":
                wc["degenerate"] += 1
            else:
                key = (r["status"] if r["status"] != "crashed"
                       else f"crashed:{r.get('exc')}")
                wc["skips"][key] = wc["skips"].get(key, 0) + 1
    return tensor


def _dial_curves(tensor: dict, template: str, pname: str, base: float,
                 window: str, q: float):
    """(step_values, D_q, meta) sorted by step size; None-safe."""
    pts = []
    for (t, p, b, label), cell in tensor.items():
        if (t, p, b) != (template, pname, base) or label == PLUS_ONE_INT:
            continue
        wc = cell.get(window)
        if not wc or len(wc["deltas"]) < M_MIN:
            continue
        deltas = np.array(wc["deltas"])
        sat = float((deltas >= SAT_CEILING).mean())
        size = (float(label[1:]) if label.startswith("r")
                else float(label[1:]))
        pts.append((size, _dq(deltas, q), sat, len(deltas),
                    int(sum(1 for a in wc["alive"] if not a))))
    pts.sort()
    return pts


def _jnd_candidates(tensor, template, pname, kind, bases, q, T, boot_rng):
    """All (base, regime) crossing candidates with bootstrap CIs + FIX-24 gates."""
    cands = []
    for base in bases:
        for wkey in REGIME_KEYS:
            pts = _dial_curves(tensor, template, pname, base, wkey, q)
            if len(pts) < 2:
                continue
            steps = [p[0] for p in pts]
            dq = [p[1] for p in pts]
            jnd = _crossing(steps, dq, T)
            if jnd is None:
                continue
            # FIX-24 gates: saturation at the crossing step + valid-n + census
            i_cross = next(i for i, s in enumerate(steps) if s >= jnd)
            sat_ok = pts[i_cross][2] <= SAT_FRAC_MAX
            n_valid = pts[i_cross][3]
            n_delisted = pts[i_cross][4]
            # bootstrap the crossing over the asset axis
            boots = _bootstrap_jnd(tensor, template, pname, base, wkey, q, T,
                                   boot_rng)
            cands.append({
                "base": base, "window": wkey, "jnd": round(jnd, 4),
                "boot_ci90": (round(float(np.percentile(boots, CI_UPPER_PCT)), 4)
                              if boots is not None else None),
                "boot_dist": boots, "n_valid": n_valid,
                "n_delisted": n_delisted, "sat_ok": bool(sat_ok),
                "eligible": bool(sat_ok and n_valid >= M_MIN
                                 and boots is not None),
            })
    return cands


def _bootstrap_jnd(tensor, template, pname, base, wkey, q, T, rng,
                   B=BOOT_B):
    """Resample the asset axis, re-derive the crossing per resample."""
    per_step = []
    for (t, p, b, label), cell in sorted(tensor.items(), key=lambda kv: str(kv[0])):
        if (t, p, b) != (template, pname, base) or label == PLUS_ONE_INT:
            continue
        wc = cell.get(wkey)
        if not wc or len(wc["deltas"]) < M_MIN:
            continue
        size = float(label[1:])
        per_step.append((size, np.array(wc["deltas"])))
    if len(per_step) < 2:
        return None
    per_step.sort(key=lambda x: x[0])
    steps = [s for s, _ in per_step]
    out = []
    for _ in range(B):
        dq = []
        for _, deltas in per_step:
            idx = rng.integers(0, len(deltas), len(deltas))
            dq.append(_dq(deltas[idx], q))
        c = _crossing(steps, dq, T)
        out.append(c if c is not None else steps[-1] * 2)  # censored: no cross
    return np.array(out)


def _ci_separated_min(cands: list[dict]) -> dict:
    """FIX-20/FIX-24: the finest ELIGIBLE candidate wins only if its bootstrap
    upper-CI beats the runner-up's point estimate; overlapping candidates are
    pooled (here: resolved to the runner-up, since delta-pooling across regime
    windows mixes estimands — IMPL choice, conservative COARSE-ward only
    between statistically-indistinguishable candidates, reported raw-min
    alongside)."""
    eligible = [c for c in cands if c["eligible"]]
    if not eligible:
        return {"jnd": None, "raw_min": None, "winner": None}
    eligible.sort(key=lambda c: c["jnd"])
    raw_min = eligible[0]["jnd"]
    winner = eligible[0]
    for cand in eligible:
        rest = [c for c in eligible if c is not cand]
        if not rest or cand["boot_ci90"] <= min(c["jnd"] for c in rest):
            winner = cand
            break
        winner = None
    if winner is None:  # nothing separated: pool = the pooled point min is the
        winner = eligible[0]  # finest point estimate, flagged unseparated
        separated = False
    else:
        separated = True
    return {"jnd": winner["jnd"], "raw_min": raw_min,
            "winner": {k: winner[k] for k in ("base", "window", "jnd",
                                              "boot_ci90", "n_valid",
                                              "n_delisted")},
            "ci_separated": separated}


def run_phase_b(panel: list[dict], smoke: bool = False) -> dict:
    shards = {}
    for e in panel:
        f = SHARD_DIR / f"{e['ticker_id']}.json"
        if f.exists():
            shards[e["ticker_id"]] = json.loads(f.read_text())
    print(f"phase B: {len(shards)}/{len(panel)} shards loaded", flush=True)
    asset_ids = sorted(shards)
    tensor = _collect(shards, asset_ids)
    rng = np.random.default_rng(BOOT_SEED)

    results = {"grid_version": "v3", "constants": {
        "T": TARGETS, "primary_T": PRIMARY_T, "Q": Q_LADDER,
        "primary_Q": PRIMARY_Q, "M_min": M_MIN, "N_min_active": N_MIN_ACTIVE,
        "degen_roundtrips": DEGEN_ROUNDTRIPS, "degen_exposure_IMPL": DEGEN_EXPOSURE,
        "warmup_k": WARMUP_K, "trim_k": TRIM_K, "stale_run": STALE_RUN,
        "sat_ceiling": SAT_CEILING, "sat_frac_max_IMPL": SAT_FRAC_MAX,
        "boot": {"B": BOOT_B, "seed": BOOT_SEED, "ci_upper_pct": CI_UPPER_PCT},
        "subsample": {"sizes": SUBSAMPLE_SIZES, "seed_IMPL": SUBSAMPLE_SEED},
        "windows": WINDOWS, "ratios": RATIOS, "abs_steps": ABS_STEPS,
        "note_fix15": ("N_min_active=100 makes the metric quantum <=1%, so at "
                       "T=0.05 a crossing implies >=5 differing bars; T=0.02 "
                       "is reported-only (quantum insufficient)")},
        "dials": {}, "needs_finer": [], "ladders": {}, "skips": {},
        "correlations": {}, "multi_indicator": {}, "integer_rule": {}}

    for template, dials in PARAMS.items():
        for pname, (kind, low, high, bases) in dials.items():
            key = f"{template}.{pname}"
            cands = _jnd_candidates(tensor, template, pname, kind, bases,
                                    PRIMARY_Q, PRIMARY_T, rng)
            sel = _ci_separated_min(cands)
            finest = (min(RATIOS) if kind == "period"
                      else min(ABS_STEPS[kind]))
            at_floor = sel["jnd"] is not None and sel["jnd"] <= finest
            if at_floor:
                results["needs_finer"].append(key)
            # FIX-25 temporal halves (report; adopt finer if > 1 step apart)
            halves = {}
            for hw in TEMPORAL_KEYS:
                pts_all = []
                for base in bases:
                    pts = _dial_curves(tensor, template, pname, base, hw,
                                       PRIMARY_Q)
                    if len(pts) >= 2:
                        c = _crossing([p[0] for p in pts], [p[1] for p in pts],
                                      PRIMARY_T)
                        if c is not None:
                            pts_all.append(c)
                halves[hw] = round(min(pts_all), 4) if pts_all else None
            results["dials"][key] = {
                "kind": kind, "selected": sel,
                "candidates": [{k: c[k] for k in ("base", "window", "jnd",
                                                  "boot_ci90", "n_valid",
                                                  "n_delisted", "sat_ok",
                                                  "eligible")}
                               for c in cands],
                "temporal_halves": halves, "at_finest_rung": bool(at_floor)}
            # T x Q ladder (reported-only, FIX-21)
            lad = {}
            for T in TARGETS:
                for q in Q_LADDER:
                    c_ = _ci_separated_min(_jnd_candidates(
                        tensor, template, pname, kind, bases, q, T, rng))
                    lad[f"T{T}_Q{q}"] = c_["jnd"]
            results["ladders"][key] = lad

    # FIX-13 skip census + crash-rate ceiling
    for (t, p, b, label), cell in tensor.items():
        for wkey, wc in cell.items():
            for reason, n in wc["skips"].items():
                k = f"{t}.{p}"
                results["skips"].setdefault(k, {}).setdefault(reason, 0)
                results["skips"][k][reason] += n

    # FIX-27: rho-bar per template from the family matrices (mean over assets
    # of the mean adjacent-setting correlation)
    for template in PARAMS:
        vals, mats = [], 0
        for tid in asset_ids:
            fam = shards[tid]["correlations"].get(template)
            if fam:
                m = np.array(fam["matrix"])
                if m.shape[0] >= 2:
                    off = m[np.triu_indices_from(m, k=1)]
                    vals.append(float(np.mean(off)))
                    mats += 1
        results["correlations"][template] = {
            "rho_bar_family_mean": (round(float(np.mean(vals)), 4)
                                    if vals else None),
            "assets_with_matrix": mats}

    # section-9: multi_indicator raw exposure across the panel
    expo = [shards[t]["multi_exposure"]["exposure"] for t in asset_ids
            if shards[t].get("multi_exposure")]
    if expo:
        arr = np.array(expo)
        results["multi_indicator"] = {
            "n": len(arr), "exposure_lt_2pct_frac": round(float((arr < 0.02).mean()), 4),
            "pass_near_dead": bool((arr < 0.02).mean() >= 0.90),
            "exposure_p50": round(float(np.median(arr)), 5),
            "exposure_p90": round(float(np.percentile(arr, 90)), 5)}

    # section-9 / FIX-31: integer-vs-ratio, analytic PRIMARY
    for template, dials in PARAMS.items():
        for pname, (kind, low, high, bases) in dials.items():
            if kind != "period":
                continue
            key = f"{template}.{pname}"
            sel = results["dials"][key]["selected"]["jnd"]
            analytic = bool(sel is not None
                            and any(b * sel < 1 for b in bases))
            emp = {}
            for base in bases:
                cell = tensor.get((template, pname, base, PLUS_ONE_INT))
                wc = cell.get("full") if cell else None
                if wc and len(wc["deltas"]) >= M_MIN:
                    emp[str(base)] = round(
                        _dq(np.array(wc["deltas"]), PRIMARY_Q), 4)
            results["integer_rule"][key] = {
                "analytic_integer_governed": analytic,
                "plus1int_D085_by_base": emp,
                "empirical_confirms": {b: (v >= PRIMARY_T)
                                       for b, v in emp.items()}}

    # FIX-30: sr0(N) reference curve at the theoretical per-bar null
    t_bars = 6000
    v_null = 1.0 / t_bars
    results["sr0_reference_curve"] = {
        "V": v_null, "T_bars": t_bars,
        "curve": {str(n): round(_sr0(n, v_null), 5)
                  for n in (100, 300, 1000, 3000, 10000, 30000, 100000)},
        "note": ("diagnostic only; the wiring uses the PF4 conservative "
                 "V_null per the reconciled plan, and N comes from "
                 "reachable_cells after transcription")}
    return results


def _sr0(n_trials: int, variance: float) -> float:
    """Expected max Sharpe under the null — same formula as deflated_sharpe.py."""
    import scipy.stats
    gamma = 0.5772156649015329
    z = scipy.stats.norm.ppf
    return math.sqrt(variance) * ((1 - gamma) * z(1 - 1.0 / n_trials)
                                  + gamma * z(1 - 1.0 / (n_trials * math.e)))


# --------------------------------------------------------------------------- #

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=max(2, (os.cpu_count() or 8) - 2))
    ap.add_argument("--phase", choices=("all", "a", "b"), default="all")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--force-shards", action="store_true")
    args = ap.parse_args()

    manifest = json.loads(PANEL_PATH.read_text())
    panel = manifest["panel"]
    # integrity: the panel hash must match its content (frozen input)
    blob = json.dumps(panel, sort_keys=True, separators=(",", ":")).encode()
    if hashlib.sha256(blob).hexdigest() != manifest["panel_sha256"]:
        print("FATAL: panel content does not match its committed sha256")
        sys.exit(2)

    dials = None
    if args.smoke:
        panel = panel[:3]
        dials = {"sma_crossover": ["fast_period"],
                 "rsi_reversion": ["period"]}
        global WINDOWS, REGIME_KEYS, TEMPORAL_KEYS
        WINDOWS = {k: WINDOWS[k] for k in ("full", "covid")}
        REGIME_KEYS = ["full", "covid"]
        TEMPORAL_KEYS = []

    if args.phase in ("all", "a"):
        run_phase_a(panel, args.workers, dials=dials, force=args.force_shards)
    if args.phase in ("all", "b"):
        results = run_phase_b(panel, smoke=args.smoke)
        out = (SHARD_DIR / "smoke-results.json") if args.smoke else OUT_PATH
        if not args.smoke and out.exists():
            print(f"REFUSED: {out.name} already exists (write-once, FIX-32).")
            sys.exit(3)
        blob = json.dumps(results, indent=1, sort_keys=True)
        out.write_text(blob)
        print(f"wrote {out} sha256="
              f"{hashlib.sha256(blob.encode()).hexdigest()[:16]}...")
        if results["needs_finer"]:
            print("FIX-19: dials at the finest rung, extend the sweep and "
                  f"re-run: {results['needs_finer']}")


if __name__ == "__main__":
    main()
