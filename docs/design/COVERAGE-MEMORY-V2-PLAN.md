# Coverage Memory v2 — the cross-run multiple-testing correction (design prerequisites)

**Status:** design only — NOT built. This records the **quant/statistics review verdict (2026-07-14)** on
whether the calibrated grid is sound to become the deflated-Sharpe (DSR) multiple-testing N, and the
**minimal correct recipe** the review requires before any code wires `feasible_cells` into the significance
path. (v1 is unaffected — flag OFF, AT-7 keeps the significance path coverage-blind.)

## Review verdict
- **v1 is sound.** The grid math is functionally correct (log binning, cell centers, integer-collapse,
  dead-corner, maximin — all verified numerically; counts reproduce exactly). The metric choice
  (position-state, rejecting return-magnitude) is right for its shipped purpose: sizing where the sampler digs.
- **The naive v2 plan (feed raw `len(feasible_cells)` in as N, keep per-run V) is NOT sound.** Five blockers
  below. The *core idea* — a grid-derived, pre-registered N as a conservative multiple-testing bound — is
  salvageable at the narrow per-(template, asset) scope, but only with the recipe below.

## Blockers (must be resolved in the v2 design)

**B1 — Full-grid N vs realized-search N.** DSR's N is the number of trials the winner was selected *from*.
`len(feasible_cells)` is the size of the whole searchable space; the docs themselves say coverage % stays low.
Feeding 11,830 when a campaign visited ~100 over-inflates the hurdle `sr0` by ~54% (3.90 vs 2.53) → the gate
rejects everything (vacuous). **Fix:** N = the *realized* cumulative cross-run **visited**-cell count (capped at
the pre-registered grid total), OR an explicitly-labelled deliberately-conservative worst-case bound — never a
silent full-grid count.

**B2 — Scope of selection.** `feasible_cells` is per-template, but a cross-run campaign cherry-picks across
assets, templates and runs. Honest N = the cardinality of the *actual selection set* the max was taken over
(cross-asset → ×n_assets; cross-template → Σ over templates; cross-run → distinct visited cells). A single
per-template count **under**-counts N in exactly the cross-run cherry-pick scenario the feature exists to fix —
the *anti-conservative (unsafe)* direction. **Fix:** derive N from the pre-registered selection scope; never let
N be narrower than the scope over which the reported winner was chosen.

**B3 — Co-scope V with N (blocker).** `sr0 = sqrt(V)·f(N)` is the expected max of N draws *from one null
population*. The plan swaps N to the grid count but keeps V = variance of *this run's* handful of period-Sharpes
(loop.py `_dsr_registry_inputs`). Pairing a full-grid N with a small, loop-selected subset V is internally
inconsistent — the safe-direction guarantee evaporates and the error sign becomes indeterminate (can flip
anti-conservative). The existing code deliberately co-scopes N and V. **Fix:** use the **theoretical null
V ≈ 1/T** (variance of a zero-skill per-period Sharpe over T bars) — needs *no stored performance*, so it
**preserves v1's overfitting-neutral firewall** — or persist per-trial period-Sharpes in a firewalled table used
only to estimate V over the same pool that defines N. Never pair full-grid N with per-run V.

**B4 — Split `n_trials` (it is dual-purpose).** In the gate, `n_trials` is both the multiplicity size (via
`sr0`) *and* the sample-adequacy guard (`<2` → auto-pass; `<PROVISIONAL_BELOW=20` → provisional). Swapping in a
grid count (always ≫20) defeats the provisional valve — a run that executed 3 real backtests would report a
*firm* grid-size FAIL. **Fix:** decouple — a realized-executed-trials counter drives the provisional/auto-pass
guard; a separate `search_size` N enters only `sr0`.

**B5 — Correlated cells ≠ independent trials (direction + magnitude).** Adjacent cells are ~1 JND apart (~5% of
days differ) → their Sharpes correlate ~0.9+. The raw cell count therefore **over-states** the independent N.
Plugged into the iid expected-max formula this raises `sr0` → deflates DSR → **over-rejects** = Type-I↓/Type-II↑
= the *safe* direction for a falsification engine. So raw cell-count is acceptable as a **conservative upper
bound** — but the over-correction grows like √(ln N), so it can make the gate vacuous. **Fix:** document it as an
upper bound; if it makes the gate useless, only ever **reduce** toward an effective-N via a *pre-registered*
cell-Sharpe correlation model (Galwey / Li-Ji effective-M, or 1+(N-1)ρ̄), **never inflate** past the raw count.
(The maximin sampler helps here: it maximises spread between picked cells, so realized trials are *more*
independent than random — supporting, not establishing, the near-independence approximation.)

## Calibration items to tighten before N (from the same review)
- **C1 — multi_indicator is UNCALIBRATABLE (near-dead). ✅ DONE (2026-07-14).** Measured: it holds a position
  for 0–11 bars over 9 years across 6 assets (oversold buy + price-below-SMA exit nearly cancel), so its JND
  can't be signal-flip-measured and its params barely produce distinct strategies. The fine analogs implied
  ~13k cells that are ~13k copies of the same non-trading null. **Applied:** a coarse grid (96 cells) +
  `coverage.py _UNCALIBRATED` flag. **v2 MUST floor/exclude multi's count from N** — do not feed 96 (or 13k)
  as a distinct-hypothesis count for a strategy that doesn't trade.
- **C2 — Noise floor + integer resolution. ✅ DONE (2026-07-14, `scripts/validate_grid_noise.py`).**
  Determinism = 0.0. RSI period is integer-governed at *every* base (+1-int flips 11–23% of positions) → applied
  one-cell-per-integer for `(rsi_reversion, period)` + `(multi_indicator, rsi_period)` (coverage.py
  `_INTEGER_PERIOD`); rsi 3,380→4,394, multi 11,830→13,013. sma/macd periods confirmed ratio-governed (floor
  ≪ T). Threshold ≈ 1 pt near the active region (step 2 documented as coarse-end). Full findings in
  COVERAGE-CALIBRATION.md §Noise-floor.
- **C3 — Median across 6 in-sample assets, applied per-asset**, leaves a directional leniency on high-vol names
  (the false-discovery direction). Since the count feeds a *penalty*, prefer a conservative high-count quantile
  or volatility-scaled resolution over the median.
- **C4 — Warmup. ✅ DONE (2026-07-14) — non-issue.** Re-measuring long-period steps with `max(period)` warmup
  bars discarded moves the disagreement by ≤ 0.001 (the union-in-market normalisation already excludes the flat
  warmup period). No re-measurement needed.
- **C5 — Provenance/pre-registration.** N is data-informed (calibrated in-sample on the same 6 assets/window),
  so it is a *frozen, data-informed pre-registered bound*, not an a-priori constant — label it as such. The
  harness + raw curves are now committed (`scripts/calibrate_coverage_grid.py`,
  `docs/design/calibration-v2-results.json`) so N is re-derivable; ideally re-calibrate on assets/windows
  disjoint from the evaluation set. Pin the box bounds — N must not silently move when a `[low,high]` range is
  widened (that is a `grid_version` bump).

## Functional reconciliation (small, but do before N)
- **F1 — feasible vs reachable.** `feasible_cells` (center-self-mapping, the sampler's *draw* domain) slightly
  **under**-counts the *reachable* set (an sma point needing no repair can bin into a cell whose center repairs
  away — 130 vs 132). For DSR-N the reachable count is the right quantity. Define one canonical cell set and use
  it for both the denominator and N. (v1 telemetry bug `pct_covered > 100%` — fixed by clamping to
  `visited ∩ feasible` — is the visible symptom of this same inconsistency.)

## Minimal correct recipe (what v2 should actually build)
1. **N = size of the pre-registered selection set** = Σ over every (template, asset) in the campaign's selection
   pool of the *reachable*-cell count, restricted to distinct cross-run cells, capped at the grid total. Pin box
   bounds + `grid_version`.
2. **Co-scope V** — theoretical null V ≈ 1/T (firewall-safe), or a firewalled pooled estimate. Never per-run V
   with grid N.
3. **Split the variable** — realized-executed-trials for the provisional/auto-pass guard; separate `search_size`
   N inside `sr0` only.
4. **Treat N as a conservative upper bound**; reduce only via a pre-registered correlation model, never inflate.
5. **Calibrate or floor multi_indicator; validate the noise floor; use a conservative (not median) cross-asset
   aggregate; re-measure with warmup discarded** before its count becomes N.
6. Keep it **behind the coverage flag** and keep the v1 AT-7 firewall intact except for the one deliberate,
   tested, performance-free wire (theoretical-V + cell-count-N) into `sr0`.
