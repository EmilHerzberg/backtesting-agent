# Coverage v2 — Reconciled Plan & Build Order

**Status:** Consolidated source of truth (2026-07-16). Reconciles three design docs after the safety pass. Where they disagree, **this doc wins**. Nothing implemented yet.
- `COVERAGE-MEMORY-V2.md` — the gate-wiring spec
- `COVERAGE-CALIBRATION-V3-PROTOCOL.md` — the grid step-size measurement
- `COVERAGE-GATE-SAFETY-MECHANISMS.md` — the safety envelope (PF/RT/MON/FB mechanism IDs referenced below)

---

## 1. Locked owner decisions (2026-07-16)

**D1 — Balance dial: strict-leaning.** Tune the in-sample gate to reliably confirm genuinely-strong edges (**reference edge ~0.9–1.0 Sharpe**) and defer weaker ones to the out-of-sample judge. The in-sample gate and the OOS judge **both apply, in sequence** — the reference edge does not toggle OOS. Higher reference edge = stricter (fewer, stronger candidates reach OOS). The exact reference edge + power floor are **finalized at pre-flight (PF1) from the measured power CURVE**, then frozen (PF5).

**D2 — "Validated" = risk-adjusted skill.** The significance PASS certifies risk-adjusted skill (excess Sharpe / IR / alpha), matching every upstream gate. **"Beats buy-and-hold on total return" is a SEPARATE, explicitly-labeled, optional filter** (default: report-only, not gated) — OD7 option 2. Implemented in the lockbox PASS (FB3) + a toggle.

---

## 2. Corrections to the earlier docs (what changed & why)

### 2a. `COVERAGE-MEMORY-V2.md` (gate-wiring spec)
- **DROP `V ≈ 1/T`.** Not reliably conservative — measured cross-trial dispersion is typically 2–3× larger, so `1/T` *lowers* the bar ~30–40% (a loosening in a firewall costume) and is the wrong null under serial dependence. → **Fixed, pre-registered conservative `V_null`** on the per-trade clock, serial-dependence-inflated, with a MANDATORY check that `sr0(V_null) ≥ sr0(status-quo)` on the frozen grid. (safety PF4)
- **DROP the `1+(N−1)·ρ̄` (Galwey/Kish) reduction with adjacent ρ̄.** For a banded correlation matrix it collapses to ≈1 for any N → cross-run accumulation becomes **inert while advertising a tightening**. → **Measure independence directly:** ONC / participation-ratio effective count on a Marčenko–Pastur-denoised return-correlation matrix of the visited-cell family; `N_used = max(N_eff, N_run)`; eigenvalue sub-floor blocks under-segmentation; **no upper cap**. (safety RT1/PF3/FB1)
- **Firewall re-anchored OUTPUT-side.** Performance is already one join away (`coverage.exemplar_hash → candidate.sharpe`), so "one integer input" is not the real guarantee. Guarantee = only scalars/verdicts reach selection/sampler/mutation; the return matrix is used in an ephemeral gate-time computation, never persisted; proven by a leak-audit + shuffle-invariance gate. (safety PF6)
- **KEEP:** the monotone-stricter floor (enabling can only tighten), the selection-set scope (B1 realized-visited, B2 campaign pool), the split `n_trials` (guard vs search_size, B4), `reachable_cells` (F1), flag-OFF = byte-identical.

### 2b. `COVERAGE-CALIBRATION-V3-PROTOCOL.md` (measurement)
- **Broaden the correlation output:** emit the FULL visited-family return-correlation matrix (or ONC-medoid-spanning subset), not just adjacent ρ̄ — it is the input to the effective-N estimator (RT1) and the estimator/bridge validation (PF2/PF3). The "ρ̄ → Kish reduction" language is retired.
- The position-disagreement ↔ return-correlation self-consistency check becomes a **DIAGNOSTIC** (PF2): ONC measures independence directly, so N no longer rides on the JND→independence bridge on the critical path. The JND grid still sizes the sampler.
- Everything else stands (150-stock survivorship-free sample, conservative aggregate, regimes, stability, pre-registration).

### 2c. OOS lockbox (our backstop) — fixes
- Underpowered-but-ran per-trade OOS → **UNEVALUATED (retryable), not terminal FAIL** (loop.py:560-563); don't burn write-once budget.
- PASS quantity → **risk-adjusted** (excess Sharpe/IR/alpha), not total-return-beats-buy-and-hold (loop.py:562). Optional total-return floor = separate toggle (D2).
- Fix the regime-mode bug where DSR softens while OOS is off (gatekeeper.py:83) — a pure loosening.
- Add campaign-wide OOS multiplicity control (FB4) before any soft-DSR ships.

---

## 3. Build order (dependencies + the "cannot enable until" gates)

Legend: 🟢 independently valuable now · 🔒 prerequisite gate · ⏸ deferred

**Track 1 — Trustworthy backstop (do first; independent of the N-wire) 🟢**
1. Lockbox FB3: underpowered→UNEVALUATED, risk-adjusted PASS, optional total-return toggle (D2); fix the regime-mode soft-DSR-with-OOS-off bug. → makes "defer to OOS" honest.

**Track 2 — Honest bar (independent) 🟢**
2. V_null fix (PF4): replace measured V with the fixed conservative null + stricter-direction check.

**Track 3 — Calibration (the measurement) 🔒 prerequisite for N**
3. Freeze + run the V3 calibration protocol: grid step-sizes + the family return-correlation matrix. Includes the C3 conservative aggregate + GRID_VERSION v2→v3 + backfill.
4. PF3 (estimator recovery on known-K) + PF2 (bridge diagnostic), validated on the calibration data → picks + freezes the effective-N estimator (conservative largest-within-tolerance rule).

**Track 4 — The core v2 wire 🔒 depends on Tracks 2+3**
5. RT1: effective-N pipeline (ONC/eigenvalue from the family return matrix; `N_used = max(N_eff, N_run)`; output-side firewall PF6) + the v2 selection-set family definition (B1/B2) + split `n_trials` (B4).

**Track 5 — Pre-flight gates 🔒 ALL must PASS before enabling**
6. PF1 (two-sided power/size calibration → the power CURVE; finalize D1's reference edge + power floor here), PF5 (freeze + hash the config), PF6 (leak-audit + shuffle-invariance).

**Track 6 — Monitoring 🟢 (ships with the wire)**
7. MON1 (power canary on the binding gate), MON2 (N/V/T decomposition telemetry), MON3 (low-power + UNEVALUATED banners).

**Track 7 — Graceful degradation ⏸ DEFERRED (gated)**
8. FB4 (campaign-wide OOS multiplicity control) → then RT2 (soft-DSR) + MON1 auto-soften. **Soft-DSR may NOT ship until FB4 lands.** Until then: DSR stays HARD, vacuity is reported (FB2), never patched by coarsening N.

**Enable gate:** the coverage-v2 flag flips ON only after Tracks 1–6 land and all pre-flight gates (PF1–PF6) PASS. **Flag OFF = byte-identical to today** throughout.

---

## 4. Shippable now, in isolation (no enable needed)
- **Track 1** (lockbox fixes) — valuable regardless of coverage-v2; hardens the ultimate arbiter.
- **Track 2** (V_null fix) — an honest tightening of the existing gate.
- **Track 3** (calibration run) — produces the grid + correlation data everything downstream needs.

Each is independently testable behind its own flag/tests before the coverage-v2 wire is built. Recommended first move: **Track 1 + Track 3 in parallel** (backstop + measurement), since Track 4 depends on Track 3 and the whole "defer to OOS" balance depends on Track 1.
