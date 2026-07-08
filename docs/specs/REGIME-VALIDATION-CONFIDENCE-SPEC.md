# Backtest & Regime Validation Confidence — Requirements, Technical Spec & Implementation Plan

**Finding:** M27 (deferred owner-decision half), broadened to the normal backtest / walk-forward path · **Status:** DRAFT (awaiting sign-off on §7 open decisions + the §5.8 broadened scope) · **Date:** 2026-07-08

> **Scope (v2):** the four levers are general *"how much do I trust this backtest result?"* primitives, so they are built as **engine-layer** statistics (§5.2) and consumed by BOTH (a) the **normal backtest / walk-forward** path — the flagship beneficiary, §5.8 — and (b) the **AI research regime/OOS** validation, §5.3–5.6. Not regime-only.

Related: `REGIME-P2-HOLDOUT-SPEC` (the existing within-regime hold-out, loop.py `_run_regime_holdout`), H18 (Šidák hold-out-reuse), M28 (regime goal-counting), M29 (decay honesty), the model-honesty principle.

---

## 1. Context & problem statement

In **regime mode** the tool finds a strategy on a *train* slice and re-tests it on an unseen *hold-out* slice (`[train_end, window_end]`) to see whether the edge persists. The verdict is one of `regime_validated` / `regime_failed` / `unvalidated`.

**The defect (M27):** validation demands a **fixed 20 trades** in the hold-out (`VALIDATE_MIN_TRADES`, loop.py:269), independent of the strategy's trading frequency or the slice length. A hold-out is short by construction (≥ `MIN_HOLD_DAYS`=120d, often exactly ~4 months / ~84 trading bars). A low-frequency strategy (~1–5 trades/yr) therefore almost never reaches 20 trades there → nearly everything lands in `unvalidated`, and `regime_validated` is effectively unreachable — even for genuinely good slow strategies.

Two secondary weaknesses in the same place:
- The verdict is **binary** (`validated` / `failed` / `unvalidated`) — it throws away *how much* evidence there was.
- The bar ignores the strategy's own tempo, so "enough trades to trust this" means the same absolute thing for a day-trader and a once-a-quarter strategy.

**The honesty constraint (non-negotiable).** A 4-month window with 2–4 trades contains *inherently* little evidence — no statistic manufactures certainty from 3 data points. This spec's job is to **extract the maximum available evidence and report its strength honestly** (including "insufficient evidence"), never to relabel thin results as "validated." See §8.

---

## 2. Goals & non-goals

**Goals**
- G1 — Make `regime_validated` *reachable* for low-frequency strategies **without weakening the standard of proof**.
- G2 — Judge "enough evidence" **relative to the strategy's own trading frequency and the window length**, in regime *and* robustness/OOS mode.
- G3 — Extract **more data points** for slow strategies (per-*bar* daily-return evidence, not only per-*trade*).
- G4 — Replace the binary verdict with a **graded confidence level** plus the numbers behind it (sample size, observed Sharpe, and a confidence interval).
- G5 — Deterministic (seeded), no LLM, €0, within-run.
- **G6 — Build once, use everywhere.** The four levers are **engine-layer** primitives consumed by BOTH the normal backtest / **walk-forward** validator (flagship) and the AI research regime/OOS validation — no duplication, and it respects the module boundaries (research → engine, never the reverse).

**Non-goals**
- N1 — Not touching the long-window OOS *pass/fail contract semantics* beyond adding the same frequency/confidence machinery (the OOS lockbox keeps its stricter absolute floor; §5.6).
- N2 — Not cross-regime multi-window testing (testing on several historical regimes) — noted as a **future** larger build (§9).
- N3 — Not changing the train/hold-out split geometry (`_train_split`) — that stays as-is.

---

## 3. Requirements

Each requirement is written to be test-gated.

| ID | Requirement |
|----|-------------|
| **R1** | The hold-out trade-count bar is **frequency- and window-scaled**, not a fixed 20. Estimate the strategy's trade rate from the *train* window; the required trade count scales with (rate × hold-out length), clamped to a sensible floor/ceiling. |
| **R2** | When there are **too few trades** for a per-trade statistic, fall back to a **per-bar (daily-return) statistic** computed over the ~N in-market days of the hold-out. |
| **R3** | The result is a **graded confidence tier** (`strong` / `moderate` / `weak` / `inconclusive` / `failed`), **always** accompanied by: the statistic used (`per_trade` vs `per_bar`), the observed hold-out Sharpe, the t-stat, `n_trades`, `n_bars_in_market`, and the scaled `min_req_trades`. |
| **R4** | A **bootstrap confidence interval** on the hold-out Sharpe (seeded → deterministic) is reported as the confidence-level number (`ci_low`, `ci_high` at a fixed level). It comes out *honestly wide* when data is thin. |
| **R5** | Frequency-awareness (R1) applies in **robustness / OOS mode** too — "enough trades to trust this" is judged relative to tempo everywhere, not just regime. |
| **R6** | **No manufactured certainty.** Per-bar evidence is *indirect* (daily returns of a held position are autocorrelated) → a per-bar-only verdict is **capped at `moderate`** and can never read `strong`. A genuinely thin case reads `inconclusive` (a first-class, clearly-labelled outcome), never `validated`. |
| **R7** | Back-compat: the existing `status` values (`regime_validated`/`regime_failed`/`unvalidated`) are retained (mapped from the tier, §6) so current consumers/tests don't break; new fields are additive. |
| **R8** | The `Candidate.confidence` tier reflects the hold-out confidence; the report + console surface the tier, the observed Sharpe, the CI, and the sample size. |
| **R9** | H18/Šidák reuse correction still applies to whichever significance bar (`t_star`) the verdict uses. Determinism-mode reproducibility (M12) is preserved (seeded bootstrap). |
| **R10** | The **walk-forward** validator judges each test window with the frequency-aware bar (R1) + per-bar fallback (R2) + graded tier (R3) instead of the current binary `trade_count ≥ 1 and test_sharpe > threshold` (`_window_is_valid`). |
| **R11** | A **single `BacktestResult`** may carry an (opt-in) confidence tier + bootstrap Sharpe CI. HONEST FRAMING: on an *in-sample* result this measures **noise/precision of the number, not overfitting** — it must be labelled as such and must NOT read as "validated" (overfit protection = walk-forward/OOS, §5.8). |
| **R12** | The bootstrap CI **complements, does not replace**, the existing Deflated-Sharpe / composite machinery (DSR handles multiple-testing selection bias; the CI handles single-estimate sampling noise). No duplication; both may be shown. |

---

## 4. Plain-language summary of the design

> Estimate how often the strategy *naturally* trades (from the train data). Ask for a number of hold-out trades that's realistic for that tempo and window — not a flat 20. If it's too slow to ever produce enough trades, judge it instead on its **day-by-day** performance while holding positions (dozens of data points instead of a handful of trades). Then, instead of a yes/no stamp, report **how strong the evidence is** — a tier plus the observed number and an honest "it's somewhere between X and Y" confidence band. Never call a 3-trade result "strongly validated."

---

## 5. Technical specification

### 5.1 Inputs available today (no new plumbing needed for the data)
- `executor.run(...)` already returns, for any backtest slice: `n_trades`, `trade_returns` (per-trade P&L list), `returns` (the **daily** equity-curve returns = the held-position daily P&L series), `equity_curve`, `sharpe_annual`. → per-trade **and** per-bar inputs both exist.
- `per_trade_t(trade_returns)` (basic_gates.py): `mean/std(ddof=1)·√N`, `0.0` for `<2`. (Existing.)
- `annualized_sharpe(returns, ppy, ddof)` + `periods_per_year(index)` (metrics.py). (Existing — reuse for the per-bar Sharpe.)
- The **train-window** selection metrics (`n_trades` over `[train_ws, train_end]`) are computed in the loop before the hold-out — the trade-rate source for R1.

### 5.2 New pure helpers (stats layer — unit-testable in isolation)
```
scaled_min_trades(train_trades, train_days, holdout_days, *, floor=5, ceil=20) -> int
    # trades_per_day = train_trades / max(train_days, 1)
    # expected_holdout = trades_per_day * holdout_days
    # return int(clamp(round(expected_holdout), floor, ceil))

per_bar_t(daily_returns) -> float
    # mean/std(ddof=1)·√N over the daily return series; 0.0 for < ~10 bars.
    # NOTE (R6): daily returns of a held position are autocorrelated → this t is OPTIMISTIC;
    # treated as indirect evidence (confidence capped, §6).

bootstrap_sharpe_ci(daily_returns, *, level=0.90, n=1000, seed) -> (lo, hi)
    # seeded numpy Generator; resample daily_returns with replacement n times;
    # annualized Sharpe of each resample; return the (level) percentile band.
    # (Enhancement option: BLOCK bootstrap to respect autocorrelation — §7 D3.)
```
All three are deterministic given inputs (+ seed for the bootstrap).

### 5.3 The verdict algorithm (core of `_run_regime_holdout`, and the OOS analogue)
```
1. Run the hold-out backtest (existing) → n_trades, trade_returns, daily = returns, sharpe.
2. min_req = scaled_min_trades(train_trades, train_days, holdout_days)     # R1
3. If n_trades >= min_req and len(trade_returns) >= 2:
       method = "per_trade";  t = per_trade_t(trade_returns)
   elif len(daily) >= MIN_BARS (~20):
       method = "per_bar";    t = per_bar_t(daily)                          # R2
   else:
       return inconclusive (too thin for ANY statistic) + observed numbers  # R6
4. ci_lo, ci_hi = bootstrap_sharpe_ci(daily, seed=run_seed)                 # R4
5. tier = confidence_tier(t, method, observed_sharpe, ci_lo, ci_hi)        # R3/R6 (see 5.4)
6. status = status_from_tier(tier)                                          # R7 (see §6)
7. return { status, confidence_tier: tier, method, observed_sharpe, t_stat: t,
            n_trades, n_bars_in_market: len(daily), min_req_trades: min_req,
            ci_low: ci_lo, ci_high: ci_hi, ci_level, t_star, holdout_period, holdout_trades }
```

### 5.4 Confidence tiers (thresholds are §7 open decisions — these are the proposed defaults)
Let `t` be the primary statistic, `s` the observed hold-out Sharpe, `t*` the Šidák-corrected bar (H18).

| Tier | Condition (proposed) |
|------|----------------------|
| `strong` | `method == per_trade` **and** `t ≥ 2.5` **and** `ci_low > 0` |
| `moderate` | `t ≥ t*` (≥1.65 base) **and** `s > 0` (per-bar-only is **capped here**, R6) |
| `weak` | `t ≥ 1.0` **and** `s > 0` (suggestive) |
| `inconclusive` | `|t| < 1.0`, or sample below the minimum for the chosen method, or `ci` straddles 0 widely |
| `failed` | `s < 0` **and** the evidence indicates a real negative/collapsed edge |

### 5.5 Data structure (enriched hold-out result — additive)
Existing keys kept: `status`, `holdout_period`, `holdout_trades`, `holdout_sharpe`, `holdout_t`, `t_star`.
New keys: `confidence_tier`, `method`, `observed_sharpe` (alias of holdout_sharpe), `n_bars_in_market`, `min_req_trades`, `ci_low`, `ci_high`, `ci_level`.
(Stored in `Candidate.holdout` → `decay_json`/`holdout_json` persistence — additive, JSON-safe.)

### 5.6 Robustness / OOS path (R5)
The OOS lockbox (`_oos_verdict`, `OOS_MIN_TRADES`) runs on a **long** window (IS-end → now, years). Apply the *same* frequency-scaled bar + per-bar fallback + tiers, but with a **higher floor** (e.g. `floor≈10`, `ceil` unchanged) because a multi-year window legitimately expects more trades. The OOS PASS/FAIL contract (D5/H3) maps from the tier the same way (§6). `VALIDATE_MIN_TRADES`/`OOS_MIN_TRADES` become the *ceil*, not a flat requirement.

### 5.7 Integration points (files)
- `src/backend/ai/research/loop.py` — `_run_regime_holdout` (verdict algorithm), the call site (pass `train_trades` + `train_days`), the regime confidence mapping (`_LEVELS`), `VALIDATE_MIN_TRADES` becomes a ceil.
- `src/backend/backtesting/engine/metrics.py` (or a new `stats.py`) — the three new pure helpers.
- `src/backend/ai/research/state.py` — `Candidate.confidence` set from the tier; (no schema change — additive dict fields on `holdout`).
- OOS: `_oos_verdict` / the lockbox helper — R5 parameterization.
- `report_generator.py` + `frontend/.../console.tsx` — surface tier + observed Sharpe + CI + sample size (R8).
- Determinism: seed the bootstrap from the run `seed` (M12).

### 5.8 Normal backtest / walk-forward application (R10–R12) — the flagship path

The same three engine primitives (§5.2) serve the standalone backtest engine, where the payoff is largest:

- **Walk-forward validator (`engine/walk_forward.py`) — primary target.** It already produces per-window train/test results — structurally identical to the regime hold-out. `_window_is_valid` today is a crude binary (`test.trade_count ≥ 1 and test.sharpe_ratio > threshold`). Replace with: `min_req = scaled_min_trades(train_trades, train_days, test_days)`; if `test.n_trades ≥ min_req` use per-trade t, else per-bar t on the test window's daily returns; assign a **tier** (and a bootstrap CI on the test Sharpe). `is_valid` maps from the tier (≥ `moderate` = valid). The window carries `confidence_tier` + `ci_low/ci_high` alongside `overfitting_score`. → walk-forward validity becomes frequency-aware and graded, not a coin-flip on one trade.
- **Single `run_backtest` (`engine/runner.py`) — opt-in `BacktestResult` fields.** Attach `sharpe_ci_low/high` (+ optional `confidence_tier`) computed from the run's daily returns (the equity curve already exists). Surfaced next to the headline Sharpe in the CLI summary / results store. **Honest label (R11):** "precision of this Sharpe on this sample", explicitly NOT an overfitting/robustness verdict.
- **Optimizer (`engine/optimizer.py`).** No objective change (avoid selection-on-a-noisy-CI); optionally record the best trial's CI for display. DSR stays the multiple-testing guard (R12).

**Layering:** primitives in `engine/` (leaf) → consumed by `engine/walk_forward.py` + `engine/runner.py` (same layer) and by `ai/research` (higher layer). The engine must not import `ai/research` (import-linter contract stays 7/7).

---

## 6. Status ↔ tier mapping (R7 back-compat)

| Tier | `status` (kept for consumers) | Candidate.confidence |
|------|------------------------------|----------------------|
| strong | `regime_validated` | high/moderate¹ |
| moderate | `regime_validated` | moderate |
| weak | `unvalidated` (suggestive) | low |
| inconclusive | `unvalidated` | very_low / low |
| failed | `regime_failed` | very_low |

¹ Regime confidence today caps at `moderate` (unvalidated firewall); a `strong` per-trade hold-out may lift that cap — §7 D4.

---

## 7. Open decisions to confirm before build

- **D1 — Tier thresholds:** `strong` t≥2.5 · `moderate` t≥1.65 (=`VALIDATE_T`) · `weak` t≥1.0. OK, or different?
- **D2 — Scaled bar clamp:** `floor=5` (regime) / `10` (OOS), `ceil=20`. OK?
- **D3 — Bootstrap:** 90% CI, n=1000, **iid vs block** resampling. iid is simpler but ignores autocorrelation (over-narrow); block is more honest but more code. Proposed: **iid for v1 + the R6 per-bar cap**, block as a fast-follow.
- **D4 — Can a per-bar-only hold-out reach `regime_validated`?** Proposed: **yes, capped at `moderate` confidence** (never `strong`). Alternative: per-bar can only ever be `weak`/`suggestive` and never flips `status` to validated (stricter — validation *always* needs real trades). ← the key methodology call.
- **D5 — High/low-freq cutoff:** implicit (per-trade if `n_trades ≥ min_req`, else per-bar). Explicit threshold instead?
- **D6 — Scope/sequencing (the broadened-scope question):** ship **Track A (walk-forward/backtest)** in this effort alongside Track B (regime/OOS)? Proposed: **yes** — build the primitives once and wire the walk-forward first (flagship). Alternative: land regime/OOS (Track B) first, Track A as an immediate fast-follow. Either way the primitives are engine-level (G6).

---

## 8. Honesty & validity notes (model-honesty principle)

- **The per-bar t overstates significance** because daily returns of a held position are serially correlated (one position → many correlated daily returns). Mitigations: the R6 cap (per-bar-only ≤ `moderate`), the honest-wide bootstrap band, and (D3) an optional block bootstrap. The tool must **never** present a per-bar result as strong proof.
- **`inconclusive` is a first-class result**, surfaced with the observed numbers — not hidden, not upgraded. "We measured X but can't certify it on this much data" is the truthful statement for a thin slice.
- **The confidence interval is the honesty anchor:** when it's wide and straddles zero, that *is* the message.
- This spec **increases** how often a real verdict runs, which **engages H18/Šidák** (more hold-out peeks consume the correction) — correct behaviour; integration tests that exercise multiple candidates will see `t_star` rise.

---

## 9. Implementation plan (phased, each PR-able + test-gated; adversarial review at the end)

**Phase 0 — engine primitives (shared foundation).** `scaled_min_trades`, `per_bar_t`, `bootstrap_sharpe_ci` as pure functions in `engine/` + unit tests (boundaries, seed-determinism, thin-input, autocorrelation caveat). *No behaviour change yet.* Everything below consumes these.

**Track A — normal backtest / walk-forward (flagship; highest value, do first).**
- **A1 — R10 walk-forward window validity.** Replace `_window_is_valid`'s binary with the frequency-aware bar + per-bar fallback + tier; window carries `confidence_tier` + Sharpe CI. Tests: a slow strategy's short test window is judged by per-bar, not auto-invalid; a fast one still needs the count; `is_valid` maps from tier.
- **A2 — R11 single-backtest CI.** Opt-in `sharpe_ci_low/high` (+ optional tier) on `BacktestResult`, surfaced in the CLI summary / results store, labelled "sampling precision, not overfitting." Tests: seed-determinism; honest label present.

**Track B — AI research regime / OOS (can run in parallel after Phase 0).**
- **B1 — R1–R4,R6 regime hold-out.** Thread `train_trades`/`train_days` into `_run_regime_holdout`; scaled bar → per-bar fallback → tier → bootstrap CI; per-bar caps at `moderate`. Tests: a slow strategy on a short slice is now adjudicated (not auto-`unvalidated`); a fast one still needs a real count; `inconclusive` surfaced with numbers. **Reworks** `test_holdout_thin_stays_unvalidated`.
- **B2 — R5 OOS lockbox.** Same machinery, higher floor; long-window PASS/FAIL contract (D5/H3) preserved. Tests: OOS bar scales; contract intact.
- **B3 — R8 surfacing.** Tier → `Candidate.confidence` + report/console fields (tier, observed Sharpe, CI, sample size).

**Phase Z — adversarial review** of the whole change (the established pattern), remediate, then merge.

*Ordering:* Phase 0 first; then Track A (flagship) and Track B in parallel; Phase Z last. Each Ax/Bx is its own PR.

**Risks:** (a) autocorrelation → §8 mitigations; (b) determinism → seed the bootstrap; (c) back-compat → keep `status`, rework the handful of hold-out tests that hard-code 20/10; (d) more real verdicts → H18 `t_star` shifts in multi-candidate integration tests (expected); (e) scope discipline — this is validation *rigor*, not an alpha model (gate-scope principle): it must not become a knob that loosens standards to pass more strategies.
