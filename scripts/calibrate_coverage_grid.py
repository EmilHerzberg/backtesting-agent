"""Signal-flip grid calibration — the reproducible source for the coverage-memory grid (GRID_VERSION="v2").

Committed for provenance (a pre-registered multiple-testing N must be re-derivable). Run:

    PYTHONPATH=. BROKER_MODE=mock python scripts/calibrate_coverage_grid.py

Writes the raw per-asset disagreement curves + per-parameter JNDs to
docs/design/calibration-v2-results.json (the versioned artifact behind
docs/design/COVERAGE-CALIBRATION.md). Requires network (yfinance) for the 6 assets.

Grounds each parameter's just-noticeable-difference (JND) in WHEN A CHANGE ACTUALLY CHANGES THE STRATEGY'S
BEHAVIOUR, on the REAL backtest engine. Metric = POSITION-STATE disagreement: reconstruct the discrete
held-position vector (long/flat/short) from each setting's trades and measure the fraction of bars where two
settings hold a DIFFERENT state, normalised by the bars where at least one is in-market. (Return-magnitude
disagreement was rejected — it saturates at ~1.0 because share-count/entry-price noise makes P&L differ even
when both settings are simply 'long'; the discrete state is the true signal.)

KNOWN LIMITATIONS (see the quant review + COVERAGE-CALIBRATION.md §Limitations): one metric, one primary
T=0.05 (no noise-floor validation), 6 assets, one window (in-sample), warmup_bars=0, and multi_indicator
under-trades so its params fall back to indicator analogs. These are acceptable for SIZING THE SAMPLER GRID;
they must be tightened before the feasible-cell count becomes the deflated-Sharpe N (v2 — see
docs/design/COVERAGE-MEMORY-V2-PLAN.md).
"""
from __future__ import annotations
import json
import os
import statistics

import numpy as np
import pandas as pd

from src.backend.ai.research.executor import _ensure_registry
from src.backend.ai.research.run import _default_fetch
from src.backend.ai.research.strategist import WINDOW_END, WINDOW_START
from src.backend.backtesting.engine.runner import BacktestConfig, run_backtest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(_REPO, "docs", "design", "calibration-v2-results.json")
ASSETS = ["AAPL", "MSFT", "NVDA", "KO", "PG", "SPY"]   # trending tech + mean-reverting staples + index
TARGETS = (0.02, 0.05, 0.10)                            # disagreement targets (T); 0.05 primary
REG = _ensure_registry()

CANON = {
    "sma_crossover": {"fast_period": 15, "slow_period": 100},
    "rsi_reversion": {"period": 14, "buy_threshold": 30.0, "sell_threshold": 70.0},
    "bollinger_breakout": {"period": 20, "std_dev": 2.0},
    "macd_cross": {"fast": 12, "slow": 26, "signal_period": 9},
    "multi_indicator": {"sma_period": 30, "rsi_period": 14, "rsi_buy": 30.0, "rsi_sell": 70.0},
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
    "multi_indicator": {"sma_period": ("period", 20, 50, [24, 35, 46]),
                        "rsi_period": ("period", 10, 20, [12, 15, 19]),
                        "rsi_buy": ("threshold", 15, 40, [20, 33]),
                        "rsi_sell": ("threshold", 60, 85, [65, 80])},
}
RATIOS = [0.05, 0.08, 0.12, 0.16, 0.20, 0.25, 0.30, 0.40, 0.50]
ABS_STEPS = {"threshold": [1, 2, 3, 4, 5, 7, 10], "multiplier": [0.1, 0.2, 0.3, 0.5, 0.75, 1.0]}

_data: dict[str, object] = {}
_cache: dict[tuple, np.ndarray] = {}


def positions_of(template, params, sym):
    key = (template, sym, tuple(sorted((k, round(float(v), 4)) for k, v in params.items())))
    if key in _cache:
        return _cache[key]
    data = _data[sym]
    try:
        cls = REG[template].create_with_params(**{k: (int(v) if float(v).is_integer() else float(v))
                                                   for k, v in params.items()})
        cfg = BacktestConfig(symbol=sym, strategy_class=cls, data=data, cash=10_000.0, commission=0.0,
                             exclusive_orders=True, trade_on_close=False, warmup_bars=0)
        res = run_backtest(cfg)
        ts = pd.DatetimeIndex(data.index).values
        p = np.zeros(len(data), dtype=np.int8)
        for t in (res.trades or []):
            side = 1 if str(getattr(t, "side", "long")).lower() == "long" else -1
            e = np.datetime64(pd.Timestamp(t.entry_time))
            x = np.datetime64(pd.Timestamp(t.exit_time))
            p[(ts >= e) & (ts < x)] = side
    except Exception:
        p = np.zeros(0, dtype=np.int8)
    _cache[key] = p
    return p


def disagreement(p1, p2):
    n = min(len(p1), len(p2))
    if n < 50:
        return None
    a, b = p1[:n], p2[:n]
    active = (a != 0) | (b != 0)
    if active.sum() < 20:
        return None
    return float((a != b).sum() / active.sum())


def mean_disagree(template, base_params, stepped_params):
    vals = []
    for sym in _data:
        d = disagreement(positions_of(template, base_params, sym), positions_of(template, stepped_params, sym))
        if d is not None:
            vals.append(d)
    return statistics.median(vals) if vals else None


def jnd_for(template, pname, kind, low, high, bases, is_int):
    others = {k: v for k, v in CANON[template].items() if k != pname}
    per_base = []
    for base in bases:
        curve = []
        if kind == "period":
            for r in RATIOS:
                stepped = round(base * (1 + r))
                if stepped > high or stepped == base:
                    continue
                md = mean_disagree(template, {**others, pname: base}, {**others, pname: stepped})
                if md is not None:
                    curve.append((r, md))
        else:
            for dstep in ABS_STEPS[kind]:
                stepped = round(base + dstep, 2)
                if stepped > high:
                    continue
                sp = int(stepped) if is_int else stepped
                md = mean_disagree(template, {**others, pname: base}, {**others, pname: sp})
                if md is not None:
                    curve.append((dstep, md))
        jnds = {str(T): next((s for s, d in curve if d >= T), None) for T in TARGETS}
        per_base.append({"base": base, "curve": [(round(s, 3), round(d, 3)) for s, d in curve], "jnd": jnds})
    return per_base


def main():
    for sym in ASSETS:
        try:
            _data[sym] = _default_fetch(sym, WINDOW_START, WINDOW_END)
            print(f"fetched {sym}: {len(_data[sym])} bars", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"skip {sym}: {e}", flush=True)
    print(f"\nassets loaded: {list(_data)}\n", flush=True)

    results = {}
    for template, params in PARAMS.items():
        results[template] = {}
        for pname, (kind, low, high, bases) in params.items():
            is_int = kind == "period" or pname == "period"
            pb = jnd_for(template, pname, kind, low, high, bases, is_int)
            results[template][pname] = {"kind": kind, "per_base": pb}
            j05 = [b["jnd"]["0.05"] for b in pb if b["jnd"]["0.05"] is not None]
            med = round(statistics.median(j05), 3) if j05 else None
            print(f"[{template:18} {pname:14} {kind:10}] JND@0.05 median={med}  "
                  f"per-base={[b['jnd']['0.05'] for b in pb]}", flush=True)
        with open(OUT, "w") as f:
            json.dump(results, f, indent=2)
    print(f"\nDONE -> {OUT}")


if __name__ == "__main__":
    main()
