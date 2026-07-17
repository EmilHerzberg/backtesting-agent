# Calibration V3 — Results Analysis (2026-07-17)

**Final artifact (post-AM-9):** `calibration-v3-results.json` (sha256
`68f6bbe9d38d8aab…`, write-once). First-run artifact superseded and retained as
`calibration-v3-results-superseded-preAM9.json` (sha `d37c802f…`).
**Runs:** 211-name frozen panel × 8 windows, 8 workers, pregates PASS, zero
crashes / zero excluded names / zero crash-rate violations in both runs.

## FINAL FROZEN GRID (AM-10) — the numbers that transcribe into coverage.py v3

| dial | frozen step | basis |
|---|---|---|
| sma_crossover.fast_period | ratio **0.0357** | measured interior, CI-separated |
| sma_crossover.slow_period | ratio **0.02** | integer quantum at governing base 30 (FIX-31 mixed) |
| rsi_reversion.period | **one cell per integer** | integer-governed, all bases |
| rsi_reversion.buy_threshold | **0.25 pts** | SCALE_FREE_TAIL (AM-10) |
| rsi_reversion.sell_threshold | **0.3996 pts** | measured interior (AM-9 found it below 0.5) |
| bollinger_breakout.period | **one cell per integer** | integer-governed, all bases (NEW vs v2) |
| bollinger_breakout.std_dev | **0.025** | SCALE_FREE_TAIL (AM-10) |
| macd_cross.fast | ratio **0.0896** | measured interior, CI-separated |
| macd_cross.signal_period | ratio **0.1089** | measured interior |
| macd_cross.slow | ratio **0.1518** | measured interior |

**AM-9 verdict on the extension question:** sell_threshold had a real floor
(0.3996 — the first-run 0.5 was ~25% too coarse; the extension paid for
itself). buy_threshold and std_dev are **scale-free** — the whole Q-ladder
(Q0.75–Q0.95) sits at every floor we sweep, so further extension is a
measurably endless regress; frozen at the finest still-crossing rung per
AM-10 with residual sub-cell distinctness absorbed by the measured-ρ̄
effective-N reduction.

## Headline per-dial JNDs (T=0.05, Q=0.85, CI-separated-min over bases × regimes)

| dial | JND | status | interpretation |
|---|---|---|---|
| sma_crossover.fast_period | **0.0357** (ratio) | interior, separated | healthy ratio grid |
| sma_crossover.slow_period | 0.02 (ratio) | AT FLOOR = +1 int at base 30 | mixed integer/ratio (FIX-31) |
| rsi_reversion.period | 0.02 (ratio) | AT FLOOR = +1 int at base 25 | **integer-governed** (analytic: all bases) |
| rsi_reversion.buy_threshold | 0.5 pts | AT extended FLOOR | real tail sensitivity; 0.5 = proposal quantum |
| rsi_reversion.sell_threshold | 0.5 pts | AT extended FLOOR | ditto (other windows 0.52–1.17) |
| bollinger_breakout.period | 0.02 (ratio) | AT FLOOR = +1 int at base 25 | **integer-governed** (analytic: all bases) |
| bollinger_breakout.std_dev | 0.05 | AT extended FLOOR | real tail sensitivity |
| macd_cross.fast | **0.0896** | interior, separated | healthy |
| macd_cross.signal_period | **0.1089** | interior | healthy |
| macd_cross.slow | **0.1505** | interior | healthy |

## Why "8 dials at the finest rung" is NOT vacuity

1. **Period dials:** the winning candidates sit at rung 0.02 ≈ exactly ONE INTEGER
   of period change at the sensitive base (25×1.02→26; 30×1.02→31). Integers
   cannot subdivide — the floor is the integer quantum, not a measurement
   failure. The FIX-31 analytic rule (base×r<1) confirms: rsi period and
   bollinger period integer-governed at every base; sma slow / macd only at the
   small bases (+1-int D0.85 at large bases ≈ 0.007 ≪ T → NOT integer-governed
   there).
2. **Thresholds / std_dev:** genuinely pinned at the extended rung (0.5 pts /
   0.05) by the conservative Q=0.85 name — a converged, non-saturated,
   CI-separated, 205-valid-asset measurement, stable across the subsample
   ladder. The 85th-percentile name flips ≥5% of in-market days on a half-point
   RSI-threshold change.

## Stability evidence (section 6)

- Bootstrap convergence 0.948–1.0 (all ≥0.90 → stable) on every dial.
- Subsample ladder: JNDs unchanged from n≈75 up; 125→150 identical ⇒ the
  stopping rule is satisfied with margin — 211 names were enough.
- survivor_calibrated = False everywhere (delisted names well-represented in
  every setting cell).
- Monotonicity: ≤3.8% non-monotone curves everywhere except
  bollinger_breakout.period (18.7% — noisiest dial; the sustained-crossing +
  integer-governance resolution makes this moot for the grid).
- multi_indicator: 99.5% of names < 2% exposure at CANON → near-dead CONFIRMED
  (stays `_UNCALIBRATED`, excluded from N).
- Family return correlations (FIX-27): ρ̄ 0.75–0.95 per template — the ONC
  effective-N reduction downstream will have real, measured bite.

## vs the shipped v2 grid

Every axis is finer than v2 assumed: thresholds 2 pts → 0.5 pts (4×),
std_dev 0.15 → 0.05 (3×), sma/macd ratios 0.06–0.30 → 0.036–0.15 (~2×),
rsi/bollinger periods → one-cell-per-integer. N grows accordingly (stricter
DSR bar = the safe direction), with the measured ρ̄ feeding the effective-N
reduction so the bar stays honest rather than vacuous (sr0 ∝ √(2·ln N) —
weak lever, FIX-30 curve committed in the results).

## Freeze decision — RESOLVED (owner chose extension; AM-9 + AM-10)

The owner chose option B (extend finer before freezing). Outcome: sell_threshold
found its true interior floor (0.3996); buy_threshold and std_dev proved
SCALE-FREE (whole Q-ladder at every swept floor) and are frozen at the finest
measured rung (0.25 / 0.025) per AM-10. The first-run section below is retained
for provenance; the FINAL FROZEN GRID table above supersedes it.

Remaining before transcription: FIX-11 K-seed JND spread across the alternate
panels (recorded as the deferred stage in the artifact).
