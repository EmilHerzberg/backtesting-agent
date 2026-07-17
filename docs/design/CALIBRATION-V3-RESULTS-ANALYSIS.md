# Calibration V3 — Results Analysis (2026-07-17)

**Artifact:** `calibration-v3-results.json` (sha256 `d37c802f2b9e35fd…`, write-once).
**Run:** 211-name frozen panel × 8 windows, 8 workers, pregates PASS, 2 extend-finer
rounds, zero crashes / zero excluded names / zero crash-rate violations.

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

## Open freeze decision (owner) before transcription

The floored NON-integer dials (buy/sell thresholds at 0.5, std_dev at 0.05)
violate FIX-19's letter ("a bottomed-out sweep can never be accepted as
fine-enough"). Options:
- **(A, recommended)** Freeze 0.5 pts / 0.05 as the grid steps — they equal the
  practical proposal quantum of the strategist, the residual within-cell
  correlation is exactly what the measured-ρ̄ effective-N absorbs, and the
  alternative only moves sr0 by a few percent. Record as amendment AM-9.
- **(B)** One more extension round beyond the §12 prepends (0.25 pts / 0.025
  mult, ~15 min compute) to locate the true floor first; also an amendment
  (the §12 EXTEND_FINER sets are exhausted).

Deferred stage (recorded in the artifact): FIX-11 K-seed JND spread across the
alternate panels — run before transcription finalizes.
