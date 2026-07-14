"""Noise-floor (C2) + warmup-contamination (C4) validation of the coverage grid.

Committed for provenance alongside scripts/calibrate_coverage_grid.py. Run:

    PYTHONPATH=. BROKER_MODE=mock python scripts/validate_grid_noise.py

C2 — is T=0.05 safely above the noise floor, or do integers govern the fine period cells?
  (a) DETERMINISM: same (template, params, asset) run twice → position disagreement must be exactly 0.
  (b) MIN-STEP FLOOR: disagreement of the SMALLEST realizable step (±1 integer for periods, ±1 RSI pt for
      thresholds, ±0.1 for std_dev) at low/mid/high base. If that floor already ≥ T=0.05, the calibrated log
      ratio r is cosmetic there and the INTEGER sets the resolution (→ integer-governed; see coverage.py
      _INTEGER_PERIOD). Analytic cross-check: a period's r-implied step is base*r integers; base*r < 1 ⇒ int.

C4 — warmup contamination: re-measure a long-period step discarding max(period) warmup bars vs warmup_bars=0.

RESULT (2026-07-14, GRID_VERSION v2): determinism = 0.0; C4 warmup Δ ≤ 0.001 (non-issue — union-in-market
already excludes the flat warmup). C2: sma/macd periods ratio-governed (floor ≪ T); RSI period is
INTEGER-GOVERNED at every base (+1-int flips 11-23% of positions) → applied one-cell-per-integer for
(rsi_reversion, period) and (multi_indicator, rsi_period). Bollinger period is mixed (integer-governed low
end, ratio high end) and its log r=0.06 + integer-collapse approximates that adequately.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

from src.backend.ai.research import coverage as cov
from src.backend.ai.research.executor import _ensure_registry
from src.backend.ai.research.run import _default_fetch
from src.backend.ai.research.strategist import WINDOW_END, WINDOW_START
from src.backend.backtesting.engine.runner import BacktestConfig, run_backtest

REG = _ensure_registry()
ASSETS = ["AAPL", "MSFT", "NVDA", "KO", "PG", "SPY"]
T = 0.05
CANON = {
    "sma_crossover": {"fast_period": 15, "slow_period": 100},
    "rsi_reversion": {"period": 14, "buy_threshold": 30.0, "sell_threshold": 70.0},
    "bollinger_breakout": {"period": 20, "std_dev": 2.0},
    "macd_cross": {"fast": 12, "slow": 26, "signal_period": 9},
    "multi_indicator": {"sma_period": 30, "rsi_period": 14, "rsi_buy": 30.0, "rsi_sell": 70.0},
}
PERIODS = [
    ("sma_crossover", "fast_period", 50, [6, 12, 25, 45]),
    ("sma_crossover", "slow_period", 200, [22, 45, 100, 180]),
    ("rsi_reversion", "period", 30, [6, 10, 18, 28]),
    ("bollinger_breakout", "period", 50, [11, 18, 30, 46]),
    ("macd_cross", "slow", 50, [27, 33, 42, 49]),
]
_data: dict = {}


def positions(template, params, sym, warmup=0):
    data = _data[sym]
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
    return p[warmup:] if warmup else p


def disag(p1, p2):
    n = min(len(p1), len(p2))
    a, b = p1[:n], p2[:n]
    act = (a != 0) | (b != 0)
    return None if act.sum() < 20 else float((a != b).sum() / act.sum())


def med_step(template, others, pname, base, step, warmup=0):
    v = [disag(positions(template, {**others, pname: base}, s, warmup),
              positions(template, {**others, pname: round(base + step, 2)}, s, warmup)) for s in _data]
    v = [x for x in v if x is not None]
    return round(float(np.median(v)), 3) if v else None


def main():
    for s in ASSETS:
        _data[s] = _default_fetch(s, WINDOW_START, WINDOW_END)
    print("assets:", list(_data), "\n")

    d = disag(positions("sma_crossover", {"fast_period": 15, "slow_period": 100}, "AAPL"),
              positions("sma_crossover", {"fast_period": 15, "slow_period": 100}, "AAPL"))
    print(f"C2(a) DETERMINISM: self-vs-self = {d} (must be 0.0)\n")

    print(f"C2(b) PERIOD min-step floor (+1 integer) vs T={T}:")
    print(f"  {'template.param':28} {'base':>4} {'r/mode':>8} {'base*r':>7} {'+1 disagree':>11}  governed")
    for template, pname, high, bases in PERIODS:
        mode = cov._mode(template, pname)
        r = cov._res(template, pname) if mode == "log" else None
        others = {k: v for k, v in CANON[template].items() if k != pname}
        for base in bases:
            if base + 1 > high:
                continue
            dd = med_step(template, others, pname, base, 1)
            br = f"{base * r:.2f}" if r else "int"
            gov = "INTEGER" if (r is None or base * r < 1 or (dd or 0) >= T) else "ratio r"
            print(f"  {template + '.' + pname:28} {base:>4} {str(round(r,2) if r else mode):>8} {br:>7} "
                  f"{str(dd):>11}  {gov}")
    print()
    print("C4 WARMUP contamination (long-period +1-int step, warmup 0 vs 2*period discarded):")
    for template, pname, base, per, others in [("sma_crossover", "slow_period", 100, 100, {"fast_period": 15}),
                                               ("bollinger_breakout", "period", 30, 30, {"std_dev": 2.0}),
                                               ("macd_cross", "slow", 42, 42, {"fast": 12, "signal_period": 9})]:
        d0 = med_step(template, others, pname, base, 1, warmup=0)
        dw = med_step(template, others, pname, base, 1, warmup=per * 2)
        print(f"  {template + '.' + pname:28} base={base}: warmup0={d0} discard={dw} delta={round((d0 or 0) - (dw or 0), 3)}")


if __name__ == "__main__":
    main()
