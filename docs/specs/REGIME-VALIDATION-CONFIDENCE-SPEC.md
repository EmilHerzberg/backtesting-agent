# Backtest & Regime Validation Confidence — Requirements, Technical Spec & Implementation Plan

**Finding:** M27 (deferred owner-decision half), broadened to the normal backtest / walk-forward path
**Status:** APPROVED **v3** (2026-07-08 — spec adversarial review folded in; recommended defaults accepted; §7 decided; implementation started)
**Date:** 2026-07-08

Related: `REGIME-P2-HOLDOUT-SPEC` (loop.py `_run_regime_holdout`), H18 (Šidák hold-out-reuse `t_star`), M28 (regime goal-counting), M49 (plateau watermark), M29 (decay), D5/H3 (OOS pass bar), the model-honesty principle, and the deflated-Sharpe machinery already in the engine.

> **Scope:** the levers are general *"how much do I trust this backtest result?"* primitives, built as **engine-layer** statistics (§5.2) and consumed by BOTH the **normal backtest / walk-forward** path (flagship, §5.8) and the **AI research regime/OOS** validation (§5.3–5.6). Not regime-only.

---

## 0. What the spec review changed (v2 → v3)

The v2 draft would have manufactured false "validated" verdicts. v3 corrects it with **one load-bearing principle** plus tightened statistics:

> **PRINCIPLE — the confidence layer is ADDITIVE; it never changes what a status MEANS.** `regime_validated` / `regime_failed` / `unvalidated` (and the OOS `PASS`/`FAIL`/`UNEVALUATED`) are **control state** consumed by M28, M49, the failure-breaker, goal_met, and the OOS lockbox. Their semantics are **unchanged**. The new **confidence tier + CI** ride *alongside* the status as evidence/display; they never flip a status.

Consequences (each ties to a review finding):
- **Per-bar (daily-return) evidence NEVER validates** (F1/F6). A strategy too thin for a real per-trade test stays `unvalidated`; per-bar only *enriches* it with a confidence signal + CI. `regime_validated` **always** requires real trades clearing the per-trade bar. The scaled bar (Lever 1) is what makes validation *reachable* for moderately-slow strategies; genuinely 1–2-trade strategies stay honestly `unvalidated` (that is the truth — there isn't enough evidence).
- **Block (not iid) bootstrap** for the CI (F3) — iid understates uncertainty on autocorrelated returns.
- **`strong` requires `t ≥ max(2.5, t_star)`** (F2, monotone with the Šidák bar) **and** a hard trade floor with df-aware (Student-t) critical values (F4-stats/F6).
- **Explicit OOS tier→outcome mapping** that preserves terminal FAIL and the excess-over-buy&hold arm (F4-completeness).
- **Tiering is a total, ordered function** with defined edge cases (F7); the per-bar series is masked to **in-market** bars via `exposure_time` (QF1).

---

## 1. Context & problem statement

In **regime mode** the tool finds a strategy on a *train* slice and re-tests it on an unseen *hold-out* (`[train_end, window_end]`) → `regime_validated` / `regime_failed` / `unvalidated`.

**The defect (M27):** validation demands a **fixed 20 trades** (`VALIDATE_MIN_TRADES`, loop.py:269) regardless of the strategy's frequency or the slice length. Hold-outs are short (~4 months / ~84 bars); a low-frequency strategy (~1–5 trades/yr) almost never reaches 20 there → nearly everything is `unvalidated` and `regime_validated` is effectively unreachable, even for good slow strategies. Secondary: the verdict is binary and ignores the strategy's own tempo.

**The honesty constraint (non-negotiable).** A 4-month window with 2–4 trades holds *inherently* little evidence — no statistic conjures certainty from 3 data points. The job is to extract the maximum available evidence and **report its strength honestly (including "insufficient")**, never to relabel thin results as validated (§8).

---

## 2. Goals & non-goals

**Goals**
- G1 — Make `regime_validated` *reachable* for **moderately** low-frequency strategies (via the frequency-scaled trade bar) **without weakening the standard of proof**.
- G2 — Judge "enough evidence" **relative to the strategy's own frequency and the window length**, in regime *and* robustness/OOS.
- G3 — For strategies too thin to *validate*, still give the user **more information**: a per-bar confidence signal + an honest CI (never a "validated" stamp).
- G4 — Replace the bare binary with a **graded confidence tier + the numbers** (sample size, observed Sharpe, CI), riding alongside the unchanged control status.
- G5 — Deterministic (seeded), no LLM, €0, within-run.
- G6 — Build once as **engine-layer** primitives; consumed by walk-forward/backtest (flagship) and research regime/OOS. Respects the import-linter boundary (research → engine, never the reverse).

**Non-goals**
- N1 — Not changing any **control-status semantics** (regime/OOS statuses stay as-is; the confidence layer is additive). Not changing the OOS PASS/FAIL contract (D5/H3).
- N2 — Not cross-regime multi-window testing (future, §9-later).
- N3 — Not changing the train/hold-out split geometry (`_train_split`).

---

## 3. Requirements

| ID | Requirement |
|----|-------------|
| **R1** | The **trade bar** for a *validation* verdict is frequency- and window-scaled (not a fixed 20): estimate trade rate from the *train* window; required trades scale with (rate × hold-out length), clamped `[floor, ceil]`. |
| **R2** | When there are **too few trades** for a per-trade test, the result stays `unvalidated`/`UNEVALUATED` (control) but is **enriched** with a per-bar (daily-return) confidence signal + CI. Per-bar **never** produces a validating status. |
| **R3** | Every hold-out/OOS result carries a **confidence tier** (`strong`/`moderate`/`weak`/`inconclusive`/`failed`) computed by a **total, ordered function** (§5.4), **always** with: `basis` (`per_trade`/`per_bar`/`none`), observed Sharpe, the t-stat, `n_trades`, `n_bars_in_market`, `min_req_trades`. |
| **R4** | A **block-bootstrap** confidence interval on the Sharpe (seeded → deterministic, annualized) is reported (`ci_low`,`ci_high`,`ci_level`). It is honestly wide on thin data. |
| **R5** | Frequency-awareness (R1) applies to **robustness/OOS** too, with a higher floor; the OOS tier→outcome mapping is explicit (§5.6) and preserves terminal FAIL + the excess-over-buy&hold arm. |
| **R6** | **A validating status requires real trades.** `regime_validated`/OOS `PASS` require `basis == per_trade` AND `t ≥ max(t_star, tier bar)` AND `n_trades ≥ STRONG/VALIDATE floor` with df-aware critical values. Per-bar can reach at most tier `weak` and never flips the status. |
| **R7** | **Control-status semantics unchanged (back-compat).** `regime_failed = a real test ran and did not clear the bar`; `unvalidated = no real test could run`. M28/M49/failure-breaker/goal_met/OOS-lockbox keep keying on the statuses exactly as today. New tier/CI fields are additive. |
| **R8** | `Candidate.confidence` derives from the tier; report + console surface tier + observed Sharpe + CI + sample size. |
| **R9** | H18/Šidák `t_star` applies to the significance bar for **every** validating tier (incl. `strong`, i.e. `t ≥ max(2.5, t_star)`) so tiers are monotone. Determinism (M12) preserved. |
| **R10** | The **walk-forward** window validity uses R1+R2+R3 (frequency-aware, graded) instead of `trade_count ≥ 1 and test_sharpe > threshold`; `is_valid` maps from the (unchanged-meaning) validity decision, tier + CI added. |
| **R11** | A single `BacktestResult` may carry an opt-in Sharpe CI (+ tier). HONEST FRAMING: in-sample = **sampling precision, not overfitting**; must be labelled so and must never read "validated". |
| **R12** | The CI **complements** the deflated-Sharpe / PBO machinery (DSR = multiple-testing selection bias; block-CI = single-estimate sampling noise incl. autocorrelation). Reuse an existing block-resample primitive if one exists (`synthetic.py`); do not duplicate DSR. |
| **R13** | The tier function is **total** (§5.4): defined for `std==0`, `<MIN_BARS`, degenerate/zero-width CI, and t-vs-Sharpe **sign disagreement** (a negative-Sharpe high-|t| is `failed`/`inconclusive`, never validating). |

---

## 4. Plain-language summary

> Ask for a realistic number of hold-out trades given how often the strategy naturally trades — not a flat 20. If it makes enough, judge it on those trades (a proper significance test at the reuse-corrected bar) → it can be **validated**, graded moderate/strong. If it's too slow to make enough trades, we **don't pretend** — it stays "not validated," but we still tell you what its day-by-day evidence looked like (a Sharpe with an honest "could be anywhere from X to Y" band and a weak/inconclusive confidence). We never turn a lucky 2-trade result into "validated."

---

## 5. Technical specification

### 5.1 Inputs available today
- `executor.run(...)` returns per slice: `n_trades`, `trade_returns` (per-trade P&L), `returns` (**whole-slice** daily equity returns — includes flat/cash bars), `equity_curve`, `exposure_time` (fraction in-market), `sharpe_annual`.
- `per_trade_t(trade_returns)` (basic_gates.py): `mean/std(ddof=1)·√N`, `0.0` for `<2`. **Note the 99.0 zero-variance shortcut** (identical trades → t=99) — must be rejected for *validation* (F6).
- `annualized_sharpe(returns, ppy, ddof)`, `periods_per_year(index)` (metrics.py).
- Train-window selection `n_trades` + `[train_ws, train_end]` dates → the trade-rate source (frequency). **Plumbing note:** the regime call site (loop.py) has these; `_oos_verdict` currently receives only the OOS metrics dict → R5 requires threading the IS train_trades/train_days in (a real, non-trivial change, not just "parameterization").

### 5.2 New engine primitives (pure, unit-testable)
```
scaled_min_trades(train_trades, train_days, holdout_days, *, floor, ceil) -> int
    if train_days <= 0 or train_trades <= 0: return ceil        # can't estimate tempo → demand the full bar
    rate = train_trades / train_days
    return int(clamp(round(rate * holdout_days), floor, ceil))

# NOTE (D8, Phase-Z resolution): NO `in_market_daily_returns` primitive ships in v1. The CI and per-bar
# evidence are computed on the REALIZED full-period daily `returns` (flat cash bars included) — the same
# series `sharpe_annual` comes from — so the CI brackets the reported Sharpe. A correct in-market mask needs
# a per-bar position series the executor does not emit (`exposure_time` is a scalar); the "last N bars" proxy
# is wrong (assumes contiguous end-exposure). `n_bars_in_market` is reported as an exposure×bars ESTIMATE.

per_bar_sharpe_and_t(daily, ppy) -> (sharpe, t, n)                 # EVIDENCE ONLY (never validates)
    # sharpe = annualized_sharpe(daily, ppy)     # full-period realized series (D8)
    # t = mean/se where se uses a HAC/Newey-West or block estimate (NOT naive std/√N) — daily returns of a
    #     held position are autocorrelated; a naive √N t is inflated ~√(bars/trades). If a HAC se is out of
    #     v1 scope, cap the per-bar contribution at tier `weak` regardless of t (it must never validate).

block_bootstrap_sharpe_ci(daily, ppy, *, level, block_len, n, seed) -> (lo, hi)   # F3
    # stationary/moving-block resample (respects autocorrelation) → distribution of annualized Sharpe →
    # (level) percentile band. Seeded numpy Generator. Reuse the block primitive in synthetic.py if present.
```

### 5.3 Verdict algorithm (regime hold-out; OOS analogue in §5.6)
```
1. Run the hold-out backtest → n_trades, trade_returns, returns, exposure_time, sharpe.
2. min_req = scaled_min_trades(train_trades, train_days, holdout_days, floor=REGIME_FLOOR, ceil=VALIDATE_MIN_TRADES)
3. ci = block_bootstrap_sharpe_ci(returns, ppy, seed=seed)               # full-period realized returns (D8); always reported (R4)
4. VALIDATION PATH (real trades):
      if n_trades >= min_req and len(trade_returns) >= 2 and not zero_variance(trade_returns):
          t = per_trade_t(trade_returns); basis = "per_trade"
          if t >= max(t_star, STRONG_T) and n_trades >= STRONG_FLOOR and ci.lo > 0: tier = strong
          elif t >= t_star and sharpe > 0:                                          tier = moderate
          elif sharpe < 0 or t <= -t_star:                                          tier = failed
          else:                                                                     tier = weak      # ran, not significant
          status = regime_validated if tier in {strong, moderate}
                 else regime_failed if tier == failed
                 else unvalidated               # 'weak' = ran but not significant → NOT validated, NOT failed
5. EVIDENCE-ONLY PATH (too few trades):    # D8: `daily` is the full-period realized series (no in-market mask)
      elif n_bars_in_market >= MIN_BARS:      # exposure×bars estimate, conservative gate
          sharpe_b, t_b, n = per_bar_sharpe_and_t(daily, ppy); basis = "per_bar"
          tier = weak if sharpe_b > 0 else inconclusive   # per-bar tier keys on the daily-Sharpe SIGN only (no CI gate)
          status = unvalidated                  # per-bar NEVER validates (R6)
6. else: basis="none"; tier=inconclusive; status=unvalidated
7. return { status, confidence_tier: tier, basis, observed_sharpe: sharpe, t_stat, n_trades,
            n_bars_in_market: n, min_req_trades: min_req, ci_low, ci_high, ci_level,
            t_star, holdout_period, holdout_trades }   # existing keys retained
```
`REGIME_FLOOR`, `STRONG_T`(2.5), `STRONG_FLOOR`, `MIN_BARS`, block/CI params → §7.

### 5.4 Tier as a total ordered function (R3/R13)
Evaluated top-down; first match wins; a default guarantees totality. Uses df-aware (Student-t) critical values at the stated confidence level for the given `n` (F4-stats).
| Order | Tier | Condition |
|------|------|-----------|
| 1 | `failed` | `basis==per_trade` AND (`observed_sharpe < 0` OR `t ≤ -t_star`) — ran a real test, edge is negative/collapsed |
| 2 | `strong` | `basis==per_trade` AND `n_trades ≥ STRONG_FLOOR` AND `t ≥ max(STRONG_T, t_star)` AND `ci_low > 0` |
| 3 | `moderate` | `basis==per_trade` AND `n_trades ≥ min_req` AND `t ≥ t_star` AND `observed_sharpe > 0` |
| 4 | `weak` | (`basis==per_trade` AND ran-but-not-significant) OR (`basis==per_bar` AND `observed_sharpe > 0`) |
| 5 | `inconclusive` | default (too thin / `std==0` / degenerate CI / `basis==none`) |
Edge cases (R13): `std==0` → not `strong`/`moderate` (falls to `inconclusive`); zero-variance per-trade `t=99` shortcut → excluded from validation (treated as `inconclusive`, not `strong`); sign disagreement (high |t|, negative Sharpe) → `failed` via rule 1.

### 5.5 Data structure (additive)
Kept: `status`, `holdout_period`, `holdout_trades`, `holdout_sharpe`, `holdout_t`, `t_star`.
Added: `confidence_tier`, `basis`, `observed_sharpe`, `n_bars_in_market`, `min_req_trades`, `ci_low`, `ci_high`, `ci_level`. (Stored in `Candidate.holdout` → JSON — additive.)

### 5.6 OOS lockbox (R5) — explicit tier→outcome mapping (F4-completeness)
The OOS runs on a long window. Same primitives, `floor=OOS_FLOOR` (higher). The OOS **outcome contract is preserved** — the tier does NOT replace `_oos_verdict`; it maps as:
| Situation | OOS outcome |
|-----------|-------------|
| `basis==per_trade`, `t ≥ t_star`, **and** positive excess over buy&hold (D5/H3) | `PASS` |
| `basis==per_trade`, ran but not significant (or fails excess) | `FAIL` (terminal — **not** UNEVALUATED) |
| too thin for a per-trade test (`basis` per_bar/none) | `UNEVALUATED` (retryable, H17) — per-bar CI reported as evidence only |
The confidence tier + CI are attached for display; the PASS/FAIL/UNEVALUATED that the lockbox/budget/goal logic consumes is exactly today's contract.

### 5.7 Integration points (files)
`loop.py` (`_run_regime_holdout` verdict + call-site plumbing of train_trades/train_days; `_LEVELS`→tier; `VALIDATE_MIN_TRADES`→ceil), engine `metrics.py`/new `stats.py` (primitives), `state.py` (`Candidate.confidence`←tier; additive holdout fields), `_oos_verdict`/lockbox (R5 + IS-frequency plumbing), `walk_forward.py` (`_window_is_valid`+window fields), `runner.py` (opt-in CI), `report_generator.py`+`console.tsx` (surfacing). Import-linter must stay 7/7 (primitives in engine, consumed by research — never the reverse).

### 5.8 Normal backtest / walk-forward (R10–R12) — flagship
- **Walk-forward** (`engine/walk_forward.py`): replace `_window_is_valid`'s binary with the R1/R2/R3 machinery on each test window; `is_valid ⇔ tier ∈ {strong, moderate}` (a real per-trade significance decision — same *meaning* as "this window's OOS edge is real," just frequency-aware); attach `confidence_tier` + CI beside `overfitting_score`.
- **Single `run_backtest`** (`engine/runner.py`): opt-in `sharpe_ci_low/high` (+ tier) from the realized equity-curve daily returns (full-period, D8 — the same series the reported Sharpe uses, so the CI brackets it); CLI/results-store surface it labelled **"sampling precision — not an overfitting/robustness verdict"** (R11).
- **Optimizer**: no objective change (never select on a noisy CI); optionally record the best trial's CI for display; DSR stays the multiple-testing guard (R12).

---

## 6. Status ↔ tier (R7 — status meaning UNCHANGED; tier is additive)
| Control status (unchanged) | When | Tier that rides along | Candidate.confidence |
|---|---|---|---|
| `regime_validated` | real per-trade test cleared the bar | `strong` or `moderate` | moderate (regime cap) / higher if D-cap lifted |
| `regime_failed` | real test ran, edge negative/collapsed | `failed` | very_low |
| `unvalidated` | ran-but-not-significant, OR too thin (per-bar/none) | `weak` / `inconclusive` | low / very_low |
M28/M49/failure-breaker/goal_met read the **status** exactly as today; the tier only sets the display confidence.

---

## 7. Decisions (APPROVED 2026-07-08)

Constants live in one module block so they are auditable/tunable.
- **D1 — Thresholds & level (DECIDED):** one-sided **95%** base (`VALIDATE_T`=1.65). `STRONG_T`=2.5, effective strong bar = `max(2.5, t_star)`. `moderate` bar = `t_star` (≥1.65). **Student-t (df-aware)** critical values at the df of the sample (df = n_trades−1 for per-trade); fall back to the normal bar only for large n.
- **D2 — Floors/ceil (DECIDED):** `REGIME_FLOOR`=5, `OOS_FLOOR`=10, `ceil`=`VALIDATE_MIN_TRADES`=20, `STRONG_FLOOR`=12 (decoupled from the scaled floor — `strong` cannot be earned on 5 trades).
- **D3 — Block bootstrap (DECIDED):** `level`=0.90, `n`=1000, `block_len = max(2, round(√N))` (moving-block on the realized full-period return series — see D8). New engine primitive (the `synthetic.py` OHLCV block-bootstrap is a different shape — reuse the *concept*, not the function). Seeded (deterministic); the research loop has no run-seed parameter, so it uses a fixed `seed=0` — fully reproducible (same inputs → same CI). Threading a per-run seed is a documented, non-blocking future nicety.
- **D4 — RESOLVED:** per-bar evidence **never validates** — caps at `weak`; status stays `unvalidated` (§0/R6).
- **D5 — DECIDED (cap-only v1):** the per-bar `t` is **display-only** and capped at tier `weak`, so an imperfect (non-HAC) `t` never gates a status. HAC/Newey-West is a documented fast-follow, only relevant if per-bar is ever allowed to influence more than the display tier.
- **D6 — DECIDED (yes):** Track A (walk-forward/backtest) ships alongside Track B; primitives built once; walk-forward first as flagship.
- **D7 — DECIDED (keep):** `regime_failed = a real per-trade test ran and did not clear the bar (negative/collapsed)`; unchanged so M28/M49/failure-breaker/goal_met are structurally unaffected.
- **D8 — DECIDED (Phase-Z resolution, 2026-07-08):** the CI and per-bar evidence are computed on the **realized full-period daily returns** (flat cash bars included), NOT an in-market-masked series. The v2 spec called for an `in_market_daily_returns(returns, exposure_time)` primitive; Phase-Z review showed (a) a correct mask needs a per-bar position series the executor does not emit (`exposure_time` is a scalar) — the leaf `confidence.py` only receives `(returns, exposure_time)`, and the "reconstruct from trade timestamps" precedent (`_lagged_sharpe_annual`) does not exist; (b) the "last `round(exp·len)` bars" proxy is statistically wrong (assumes contiguous end-exposure) — a wrong mask is worse than none (model-honesty); (c) **decisively**, the reported Sharpe is full-period, so the CI *must* be built on the same full-period series or it need not even bracket the point estimate. Impact of the flat bars is display-only and strictly conservative: they pull the per-bar Sharpe toward zero, never manufacturing a validating verdict (`validates` is a per-trade decision that never consults the CI/per-bar series; strong↔moderate is cosmetic since both validate). True in-market masking is a future enhancement gated on the executor emitting a per-bar exposure mask.
  - **D8 estimator caveat (recheck-refined):** the block-bootstrap CI is built on the **arithmetic** annualized Sharpe (`annualized_sharpe` = mean/std·√ppy, the natural bootstrap statistic), whereas the *headline* `holdout_sharpe`/`sharpe_annual` is the **geometric** (compounded) estimator (`benchmark_sharpe`, backtesting.py-compatible). By Jensen these differ by ≈ σ²·ppy/2 (daily σ≈1.5% → ≈0.1 Sharpe). We keep the arithmetic bootstrap (the geometric estimator needs a calendar-indexed price series; block-stitched resamples have none), so on the per-trade path the CI can sit slightly ABOVE the geometric headline. **What `observed_sharpe` actually is:** the Sharpe the tier's positive-edge check keyed on — the **geometric headline** on the per-trade *validating* path (so it equals `holdout_sharpe` there), the **arithmetic daily** Sharpe on the per-bar *evidence* path. It is NOT re-defined to the CI's arithmetic centre; doing so would make the tier's positive-edge gate use the arithmetic Sharpe, which would validate a **volatility-drag** strategy (positive per-trade mean but a negative *compounded* return) that an investor would lose money holding — the per-trade gate deliberately uses the realized geometric Sharpe (consistent with D7: a collapsed/negative compounded edge is `failed`, not validated). Net: the arithmetic-vs-geometric distinction is **display-only** (the CI band is arithmetic; the tier/headline Sharpe is geometric), and the SERIES choice D8 governs (full-period vs in-market) never moves a verdict. The estimator used for the sign gate is the geometric one *by design*, not by accident.

---

## 8. Honesty & validity notes (model-honesty principle)

- **Per-bar never certifies.** A held position's daily returns are one bet observed many times (autocorrelated); the naive `√N` t is inflated ~`√(bars/trades)`. v3 therefore forbids per-bar from producing any validating status (R6) — it is *evidence with a confidence band*, never a stamp. A genuinely 2-trade slice reads: `unvalidated` · observed Sharpe X · 90% CI [lo, hi] · confidence weak/inconclusive. That is the honest statement.
- **The CI must not be over-narrow.** Block bootstrap (not iid) so autocorrelation widens the band truthfully; a wide band straddling 0 *is* the message.
- **Scope discipline (gate-scope principle):** the scaled bar changes only *which statistic runs and how many trades are expected*, **never the significance standard** — `t_star` (H18) still gates every validating tier. This is validation *rigor*, not an alpha knob to pass more strategies.
- **`inconclusive` is first-class**, surfaced with the numbers — not hidden, not upgraded.
- **DSR complementarity (R12):** the block-CI addresses single-estimate sampling noise; the deflated Sharpe addresses selection over many trials. Show both; conflate neither.
- More real verdicts → **more H18 peeks consumed** (t_star rises across candidates) — correct; integration tests over multiple candidates will see it.

---

## 9. Implementation plan (phased, each PR-able + test-gated; adversarial review at the end)

**Phase 0 — engine primitives.** `scaled_min_trades`, `per_bar_sharpe_and_t`, `block_bootstrap_sharpe_ci` + the total tier function → pure functions in `engine/` + unit tests (boundaries, seed-determinism, thin/degenerate inputs, std==0, sign-disagreement, full-period CI brackets the reported Sharpe — D8). *No behaviour change.* (No `in_market_daily_returns` — dropped per D8.)

**Track A — walk-forward / backtest (flagship).**
- A1 — R10 walk-forward window validity (tier-based, frequency-aware) + window CI. Tests.
- A2 — R11 single-backtest opt-in CI + honest CLI label. Tests.

**Track B — regime / OOS.**
- B1 — R1–R4,R6,R13 regime hold-out verdict (scaled bar → validation-or-evidence → tier → block CI; per-bar can't validate). Tests.
- B2 — R5 OOS: IS-frequency plumbing into `_oos_verdict` + explicit tier→{PASS,FAIL,UNEVALUATED} mapping preserving the D5/H3 excess arm. Tests.
- B3 — R7/R8 surfacing: tier → `Candidate.confidence`; report/console fields. Confirm M28/M49/goal_met untouched (status semantics preserved). Tests.

**Phase Z — adversarial review**, remediate, merge.

**Tests to rework (enumerated — do not under-count):** `test_regime_holdout.py` (`test_holdout_validated`, `test_holdout_failed_when_edge_collapses`, `test_holdout_thin_stays_unvalidated`, `test_thin_holdout_*`, the M30 wiring test's status assertions), `test_loop.py` (regime candidate confidence/validation_status; M49 regime_failed watermark), `test_oos_lockbox_2a.py` (OOS_MIN_TRADES boundary → now a floor/ceil), `test_optimizer_5a.py`/`test_walk_forward_*` (window validity + new fields), any test asserting the old `regime_failed`/`unvalidated` reason strings. Each Phase re-baselines its own set.

**Risks:** (a) autocorrelation → per-bar-can't-validate + block CI + HAC-later (D5); (b) determinism → seed the block bootstrap; (c) **control-flow back-compat** → statuses keep their meaning (R7/D7), so M28/M49/goal_met are structurally unchanged — the highest-risk area, gated by explicit "status semantics preserved" tests; (d) `strong` on tiny N → Student-t + `STRONG_FLOOR` (D1/D2); (e) more real verdicts → H18 `t_star` shifts (expected); (f) scope discipline (§8) — reviewer to check the bar never *loosens* the significance standard.

**Later (N2):** cross-regime multi-window testing (several historical regimes) for genuinely more *independent* evidence — the only real cure for the low-frequency data limit.
