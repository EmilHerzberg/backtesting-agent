"""Coverage grid calibration V3 — the pre-registered 211-name warehouse study.

Implements COVERAGE-CALIBRATION-V3-PROTOCOL.md sections 3-9 (+ the section-12
freeze amendments). Produces the measurement behind GRID_VERSION="v3" and the
family return-correlation inputs the coverage-v2 effective-N wire needs. The
shipped v2 harness (calibrate_coverage_grid.py) stays untouched as provenance.

Reviewed 2026-07-17 (5-lens adversarial pass, findings in
docs/reviews/HARNESS-REVIEW-2026-07-17.json); this version fixes every
blocker/high: a real pooling CI-separated-min (FIX-20), joint asset-axis
bootstrap, enforced crash-rate ceiling (FIX-13), census-balance + survivor
flags (FIX-24), temporal-half adoption (FIX-25), executable extend-finer
loop (FIX-19), section-6 convergence + subsample ladder, monotonicity
diagnostic (FIX-18), shard provenance + smoke isolation, engine-exception
quarantine, and pre-run hard gates (FIX-12 window-sensitivity +
self-determinism).

Phases (resume-safe):
- Phase A (expensive, parallel): one JSON shard per asset under
  data/calibration_v3_shards/ with a PROVENANCE stamp (windows/dials/rungs/
  constants hash) — a shard is reused only if its provenance matches, so a
  smoke run (which writes under smoke/) or a constants change can never
  silently contaminate a full run. A name failing the warehouse guards is
  quarantined as an 'adjustment-excluded' shard (pre-registered skip reason),
  never aborting the run; any OTHER per-asset failure is recorded and blocks
  the final results write instead of killing hours of compute mid-run.
- Phase B (cheap, deterministic): aggregation + selection + stability +
  section-9 confirmations. Runs entirely in memory across extend-finer
  rounds; only the FINAL stable results are written, write-once (FIX-32),
  timestamp-free.

Run (repo root):
    PYTHONPATH=. BROKER_MODE=mock python scripts/calibrate_coverage_grid_v3.py \
        [--workers 8] [--phase all|a|b] [--smoke] [--extend-rounds 3]
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
# Frozen constants (protocol sections 3-6 + section-12; IMPL = implementer-
# frozen values, surfaced in the results manifest)
# --------------------------------------------------------------------------- #

PANEL_PATH = _REPO / "docs" / "design" / "calibration-v3-panel.json"
FRAME_PATH = _REPO / "docs" / "design" / "calibration-v3-frame-snapshot.json"
ALTSEED_PATH = _REPO / "docs" / "design" / "calibration-v3-panel-altseeds.json"
OUT_PATH = _REPO / "docs" / "design" / "calibration-v3-results.json"
KSEED_PATH = _REPO / "docs" / "design" / "calibration-v3-kseed.json"
SHARD_ROOT = _REPO.parent / "data" / "calibration_v3_shards"

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
REGIME_KEYS = ["full", "dotcom", "gfc", "covid", "calm_a", "calm_b"]
TEMPORAL_KEYS = ["half_1", "half_2"]

TARGETS = (0.02, 0.05, 0.10)
PRIMARY_T = 0.05
Q_LADDER = (0.50, 0.75, 0.85, 0.95, 1.00)
PRIMARY_Q = 0.85

M_MIN = 30
N_MIN_ACTIVE = 100
DEGEN_ROUNDTRIPS = 3
DEGEN_EXPOSURE = 0.02      # IMPL
WARMUP_K = 3
TRIM_K = 5
STALE_RUN = 3
SAT_CEILING = 0.95
SAT_FRAC_MAX = 0.50        # IMPL
BOOT_B = 500
BOOT_SEED = 20230706
CI_UPPER_PCT = 90
BOOT_CENSOR_MULT = 2.0     # IMPL: non-crossing resample -> coarsest rung x this
SUBSAMPLE_SIZES = (50, 75, 100, 125, 150)
SUBSAMPLE_SEED = 20230707  # IMPL
MONO_TOL = 0.02
CENSUS_MIN_CELLS = 3       # IMPL: valid set must span >=3 of 6 living cells
CENSUS_MIN_DELISTED = 1    # IMPL: ...and >=1 non-survivor, else candidate
                           # cannot SET the dial (reported finer-but-unreliable)
SURVIVOR_FLAG_BELOW = 30   # protocol section 5: < M_min non-survivors -> flag
MAX_CRASH_RATE = 0.05      # FIX-13: enforced per dial in phase B
CONVERGENCE_MIN = 0.90     # section 6

CANON = {
    "sma_crossover": {"fast_period": 15, "slow_period": 100},
    "rsi_reversion": {"period": 14, "buy_threshold": 30.0, "sell_threshold": 70.0},
    "bollinger_breakout": {"period": 20, "std_dev": 2.0},
    "macd_cross": {"fast": 12, "slow": 26, "signal_period": 9},
    "multi_indicator": {"sma_period": 30, "rsi_period": 14,
                        "rsi_buy": 30.0, "rsi_sell": 70.0},
}
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
ABS_STEPS = {"threshold": [1.0, 2.0, 3.0, 4.0, 5.0, 7.0, 10.0],
             "multiplier": [0.1, 0.2, 0.3, 0.5, 0.75, 1.0]}
EXTEND_FINER = {"period": [0.02, 0.03], "threshold": [0.25, 0.5],
                "multiplier": [0.025, 0.05]}  # AM-9: owner chose to extend
                # past the first-round floors (0.5 pts / 0.05) before freezing
PLUS_ONE_INT = "+1int"

SKIP_REASONS = {"no_bars_in_window", "overlap_lt_50", "active_lt_nmin",
                "bars_lt_warmup_k", "crashed"}


def _constants_hash() -> str:
    blob = json.dumps({
        "windows": WINDOWS, "T": TARGETS, "Q": Q_LADDER, "M_min": M_MIN,
        "nmin": N_MIN_ACTIVE, "degen": [DEGEN_ROUNDTRIPS, DEGEN_EXPOSURE],
        "warmup_k": WARMUP_K, "trim": [TRIM_K, STALE_RUN],
        "canon": CANON, "params": {t: {p: list(v) for p, v in d.items()}
                                   for t, d in PARAMS.items()},
    }, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# Phase A — per-asset worker
# --------------------------------------------------------------------------- #

_WORKER = {}


def _init_worker():
    os.environ.setdefault("BROKER_MODE", "mock")
    os.environ["TQDM_DISABLE"] = "1"
    from src.backend.ai.research.executor import _ensure_registry
    _WORKER["REG"] = _ensure_registry()


def _rungs_for(kind: str, pname_extra: list) -> list[float]:
    base_rungs = RATIOS if kind == "period" else ABS_STEPS[kind]
    return sorted(set(list(base_rungs) + list(pname_extra)))


def _steps_for(kind: str, base: float, high: float,
               rungs: list[float]) -> list[tuple[str, float, float]]:
    """(label, nominal_rung, stepped_value); clamped, deduped on the realized
    value (an absent rung for a small base is simply not measured there)."""
    out, seen = [], set()
    if kind == "period":
        for r in rungs:
            s = round(base * (1 + r))
            if s <= high and s != base and s not in seen:
                seen.add(s)
                out.append((f"r{r}", r, float(s)))
        one = base + 1
        if one <= high and one not in seen:
            out.append((PLUS_ONE_INT, 1.0 / base, float(one)))
    else:
        for d in rungs:
            s = round(base + d, 2)
            if s <= high and s not in seen:
                seen.add(s)
                out.append((f"a{d}", d, s))
    return out


def _positions(template: str, params: dict, data, cache: dict, window_key: str):
    """Backtest one setting on one window slice; cache keyed WITH the window
    (FIX-12). Catches the ENGINE's own error hierarchy (+ValueError from
    parameter construction) — anything else propagates (FIX-13)."""
    import pandas as pd
    from src.backend.backtesting.engine.exceptions import BacktestError
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
    except (BacktestError, ValueError) as e:
        out.update(status="crashed", exc=type(e).__name__,
                   p=np.zeros(0, np.int8), trades=0)
    cache[key] = out
    return out


def _trim_mask(adjc: np.ndarray, is_delisted_tail: bool) -> np.ndarray:
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


def _delta(pa: dict, pb: dict, mask: np.ndarray) -> dict:
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
    n_masked = int(m.sum())
    act_a = int(((a != 0) & m).sum())
    act_b = int(((b != 0) & m).sum())
    active = ((a != 0) | (b != 0)) & m
    n_active = int(active.sum())
    rec.update(trades_a=pa["trades"], trades_b=pb["trades"],
               expo_a=round(act_a / max(n_masked, 1), 4),
               expo_b=round(act_b / max(n_masked, 1), 4))
    if min(act_a, act_b) < N_MIN_ACTIVE:
        rec["status"] = "active_lt_nmin"
        return rec
    diff = int(((a != b) & m).sum())
    rec["status"] = "ok"
    rec["delta"] = round(diff / n_active, 5)
    rec["degenerate"] = bool(
        min(pa["trades"], pb["trades"]) < DEGEN_ROUNDTRIPS
        or min(rec["expo_a"], rec["expo_b"]) < DEGEN_EXPOSURE)
    return rec


def _strategy_returns(p: np.ndarray, logret: np.ndarray) -> np.ndarray:
    """Position held ENTERING bar i x return OF bar i: logret[i] =
    log(adjc[i+1]/adjc[i]); pairing p[i] with logret[i] uses only the
    position decided by bar i's close for the i->i+1 return (no leak)."""
    n = min(len(p) - 1, len(logret))
    return p[:n] * logret[:n]


def scan_asset(entry: dict, windows: dict, dials: dict,
               extra_rungs: dict) -> dict:
    """Phase-A worker for ONE panel name. Never raises for data problems —
    a warehouse-guard failure returns a quarantined shard (pre-registered
    'adjustment-excluded'); unexpected exceptions propagate (recorded by the
    parent as a failed shard that BLOCKS the final write, not the run)."""
    from scripts._warehouse import WarehouseDataError, warehouse_fetch

    sym = entry["symbol"]
    meta = {"symbol": sym, "ticker_id": entry["ticker_id"],
            "alive": entry["alive_flag"], "sleeve": entry.get("sleeve"),
            "cell": (f"{entry.get('cap_bucket')}|{entry.get('vol_bucket')}"
                     if entry.get("cap_bucket") else None),
            "vol": entry.get("vol")}
    try:
        full = warehouse_fetch(sym, windows["full"][0], windows["full"][1],
                               enforce_quality=False)  # panel pre-gated (AM-2)
    except WarehouseDataError as e:
        return {**meta, "excluded": "adjustment-excluded", "reason": str(e),
                "records": [], "correlations": {}, "multi_exposure": None,
                "trim": {}}
    is_delisted = not entry["alive_flag"]
    shard = {**meta, "excluded": None, "records": [], "correlations": {},
             "multi_exposure": None, "trim": {}}

    for wkey, (lo, hi) in windows.items():
        data = full.loc[lo:hi]
        if len(data) == 0:
            continue
        adjc = data["Close"].to_numpy()
        tail_here = is_delisted and (data.index[-1] == full.index[-1])
        mask = _trim_mask(adjc, tail_here)
        if tail_here:
            shard["trim"][wkey] = int((~mask).sum())
        cache: dict = {}
        for template, dial_names in dials.items():
            for pname in dial_names:
                kind, low, high, bases = PARAMS[template][pname]
                rungs = _rungs_for(kind, extra_rungs.get(f"{template}.{pname}",
                                                         []))
                others = {k: v for k, v in CANON[template].items()
                          if k != pname}
                for base in bases:
                    pa = None
                    for label, rung, stepped in _steps_for(kind, base, high,
                                                           rungs):
                        req = (WARMUP_K * max(base, stepped)
                               if kind == "period" else 50)
                        rec = {"w": wkey, "t": template, "p": pname,
                               "base": base, "step": label, "rung": rung}
                        if len(data) < 50:
                            rec["status"] = "overlap_lt_50"
                            shard["records"].append(rec)
                            continue
                        if len(data) < req:
                            rec["status"] = "bars_lt_warmup_k"
                            shard["records"].append(rec)
                            continue
                        if pa is None:
                            pa = _positions(template, {**others, pname: base},
                                            data, cache, wkey)
                        pb = _positions(template, {**others, pname: stepped},
                                        data, cache, wkey)
                        rec.update(_delta(pa, pb, mask))
                        shard["records"].append(rec)
        if wkey == "full":
            logret = np.diff(np.log(adjc))
            for template in dials:
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
            cachem: dict = {}
            pm = _positions("multi_indicator", CANON["multi_indicator"], data,
                            cachem, wkey)
            if pm["status"] != "crashed":
                shard["multi_exposure"] = {
                    "exposure": round(float((pm["p"] != 0).mean()), 5),
                    "holding_bars": int((pm["p"] != 0).sum()),
                    "trades": pm["trades"]}
    return shard


def _provenance(windows: dict, dials: dict, extra_rungs: dict) -> dict:
    return {"windows": sorted(windows),
            "dials": {t: sorted(d) for t, d in sorted(dials.items())},
            "extra_rungs": {k: sorted(v) for k, v in sorted(extra_rungs.items())},
            "constants": _constants_hash()}


def run_phase_a(panel: list[dict], workers: int, shard_dir: Path,
                windows: dict, dials: dict, extra_rungs: dict) -> list[str]:
    """Compute missing/stale shards. Returns symbols whose shard FAILED
    (unexpected exception) — these block the final results write."""
    shard_dir.mkdir(parents=True, exist_ok=True)
    prov = _provenance(windows, dials, extra_rungs)
    todo = []
    for e in panel:
        f = shard_dir / f"{e['ticker_id']}.json"
        if f.exists():
            try:
                old = json.loads(f.read_text())
                if old.get("provenance") == prov:
                    continue
                print(f"  stale shard (provenance changed): {e['symbol']}")
            except (json.JSONDecodeError, OSError):
                print(f"  unreadable shard: {e['symbol']}")
        todo.append(e)
    print(f"phase A: {len(todo)}/{len(panel)} shards to compute "
          f"({workers} workers)", flush=True)
    failed: list[str] = []
    if not todo:
        return failed
    with ProcessPoolExecutor(max_workers=workers,
                             initializer=_init_worker) as ex:
        futs = {ex.submit(scan_asset, e, windows, dials, extra_rungs): e
                for e in todo}
        done = 0
        for fut in as_completed(futs):
            e = futs[fut]
            try:
                shard = fut.result()
            except Exception as exc:   # record + continue; blocks final write
                print(f"  FAILED {e['symbol']}: {type(exc).__name__}: {exc}",
                      flush=True)
                shard = {"symbol": e["symbol"], "ticker_id": e["ticker_id"],
                         "excluded": f"failed:{type(exc).__name__}",
                         "reason": str(exc)[:300], "records": [],
                         "correlations": {}, "multi_exposure": None,
                         "trim": {}, "alive": e["alive_flag"],
                         "sleeve": e.get("sleeve"), "cell": None,
                         "vol": e.get("vol")}
                failed.append(e["symbol"])
            shard["provenance"] = prov
            (shard_dir / f"{e['ticker_id']}.json").write_text(
                json.dumps(shard))
            done += 1
            if done % 10 == 0 or done == len(todo):
                print(f"  {done}/{len(todo)} shards", flush=True)
    return failed


def run_pregates(panel: list[dict], windows: dict) -> None:
    """Section-3/FIX-12 hard pre-run gates: (a) self-vs-self determinism on a
    gappy name, (b) a crisis-window delta must DIFFER from the full-window
    delta for at least one high-vol name (proves the cache does not collapse
    regimes)."""
    _init_worker()
    hv = max((e for e in panel if e.get("vol")), key=lambda e: e["vol"])
    d1 = scan_asset(hv, {"full": windows["full"], "covid": windows["covid"]},
                    {"sma_crossover": ["fast_period"]}, {})
    d2 = scan_asset(hv, {"full": windows["full"], "covid": windows["covid"]},
                    {"sma_crossover": ["fast_period"]}, {})
    if json.dumps(d1["records"]) != json.dumps(d2["records"]):
        print("PREGATE FAIL: self-vs-self not deterministic")
        sys.exit(4)
    full_d = {(r["base"], r["step"]): r.get("delta") for r in d1["records"]
              if r["w"] == "full" and r["status"] == "ok"}
    cov_d = {(r["base"], r["step"]): r.get("delta") for r in d1["records"]
             if r["w"] == "covid" and r["status"] == "ok"}
    shared = [k for k in full_d if k in cov_d]
    if shared and all(full_d[k] == cov_d[k] for k in shared):
        print("PREGATE FAIL: crisis-window deltas identical to full-window "
              "(FIX-12 regime collapse)")
        sys.exit(4)
    print(f"pregates OK (determinism + regime sensitivity on {hv['symbol']})")


# --------------------------------------------------------------------------- #
# Phase B — deterministic aggregation & selection
# --------------------------------------------------------------------------- #

def _load_shards(panel: list[dict], shard_dir: Path) -> tuple[dict, dict]:
    shards, excluded = {}, {}
    for e in panel:
        f = shard_dir / f"{e['ticker_id']}.json"
        if not f.exists():
            continue
        sh = json.loads(f.read_text())
        if sh.get("excluded"):
            excluded[sh["symbol"]] = sh["excluded"]
        else:
            shards[e["ticker_id"]] = sh
    return shards, excluded


class Tensor:
    """delta[(t,p)][base][window][rung] -> {tid: (delta, degenerate)} plus
    per-asset meta for census/strata work."""

    def __init__(self, shards: dict):
        self.meta = {tid: {"alive": sh["alive"], "cell": sh.get("cell"),
                           "sleeve": sh.get("sleeve"), "vol": sh.get("vol")}
                     for tid, sh in shards.items()}
        self.d: dict = {}
        self.skips: dict = {}
        self.attempted: dict = {}
        for tid, sh in shards.items():
            for r in sh["records"]:
                dial = (r["t"], r["p"])
                self.attempted[dial] = self.attempted.get(dial, 0) + 1
                if r["status"] != "ok":
                    key = (r["status"] if r["status"] != "crashed"
                           else f"crashed:{r.get('exc')}")
                    self.skips.setdefault(dial, {}).setdefault(key, 0)
                    self.skips[dial][key] += 1
                    if r["status"] == "crashed":
                        self.skips[dial]["crashed"] = \
                            self.skips[dial].get("crashed", 0) + 1
                    continue
                if r["step"] == PLUS_ONE_INT and r["w"] != "full":
                    continue
                slot = (self.d.setdefault(dial, {})
                        .setdefault(r["base"], {})
                        .setdefault(r["w"], {})
                        .setdefault(r["rung"] if r["step"] != PLUS_ONE_INT
                                    else PLUS_ONE_INT, {}))
                slot[tid] = (r["delta"], r["degenerate"])

    def curve(self, dial, base, window, subset=None):
        """[(rung, {tid: delta})] for valid non-degenerate readings."""
        out = []
        for rung, readings in sorted(
                self.d.get(dial, {}).get(base, {}).get(window, {}).items(),
                key=lambda kv: (isinstance(kv[0], str), kv[0])):
            if rung == PLUS_ONE_INT:
                continue
            vals = {tid: v for tid, (v, degen) in readings.items()
                    if not degen and (subset is None or tid in subset)}
            out.append((rung, vals))
        return out

    def degen_stats(self, dial, base, window):
        out = {}
        for rung, readings in (self.d.get(dial, {}).get(base, {})
                               .get(window, {})).items():
            if rung == PLUS_ONE_INT:
                continue
            n = len(readings)
            degen = sum(1 for v, dg in readings.values() if dg)
            sat = sum(1 for v, dg in readings.values()
                      if not dg and v >= SAT_CEILING)
            valid = n - degen
            out[str(rung)] = {"n": n, "degenerate": degen,
                              "sat_frac": round(sat / valid, 3) if valid else None}
        return out


def _dq_arr(vals: list[float], q: float) -> float:
    return float(np.percentile(np.array(vals), q * 100))


def _point_curve(curve, q, subset=None):
    """[(rung, D_q, n_valid, sat_frac, strata)] for rungs with >= M_MIN."""
    pts = []
    for rung, vals in curve:
        v = list(vals.values())
        if len(v) < M_MIN:
            continue
        sat = sum(1 for x in v if x >= SAT_CEILING) / len(v)
        pts.append((rung, _dq_arr(v, q), len(v), sat, set(vals)))
    return pts


def _crossing(steps: list[float], dq: list[float], T: float):
    """(value, at_floor): interpolated SUSTAINED crossing; at_floor=True when
    the crossing sits on the finest measured rung (FIX-19 trigger)."""
    idx = None
    for i in range(len(dq)):
        if dq[i] >= T and all(d >= T for d in dq[i:]):
            idx = i
            break
    if idx is None:
        return None, False
    if idx == 0:
        return steps[0], True
    x0, x1, y0, y1 = steps[idx - 1], steps[idx], dq[idx - 1], dq[idx]
    val = x1 if y1 == y0 else x0 + (x1 - x0) * (T - y0) / (y1 - y0)
    return val, False


def _census(tensor: Tensor, tids: set) -> dict:
    cells = {tensor.meta[t]["cell"] for t in tids if tensor.meta[t]["cell"]}
    n_delisted = sum(1 for t in tids if not tensor.meta[t]["alive"])
    return {"living_cells": len(cells), "n_delisted": n_delisted,
            "balanced": len(cells) >= CENSUS_MIN_CELLS
            and n_delisted >= CENSUS_MIN_DELISTED,
            "survivor_calibrated": n_delisted < SURVIVOR_FLAG_BELOW}


def _joint_bootstrap(curves: list, q: float, T: float, rng) -> np.ndarray | None:
    """Joint asset-axis bootstrap over a candidate GROUP (pooled): resample
    the asset union once per iteration and rebuild every rung from the same
    resample — preserves within-asset curve structure (review fix)."""
    rung_map: dict[float, list] = {}
    assets: set = set()
    for member_idx, curve in enumerate(curves):
        for rung, vals in curve:
            rung_map.setdefault(rung, []).append((member_idx, vals))
            assets.update(vals)
    if not rung_map:
        return None
    asset_list = sorted(assets)
    steps = sorted(rung_map)
    if len(steps) < 2:
        return None
    coarsest = steps[-1]
    out = np.empty(BOOT_B)
    for i in range(BOOT_B):
        sample = [asset_list[j] for j in
                  rng.integers(0, len(asset_list), len(asset_list))]
        dq, ss = [], []
        for rung in steps:
            v = []
            for member_idx, vals in rung_map[rung]:
                for tid in sample:
                    if tid in vals:
                        v.append(vals[tid])
            if len(v) >= M_MIN:
                ss.append(rung)
                dq.append(_dq_arr(v, q))
        c, _ = _crossing(ss, dq, T) if len(ss) >= 2 else (None, False)
        out[i] = c if c is not None else coarsest * BOOT_CENSOR_MULT
    return out


def _candidates(tensor: Tensor, dial, kind, bases, q, T, wkeys,
                subset=None) -> list[dict]:
    cands = []
    for base in bases:
        for wkey in wkeys:
            curve = tensor.curve(dial, base, wkey, subset)
            pts = _point_curve(curve, q)
            if len(pts) < 2:
                continue
            steps = [p[0] for p in pts]
            dq = [p[1] for p in pts]
            jnd, at_floor = _crossing(steps, dq, T)
            if jnd is None:
                continue
            i_cross = next(i for i, s in enumerate(steps) if s >= jnd)
            census = _census(tensor, pts[i_cross][4])
            cands.append({
                "base": base, "window": wkey, "jnd": round(jnd, 4),
                "at_floor": at_floor, "n_valid": pts[i_cross][2],
                "sat_ok": pts[i_cross][3] <= SAT_FRAC_MAX,
                "census": census, "curve": curve,
                "eligible": bool(pts[i_cross][3] <= SAT_FRAC_MAX
                                 and pts[i_cross][2] >= M_MIN
                                 and census["balanced"]),
            })
    return cands


def _select(cands: list[dict], q, T, rng) -> dict:
    """FIX-20 pooling CI-separated-min: pool the finest candidates until the
    pooled crossing's bootstrap upper-CI beats the next remaining candidate's
    point estimate (or nothing remains). Deterministic given the rng stream."""
    eligible = sorted([c for c in cands if c["eligible"]],
                      key=lambda c: (c["jnd"], c["window"], str(c["base"])))
    if not eligible:
        return {"jnd": None, "raw_min": None, "separated": None,
                "pooled_members": [], "at_floor": False, "boot": None}
    raw_min = eligible[0]["jnd"]
    group = [eligible[0]]
    rest = eligible[1:]
    while True:
        boots = _joint_bootstrap([c["curve"] for c in group], q, T, rng)
        pts = _point_curve(_pool_curves([c["curve"] for c in group]), q)
        if len(pts) >= 2:
            pjnd, floor = _crossing([p[0] for p in pts], [p[1] for p in pts], T)
        else:
            pjnd, floor = group[0]["jnd"], group[0]["at_floor"]
        if pjnd is None:
            pjnd, floor = group[0]["jnd"], group[0]["at_floor"]
        ci90 = (float(np.percentile(boots, CI_UPPER_PCT))
                if boots is not None else None)
        if not rest or (ci90 is not None and ci90 <= rest[0]["jnd"]):
            return {"jnd": round(pjnd, 4), "raw_min": raw_min,
                    "separated": bool(rest) and len(group) == 1,
                    "pooled_members": [{"base": c["base"], "window": c["window"],
                                        "jnd": c["jnd"]} for c in group],
                    "at_floor": bool(floor or any(c["at_floor"] for c in group)),
                    "boot": boots}
        group.append(rest.pop(0))


def _pool_curves(curves: list) -> list:
    merged: dict[float, dict] = {}
    for member_idx, curve in enumerate(curves):
        for rung, vals in curve:
            slot = merged.setdefault(rung, {})
            for tid, v in vals.items():
                slot[(member_idx, tid)] = v
    return [(rung, merged[rung]) for rung in sorted(merged)]


def _convergence(sel: dict, kind: str) -> dict | None:
    """Section 6: >=90% of resamples on the point rung or finer; coarser in
    >10% = instability."""
    if sel["boot"] is None or sel["jnd"] is None:
        return None
    rungs = sorted(set(RATIOS if kind == "period" else ABS_STEPS[kind]))
    point_rung = next((r for r in rungs if r >= sel["jnd"]), rungs[-1])
    finer_or_point = float((sel["boot"] <= point_rung).mean())
    return {"frac_point_or_finer": round(finer_or_point, 3),
            "stable": finer_or_point >= CONVERGENCE_MIN}


def _strata_subpanel(tensor: Tensor, size: int, rng) -> set:
    groups: dict[str, list] = {}
    for tid, m in tensor.meta.items():
        groups.setdefault(f"{m['sleeve']}|{m['cell']}", []).append(tid)
    total = len(tensor.meta)
    chosen: set = set()
    for gkey in sorted(groups):
        tids = sorted(groups[gkey])
        take = max(1, round(size * len(tids) / total))
        idx = rng.permutation(len(tids))[:take]
        chosen.update(tids[i] for i in idx)
    return chosen


def run_phase_b(panel: list[dict], shard_dir: Path) -> dict:
    shards, excluded = _load_shards(panel, shard_dir)
    print(f"phase B: {len(shards)} shards, {len(excluded)} excluded", flush=True)
    tensor = Tensor(shards)
    rng = np.random.default_rng(BOOT_SEED)

    results = {"grid_version": "v3", "constants": {
        "T": TARGETS, "primary_T": PRIMARY_T, "Q": Q_LADDER,
        "primary_Q": PRIMARY_Q, "M_min": M_MIN, "N_min_active": N_MIN_ACTIVE,
        "degen_roundtrips": DEGEN_ROUNDTRIPS,
        "degen_exposure_IMPL": DEGEN_EXPOSURE, "warmup_k": WARMUP_K,
        "trim_k": TRIM_K, "stale_run": STALE_RUN, "sat_ceiling": SAT_CEILING,
        "sat_frac_max_IMPL": SAT_FRAC_MAX,
        "boot": {"B": BOOT_B, "seed": BOOT_SEED, "ci_upper_pct": CI_UPPER_PCT,
                 "censor_mult_IMPL": BOOT_CENSOR_MULT},
        "census_IMPL": {"min_cells": CENSUS_MIN_CELLS,
                        "min_delisted": CENSUS_MIN_DELISTED,
                        "survivor_flag_below": SURVIVOR_FLAG_BELOW},
        "subsample": {"sizes": SUBSAMPLE_SIZES, "seed_IMPL": SUBSAMPLE_SEED},
        "windows": WINDOWS, "ratios": RATIOS, "abs_steps": ABS_STEPS,
        "constants_hash": _constants_hash(),
        "note_fix15": ("N_min_active=100 => quantum <=1%; at T=0.05 a "
                       "crossing implies >=5 differing bars; T=0.02 "
                       "reported-only"),
        "deferred": ["FIX-11 K-seed JND spread (needs alt-panel shards; "
                     "run as a follow-up stage before transcription)"]},
        "excluded_names": excluded, "dials": {}, "needs_finer": [],
        "ladders": {}, "skips": {}, "curves": {}, "monotonicity": {},
        "correlations": {}, "multi_indicator": {}, "integer_rule": {},
        "subsample_ladder": {}, "crash_rate_violations": []}

    # FIX-13: enforced per-dial crash-rate ceiling with real denominators
    for dial, att in sorted(tensor.attempted.items()):
        key = f"{dial[0]}.{dial[1]}"
        sk = tensor.skips.get(dial, {})
        crashed = sk.get("crashed", 0)
        rate = crashed / att if att else 0.0
        results["skips"][key] = {"attempted": att, "crash_rate": round(rate, 4),
                                 **{k: v for k, v in sorted(sk.items())}}
        unknown = {k.split(":")[0] for k in sk} - SKIP_REASONS
        if unknown:
            results["crash_rate_violations"].append(
                f"{key}: unknown skip reasons {sorted(unknown)}")
        if rate > MAX_CRASH_RATE:
            results["crash_rate_violations"].append(
                f"{key}: crash rate {rate:.3f} > {MAX_CRASH_RATE}")

    for template, dials in PARAMS.items():
        for pname, (kind, low, high, bases) in dials.items():
            dial = (template, pname)
            key = f"{template}.{pname}"
            cands = _candidates(tensor, dial, kind, bases, PRIMARY_Q,
                                PRIMARY_T, REGIME_KEYS)
            sel = _select(cands, PRIMARY_Q, PRIMARY_T, rng)
            conv = _convergence(sel, kind)
            # FIX-25: temporal halves through the same gated machinery;
            # adopt the finer half if it beats the selection by > one rung.
            halves = {}
            for hw in TEMPORAL_KEYS:
                hsel = _select(_candidates(tensor, dial, kind, bases,
                                           PRIMARY_Q, PRIMARY_T, [hw]),
                               PRIMARY_Q, PRIMARY_T, rng)
                halves[hw] = hsel["jnd"]
            adopted_from_half = None
            if sel["jnd"] is not None:
                rungs = sorted(RATIOS if kind == "period"
                               else ABS_STEPS[kind])
                finer_halves = [v for v in halves.values()
                                if v is not None and v < sel["jnd"]]
                if finer_halves:
                    h = min(finer_halves)
                    i_sel = next((i for i, r in enumerate(rungs)
                                  if r >= sel["jnd"]), len(rungs) - 1)
                    i_h = next((i for i, r in enumerate(rungs) if r >= h),
                               len(rungs) - 1)
                    if i_sel - i_h > 1:      # diverges beyond one grid step
                        adopted_from_half = h
            final_jnd = adopted_from_half if adopted_from_half is not None \
                else sel["jnd"]
            at_floor = sel["at_floor"] or any(
                c["at_floor"] for c in cands if c["eligible"])
            if at_floor:
                results["needs_finer"].append(key)
            # FIX-18 monotonicity diagnostic
            mono_bad = mono_n = 0
            for base in bases:
                for wkey in REGIME_KEYS:
                    per_asset: dict[int, list] = {}
                    for rung, vals in tensor.curve(dial, base, wkey):
                        for tid, v in vals.items():
                            per_asset.setdefault(tid, []).append((rung, v))
                    for tid, pts in per_asset.items():
                        if len(pts) < 3:
                            continue
                        mono_n += 1
                        run_max, bad = -1.0, False
                        for _, v in sorted(pts):
                            if v < run_max - MONO_TOL:
                                bad = True
                            run_max = max(run_max, v)
                        mono_bad += bad
            results["monotonicity"][key] = (round(mono_bad / mono_n, 4)
                                            if mono_n else None)
            results["dials"][key] = {
                "kind": kind,
                "jnd": final_jnd,
                "selected": {k: sel[k] for k in ("jnd", "raw_min", "separated",
                                                 "pooled_members", "at_floor")},
                "adopted_from_temporal_half": adopted_from_half,
                "temporal_halves": halves,
                "convergence": conv,
                "candidates": [{k: c[k] for k in ("base", "window", "jnd",
                                                  "at_floor", "n_valid",
                                                  "sat_ok", "eligible")}
                               | {"census": c["census"]} for c in cands],
                "survivor_calibrated": all(
                    c["census"]["survivor_calibrated"] for c in cands
                    if c["eligible"]) if any(c["eligible"] for c in cands)
                else None}
            # FIX-14 per-(base,window,rung) validity reporting
            results["curves"][key] = {
                f"{b}|{w}": tensor.degen_stats(dial, b, w)
                for b in bases for w in REGIME_KEYS + TEMPORAL_KEYS
                if tensor.d.get(dial, {}).get(b, {}).get(w)}
            # FIX-21 ladders (reported-only)
            lad = {}
            for T in TARGETS:
                for q in Q_LADDER:
                    lsel = _select(_candidates(tensor, dial, kind, bases, q, T,
                                               REGIME_KEYS), q, T, rng)
                    lad[f"T{T}_Q{q}"] = lsel["jnd"]
            results["ladders"][key] = lad

    # Section-6 subsample ladder (strata-preserving, seeded)
    srng = np.random.default_rng(SUBSAMPLE_SEED)
    for size in SUBSAMPLE_SIZES:
        if size >= len(tensor.meta):
            continue
        subset = _strata_subpanel(tensor, size, srng)
        row = {}
        sub_rng = np.random.default_rng(BOOT_SEED + size)
        for template, dials in PARAMS.items():
            for pname, (kind, low, high, bases) in dials.items():
                sel = _select(_candidates(tensor, (template, pname), kind,
                                          bases, PRIMARY_Q, PRIMARY_T,
                                          REGIME_KEYS, subset=subset),
                              PRIMARY_Q, PRIMARY_T, sub_rng)
                row[f"{template}.{pname}"] = sel["jnd"]
        results["subsample_ladder"][str(size)] = row

    # FIX-27 rho-bar + section-9 confirmations
    asset_ids = sorted(shards)
    for template in PARAMS:
        vals, mats = [], 0
        for tid in asset_ids:
            fam = shards[tid]["correlations"].get(template)
            if fam:
                m = np.array(fam["matrix"])
                if m.shape[0] >= 2:
                    vals.append(float(np.mean(m[np.triu_indices_from(m, k=1)])))
                    mats += 1
        results["correlations"][template] = {
            "rho_bar_family_mean": round(float(np.mean(vals)), 4) if vals else None,
            "assets_with_matrix": mats}
    expo = [shards[t]["multi_exposure"]["exposure"] for t in asset_ids
            if shards[t].get("multi_exposure")]
    if expo:
        arr = np.array(expo)
        results["multi_indicator"] = {
            "n": len(arr),
            "exposure_lt_2pct_frac": round(float((arr < 0.02).mean()), 4),
            "pass_near_dead": bool((arr < 0.02).mean() >= 0.90),
            "exposure_p50": round(float(np.median(arr)), 5),
            "exposure_p90": round(float(np.percentile(arr, 90)), 5)}
    for template, dials in PARAMS.items():
        for pname, (kind, low, high, bases) in dials.items():
            if kind != "period":
                continue
            key = f"{template}.{pname}"
            jnd = results["dials"][key]["jnd"]
            per_base = {str(b): bool(jnd is not None and b * jnd < 1)
                        for b in bases}
            gov = results["dials"][key]["selected"]["pooled_members"]
            gov_bases = {str(m["base"]) for m in gov}
            emp = {}
            for base in bases:
                readings = (tensor.d.get((template, pname), {})
                            .get(base, {}).get("full", {}).get(PLUS_ONE_INT))
                if readings:
                    v = [x for x, dg in readings.values() if not dg]
                    if len(v) >= M_MIN:
                        emp[str(base)] = round(_dq_arr(v, PRIMARY_Q), 4)
            results["integer_rule"][key] = {
                "analytic_per_base": per_base,
                "governing_bases": sorted(gov_bases),
                "analytic_integer_governed": bool(
                    jnd is not None and any(per_base[b] for b in gov_bases
                                            if b in per_base)),
                "plus1int_D085_by_base": emp,
                "empirical_confirms": {b: bool(v >= PRIMARY_T)
                                       for b, v in emp.items()}}

    t_bars = 6000
    v_null = 1.0 / t_bars
    results["sr0_reference_curve"] = {
        "V": v_null, "T_bars": t_bars,
        "curve": {str(n): round(_sr0(n, v_null), 5)
                  for n in (100, 300, 1000, 3000, 10000, 30000, 100000)},
        "note": ("diagnostic only; wiring uses the PF4 conservative V_null "
                 "and reachable_cells after transcription")}
    return results


def _sr0(n_trials: int, variance: float) -> float:
    import scipy.stats
    gamma = 0.5772156649015329
    z = scipy.stats.norm.ppf
    return math.sqrt(variance) * ((1 - gamma) * z(1 - 1.0 / n_trials)
                                  + gamma * z(1 - 1.0 / (n_trials * math.e)))


# --------------------------------------------------------------------------- #
# FIX-11 K-seed stage — cross-panel-draw stability of the frozen JNDs
# --------------------------------------------------------------------------- #

def build_alt_panel(sleeves: dict, frame: dict, cutpoints: dict) -> list[dict]:
    """Reconstruct full panel entries for one alt-seed draw from the committed
    freeze artifacts (the altseeds file carries symbol lists only; the frame
    snapshot supplies vol/cap features; cutpoints supply the cell buckets)."""
    by_symbol = {}
    for pool_name, names in frame["pools"].items():
        for n in names:
            by_symbol[n["symbol"]] = (pool_name, n)
    t1, t2 = cutpoints["cap_tertiles_combined"]
    vmed = cutpoints["vol_median_combined"]
    entries = []
    for sleeve, syms in sleeves.items():
        if not isinstance(syms, list):
            continue   # _fix1_exclusions counter
        for sym in syms:
            pool, n = by_symbol[sym]
            alive = pool == "living"
            cap = n.get("median_pit_cap")
            entries.append({
                "ticker_id": n["ticker_id"], "symbol": sym,
                "alive_flag": alive, "sleeve": sleeve, "vol": n["vol"],
                "cap_bucket": (None if not alive or cap is None else
                               "small" if cap <= t1 else
                               "mid" if cap <= t2 else "large_liquid"),
                "vol_bucket": (None if not alive else
                               "high" if n["vol"] >= vmed else "low"),
            })
    return entries


def kseed_select(entries: list[dict], shard_dir: Path) -> dict:
    """Per-dial CI-separated-min selection on ONE alt panel (fresh rng per
    panel; the temporal-half adoption branch was inert on the primary and is
    omitted here — noted in the artifact)."""
    shards, excluded = _load_shards(entries, shard_dir)
    tensor = Tensor(shards)
    rng = np.random.default_rng(BOOT_SEED)
    out = {}
    for template, dials in PARAMS.items():
        for pname, (kind, low, high, bases) in dials.items():
            sel = _select(_candidates(tensor, (template, pname), kind, bases,
                                      PRIMARY_Q, PRIMARY_T, REGIME_KEYS),
                          PRIMARY_Q, PRIMARY_T, rng)
            out[f"{template}.{pname}"] = sel["jnd"]
    return out


def run_kseed(workers: int) -> None:
    if KSEED_PATH.exists():
        print(f"REFUSED: {KSEED_PATH.name} already exists (write-once).")
        sys.exit(3)
    results = json.loads(OUT_PATH.read_text())
    frame = json.loads(FRAME_PATH.read_text())
    alts = json.loads(ALTSEED_PATH.read_text())
    cutpoints = json.loads(PANEL_PATH.read_text())["cutpoints"]
    extra = results["extra_rungs"]
    dials = {t: sorted(p) for t, p in PARAMS.items()}
    shard_dir = SHARD_ROOT / "full"

    kout = {"note": ("FIX-11 draw-level stability: per-dial JND re-derived on "
                     "the 4 alternate panel draws with the primary's frozen "
                     "sweep (same windows/dials/extra rungs; shards shared). "
                     "Bootstrap draws use a fresh stream per panel, so this "
                     "checks stability, not byte-reproduction; the primary "
                     "row is the frozen artifact value. Temporal-half "
                     "adoption omitted (inert on the primary)."),
            "seeds": {"20230701":
                      {k: d["jnd"] for k, d in results["dials"].items()}},
            "spread": {}}
    for seed_str, sleeves in sorted(alts.items()):
        entries = build_alt_panel(sleeves, frame, cutpoints)
        print(f"kseed {seed_str}: {len(entries)} names")
        failed = run_phase_a(entries, workers, shard_dir, WINDOWS, dials, extra)
        if failed:
            print(f"REFUSING kseed write: failed shards {failed}")
            sys.exit(4)
        kout["seeds"][seed_str] = kseed_select(entries, shard_dir)

    # Spread verdict: per dial, JNDs across the 5 seeds mapped to rung indices
    # of the frozen sweep; PASS = max-min <= 1 rung (section-6 tolerance).
    for key in kout["seeds"]["20230701"]:
        t, p = key.split(".")
        kind = PARAMS[t][p][0]
        rungs = sorted(set((RATIOS if kind == "period" else ABS_STEPS[kind])
                           + extra.get(key, [])))
        vals = [kout["seeds"][s].get(key) for s in kout["seeds"]]
        if any(v is None for v in vals):
            kout["spread"][key] = {"values": vals, "verdict": "UNDEFINED"}
            continue
        idxs = [next((i for i, r in enumerate(rungs) if r >= v - 1e-9),
                     len(rungs) - 1) for v in vals]
        kout["spread"][key] = {
            "values": vals, "rung_indices": idxs,
            "spread_rungs": max(idxs) - min(idxs),
            "verdict": "STABLE" if max(idxs) - min(idxs) <= 1 else "UNSTABLE"}
    KSEED_PATH.write_text(json.dumps(kout, indent=1, sort_keys=True))
    n_unstable = sum(1 for v in kout["spread"].values()
                     if v["verdict"] == "UNSTABLE")
    print(f"wrote {KSEED_PATH.name}: "
          f"{len(kout['spread']) - n_unstable}/{len(kout['spread'])} dials "
          f"STABLE across the 5 panel draws")


def main():
    os.environ["TQDM_DISABLE"] = "1"
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int,
                    default=max(2, (os.cpu_count() or 8) - 2))
    ap.add_argument("--phase", choices=("all", "a", "b"), default="all")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--extend-rounds", type=int, default=3,
                    help="max FIX-19 extend-finer re-measure rounds")
    ap.add_argument("--accept-crash-rate", action="store_true",
                    help="write results despite a crash-rate violation "
                         "(records the override in the artifact)")
    ap.add_argument("--kseed", action="store_true",
                    help="FIX-11 stage: re-derive JNDs on the 4 alternate "
                         "panel draws and report the cross-seed spread")
    args = ap.parse_args()

    if args.kseed:
        run_kseed(args.workers)
        return

    manifest = json.loads(PANEL_PATH.read_text())
    panel = manifest["panel"]
    blob = json.dumps(panel, sort_keys=True, separators=(",", ":")).encode()
    if hashlib.sha256(blob).hexdigest() != manifest["panel_sha256"]:
        print("FATAL: panel content does not match its committed sha256")
        sys.exit(2)

    windows = dict(WINDOWS)
    dials = {t: sorted(p) for t, p in PARAMS.items()}
    shard_dir = SHARD_ROOT / ("smoke" if args.smoke else "full")
    if args.smoke:
        panel = panel[:3]
        dials = {"sma_crossover": ["fast_period"],
                 "rsi_reversion": ["period"]}
        windows = {k: WINDOWS[k] for k in ("full", "covid")}
        global REGIME_KEYS, TEMPORAL_KEYS
        REGIME_KEYS = ["full", "covid"]
        TEMPORAL_KEYS = []

    extra_rungs: dict[str, list] = {}
    failed: list[str] = []
    if args.phase in ("all", "a"):
        if not args.smoke:
            run_pregates(panel, windows)
        failed = run_phase_a(panel, args.workers, shard_dir, windows, dials,
                             extra_rungs)
    if args.phase == "a":
        return

    results = run_phase_b(panel, shard_dir)
    # FIX-19: executable extend-finer loop — prepend finer rungs for the
    # bottomed-out dials, re-measure just those dials, re-aggregate.
    rounds = 0
    while results["needs_finer"] and rounds < args.extend_rounds \
            and args.phase == "all":
        rounds += 1
        print(f"FIX-19 round {rounds}: extending finer for "
              f"{results['needs_finer']}", flush=True)
        redo = {}
        for key in results["needs_finer"]:
            t, p = key.split(".")
            kind = PARAMS[t][p][0]
            cur = extra_rungs.get(key, [])
            nxt = [r for r in EXTEND_FINER[kind] if r not in cur]
            if not nxt:
                print(f"  {key}: EXTEND_FINER exhausted — report stands")
                continue
            extra_rungs[key] = sorted(cur + nxt)
            redo.setdefault(t, set()).add(p)
        if not redo:
            break
        # Recompute FULL shards (all dials) with the extended rung set — a
        # partial-dials pass would overwrite shards with partial records and
        # destroy every other dial's measurements (caught live 2026-07-17).
        failed += run_phase_a(panel, args.workers, shard_dir, windows, dials,
                              extra_rungs)
        results = run_phase_b(panel, shard_dir)
    results["extend_finer_rounds"] = rounds
    results["extra_rungs"] = extra_rungs

    if failed:
        print(f"REFUSING final write: {len(failed)} shards FAILED with "
              f"non-enumerated exceptions: {failed}")
        sys.exit(4)
    if results["crash_rate_violations"] and not args.accept_crash_rate:
        print("REFUSING final write (FIX-13): "
              f"{results['crash_rate_violations']}\n"
              "Investigate; --accept-crash-rate records an explicit override.")
        sys.exit(4)
    results["crash_rate_override"] = bool(results["crash_rate_violations"]
                                          and args.accept_crash_rate)

    out = (shard_dir / "smoke-results.json") if args.smoke else OUT_PATH
    if not args.smoke and out.exists():
        print(f"REFUSED: {out.name} already exists (write-once, FIX-32).")
        sys.exit(3)
    blob = json.dumps(results, indent=1, sort_keys=True)
    out.write_text(blob)
    print(f"wrote {out} sha256="
          f"{hashlib.sha256(blob.encode()).hexdigest()[:16]}...")
    if results["needs_finer"]:
        print(f"NOTE: dials still at the finest rung after {rounds} extend "
              f"rounds: {results['needs_finer']} — protocol section 12 / "
              "FIX-19: do NOT transcribe these without further extension.")


if __name__ == "__main__":
    main()
