# Quantitative Correctness Review — backtesting-agent

**Date:** 2026-07-03
**Scope:** End-to-end functional and quantitative review of the standalone `backtesting-agent` repository (deterministic backtest core + AI research pipeline + market-data + API/frontend fidelity).

---

## Methodology

This review synthesizes a multi-agent audit organized as follows:

- **28 review areas** — one expert lens per area of the system: `engine-runner`, `strategies`, `indicators`, `metrics`, `dsr-stats`, `gates`, `optimizer`, `lockbox-oos`, `regime-holdout`, `marketdata`, `executor`, `loop-state`, `persistence-results`, `strategist-llm`, `critic-llm`, `reporter`, `director`, `llm-infra`, `api-contract`, three "fresh eyes" passes (`fresh-quant` hostile end-to-end trace, `fresh-institutional` practice-gap, `fresh-oss-user` release-day skeptic), plus six deep-dive extras (`benchmarks-annualization`, `cost-model-math`, `goals-criteria`, `leakage-marker-granularity`, `determinism-repro`, `currency-fx`).
- **Severity-scaled adversarial verification.** Every **high/critical** finding received **two independent verification lenses** (a code-behavior check and a quant-correctness check), with a **tiebreak** lens when they disagreed. Every **medium** finding received a **single code-truth lens**. **Low** notes were recorded but not adversarially checked. A **completeness-critic pass** confirmed no whole class of defect was dropped.
- **Status vocabulary.** `confirmed` = survived adversarial verification. `confirmed-contested` = survived only via the tiebreak lens (one verifier had wanted to refute or downgrade). `refuted` = killed by verification (reported in the appendix only). `unverified-low` = low-severity note, not adversarially checked (reported as a note). Findings labeled *contested* are flagged inline.

The findings below are **already deduplicated** — they are not re-merged. Where two surviving entries still share a root cause, they are cross-referenced explicitly (see the "Cross-references & contradictions" callouts).

---

## Executive summary

The deterministic core of this system is genuinely thoughtful and, in several places, better honesty engineering than most open-source backtesters: the `backtesting.py` wrapper gets signal-to-fill timing right (decide on bar-*t* close, fill at *t+1* open), the shipped strategies are causal in the default path, metrics are unit-normalized after the F-013 fraction fix, the report layer forbids the LLM from emitting digits, and the UI repeatedly labels regime results UNVALIDATED. **Despite that, a "validated" or "survived all gates" claim published by this system today cannot be trusted**, for cross-component reasons that no single-file review would catch. Three defects are result-corrupting at the critical level: walk-forward out-of-sample windows run every indicator **cold with no warm-up buffer**, so the "validated" strategy is literally not the strategy that traded in-sample; every benchmark Sharpe **hardcodes `sqrt(252)`** regardless of bar interval, so weekly/hourly benchmark and residual Sharpe are inflated ~2.2x and the gate compares an interval-aware strategy Sharpe against an interval-blind benchmark Sharpe; and a run's **"goal met" decision is made on raw candidate count**, entirely ignoring the user's typed Sharpe/drawdown/profit-factor thresholds. The flagship statistical control — the Deflated Sharpe gate — is fed the variance of *annualized* trial Sharpes into a *per-period* formula (independently found by six reviewers), so it is either vacuous below 20 trials or a kill-everything switch above; and the multiplicity count *N* resets every run while the OOS lockbox budget never binds because each candidate mints a fresh lineage id. The **default deployed run performs no out-of-sample validation at all** yet grades candidates "strong". Transaction-cost realism is understated in the AI path (commission only, no spread/slippage that the CLI adds). The market-data layer never models adjustment semantics: the cache incrementally merges back-adjusted Yahoo prices (going stale after every dividend/split), a timezone dedup bug can duplicate or crash on real data, the survivorship-bias hard gate is silently bypassed, and providers mix adjusted/unadjusted conventions. A striking amount of advertised machinery is **dead code**: the leakage canary, the lag-fragility gate, the determinism fingerprints, `gates.default.yaml`, the entire `costs/` realism package, the goal-criteria parser, and the anti-brute-force budget caps are all unwired. The LLM path degrades to the rule-based heuristic **silently** (a 700-token cap truncates reasoning models; failures leave no trace; the run still badges itself `full_ai`/`mechanism_only`), and the honesty markers themselves have holes (a `{{digit}}` template carve-out bypasses the numeric scanner; "regime bull/bear" labels are computed from the strategy's own equity, not the market; the leakage badge is provider-granular and masks the actual model that ran). None of this makes the codebase worthless — the bones are good and most defects are wiring, not architecture — but the gap between what the system *advertises* (statistically honest, OOS-validated, leakage-aware candidates) and what it *delivers today* is wide, and the fixes must start with the statistical wiring that corrupts results before touching anything cosmetic.

---

## Severity scoreboard (confirmed + confirmed-contested)

| Severity | Count | IDs |
|---|---|---|
| Critical | 3 | C1–C3 |
| High | 32 | H1–H32 |
| Medium | 60 | M1–M60 |
| Low | 23 | L1–L23 |
| **Total confirmed** | **118** | |
| Refuted (appendix A) | 5 | R1–R5 |
| Low notes, unverified (appendix B) | 29 | N1–N29 |

Verification depth: all 3 critical and 32 high findings passed a two-lens (+ tiebreak where needed) check; all 60 medium findings passed a single code-truth lens. Ten of the confirmed findings survived only via tiebreak (marked *contested*): H20, M26, M48, M50, M57, M58, M59, L8, L18, L23.

---

## Critical findings

### C1 — Walk-forward OOS test windows are evaluated with no indicator warm-up (silent train/test spec mismatch in every OOS result)
- **Where:** `src/backend/backtesting/engine/walk_forward.py:161-176`; `src/backend/marketdata/windows.py:149-150`
- **What happens:** Each test window is a bare slice starting exactly at `train_end` (`test_df = df[(df.index >= train_end) & (df.index < test_end)]`), fed into a standalone `Backtest(test_df, strategy)`. All indicators recompute from the first bar of the ~3-month slice with zero prior history. Any indicator whose lookback exceeds the window (SMA/EMA up to 200 in the parameter spaces vs ~63 bars) is NaN/unconverged for the *entire* window; ewm indicators run seed-dominated; and the "validated" strategy is not the strategy that traded in-sample.
- **Why it matters:** This is the load-bearing OOS check. Slow strategies produce zero trades (which C-linked defect H6 then counts as a "valid" window), and every walk-forward `is_strategy_validated=True` verdict is built on a systematically crippled version of the strategy. Result validity of the entire OOS claim is compromised.
- **Fix:** Prepend a burn-in prefix — slice `test_df` from `train_end - max_lookback`, mask trading before `train_end` (pass a `trade_start` timestamp), derive `max_lookback` from the chosen strategy's largest period. Require ≥1 trade before counting a window valid.
- **Status:** confirmed (2-lens: one uphold; a second noted the mechanism is real but severity depends on parameter mix — still critical for slow-lookback templates).
- **Also found by:** `engine-runner` (same defect, "systematically suppressing OOS trades"). Shares its root cause with **M26** (OOS lockbox / regime hold-out / decay backtests also cold-start) — see cross-reference at M26.

### C2 — Every benchmark/residual/market Sharpe hardcodes `sqrt(252)`; the gate then compares incompatibly-annualized numbers
- **Where:** `src/backend/backtesting/benchmarks/buy_hold.py:59`; `benchmarks/market.py:82,95`; `src/backend/ai/research/executor.py:99` (the buy-and-hold Sharpe that actually feeds the gate); `engine/runner.py:347` (`calculate_sortino` default `periods_per_year=252`, called with no argument)
- **What happens:** Every benchmark Sharpe multiplies by `math.sqrt(252)` unconditionally, but the platform supports `1wk` and `1h` bars for every provider (ATS-129). For weekly bars the correct factor is `sqrt(52)`, so benchmark/residual/market/buy-hold Sharpe are inflated by `sqrt(252/52) ≈ 2.20x`; for hourly bars the error is larger. Critically, the **strategy** Sharpe comes from `backtesting.py`, which *infers* the correct factor from the bar frequency, so `BenchmarkRelativeGate` Path A subtracts a correctly-annualized strategy Sharpe from a wrongly-annualized benchmark Sharpe.
- **Why it matters:** On any non-daily run the gate's core comparison is between two numbers on different scales — the benchmark bar is silently ~2.2x too high (weekly), so strategies are handicapped or flattered arbitrarily, and every reported alpha-vs-market/Sortino inherits the wrong factor. This corrupts the accept/reject decision itself.
- **Fix:** Derive `periods_per_year` from the run's `BarInterval` (252 daily equity, 365 daily crypto, 52 weekly, ~1638 RTH-hourly), thread it through `BacktestConfig`→executor into `compute_buy_hold`, `compute_market_benchmark`, and `calculate_sortino`; ideally reuse the exact freq→factor logic `backtesting.py` uses so strategy and benchmark are annualized identically.
- **Status:** confirmed (2-lens uphold; textbook-standard correction).
- **Also found by:** `extra-benchmarks-annualization` (primary). Feeds the estimator-mismatch findings **M5/M6** (which add the geometric-vs-arithmetic and ddof issues on top of the annualization error).

### C3 — Goal completion is decided on raw candidate count and ignores the user's typed Sharpe/drawdown/profit-factor thresholds
- **Where:** `src/backend/ai/research/state.py:217-226`; `ai/research/loop.py:172,826`; `run.py:145-153`; `src/backend/backtesting/gates/basic_gates.py:182`
- **What happens:** `goal_met()` returns `len(self.candidates) >= target_candidates`; `validated_count()` is the same OOS-filtered count. The live loop marks a run `goal_met`/`completed` purely on this count. The user's free-text goal is stored on `GoalBrief.goal_text` but **never parsed** into numeric criteria; the only performance bar a candidate must clear is the gatekeeper's hardcoded `MIN_SHARPE=0.5` plus generic gates. Nothing reads the user's stated numbers. `test_state.py:46-52` pins that `goal_met()` is `True` for two default (zero-metric) candidates.
- **Why it matters:** A run reports "goal met / completed" with candidates that violate the user's explicit request — e.g. a user asking for "Sharpe > 2, drawdown < 10%" gets a "completed" run whose candidates clear only 0.5 Sharpe. The headline honesty contract (the user set a bar; the system says it was met) is false. This is the core honesty defect the whole goal subsystem was built to prevent.
- **Fix:** Parse the goal once at run creation (`parse_criteria(goal_text)`), persist the criteria on `GoalBrief`, and change `goal_met()`/`validated_count()` to count only candidates satisfying `candidate_meets_criteria(...)` — after fixing the drawdown-sign bug **H30** and the dead-code wiring **M50**. Surface the parsed criteria in the UI/preview.
- **Status:** confirmed (2-lens uphold).
- **Also found by:** `extra-goals-criteria-decorative` (primary). Directly caused by **M50** (the criteria parser is dead code) and undermined by **H30** (even if wired, the drawdown criterion is vacuous).

---

## High findings

> **Cross-reference — the DSR cluster.** H1, H2, M24, M25 (and low note N7) are four surviving, non-duplicate findings that together explain *why the flagship Deflated Sharpe multiplicity gate does not work*: wrong variance units (H1), wrong trial count *N* (H2), a magic-number variance floor in the wrong units (M24), and inconsistent registry inputs (M25). They must be fixed together.

### H1 — Annualized trial-Sharpe variance is fed into the per-period Deflated Sharpe formula → DSR pinned near 0 (or kill-everything)
- **Where:** `src/backend/ai/research/loop.py:630-641`; `src/backend/backtesting/gates/deflated_sharpe.py:29,34,44,52`
- **What happens:** `deflated_sharpe()` is documented and implemented in *per-period* units (`sr_hat = r.mean()/r.std(ddof=1)` on daily returns; contract: "Do NOT pass annualized Sharpe"). The loop collects **annualized** Sharpes (`metrics['sharpe_annual']`) and passes `np.var(_sharpe_values)` as `trial_sr_variance`. Variance of annualized SRs is ~252x the per-period variance, so the expected-max-SR hurdle `sr0` is ~15.9x too large relative to `sr_hat`. Reproduced numerically: `deflated_sharpe(..., var_annual=0.44) → 0.0` vs `var_annual/252 → 0.044`.
- **Why it matters:** The multiplicity control — the statistical centerpiece the whole "statistically honest candidates" claim rests on — is either vacuous (below 20 trials, provisional pass) or a near-certain reject (≥20 trials). Either way it is not measuring multiple-testing risk.
- **Fix:** Track per-bar Sharpe per trial and feed `np.var(per_bar_sharpes, ddof=1)`; or minimally divide the annual-SR variance by the annualization factor. Add a regression test asserting DSR is non-degenerate for a realistic dispersion.
- **Status:** confirmed (2-lens uphold).
- **Also found by:** **six** reviewers independently — `metrics`, `gates`, `executor`, `fresh-quant`, `fresh-institutional`, `fresh-oss-user`. This is the single most cross-corroborated finding in the review.

### H2 — Multiple-testing *N* is a per-run in-memory counter, not the registry's cross-run trial count (resets every run, never finalized)
- **Where:** `src/backend/ai/research/gatekeeper.py:100-103`; `loop.py:641`; `event_registry.py:150` (the correct, unused `valid_research_trial_count()`)
- **What happens:** DSR's `n_trials` must be "total valid research trial count from the registry," but the loop passes `state.total_iterations` — the current run's counter only. Re-running research on the same data restarts *N* at 1; each candidate is gated with *N*=trials-so-far and never re-deflated with the final *N*; and `total_iterations` counts even no-backtest iterations.
- **Why it matters:** Ten 15-trial runs on the same data never leave the provisional window despite ~150 effective trials; the multiplicity denominator the DSR depends on is systematically wrong. Combined with H1 the gate is doubly broken.
- **Fix:** Wire `update_registry_stats` to `registry.valid_research_trial_count()` scoped to the (asset universe, data snapshot); re-evaluate each surviving candidate's DSR at report time with the final *N*; disclose *N* in the dossier.
- **Status:** confirmed (2-lens uphold).
- **Also found by:** `fresh-institutional` ("multiple-testing accounting is per-session only; OOS budget trivially resets").

### H3 — OOS lockbox PASS is sign-only (`Sharpe>0 AND return>0`) — weaker than every in-sample bar it is meant to out-rank
- **Where:** `src/backend/ai/research/loop.py:368-384`
- **What happens:** `_oos_backtest` declares PASS iff `sharpe_annual > 0 and total_return > 0` over the OOS window — no minimum trade count, no significance test, no benchmark check, no drawdown condition. Over the hardcoded 2024-01..2025-12 window (a rising market for the default large caps) almost any long-biased strategy passes by base rate.
- **Why it matters:** The "final test" is the *loosest* filter in the pipeline, yet its PASS is what mints the "validated" label and gates `goal_met` in some paths. A strategy with a single winning trade in two years, or one that merely rode beta, returns PASS.
- **Fix:** Reuse the hold-out bar: require a minimum trade count and per-trade `t ≥ 1.65` (or OOS Sharpe above a floor AND excess over buy-and-hold), and return `UNEVALUABLE` (not FAIL/PASS) when trades < minimum. Pin the criterion in a test.
- **Status:** confirmed (2-lens uphold).
- **Also found by:** `dsr-stats`, `loop-state`, `fresh-institutional`.

### H4 — `config/gates.default.yaml` is never loaded — shipped config silently diverges from the live thresholds
- **Where:** `config/gates.default.yaml:1-62`; live thresholds in `gatekeeper.py` `RIGOR_PRESETS`
- **What happens:** The repo ships a per-gate threshold YAML (`min_trades: 50`, `min_sharpe: 0.5`, `deflated_sharpe.threshold: 0.95`, `cost_multiplier: 2.0`) that no code reads. Actual thresholds come from hardcoded class constants overridden by `RIGOR_PRESETS`, which *contradict* the YAML: `min_trades` is 5/5/8 (not 50), there is no `activity_t` key at all, exploratory DSR is 0.90 (YAML says 0.95), `cost_multiplier` varies 1.5/2.0/3.0.
- **Why it matters:** For an open-source release, the file a user will edit to tune rigor has zero effect, and the documented thresholds are off by an order of magnitude from what runs. Reproducibility/config-honesty defect.
- **Fix:** Either wire the YAML in (with presets overlaying it) or delete it and document `RIGOR_PRESETS` as the single source of truth; add a test asserting YAML == effective gate attributes for the `standard` preset.
- **Status:** confirmed (2-lens uphold).

### H5 — The default (deployed) research flow performs no out-of-sample validation, yet grades candidates "strong"
- **Where:** `src/backend/ai/research/run.py:79,117-119,131-134`; `router.py:49`; `quality.py` (~100-110)
- **What happens:** `run_research(enable_oos=False)` and `StartRunRequest(enable_oos=False, rigor='standard')` mean the standard run selects and accepts candidates entirely in-sample on the fixed 2015-2023 window — no walk-forward (reachable only from the CLI), no hold-out, no OOS. `validated_count()` then equals raw candidate count, and `quality._robustness_tier` grades a candidate "strong" ("a strong statistical confidence") when `oos in ('PASS','OFF','PENDING')` — i.e. OFF is treated like PASS.
- **Why it matters:** The README's headline is statistically honest, OOS-checked candidates; the default binary delivers an in-sample-only run labeled "strong." This is the single widest advertise-vs-deliver gap.
- **Fix:** Default `enable_oos=True` (the lockbox is a free local backtest), or cap the tier at "moderate" when `oos == 'OFF'` and surface an explicit "in-sample only, no hold-out" marker on every report/candidate. Align README wording.
- **Status:** confirmed (2-lens uphold).
- **Also found by:** `fresh-institutional` (primary).

### H6 — Walk-forward validity counts zero-trade/NaN-Sharpe windows as "valid" and silently drops crashed windows from the denominator
- **Where:** `src/backend/backtesting/engine/walk_forward.py:152-156,171-186,215-229`
- **What happens:** A zero-trade window → `backtesting.py` Sharpe NaN → `runner._parse_stats` maps NaN→0.0 → `is_valid = 0.0 >= threshold(0.0)` marks the dead window VALID. Crashed windows are `continue`d, shrinking the denominator, so 9 crashed + 1 valid reports 100% valid. Combined equity also concatenates windows without chain-linking.
- **Why it matters:** A strategy that never trades out-of-sample can report `pct_valid_windows=100`, `is_strategy_validated=True`. Directly amplifies C1 (cold-start suppresses trades → all-zero-trade windows → all "valid").
- **Fix:** Require `trade_count ≥ 1` AND strictly positive Sharpe (or threshold > 0); treat NaN as invalid; count crashed windows in the denominator; chain-link combined equity multiplicatively.
- **Status:** confirmed (2-lens uphold).
- **Also found by:** `metrics`, `fresh-quant`.

### H7 — `Backtest(...)` never sets `finalize_trades` — open-at-end trades are silently excluded from all trade stats
- **Where:** `src/backend/backtesting/engine/runner.py:240-249,294-299`
- **What happens:** `backtesting.py 0.6.5` defaults `finalize_trades=False`; any trade open on the last bar is dropped from `# Trades`, `Win Rate`, etc., while its unrealized PnL stays in the equity curve and `Return [%]`. So `trade_count`/`win_rate`/`profit_factor` are inconsistent with `total_return`; a buy-and-hold-style run can throw `NoTradesError` ("never generated a signal") while fully invested; and `trade_returns` systematically omits the final trade.
- **Why it matters:** Per-trade statistics (the t-stat gate, profit factor, the reported trade list) disagree with the return, and the activity/edge gates operate on a truncated trade series.
- **Fix:** Pass `finalize_trades=True`; pin with a buy-and-hold test (`trade_count==1`, profit_factor consistent with return). Expose open-trade PnL explicitly if it must be separated.
- **Status:** confirmed (2-lens uphold; reproduced empirically).

### H8 — The leakage-canary positive control (`LeakyClosePeek`) is not actually leaky, and its discrimination test asserts nothing
- **Where:** `src/backend/backtesting/strategies/reference/leaky_close_peek.py:12-30`; `tests/unit/backtesting/gates/test_leakage_suite.py:37-43,86-117`
- **What happens:** `LeakyClosePeek` "peeks" at the current bar's Close, but under `trade_on_close=False` the order fills at the *next* bar's open — the standard causal pattern that `CleanSMACross` also uses. On zero-drift synthetic data it has no exploitable edge, so it cannot systematically fail the canary as its docstring claims. The discrimination test computes `leaky_mean`/`clean_mean` and never compares them.
- **Why it matters:** The published anti-leakage guarantee is *unvalidated*: the suite's own reference "leak" is a false positive control, so the canary's ability to detect look-ahead is untested.
- **Fix:** Build a genuinely leaky reference (indicator with `.shift(-1)`), verify empirically the canary fails it and passes `CleanSMACross`, and turn the test into a real assertion.
- **Status:** confirmed (2-lens uphold).
- **Also found by:** `strategies`.

### H9 — Sortino downside deviation is the centered std of negative returns only — explodes to ~1e15 or NaN
- **Where:** `src/backend/backtesting/engine/metrics.py:83-120`; caller `runner.py:347`
- **What happens:** `calculate_sortino` uses `downside.std()` (pandas ddof=1, mean-centered on the negatives), not the standard uncentered `sqrt(mean(min(r-target,0)^2))`. Centering removes the mean loss, so a strategy losing a steady −1%/day has centered-std ≈ float noise and Sortino explodes to ~1.7e15 (verified); with exactly one negative return, ddof=1 std is NaN and propagates into `sortino_ratio`, the optimizer objective, and stored results. `backtesting.py` already computes the correct Sortino, which this overrides.
- **Why it matters:** Sortino is a first-class optimizer objective (see H10) and a stored/displayed metric; the values are meaningless and can be NaN. No unit test covers this function.
- **Fix:** Use `stats['Sortino Ratio']` or the standard uncentered formula with an epsilon guard; add tests for identical-losses, single-loss, all-positive.
- **Status:** confirmed (2-lens uphold; one verifier noted a trivial `runner.py:301` vs `:347` citation slip — immaterial).
- **Also found by:** `engine-runner`, `fresh-quant`.

### H10 — `999.99` sentinels for infinite Sortino/profit-factor turn the `sortino`/`profit_factor` objectives into a degenerate-strategy attractor
- **Where:** `src/backend/backtesting/engine/optimizer.py:303-324`; `metrics.py:110-111,161-162`
- **What happens:** `calculate_sortino` returns `999.99` when there are no negative returns and mean excess > 0; `calculate_profit_factor` returns `999.99` with no losing trades. Since equity is flat (return 0, not negative) while in cash, a parameter set with one short winning trade and no down bars scores 999.99 — orders of magnitude above any real strategy — and Optuna converges on degenerate near-no-trade strategies when `objective_metric='sortino'` or the composite includes these keys.
- **Why it matters:** The optimizer is actively steered toward pathological strategies, and the sentinel contradicts the documented metric contract.
- **Fix:** Require a minimum trade/downside sample before trusting sortino/profit-factor, or winsorize to a plausible band (e.g. [−10,10]) before optimization.
- **Status:** confirmed (2-lens uphold).
- **Also found by:** `metrics`.

### H11 — ADX signal maps trend *strength* to BUY — strong downtrends emit persistent BUY; plus a tie-case DM asymmetry
- **Where:** `src/backend/backtesting/indicators/trend.py:197-203` (signal), `178-182` (DM bug)
- **What happens:** `ADXIndicator.signal` returns BUY whenever `ADX > 25`. ADX is direction-agnostic (`|+DI−−DI|/(+DI+−DI)`), so a crash produces ADX ≫ 25 and this indicator votes BUY on every bar of the crash — injecting a systematic long bias into the voting `DynamicStrategy` exactly in strong downtrends. Separately the `minus_dm` filter is computed against the already-zeroed `plus_dm`, so on `up-move == down-move` ties it yields `plus_dm=0, minus_dm=2` where Wilder requires both zero.
- **Why it matters:** Any generated strategy composed with ADX is corrupted with a downtrend-long bias; the composition feature is a headline capability.
- **Fix:** Filter DM from the raw series; make `signal()` directional (BUY on `+DI` crossing above `−DI` with `ADX>25`).
- **Status:** confirmed (2-lens uphold; ADX is a strength index, this is standard not stylistic).
- **Also found by:** `strategies`.

### H12 — The pandas indicator library emits directional signals during warm-up; the generator's `HOLD→0.0` conversion defeats `backtesting.py`'s NaN warm-up skip
- **Where:** `src/backend/backtesting/indicators/momentum.py:53-66`; `trend.py:69-81,117-148,189-203`; `volatility.py:98,151-156`; `strategies/generator.py:152-184`
- **What happens:** No ewm indicator sets `min_periods`, and `ewm(adjust=False)` never yields NaN, so `signal()` emits BUY/SELL from bar 1 on unconverged values (verified: `RSI(14)=0.0` at bar 1 → BUY; ADX BUY on bars 1-9; EMA SELL/BUY from bar 1). In `generate_strategy._signal_fn`, HOLD is mapped to `0.0` (not NaN), so `backtesting.py`'s leading-NaN skip sees no NaN and starts trading at bar 1 on garbage indicator values.
- **Why it matters:** Every generated/looped strategy trades on unconverged indicators during warm-up, contaminating the signal shape the optimizer selects on.
- **Fix:** Add `min_periods` to every ewm/rolling chain and return NaN (not 0.0) for warm-up bars in `_signal_fn`.
- **Status:** confirmed (2-lens uphold; reproduced with the repo's own code).

### H13 — The event gate is honored only by `SMACrossover` — silently ignored by every other strategy and never wired from YAML
- **Where:** `src/backend/backtesting/strategies/sma_crossover.py:58-76` (only call site); `engine/runner.py:219-238`; `config/schema.py:75-97`; `cli.py:306-309`
- **What happens:** `StrategyBase._apply_event_gate` is called from exactly one strategy. RSI, Bollinger, MACD, MultiIndicator, SentimentAwareRebound, and the generator's `DynamicStrategy` all call `self.buy()` directly. Yet `run_backtest` attaches `_gates_df`/`_event_gate_config` to *any* class when `event_gate.enabled`, and the schema docstring promises the backtest "applies them at each entry signal." So a user enabling the gate with any non-SMA strategy gets a fully ungated backtest with `blocked_trades_count=0` — indistinguishable from "gate had no effect."
- **Why it matters:** The event-gate is a flagship differentiator; for 5 of 6 strategy families it is silently inert, and there is no wiring from `BacktestFullConfig` through the CLI at all.
- **Fix:** Move gate application into `StrategyBase` (a `gated_buy()` used by every template), or raise/warn when `event_gate.enabled` but the class never consults the gate; wire the config through.
- **Status:** confirmed (2-lens uphold).

> **Cross-reference — the OOS lockbox is defeated four ways.** H3 (weak bar), H14 (budget never binds), H15 (stale window), H16 (verdict-recovery failure), H17 (error≠fail) are five non-duplicate defects that each independently undercut the "genuine out-of-sample discipline" claim. The lockbox *architecture* is sound; the *wiring* defeats nearly every safeguard.

### H14 — The OOS evaluation budget never binds: every candidate mints a fresh lineage, enabling unbounded peeks at the same OOS window
- **Where:** `src/backend/ai/research/loop.py:358,526-539`; `validation/lineage.py:3-5,51-63`; `state.py:221-226`
- **What happens:** The only defense against repeated OOS peeking is a 3-evaluation budget per lineage *family*. But `create_child` mints a brand-new `lineage_id` for every child, the loop creates a new root/child on *every* proposal, and `ensure_budget(state.current_lineage_id)` keys on that per-iteration id — a fresh budget of 3 per candidate, of which exactly 1 is consumed. `get_root` exists but is never called on this path. Traced: 25 candidates → 25 lineage ids → 25 budgets → 25 evaluations of the identical 2024-2025 window.
- **Why it matters:** "OOS-validated" is selection *on* a fixed, weak-bar OOS window with no multiplicity cap — the exact peeking the lockbox was built to prevent.
- **Fix:** Resolve the root via `get_root` and key `ensure_budget`/`PromotionToken` on it; cap total OOS evaluations per run; disclose peeks-per-family.
- **Status:** confirmed (2-lens uphold).
- **Also found by:** `director`, `fresh-quant`, `fresh-oss-user`.

### H15 — The OOS window is hardcoded to end `2025-12-31` — stale, publicly known, and inside current LLM training windows
- **Where:** `src/backend/ai/research/loop.py:370-371`; `strategist.py:28`
- **What happens:** OOS start = the fixed IS `window_end` (2023-12-31), end = the literal `"2025-12-31"`. Today this means ~18 months of genuinely unseen 2026 data are never used (gap grows monotonically), and in `full_ai` mode any model with a 2025/2026 cutoff has the 2024-2025 path in its training data, so an OOS PASS can confirm recall, not generalization — the exact failure the repo's own leakage research documents.
- **Why it matters:** The "out-of-sample" window is neither fresh nor unseen; there is no leakage marker on the OOS path.
- **Fix:** Derive OOS end dynamically (today minus a settlement lag) or make it explicit config with a startup warning when it lags "now"; attach the leakage marker to every `OOSResult`.
- **Status:** confirmed (2-lens: one uphold; a second agreed the kernel is valid but felt "high" overstated the training-recall angle — the staleness half alone justifies high).

### H16 — `AlreadyEvaluatedError` is swallowed without recovering the stored verdict → re-runs show all candidates PENDING and can never meet the goal
- **Where:** `src/backend/ai/research/loop.py:798-801`; `lockbox/service.py:112-116,68-70`; `run.py:80`
- **What happens:** The lockbox DB defaults to a persistent shared file `oos_lockbox.db` (router never overrides). Terminal results are keyed by `strategy_hash = sha256(template, params, asset)` — no run/window component — and `run_research` defaults `seed=42`, so a second OOS-enabled run over the same assets regenerates the same hashes and `evaluate` raises `AlreadyEvaluatedError` for every candidate. The loop catches *all* exceptions from `_run_oos_lockbox` and only logs, so no `OOSResult` is appended: `validated_count()` stays 0, the Director never reaches `goal_met`, and the run burns its whole budget.
- **Why it matters:** Deterministic, silent failure of the entire OOS-enabled path on any repeat run — the second run of a shared deployment can never validate anything.
- **Fix:** Add `get_result(strategy_hash)`; catch `AlreadyEvaluatedError` specifically and append the stored outcome (marked `reused=True`); namespace the DB per OOS-window version.
- **Status:** confirmed (2-lens uphold).
- **Also found by:** `persistence-results`.

### H17 — Any exception during the OOS backtest is recorded as a terminal, immutable FAIL and consumes budget
- **Where:** `src/backend/backtesting/lockbox/service.py:125-149`; `loop.py:383-384`
- **What happens:** `service.evaluate` converts *every* exception from the callable into `passed=False` and writes an immutable `OOSResultRow`; `_oos_backtest` also returns `False` on any exception (data outage, empty frame, executor error). The FAIL can never be overwritten (`AlreadyEvaluatedError`), and budget is consumed. A transient yfinance outage permanently brands a strategy an OOS failure, and `quality.py` makes OOS FAIL dispositive ("weak"), narrated as "terminal and cannot be revised."
- **Why it matters:** "Could not evaluate" is conflated with "evaluated and failed" — an infrastructure error becomes a permanent, honesty-corrupting verdict.
- **Fix:** Add a third metric-free outcome `ERROR/UNEVALUATED` that does not write a terminal row nor consume budget; show it as "not evaluated," not FAIL.
- **Status:** confirmed (2-lens uphold).
- **Also found by:** `executor`, `loop-state`, `persistence-results`.

### H18 — The regime hold-out slice is reused for every surfaced candidate and then used for ranking — uncorrected multiple testing on one shared slice
- **Where:** `src/backend/ai/research/loop.py:765-780`; `router.py:633-653`
- **What happens:** The P2 hold-out runs inline on every surfaced idea, testing every candidate on the *same* fixed slice `[train_end, window_end]` at `t*=1.65` (~5-6% per-test false-positive rate), and `/candidates` then sorts `regime_validated` first. That makes the presented "VALIDATED" pick a selection *on* the hold-out; across reruns (`_tried_hashes` is per-run only) the slice can be mined indefinitely. The OOS path has budget machinery; the hold-out path has none.
- **Why it matters:** Family-wise false-validation probability is ~`1-(0.94)^N` per run and unbounded across reruns — the "validated" label is not a one-shot confirmation.
- **Fix:** Evaluate the hold-out once per run on the single top-ranked-on-train candidate, or apply a Šidák/Bonferroni-corrected `t*` and persist a per-(window,asset) hold-out evaluation count like the OOS budget.
- **Status:** confirmed (2-lens uphold).
- **Also found by:** `loop-state`, `director`, `fresh-institutional`.

### H19 — `AgentBudgetController` is inert: per-hypothesis and mutation caps can never fire, and `is_mutation` is always True
- **Where:** `src/backend/ai/research/loop.py:541,549-560`; `budgets.py:74-105`; `strategist.py:175,398`
- **What happens:** Every `propose()` mints a fresh `hypothesis_id` (`hyp_{uuid4}`), and `check_and_consume` resets the per-hypothesis counters whenever the id changes — i.e. every iteration — so `max_trials_per_hypothesis=25` and `max_mutations_after_failed_gate=10` never trigger. Independently, `_prev_hypothesis_template` is assigned *before* `is_mutation` compares against it, so `is_mutation` is always True.
- **Why it matters:** The advertised "prevents brute-force parameter mutation and fake discovery" guard does nothing — the anti-overfitting brake is absent.
- **Fix:** Compute `is_mutation` before updating the prev-template; give the controller a stable key (template or lineage root) rather than a per-call uuid.
- **Status:** confirmed (2-lens uphold).
- **Also found by:** **seven** reviewers — `lockbox-oos`, `strategist-llm`, `director`, `llm-infra`, `fresh-quant`, `fresh-institutional`, `fresh-oss-user`.

### H20 — The daily "per-lineage" budget counter never resets on lineage switch — acts as a global 100-proposals/day kill switch *(contested)*
- **Where:** `src/backend/ai/research/budgets.py:79-80,89-93`
- **What happens:** `check_and_consume` updates `current_lineage_id` on a lineage switch but (unlike the hypothesis branch) never resets `trials_this_lineage_today`. Since the loop mints a new lineage nearly every iteration, the counter is effectively a global per-agent daily counter. After 100 successful proposals in one run (reachable with `max_runs>100` — `GoalBrief` default is 200) every subsequent `check` raises `BudgetExceededError`, killing the run early.
- **Why it matters:** A long run silently dies at 100 proposals under a cap advertised as per-lineage; combined with H19 the whole budget subsystem enforces the wrong thing.
- **Fix:** Key usage per `(agent_id, lineage_id)` in a dict, or reset the counter on lineage change, or rename/document it as a global daily cap sized above `max_runs`.
- **Status:** confirmed-contested (control-flow verified; tiebreak upheld against a lens that read the reachability as unlikely).

> **Cross-reference — market-data adjustment is unmodeled.** H21, H22, H23, H24 and M35 all stem from one architectural gap: *adjustment semantics are never a first-class concept*. The cache, the provider registry, and the snapshot metadata record no notion of "adjusted vs raw," so incremental merges corrupt data, dedup misfires, providers mix conventions, and the survivorship gate is fed the wrong flags.

### H21 — `CacheManager` incrementally merges back-adjusted Yahoo prices by timestamp — cached history goes stale after every dividend/split and is never corrected
- **Where:** `src/backend/marketdata/cache.py:84-107,194-247`
- **What happens:** yfinance returns `auto_adjust=True` (split+dividend folded into all bars, re-based to the fetch date). `get_or_fetch` fetches only bars newer than the latest cached bar and `_store_cache` skips timestamps that already exist. Back-adjusted series cannot be merged this way: after any corporate action, every historical bar's adjusted value changes, so the cached head and the new tail sit on different price bases, producing an artificial discontinuity at the seam.
- **Why it matters:** Any cached asset that pays a dividend or splits silently develops a price jump at the join, corrupting returns/vol/indicator warm-up for every subsequent backtest.
- **Fix:** Cache raw OHLCV + separate split/dividend series and adjust at read time, or treat adjusted series as immutable snapshots (refetch + replace on refresh); add an adjustment-mode dimension to the cache key.
- **Status:** confirmed (2-lens uphold).

### H22 — Fallback/aggregated providers silently mix adjustment conventions; AlphaVantage uses the UNADJUSTED endpoints despite a comment claiming adjusted
- **Where:** `src/backend/marketdata/provider.py:243-250,340,656-684`
- **What happens:** Yahoo returns split+dividend-adjusted; `AlphaVantageProvider` calls `get_daily()`/`get_weekly()` (raw `TIME_SERIES_DAILY/WEEKLY`) even though the interval-map comment claims `..._WEEKLY_ADJUSTED`; Polygon is split-adjusted only; Finnhub raw. `AggregatedDataProvider` then picks whichever provider returned the *most rows*, mixing conventions across a fallback.
- **Why it matters:** Depending on which provider answers, the same backtest runs on total-return-adjusted, split-only, or raw prices — with raw prices, splits appear as huge fake returns and dividends vanish, distorting benchmark and strategy alike.
- **Fix:** Declare an adjustment mode per provider; only fall back between providers with identical semantics (log on change); switch AlphaVantage to the `*_adjusted` endpoints; make aggregation respect priority, not row count.
- **Status:** confirmed (2-lens uphold).
- **Related:** **M35** is the AlphaVantage half of this defect seen from the benchmark-annualization lens.

### H23 — `_store_cache` dedup compares exchange-local naive time against stored UTC → dedup never matches real yfinance data (IntegrityError or duplicate rows)
- **Where:** `src/backend/marketdata/cache.py:216-239`
- **What happens:** For tz-aware bars (real yfinance daily bars are America/New_York), the existence check uses `dt.replace(tzinfo=None)` (00:00 NY wall time) but stores `dt.astimezone(utc)` (05:00); SQLite drops tzinfo on write so `existing_ts` round-trips as naive-UTC (05:00). 00:00 is never in {05:00,…}, so every overlapping bar in an incremental fetch is re-inserted, violating `uq_price_point` (IntegrityError) or duplicating rows. Reproduced end-to-end.
- **Why it matters:** The cache breaks on the platform's own default provider's real data; the incremental path either crashes or silently duplicates.
- **Fix:** Compute `dt_utc` first and use `dt_utc.replace(tzinfo=None)` for the check (mirroring `yahoo.py`); add a store-twice test; consider `INSERT OR REPLACE`.
- **Status:** confirmed (2-lens uphold; reproduced against the real model).

### H24 — The survivorship-bias hard gate is bypassed: the research loop feeds hand-rolled bias flags the gate never checks
- **Where:** `src/backend/ai/research/loop.py:577,649`; `gates/basic_gates.py:60-78`; `config/provider_capabilities.yaml`
- **What happens:** `ProviderCapabilityGate` HARD-fails when `bias_flags['survivorship_bias']` is True; config marks yfinance `survivorship_bias_risk: true`, `research_conclusion_allowed: false`, and the unit test is named `test_yfinance_fails`. But the loop builds the snapshot flags as `{"prototype_data": True}` — a key the gate never reads — so `flags.get('survivorship_bias', False)` is always False and the gate always passes.
- **Why it matters:** The one hard gate designed to block research conclusions on biased prototype data is silently inert for the default provider; every yfinance run passes a check it was designed to fail.
- **Fix:** Populate `bias_flags` via `get_bias_flags(provider)` (or route through `DataSnapshotCreator`), then decide semantics explicitly (hard-fail, or a SOFT annotation); add an integration test.
- **Status:** confirmed (2-lens uphold).

### H25 — Strategist `max_tokens=700` contradicts the truncation fix already applied to the Critic → `full_ai` silently degrades to rule-based with reasoning models
- **Where:** `src/backend/ai/research/strategist.py:320-342`; cf. `critic.py:189-190`
- **What happens:** `LLMStrategist.propose` uses `max_tokens=700`, while the Critic in the same repo documents the lesson ("reasoner models spend tokens on reasoning BEFORE the JSON verdict; 900 truncated it → heuristic") and was raised to 4000. The two production-recommended mechanism-only models (deepseek-reasoner, byteplus seed-2-0-pro) are both `supports_reasoning=True`, so the 700-token cap routinely truncates before the JSON completes → `extract_json_object` returns None → silent fallback to `RuleBasedStrategist` *after* the tokens were billed.
- **Why it matters:** For exactly the models the project recommends, `agent_mode=full_ai` can be ~100% heuristic while still billing and badging itself as AI-driven.
- **Fix:** Raise strategist `max_tokens` to the Critic's order (~4000) when the model supports reasoning; log and count fallbacks; surface an "llm vs fallback proposals" ratio in the report.
- **Status:** confirmed (2-lens uphold).

### H26 — The heuristic Critic hard-rejects <30 trades, overriding the calibrated smart-activity gate in the default (rule_based) mode
- **Where:** `src/backend/ai/research/critic.py:301-345`; `gatekeeper.py:29-37`; `loop.py:702-717`
- **What happens:** In the default `rule_based` mode (and on any LLM failure), `_heuristic_review` labels `n_trades < 30` as "insufficient," the word matches the `critical` keyword check, and the recommendation becomes `reject` — which kills the candidate in robustness mode. Yet the gate layer was explicitly re-calibrated to a 5-8 trade floor (observed median ~12; "the old hardcoded 50 passed 0%").
- **Why it matters:** The data-backed rigor presets are silently overruled by a crude hardcoded 30, so most gate-passing strategies are killed by the critic on trade count alone — the calibration work is defeated.
- **Fix:** Pass the active `min_trades`/`activity_t` into the critic (or defer to the activity gate's tier); make `investigate` non-terminal.
- **Status:** confirmed (2-lens uphold; confidence medium on exact reachability).
- **Also found by:** `critic-llm`, `fresh-quant`, `fresh-oss-user`.

### H27 — `persist_snapshot` advances flush cursors before commit — a failed commit silently and permanently drops events/candidates/failures/hypotheses
- **Where:** `src/backend/ai/research/persistence.py:117-240`
- **What happens:** The heartbeat flusher increments `persisted_events`/`persisted_candidates`/`persisted_failures`/`persisted_hypotheses`/`persisted_lineage_count` inside the loop, *before* the single `session.commit()`. If the commit raises (SQLite lock, disk), the transaction rolls back, the outer `except` swallows it, and the already-advanced cursors mean those rows are never retried. Because `/events` and SSE read only `research_events`, the lost rows vanish from the live UI and the durable record.
- **Why it matters:** The audit trail — the durable evidence for every "validated" claim — can silently lose data with no error surfaced.
- **Fix:** Compute new cursor values into locals and assign to `rec.*` only after commit succeeds (or restore cursors in the except path).
- **Status:** confirmed (2-lens uphold).
- **Also found by:** `loop-state`, `persistence-results`.

### H28 — The `{{...}}` template carve-out in the numeric-claim scanner is a live bypass — `{{1.2}}` ships digits to the report unscanned
- **Where:** `src/backend/ai/research/reporter.py:24-25,39`
- **What happens:** `scan_for_numeric_claims()` strips `\{\{[^}]+\}\}` before scanning, to protect a template-rendering step that *does not exist* — `serialize_report()` dumps narratives verbatim and the frontend renders `{s.narrative}` raw. So any LLM output wrapped in double braces (e.g. `"Sharpe was {{1.2}}"`) passes `assert_no_numeric_claims()` and appears verbatim in the user-facing report. LLMs spontaneously emit `{{placeholder}}` syntax.
- **Why it matters:** The digit-free-report guarantee — the platform's flagship honesty mechanism — has a trivial, live bypass.
- **Fix:** Remove the carve-out for LLM text, or restrict it to a whitelist of binding identifiers `[a-z_.]+` (no digits); fix the test that currently pins the bypass.
- **Status:** confirmed (2-lens uphold; reproduced: scan returns `[]` for `{{1.2}}`).

### H29 — The AI research executor charges only commission, silently dropping the spread and slippage the CLI adds
- **Where:** `src/backend/ai/research/executor.py:47-49,75-85`; cf. `cli.py:307-309`
- **What happens:** `ResearchExecutor.__init__` takes bare `commission=0.001` and passes it straight into `BacktestConfig` with no spread/slippage. The CLI builds `commission = commission_pct + spread_bps/10_000/2 + slippage_bps/10_000` = 14.5 bps/side vs the executor's 10 bps/side. Since the AI loop is the core product, every LLM-generated strategy is evaluated at ~30% lower transaction cost than an equivalent CLI run, and every downstream gate (`cost_stress`, cost-sensitivity) stresses the thinner baseline.
- **Why it matters:** Net performance of AI-discovered strategies is systematically overstated relative to the platform's own documented cost model, especially for high-turnover templates.
- **Fix:** Route both paths through one cost helper (`CostConfig`/`CostsConfigYaml`) so the research executor uses commission+spread+slippage; make it a `StartRunRequest` field.
- **Status:** confirmed (2-lens uphold).
- **⚠ Cross-reference / severity contradiction:** This is the **same root-cause defect as M55** (`fresh-oss-user` reported it as *medium*, `extra-cost-model-math` as *high*). They were not merged during dedup. Treat as one issue at **high** severity; M55 adds the "no `StartRunRequest` knob / preview understatement" angle.

### H30 — The drawdown criterion in `candidate_meets_criteria` is vacuous (sign/convention mismatch, always True)
- **Where:** `src/backend/ai/goals/criteria.py:62-71,98-117`
- **What happens:** `parse_criteria` stores a max-drawdown target as a *negative* fraction (`"20%"` → value `-0.20`, op `>=`), and `candidate_meets_criteria` tests `candidate['max_drawdown'] >= -0.20`. But the candidate dicts carry `max_drawdown` as a *positive* magnitude, so any non-negative drawdown satisfies `>= -0.20` — the criterion never rejects. There is also a scale mismatch (fraction vs percent) and metric-key mismatches (`sharpe_ratio` vs `sharpe_annual`, `trade_count` vs `n_trades`).
- **Why it matters:** Even once the criteria path is wired (see C3/M50), the drawdown bar the user set is silently ignored — a 90%-drawdown candidate passes a "drawdown < 20%" goal.
- **Fix:** Store the DD target as a positive limit with op `<=`; normalize scale; reconcile metric keys with the actual candidate dict shape; add a "30% DD fails a 20% goal" test.
- **Status:** confirmed (2-lens uphold).

### H31 — The run-level leakage marker is provider-granular and masks the actually-used model
- **Where:** `src/backend/ai/research/router.py:516,579,617`; `ai/leakage.py:40-53`; `state.py:209`
- **What happens:** The run badge is `provider_leakage(state.provider_type)`, which returns `mechanism_only` if *any* model the provider ships is clean. Both clean providers also ship an unvalidated sibling (deepseek-reasoner + deepseek-chat; seed-2-0-pro + seed-2-0-lite). The run stores only `provider_type`, never the model that executed, so a run on `deepseek-chat` (unvalidated) is badged `mechanism_only` — the flagship anti-leakage feature is systematically over-optimistic.
- **Why it matters:** The 3-state leakage badge is the project's core honesty differentiator; at run level it cannot distinguish the leakage class of the model that actually drove selection.
- **Fix:** Add `model_id` to `ResearchState`, set it at `run.py:176`, persist it, and compute the badge with `model_leakage(model_id)` for runs.
- **Status:** confirmed (2-lens uphold).
- **Related:** **M56** (the roll-up precedence is optimistic — `mechanism_only` before `risk`) compounds this once a mixed-class provider is added.

### H32 — Market-benchmark alpha/beta regresses non-USD asset returns against SPY (USD) with no FX normalization
- **Where:** `src/backend/backtesting/benchmarks/market.py:60-108` (esp. 97)
- **What happens:** `compute_market_benchmark` regresses per-bar strategy/asset returns directly against SPY (USD) returns. For the shipped non-USD universe (`get_dax_symbols()` returns 30 EUR-denominated `.DE` tickers; clustering also carries `.L`/`.SW`/`.AS`), `beta_vs_market` absorbs EUR/USD FX comovement and `alpha_vs_market` becomes a currency-contaminated hybrid. A currency-inference helper (`symbol_currency_hint`) exists but is never called.
- **Why it matters:** Alpha/beta/residual-Sharpe for every non-USD asset are silently contaminated by FX — relevant given the German asset universe is a first-class shipped universe.
- **Fix:** Put both legs in one currency before regressing (add FX return, or convert SPY into the asset currency); set alpha/beta to None + a flag when no FX series is available.
- **Status:** confirmed (2-lens uphold; confidence medium on magnitude).
- **Note:** `compute_market_benchmark` currently has no live caller, but the columns are persisted (`registry/models.py:161`) and advertised.

---

## Medium findings

> Where a medium finding shares a root cause with a higher-severity one, the link is noted. Medium findings received a single code-truth lens; all listed here are `confirmed` unless marked *(contested)* (survived tiebreak).

### M1 — F-027 NaN auto-fix back-fills leading OHLC gaps with future prices (look-ahead) and can break OHLC invariants
- **Where:** `engine/runner.py:190-211`. `cleaned[ohlc_cols].ffill().bfill()` copies the first *future* valid price backward into leading NaNs — a silent look-ahead into warm-up/benchmark computation — and per-column filling can violate `High >= max(Open,Close)`. The error-message helper path points to a non-existent file. **Fix:** drop leading-NaN rows, ffill interior only, re-clip High/Low; flag that auto-fill occurred. **Status:** confirmed.

### M2 — Calmar uses arithmetic `total_return/years` instead of CAGR (and its docstring contradicts the units passed)
- **Where:** `engine/metrics.py:123-142`; caller `runner.py:349-360`. Overstates annualized return (100%/2yr → 50% not 41.4%); for 3-month walk-forward windows it ×4-extrapolates into wildly inflated Calmar values fed to the optimizer. Docstring says percent, caller passes fractions (scale-invariant today, a trap tomorrow). **Fix:** CAGR with a min-duration guard; fix docstring. **Status:** confirmed. **Also found by:** `metrics`.

### M3 — The per-bar equity curve including the flat warm-up region is handed downstream as "daily returns" to gates and metrics
- **Where:** `runner.py:332-341`; consumer `executor.py:87-91,116-117`. The library backfills pre-warm-up bars to initial cash, so the returns array has a leading run of exact zeros (up to 200 bars), diluting per-bar mean, shrinking measured vol, and inflating the sample size *n* used by the canary/per-bar SR toward 0. **Fix:** trim to the first active bar; document the per-bar==daily assumption. **Status:** confirmed. **Related:** compounds C1/H12 (warm-up problems).

### M4 — The composite optimizer objective mixes units: the drawdown penalty is ~100x too weak after the F-013 fraction conversion
- **Where:** `optimizer.py:35-38,309-324`. Default `0.6*sharpe + (-0.4)*max_drawdown` with `max_drawdown` now a *fraction*: a 50% drawdown contributes only −0.2 vs +0.6 per Sharpe unit, so "composite" (the default objective) silently degenerates to Sharpe maximization. Same trap for `profit_factor` (capped 999.99 would dominate). **Fix:** rescale weights for fraction units or normalize each metric; clamp profit-factor; test that a 50% DD lowers the score. **Status:** confirmed.

### M5 — `BenchmarkRelativeGate` Path A compares two different Sharpe estimators (geometric vs arithmetic)
- **Where:** `executor.py:93-115`; `basic_gates.py:218-233`; `buy_hold.py:55-61`. Strategy Sharpe is `backtesting.py`'s geometric estimator; `bh_sharpe` is arithmetic `mean/std*sqrt(252)`. Arithmetic exceeds geometric by ~σ/2 (~0.1-0.2 Sharpe), comparable to the `SHARPE_IMPROVEMENT_MIN=0.2` threshold itself, systematically handicapping the strategy. **Fix:** one Sharpe definition platform-wide. **Status:** confirmed. **Cross-reference:** shares root cause with **M6** and sits on top of **C2** (the annualization error).

### M6 — The gate compares two Sharpe estimators computed by different formulas; the documented `compute_buy_hold` Sharpe (ddof=1) is discarded for the executor's ad-hoc ddof=0 computation
- **Where:** `executor.py:94-99,113-114`; `buy_hold.py:57-59`; `basic_gates.py:227-233`. `compute_buy_hold` computes a ddof=1 annualized Sharpe but the runner only reads its `total_return`; the gate reads the executor's separate ddof=0 computation — two independent buy-hold Sharpes with different ddof and annualization, neither matching the strategy estimator. **Fix:** compute the benchmark Sharpe once, in `compute_buy_hold`, with the same estimator/annualization as the strategy. **Status:** confirmed. **Cross-reference:** the ddof/estimator sibling of **M5**; both are subsumed by a single "one Sharpe definition" fix.

### M7 — The research loop omits `buy_hold_max_drawdown` → `BenchmarkRelativeGate` Path B (drawdown improvement) is permanently dead
- **Where:** `loop.py:623-626`; `gatekeeper.py:121-127`; `basic_gates.py:236-241`. The executor computes it but the loop's `artifacts.benchmark` dict carries only return + Sharpe, and the gatekeeper enrichment fallback fires only for an *empty* dict, so `bh_dd=0.0` hard-codes Path B False. **Fix:** add the key at `loop.py:623-626`. **Status:** confirmed. **Also found by:** `executor`, `fresh-oss-user`. **Cross-reference:** the "Path B dead" half of **M19**.

### M8 — Failed optimizer trials become COMPLETE trials with `value=-inf` (direction-unaware; documented `OptimizationError` never fires; all-failed study crashes the final re-run)
- **Where:** `optimizer.py:179-184,341-362`. Optuna rejects only NaN; ±inf is accepted, so exceptions become COMPLETE −inf trials. The documented "raises if no valid trial completes" can never fire on exception-failures; an all-failed study picks a −inf best and re-raises a raw `BacktestError` after burning the whole budget; and `direction='minimize'` would select crashing params as best. **Fix:** `raise TrialPruned` / re-raise; exclude non-finite from best selection; wrap the final re-run. **Status:** confirmed. **Also found by:** `engine-runner`.

### M9 — The composite objective silently ignores unknown weight keys (a typo → weight applied to nothing)
- **Where:** `optimizer.py:309-324`. `metric_map.get(key, 0.0)` with no validation of user YAML keys — `{'drawdown': -0.4}` (vs `max_drawdown`) silently optimizes pure Sharpe; all-unknown weights → constant 0.0 objective (pure noise). **Fix:** validate keys against `metric_map`, raise on unknown. **Status:** confirmed.

### M10 — Walk-forward silently ignores all YAML optuna settings (per-window optimization always uses default composite/TPE/median)
- **Where:** `walk_forward.py:144-150`. `OptimizationConfig` is built with only strategy/data/n_trials/cash/commission; sampler, pruner, `objective_metric`, `composite_weights`, seed all fall to defaults. A user setting `objective: sharpe` gets windows optimized on the default composite instead — and windows are then *scored* on test Sharpe, an internal inconsistency. **Fix:** add the fields to `WalkForwardConfig`, forward from CLI, per-window seed. **Status:** confirmed.

### M11 — Walk-forward `overfitting_score` explodes on near-zero train Sharpe (0.001 floor) and misclassifies negative-train windows, corrupting the aggregate
- **Where:** `walk_forward.py:177-184,225-226`. `test/train` with `train_sharpe = ... else 0.001` maps 0.0 train Sharpe to 0.001, so `test 0.3 / 0.001 = 300`; unweighted averaging makes the headline "closer to 1.0 = less overfitting" meaningless whenever any window has weak train performance (the common case). **Fix:** compute the ratio only above a meaningful floor; exclude/clip; report median. **Status:** confirmed.

### M12 — Seed/determinism plumbing is dead: no caller can seed the sampler, determinism mode never seeds, forced-serial-when-seeded not enforced
- **Where:** `optimizer.py:85-87,126,129-139`. `OptimizationConfig.seed` reaches the sampler but no production caller sets it and the YAML schema has no seed field; `BACKTEST_DETERMINISM_MODE` clamps only `n_jobs` and does **not** seed, so "deterministic" runs still use `TPESampler(seed=None)` and explore different sequences. **Fix:** expose seed through `OptunaConfig`/CLI; inject a fixed seed in determinism mode; clamp `n_jobs` when seeded. **Status:** confirmed. **Cross-reference:** part of the broader determinism-unwired cluster (M57-M59).

### M13 — The documented event-gate integration pattern `self.buy(size=size)` buys ONE SHARE instead of full equity when ungated (`size=1.0`)
- **Where:** `strategies/base.py:231-235`; `sma_crossover.py:64-73`. `backtesting.py` treats `size==1.0` as one whole unit (~2% exposure), while a REDUCE-gated `size=0.5` buys 50% of equity — the gate *increases* position size relative to ungated, inverting its semantics and invalidating gated-vs-ungated comparisons. The in-code comment claiming "size==1 is 100% of cash" is factually wrong. **Fix:** a `_gated_buy(size_fraction)` helper mapping `>=1.0`→full-equity; regression test on exposure. **Status:** confirmed.

### M14 — `create_with_params` silently accepts unknown/typo'd parameter names — backtests run with defaults while results are recorded under the requested params
- **Where:** `strategies/base.py:79-108`. `attrs = {k:v for k,v in params.items()}` with no name check; a misspelled param becomes an inert class attribute, the strategy runs with defaults, and the pipeline records the run under the requested (untested) parameterization. **Fix:** validate keys against `parameter_space()`, raise `InvalidParameterError`. **Status:** confirmed. **Also found by:** `executor`. **Related:** compounds **M38** (LLM proposals with no provenance).

### M15 — `BollingerBreakout` implements mean-reversion, the inverse of its name — and the goal planner routes "breakout" requests to it
- **Where:** `strategies/bollinger_breakout.py:14-29,74-93`; `planner.py:80`. Buys when price crosses *below* the lower band (textbook mean-reversion); the AI layer internally maps it to `mean_reversion`, yet `planner.py` maps the user keyword "breakout" to the mean_reversion family — a user asking for a breakout strategy silently gets mean-reversion. **Fix:** rename to `BollingerMeanReversion` (deprecated alias) or implement the real breakout; fix the planner keyword map. **Status:** confirmed.

### M16 — `RSIIndicator` and `MultiIndicator` still contain the RSI bug the repo already fixed elsewhere (F-014): zero-loss → NaN/HOLD instead of 100, zero-biased ewm seed
- **Where:** `indicators/momentum.py:47-58`; `strategies/multi_indicator.py:52-62`. `rs = avg_gain/avg_loss.replace(0,np.nan)` → RSI NaN → HOLD when no loss yet, so a perfect uptrend never registers as overbought; both ewms seeded at 0 instead of Wilder's SMA seed (deviates 0.33 RSI after 60 bars). `rsi_reversion.py` already fixes this. **Fix:** extract and reuse the F-014 implementation. **Status:** confirmed. **Also found by:** `strategies`.

### M17 — `generate_strategy`'s dynamic categorical space crashes Optuna on the second trial — the combinatorial indicator-composition feature is unusable as documented
- **Where:** `strategies/generator.py:94-104`. The candidate list for slot `i>=1` depends on earlier slots' picks in the same trial, but Optuna requires a fixed choice set per named param; trial 2 raises `ValueError: CategoricalDistribution does not support dynamic value space` (reproduced). No in-repo caller exists, so the flagship "AI composes multi-indicator strategies" path is dead. **Fix:** always suggest from the full list and prune conflicts, or encode combinations as a single categorical. **Status:** confirmed.

### M18 — Zero test coverage for the pandas `BacktestIndicator` library that the engine actually uses
- **Where:** `tests/unit/indicators` (covers only the legacy Decimal indicators). Not a single test imports `src.backend.backtesting.indicators.*` — the RSI/ADX/MACD/warm-up defects (H11, H12, M16, L1) would all have been caught by shallow reference-value tests. **Fix:** add reference-value + signal-semantics tests per `BacktestIndicator`. **Status:** confirmed.

### M19 — `BenchmarkRelativeGate` is nearly vacuous: Path C passes any positive excess return and Path B is dead
- **Where:** `basic_gates.py:206-263`; `loop.py:623-626`. `path_c = (strategy_return - bh_return) > 0` with no risk adjustment (mislabeled "Positive alpha"); since pass = A∨B∨C, Path C dominates and the `benchmark_sharpe_min` rigor knob (Path A only) never binds. Path B is dead (see M7). **Fix:** make Path C risk-aware (or drop it); forward `buy_hold_max_drawdown`. **Status:** confirmed. **Also found by:** `fresh-institutional`. **Cross-reference:** the "Path B dead" defect is the same root cause as **M7**.

### M20 — Rigor presets don't bind below Sharpe 0.5: un-preset `MIN_STRESSED_SHARPE=0.5` makes exploratory `min_sharpe=0.3` unreachable
- **Where:** `gatekeeper.py:33-64`; `cost_stress_gate.py:25,42-46,60`. `build_default_pipeline` scales the perf floor and cost multiplier but never touches `CostStressGate.MIN_STRESSED_SHARPE`, so every strategy with `0.3 <= Sharpe < 0.5` passes the exploratory perf floor and then deterministically hard-fails cost_stress — the exploratory tier can't actually accept anything below 0.5. **Fix:** add `min_stressed_sharpe` to each preset; preset-coherence test. **Status:** confirmed.

### M21 — Graveyard kill-cause misattribution: soft FAILs claim `first_failed_gate` and ERROR results set no cause and don't short-circuit
- **Where:** `gates/pipeline.py:155-183`. Any FAIL (including regime-demoted SOFT gates that run before the hard kill) sets `first_failed` regardless of severity, so the graveyard/report/critic attribute the kill to the first soft weakness; ERROR in a hard gate skips both branches (no cause, no short-circuit). **Fix:** record `first_failed` only for hard fails; treat hard-gate ERROR as terminal with a distinct field. **Status:** confirmed.

### M22 — `LeakageCanaryGate` and the synthetic-path generators are dead code — runtime leakage protection is advertised but never wired
- **Where:** `gates/canary.py:38-148`; `gatekeeper.py:129-141`. `build_default_pipeline` assembles 9 gates and omits the canary; even if added it double-provisional-passes (needs `run_strategy_fn` nobody supplies and `ctx.metrics['ohlcv_df']` the gatekeeper strips). **Fix:** wire it for survivors (pass a `run_strategy_fn` closure and forward `ohlcv_df`), vary seed per (hash, asset); until then document it as CI-only. **Status:** confirmed.

### M23 — `LagFragilityGate` has no producer of `lagged_sharpe_annual` — always provisional-PASS, displayed as a passed gate
- **Where:** `gates/lag_gate.py:27-38`; `gatekeeper.py:129-150`. The key is read only in `lag_gate.py` and produced nowhere (the gatekeeper metrics allowlist omits it), so the "+1 bar lag fragility" microstructure check never evaluates anything, yet appears as `status=PASS` (the `provisional` detail is dropped by the critic's evidence rendering). **Fix:** implement the producer (re-run with 1-bar-delayed signals) or set `NOT_EVALUATED` and surface it. **Status:** confirmed. **Also found by:** `executor`, `fresh-institutional`, `fresh-oss-user`.

### M24 — `quality.py` detects "defaulted variance" by float-equality with 0.001, and the 0.001 floor is in the wrong units after the DSR fix
- **Where:** `ai/research/quality.py:59-69`; `gatekeeper.py:103`; `deflated_sharpe.py:90-91`. A genuinely measured variance ≤0.001 is silently replaced by the floor before the gate sees it, and provisional detection via magic-value equality is fragile; at ≥20 trials this can render a hard PASS/FAIL on a fabricated variance. The floor was calibrated for the (wrong) annualized units. **Fix:** emit an explicit `sr_variance_defaulted` boolean; re-derive the floor in per-bar units. **Status:** confirmed. **Cross-reference:** part of the DSR cluster with H1/H2/M25.

### M25 — DSR registry inputs are inconsistent: `n_trials` includes no-metric iterations, variance is pooled across assets and lost on resume
- **Where:** `loop.py:438-439,630-631,640-641`; `gatekeeper.py:100-103`. `n_trials=total_iterations` counts strategist/data errors and skips (up to ~3x the real family in a budget-deadlock run), and `_sharpe_values` is a session-global list never cleared on `advance_asset`, so asset B's trial-SR variance is contaminated by asset A. **Fix:** feed `n_trials = len(_sharpe_values)`; decide per-asset vs per-session and make both inputs match; persist the sample list. **Status:** confirmed (confidence medium). **Cross-reference:** DSR cluster (H1/H2/M24).

### M26 — OOS lockbox, regime hold-out, and decay backtests start cold — no indicator warm-up buffer before the evaluation window *(contested)*
- **Where:** `loop.py:273-331,368-384`. All three re-eval paths fetch data for exactly the evaluation window and run from scratch; a slow SMA-200 burns ~9.5 months of a 2-year OOS window, and the `MIN_HOLD_DAYS=120` calendar-day hold-out (~84 trading bars) is shorter than many templates' warm-up, so slow strategies structurally produce few/zero hold-out trades and "decay" conflates warm-up artifact with real edge decay. **Fix:** fetch a warm-up buffer before the window and score only in-window trades. **Status:** confirmed-contested (code behavior fully confirmed; a lens argued the quant impact was smaller than framed → downgraded to medium via tiebreak). **Also found by:** `lockbox-oos`, `executor`, `fresh-quant`, `fresh-institutional`. **Cross-reference:** same root cause as **C1** (cold-start), applied to the OOS/hold-out/decay paths.

### M27 — `regime_validated` is a near-dead path: 20 trades in a 120-day cold-started hold-out is practically unreachable for the template library
- **Where:** `loop.py:240-241,311-324`. `VALIDATE_MIN_TRADES=20` in a ~82-trading-bar hold-out that also consumes warm-up (M26); the repo's own calibration is ~1.3 trades/year median, so 20 trades in 4 months is a tail event and slow templates produce zero. The "validated" tier is essentially decorative. **Fix:** fetch warm-up history, scale the trade minimum to hold-out length, fall back to a bar-level return t-test; always report the observed hold-out Sharpe/t. **Status:** confirmed.

### M28 — Regime runs declare `goal_met`/COMPLETED counting unvalidated and even `regime_failed` ideas as "validated"
- **Where:** `state.py:221-226`; `run.py:132`; `loop.py:173-174,791-793`. `validated_count(oos_enabled=False)` returns raw candidate count, and regime mode force-disables OOS, but the hold-out status never feeds flow control: three all-`regime_failed` ideas still hit `goal_met` and stop the search; `regime_failed` even resets `consecutive_failures` to 0. The `run.py` claim that P2 "replaces" OOS is false at the Director level. **Fix:** exclude `regime_failed` from `validated_count` in regime mode, or rename the stop reason to `ideas_surfaced`. **Status:** confirmed. **Also found by:** `loop-state`, `director`.

### M29 — Decay `retained_fraction` divides by an unguarded near-zero in-regime Sharpe and drops negative-edge information
- **Where:** `loop.py:284-285`. `retained = oor_sharpe / in_regime_sharpe if in_regime_sharpe > 0 else None`; with the SOFT perf floor in regime mode, a train Sharpe of 0.02 and out-of-regime 0.5 reports "retained 2500% of the edge," and `in_regime_sharpe <= 0` silently drops the sign. **Fix:** report the difference; emit a ratio only above a Sharpe floor; clamp to a sane band. **Status:** confirmed.

### M30 — Zero test coverage of the select-on-train wiring: `train_end` is never exercised through `run.py` or the loop
- **Where:** `tests/unit/ai/research/test_regime_holdout.py`. Tests cover only pure helpers with fakes; grep for `train_end` across `tests/` returns zero. Nothing asserts that the strategist/fallback/critic receive the TRAIN slice (the load-bearing P2-R1 anti-leakage wiring) or the confidence/status transitions. **Fix:** integration test asserting selection backtests use `window_end==train_end`, one hold-out per candidate on `[train_end, window_end]`, and the status/confidence transitions. **Status:** confirmed.

### M31 — Regime candidate headline metrics are train-slice-only but the UI labels them with the full user window
- **Where:** `loop.py:719-735`; `console.tsx:160`; `router.py:590-618`. In a split regime run the candidate Sharpe/return/DD/trades come from the selection backtest (60-75% of the window), but the console shows `regime · {window_start}→{window_end}` and `RunStatusResponse` never exposes `train_end`. A user reads "Sharpe 1.4 over 2020-2022" for a number measured over the train slice only. **Fix:** expose `train_end`; label candidate metrics "train slice"; optionally report recombined full-window metrics. **Status:** confirmed.

### M32 — Yahoo end date is exclusive while the `DataProvider` contract (and other providers) treat end as inclusive — last bar systematically dropped, semantics differ per provider and per mode
- **Where:** `provider.py:63,201-207`. The ABC says "end inclusive"; yfinance `history(end=...)` is exclusive, so the last requested day is omitted, while AlphaVantage/FrozenSnapshot/Tiingo/Finnhub filter inclusively — so "deterministic" (frozen) and live runs disagree by one bar by construction. **Fix:** pass `end + 1 day` to yfinance and trim, or normalize the ABC to exclusive-end everywhere; cross-provider contract test. **Status:** confirmed.

### M33 — `TiingoProvider` rename maps both raw and adjusted fields to the same names, producing duplicate-labeled columns
- **Where:** `provider.py:553-567`. Tiingo returns both `close` and `adjClose`; `col_map` renames both to `Close`, and pandas does not merge → duplicate `Close`/`Open`/… labels, so `df['Close']` becomes a 2-column DataFrame and downstream `float(row['Close'])` raises `TypeError` (or silently uses an undefined blend of raw/adjusted). **Fix:** select and rename only the adj* fields (fall back to raw); assert no duplicate columns. **Status:** confirmed.

### M34 — `CoinGeckoProvider` ignores the requested start/end window and interval, and fabricates `Volume=0`
- **Where:** `provider.py:476-507`. Computes `days` from the span (clamped 365) and calls `/ohlc?days=N`, which returns the most recent N days ending *today* — never filtered by start/end — so a request for 2021 data receives 2025-2026 data; `interval` is ignored (CoinGecko auto-selects 4-day candles for spans >30d), and Volume is hardcoded 0. **Fix:** use `/market_chart/range`, filter to `[start,end]`, reject non-matching intervals, return NaN volume. **Status:** confirmed.

### M35 — AlphaVantage fetches NON-adjusted close despite a comment claiming the adjusted series
- **Where:** `provider.py:35,243-246,262-270`. `get_daily()/get_weekly()` map to the raw endpoints, but the weekly branch is annotated `TIME_SERIES_WEEKLY_ADJUSTED`; with raw close the buy-hold benchmark omits dividends and shows split spikes. **Fix:** use `get_daily_adjusted`/`get_weekly_adjusted`, map `5. adjusted close`→Close. **Status:** confirmed (confidence medium). **Cross-reference:** the AlphaVantage-specific half of **H22**.

### M36 — No currency/denomination field anywhere in the asset model or provider output
- **Where:** `marketdata/assets.py:15-23`; `schema.py:11-15`; `provider.py:39`. `AssetConfig` has no currency; every provider returns bare OHLCV with no denomination tag; `symbol_currency_hint` exists but has zero callers. This is the structural precondition that lets the FX contamination in **H32** happen silently. **Fix:** add an explicit `currency` field, populate from provider metadata/`symbol_currency_hint`, thread it to the benchmark layer. **Status:** confirmed.

### M37 — Failure feedback drops the Critic's reasoning — `killed_by: critic_rejection` carries no substance, making prompt instruction #3 unfollowable
- **Where:** `strategist.py:350-354`. For critic kills, `failure_reason='critic_rejection'` with `failed_gate=None`, so the strategist sees only the literal string `'critic_rejection'` while the diagnostic reason lives in the dropped `critic_notes`. The prompt tells it to "change the MECHANISM if they merely tracked the market" — but the pure-beta reason is exactly what's dropped. **Fix:** include a bounded `critic_note` excerpt. **Status:** confirmed.

### M38 — LLM proposals are silently clamped / midpoint-filled / repaired with no provenance — an `llm_strategist` spec can run with system-invented params under the LLM's narrative
- **Where:** `strategist.py:378-394`. `_build` clamps, midpoint-fills missing/non-numeric params, and `_repair_params` bumps `slow_period`, then records the Hypothesis with the LLM's untouched rationale and `author='llm_strategist'` — so the stored narrative can cite parameter values the executed spec no longer has (worst case: a string `params` → all midpoints). The raw proposal is discarded. **Fix:** store raw params + a `repaired:[...]` list; reject >N repairs (fallback); state the `fast+5<=slow` constraint in the prompt. **Status:** confirmed. **Related:** compounds **M14**.

### M39 — Silent LLM→heuristic degradation is invisible in persisted results — a run whose AI calls all failed still presents as AI-critiqued
- **Where:** `critic.py:196-203`; `strategist.py:336-342`; `run.py:174`; `router.py:573-574`. Every LLM failure (dead key, provider 4xx, timeout, unparseable JSON) falls back to the heuristic with only a `logger.warning`; the heuristic returns the same dict shape, `TokenLedger.record` fires only on success, and `state.agent_mode` keeps reporting `full_ai`. A dead-key run does 0 LLM calls yet badges itself AI-driven. **Fix:** add ok/failed/fallback counters, stamp each critique `source=llm|heuristic`, downgrade the mode/banner above a fallback threshold. **Status:** confirmed. **Also found by:** `critic-llm`. **Cross-reference:** the same silent-degradation family as **H25** (max_tokens) and **M43** (model substitution).

### M40 — The heuristic critic can accept with "high" confidence without any benchmark data, and losing strategies skip the pure-beta and cost checks
- **Where:** `critic.py:297-360`. The benchmark check is gated on `bh_return > 0 and total_return > 0`, so a missing benchmark or a losing strategy skips it entirely; a strategy with `n_trades>=30, sharpe<=3, max_dd>=-0.30` gets `accept` (high if `n_trades>=100`), violating the prompt's "NEVER accept without checking benchmark." The cost/sample checks are also mislabeled (raw return magnitude, not a stressed re-run). **Fix:** flag missing benchmark as accept-blocking; check underperformance regardless of sign; treat `total_return<=0` as critical. **Status:** confirmed.

### M41 — `critic_confidence` is decorative, and the prompt's "high" calibration rule references evidence the critic is never given
- **Where:** `critic.py:77-83`; `state.py:221-226`; `loop.py:730`. Nothing downstream consumes `critic_confidence` except display; a low- and high-confidence accept are operationally identical. Worse, "high requires walk-forward validated" is unsatisfiable — `_render_evidence` has no walk-forward field (no WF gate; OOS runs after the critic). **Fix:** wire confidence into control flow (only medium+ accepts count) and drop the WF clause, or document it as advisory. **Status:** confirmed.

### M42 — `extract_json_object` is a widest-brace-span slice: stray braces, multiple objects, or raw newlines in strings discard billed LLM output
- **Where:** `agent_llm.py:21-35`. Slices first `{` to last `}` and `json.loads` the whole span (docstring claims "first object"); prose containing any `}` → None, two objects → None, a raw newline in a string → None. Each None routes to the heuristic *after* billing. **Fix:** `JSONDecoder(strict=False).raw_decode` from each `{` (first balanced parse wins); strip code fences. **Status:** confirmed (reproduced). **Cross-reference:** a mechanism behind the silent degradation of **M39**/**H25**.

### M43 — `resolve_agent_llm` silently substitutes `models[0]` when the requested model id is not found — and a test pins the silent swap
- **Where:** `agent_llm.py:81`. `next((m for m in models if m.model_id==model), None) or models[0]` — any id mismatch resolves to the provider's first model, with its pricing and *its leakage class*, with no log. For BytePlus `models[0]` is the mechanism-only pro while a mistyped lite request would run a different leakage class than selected. **Fix:** return None (caller downgrades to rule_based with a warning) or log the substitution and record the effective model. **Status:** confirmed. **Cross-reference:** feeds the leakage-honesty gap of **H31**.

### M44 — `TokenLedger` treats unknown model pricing as €0 — `used_eur` (the declared "ground truth" cost) reads €0.0000 and the € budget cap never binds
- **Where:** `agent_llm.py:82-117`. `float(mi.input_price_per_m or 0)` accumulates €0/call, so a paid but unpriced model shows €0.0000 in the HUD and Director R2's `used_eur >= max_eur` cap can never trigger — the advertised "€50 cap" is unenforceable for exactly those models. **Fix:** carry pricing as `float|None`; refuse AI mode or track `cost_known=false` and surface "unknown (N tokens)"; never feed a fabricated 0 into the cap. **Status:** confirmed. **Also found by:** `llm-infra`.

### M45 — `Decimal('0')` truthiness in `/ai/models` maps genuinely free models to null pricing — "free" becomes "unknown" and the free-model UI path is unreachable
- **Where:** `api/routers/ai.py:208-209`. `float(m.input_price_per_m) if m.input_price_per_m else None` — `Decimal("0")` is falsy, so a free model (zhipu glm-4.5-flash, priced 0/0) is served as `null`, the cost helper says "unknown — no pricing configured," and the cheapest-model auto-picker sorts the free model to the *bottom* (`?? 1e9`). **Fix:** explicit `is not None` check; contract test that 0 round-trips as 0. **Status:** confirmed.

### M46 — The run-level OOS descriptor says "passed out-of-sample" if any single candidate passed, even when others failed
- **Where:** `report_generator.py:235,249-252`. `oos_pass = count(PASS)`; `d["oos"] = "passed" if oos_pass else "failed"`, ignoring `oos_failed`. With 1 PASS and 3 FAILs the LLM is told the run "passed out-of-sample." Related: the "best survivor" is picked by raw in-sample Sharpe (a hold-out-failed candidate can outrank a validated one), and missing benchmark defaults to 0.0 → "unknown" becomes "positive excess." **Fix:** tri-state descriptor; prefer validated/PASS survivors; "benchmark unavailable" instead of 0.0. **Status:** confirmed.

### M47 — The persisted audit trail stamps events and candidates with flush-time phase/lineage/timestamp instead of emission-time values
- **Where:** `persistence.py:117-131,177`; `router.py:377-378`. The 2-second flusher writes every buffered event with `phase=run.phase`, `lineage_id=run.current_lineage`, and an INSERT-time timestamp, so a batch shares one timestamp and the *current* phase/lineage; a candidate found just before a `next_asset` decision is attributed to the wrong lineage, which then feeds `/candidates`. **Fix:** capture ts/phase/lineage at emission time; store lineage on the Candidate at creation. **Status:** confirmed.

### M48 — The Director has no rule for persistent "skipped" outcomes — zombie spin on the last asset burning LLM calls and wall-clock *(contested)*
- **Where:** `loop.py:549-560,151-190,473-477`. On `BudgetExceededError`, `outcome='skipped'` leaves all counters untouched, so R1-R4 can never newly fire and R5 (fairness) is disabled on an empty queue; once the budget controller rejects permanently (reachable via H19/H20), the loop returns `continue` forever and each iteration still runs the paid strategist call. **Fix:** track `consecutive_skips`, add a Director breaker, or check budget before the strategist call. **Status:** confirmed-contested (mechanically confirmed; a lens noted the wall-clock/T6 backstop eventually terminates → tiebreak upheld the wasted-cost concern at medium).

### M49 — The plateau watermark includes Sharpe from gate-failed and critic-rejected trials
- **Where:** `loop.py:786-789,183-185,137-142`. `best_sharpe_on_asset` appends `max(sharpe, prev)` for `gate_fail`/`critic_reject`/`candidate` alike, so one overfit strategy with a huge raw Sharpe that FAILS the gates permanently raises the watermark and makes genuinely improving gate-passing candidates register as zero progress → the asset is abandoned as `asset_exhausted`. **Fix:** track the watermark on gate-passing Sharpe only (or two series). **Status:** confirmed (confidence medium).

### M50 — `parse_criteria` / `check_target_reached` / `candidate_meets_criteria` are dead code (zero callers) *(contested)*
- **Where:** `ai/goals/criteria.py:35-117`; `planner.py:293`. The entire structured-criteria enforcement path is never invoked; run creation parses only scope (symbol/strategy pools), not criteria. This is the mechanism behind **C3**. **Fix:** wire the parser at run start and evaluate candidates against it (after fixing **H30**), or delete and stop implying criteria are enforced. **Status:** confirmed-contested (a lens read some callers as reachable at a different repo root; tiebreak confirmed zero callers within `backtesting-agent`). **Cross-reference:** the direct cause of **C3**, gated by **H30**.

### M51 — Pausing a run consumes its wall-clock budget — resuming after a long pause immediately terminates the run as `budget_exhausted`
- **Where:** `loop.py:479-486`; `state.py:60-61`; `loop.py:175-177`. The cooperative pause (`while control()=="pause": sleep(0.4)`) never adjusts the wall-clock budget, so a run paused overnight resumes and gets one more trial before the Director declares `budget_exhausted`. **Fix:** accumulate paused duration and subtract it from elapsed. **Status:** confirmed. **Also found by:** `loop-state`.

### M52 — The create-run request is server-validated only for mode/window: `agent_mode`, `rigor`, `model`, and all budget numbers pass through unvalidated and are silently coerced while the DB records the raw request
- **Where:** `router.py:39-76`; `run.py`. `agent_mode` is a free string (any non-`rule_based` value resolves an LLM, sets a provider leakage marker, then makes zero LLM calls); `rigor` silently falls back to `standard`; `model` mismatches hit **M43**; budget numbers are un-bounded. The DB records the requested (not effective) values — a silent spec mismatch in the reproducibility record. **Fix:** `Literal` enums for mode/rigor, `Field(ge=…)` for budgets, persist the effective model/mode. **Status:** confirmed.

### M53 — DB-sourced timestamps are serialized without a UTC offset and the frontend parses them as local time — activity-stream times wrong by the UTC offset for every non-UTC user
- **Where:** `persistence.py:714-731`; `router.py:881-895`; `console.tsx:301`. SQLite round-trips drop tzinfo, so the offset-less ISO string is parsed as *local* time by `new Date(...)`; a Berlin user sees every event 2 hours in the past. Events always come from the DB, so this affects every run. The `/state` `started_at` also uses two different formats across code paths. **Fix:** append `Z`/`+00:00` at every DB→JSON boundary. **Status:** confirmed (reproduced).

### M54 — Backend restart leaves paused runs as unrecoverable zombies: never marked interrupted, resume/stop 404, frontend polls forever
- **Where:** `persistence.py:243-255`. `mark_orphaned_runs_interrupted` flips only `status=='running'`; a paused run's DB row says `paused`, so after restart `/state` reports `paused` (non-terminal → polls forever), the UI shows Resume, but `/resume` and `/stop` 404 because the in-memory record is gone. **Fix:** include `paused` in the orphan sweep (`status.in_(("running","paused"))`). **Status:** confirmed.

### M55 — The research-loop cost model silently drops the documented spread/slippage defaults — inconsistent with the CLI path and the config schema
- **Where:** `executor.py:47-48,75-83`; `run.py:194`; `cli.py:307-309`; `config/schema.py:35-40`. `ResearchExecutor()` uses commission-only (10 bps/side) while the CLI folds spread+slippage (14.5 bps/side); the `costs/` modules are imported nowhere in the research path, and there is no `StartRunRequest` knob. **Fix:** build the research commission the same way the CLI does; surface effective bps/side; expose it in the request. **Status:** confirmed. **⚠ Cross-reference / contradiction:** identical root cause to **H29**, filed at *high* by `extra-cost-model-math` and *medium* by `fresh-oss-user`; treat as one **high** issue.

### M56 — `provider_leakage` precedence is optimistic (mechanism_only before risk); reused for the run badge it can silently suppress the risk warning
- **Where:** `ai/leakage.py:48-53`; `console.tsx:163-170`. The roll-up returns `mechanism_only` before checking `risk`, so a provider shipping both a clean and a risk model summarizes to `mechanism_only`; since the console warns only on `state.leakage==='risk'`, a run that used the risk model would show no warning the moment a mixed provider is added. **Fix:** pessimistic precedence (`risk` first) for run/honesty contexts, or use `model_leakage(model_id)` per **H31**; keep optimistic roll-up only for the "does this provider offer a clean option" dropdown. **Status:** confirmed (confidence medium). **Cross-reference:** compounds **H31**.

> **Cross-reference — determinism is unwired.** M57, M58, M59 (and low note N28, plus M12) are the determinism cluster: the fingerprint API, the CI gate, and the env-pinning function are each independently non-functional, so the "reproducible baseline" premise the module advertises does not exist at runtime. R4/R5 in the appendix are the two determinism claims that were *refuted* (over-stated), so the honest picture is "mostly unwired, not entirely broken."

### M57 — The determinism fingerprint API is dead code — no run computes or stores `h_strict`/`h_loose`/`h_config` *(contested)*
- **Where:** `backtesting/determinism.py:1-25,305-350`. `compute_run_fingerprint`/`RunFingerprint`/`apply_determinism_env`/`compute_h_*` have zero non-test callers; the runner, dispatcher, optimizer, and results store never compute or persist a fingerprint. **Fix:** wire `compute_run_fingerprint` into `run_backtest`/the results store, or downgrade the docstring from an asserted guarantee to "not yet enforced." **Status:** confirmed-contested (grep-verified zero callers; a lens argued the abstract premise doesn't make it a defect → tiebreak upheld the advertise-vs-deliver gap).

### M58 — The determinism CI gate cannot run — the reference runner script and golden snapshot are absent from the repo *(contested)*
- **Where:** `tests/unit/backtesting/test_determinism.py:222-293`. No `scripts/` dir (so `check_backtest_determinism.py`/`freeze_yfinance_snapshot.py` are missing) and no `data/golden/`, so every `@pytest.mark.determinism` test (including `test_matches_golden_hash`) silently *skips* — golden-hash drift is never caught, and the committed golden JSON references a monolith SHA. **Fix:** port the scripts + a committed golden snapshot; add a CI job that fails (not skips) when the snapshot is missing; regenerate the golden under this repo's SHA. **Status:** confirmed-contested (mechanically confirmed; tiebreak upheld against a lens that read the skip as acceptable).

### M59 — `apply_determinism_env` is a no-op for its stated purpose even if it were called *(contested)*
- **Where:** `determinism.py:367-388`. Runtime `os.environ['PYTHONHASHSEED']` is inert (consumed only at interpreter startup); the BLAS thread caps are read at native-lib import, but `determinism.py` imports numpy at module top, so by the time any caller runs, numpy is already imported; and `setdefault` cannot correct a pre-existing wrong value. **Fix:** set env in a launcher/`sitecustomize` before numpy import (or re-exec), use `threadpoolctl.threadpool_limits(1)` at runtime, replace `setdefault` with explicit assignment. **Status:** confirmed-contested (all three mechanics verified; tiebreak upheld against a lens that felt the low-level facts didn't rise to a "defect").

### M60 — "Regime breakdown" labels bull/bear/sideways from the STRATEGY's own equity returns, not the market — mislabeled in the dossier and fed to the critic as regime dependence
- **Where:** `loop.py:195-222`; `executor.py:87-91`; `candidates/[hash]/page.tsx:212-228`; `critic.py:307-321`. `_compute_regime_analysis` receives the strategy's equity returns (`np.diff(eq)/eq[:-1]`), splits them into thirds, and labels each "bull" if the *strategy's* cumulative return in that third exceeds +5%. The dossier renders this as market "Regime breakdown," and the critic rejects for "regime concentration" on it. A flat market where the strategy made money is mislabeled "bull." **Fix:** compute regime labels from the asset's close-to-close returns (available in the executor), or rename to "Performance by sub-period." **Status:** confirmed. **Also found by:** **five** reviewers — `metrics`, `persistence-results`, `fresh-quant`, `fresh-institutional`, `fresh-oss-user`.

---

## Low findings (confirmed)

- **L1 — MACD cross detection guarantees a spurious SELL on bar 0 (`fill_value=True`); Stochastic has the mirror first-valid-bar cross.** `indicators/trend.py:140-148`; `momentum.py:117-130`. At bar 0 `macd==signal==0`, so `cross_down` fires → SELL on the first bar of every dataset; contributes −weight in the voting ensemble. **Fix:** `fill_value=False` + require warmed-up previous bars (the min_periods fix from H12 solves both). **Status:** confirmed.
- **L2 — Smart-activity gate: normal quantiles used as `t*` at N as low as 5, calibrated circularly on the generator it filters, with the cited calibration doc missing.** `gatekeeper.py:27-37`; `basic_gates.py:126-171`. `activity_t=1.0/1.65/2.33` are z-quantiles applied to a Student-t statistic (df=N-1); at df=4 the implied ~95% is ~2x overstated; the calibration doc `SMART-ACTIVITY-CALIBRATION.md` is not in the repo. **Fix:** Student-t critical values, or raise the floor to N≥30; ship or drop the doc. **Status:** confirmed.
- **L3 — `CostStressGate`/`LagFragilityGate` nest their payload under `details['details']`, so regime weakness reasons come back empty.** `cost_stress_gate.py:48-79`; `lag_gate.py:34-65`; `canary.py:75-96`. These gates pass `details={...}` (captured as `**details` under key `details`) while siblings spread flat; `loop.py:752` reads `_r.get('details').get('reason')` → `''` for the nested shape, so regime SOFT-gate weaknesses render blank. **Fix:** spread flat, or flatten a `details` kwarg defensively; extend the flat-shape test to all gates. **Status:** confirmed.
- **L4 — Pruner configuration is dead code: the objective never reports intermediate values, so median/hyperband pruners and `pruner_warmup_trials` do nothing.** `optimizer.py:127,150-186,234-251`. No `trial.report`/`should_prune` anywhere; every trial runs to completion. **Fix:** implement staged evaluation or default `pruner='none'` and document. **Status:** confirmed.
- **L5 — `check_gaps` flags every US market holiday as a missing trading day, contradicting its docstring; `fill_gaps` would fabricate holiday bars with forward-filled volume.** `marketdata/quality.py:64-96,231-267`. `bdate_range` excludes only weekends, so ~9 "missing" days/year inflate `total_issues` and train users to ignore the report. **Fix:** use a NYSE/holiday calendar; fill Volume with 0, never synthesize non-trading bars. **Status:** confirmed.
- **L6 — Survivorship-biased current-constituent universes with no user-visible disclosure; `config/nasdaq100.yaml` is dead config.** `config/nasdaq100.yaml`; `assets.py:29-77`. All universes are today's members (PLTR/MSTR/APP/ARM entered *because* they performed); the only disclosure is a YAML comment no surface renders; the YAML is never parsed. **Fix:** README + report "Data limitations" section; wire or delete the YAML; tag results with a survivorship flag. **Status:** confirmed.
- **L7 — `_downsample_curve` stride sampling visually flattens drawdowns and drops the final equity points.** `loop.py:225-236`. Keeps every ~19th bar for a 2265-bar window, so sub-19-bar crashes vanish from the "Evidence drill-down" chart (which then shows less risk than the `max_drawdown` metric claims), and the true last point is excluded. **Fix:** extreme-preserving downsample (per-bucket min/max or LTTB) + always append the last point. **Status:** confirmed.
- **L8 — Candidate artifacts are never fully persisted: only a 120-point downsample survives, `run_artifact_id` dangles, and the schema docstring claims a parquet store that is never written.** *(contested)* `persistence.py:162,171-175`; `db_models.py:7-9`; `executor.py:104-123`. `executor.run()` returns no `run_id`, so `run_artifact_id` is always a random uuid referencing nothing; the full curve/returns/trade list are discarded each iteration. **Fix:** persist full artifacts keyed by `run_artifact_id`, or delete the dangling id and correct the docstring. **Status:** confirmed-contested (code-behavior confirmed; a lens read it as documentation-only → tiebreak upheld).
- **L9 — `ModelInfo.supports_json_mode` defaults to True, so `response_format=json_object` is sent to models never validated for it → provider rejection triggers total silent degradation.** `ai/models.py:22`; `deepseek.py`; `byteplus.py`; `agent_llm.py:88`. deepseek-reasoner, both BytePlus models, and the Anthropic shim inherit True; a rejection routes the whole call to the heuristic. **Fix:** default False, set True only on verified models, or catch the rejection and retry once without json_mode. **Status:** confirmed. **Also found by:** `strategist-llm`.
- **L10 — "investigate" is downstream-identical to "reject" in robustness mode, contradicting the verdict contract given to the model and inflating reported critic rejections.** `loop.py:702-717`; `critic.py:81`. `_critic_no = _rec in ("reject","investigate")` kills both; the model's calibrated middle verdict is a lie and reports over-count rejections. **Fix:** implement a real investigate path (accept + low-confidence tag) or collapse the prompt contract to accept/reject. **Status:** confirmed.
- **L11 — Regime DG-1 invariant violated: a critic "investigate" can RAISE candidate confidence from very_low to low.** `loop.py:754-761`. `candidate.confidence = "very_low" if reject else "low"` overwrites the gate-derived tier *unconditionally*, so an investigate verdict bumps a very_low candidate up — the "critic only lowers" invariant is broken for the weakest ideas. **Fix:** take the minimum against the existing tier; add a test. **Status:** confirmed.
- **L12 — `validate_narratives()` scans only 6 of 8 sections despite claiming "all narrative slots"; the production belt-and-suspenders swallows its failures.** `reporter.py:99-104`; `report_generator.py:347-351`. `dsr_analysis` and `oos_status` are unscanned — and `dsr_analysis` is the one dynamically-assembled rule-based narrative; the post-LLM call is wrapped in `except: pass`. **Fix:** iterate all 8 sections; on failure revert to the template. **Status:** confirmed.
- **L13 — The digit-only scanner cannot catch spelled-out quantitative claims, which the prompt actively encourages.** `reporter.py:17-22`. "returns nearly doubled," "two-thirds of trades won," "½," "⅔" all pass; the prompt says "Describe magnitudes in WORDS." **Fix:** add a word-number lexicon and `\N{...}` fraction/superscript classes, or soften the "cannot fabricate numbers" claim to "digit-based figures." **Status:** confirmed.
- **L14 — Provider USD list prices are labeled and displayed as EUR throughout; `engine.py` calls the identical arithmetic `estimated_cost_usd`.** `providers/deepseek.py:12-18`; `agent_llm.py:44-45`; `engine.py:33`; `cost.ts:8-9`. The hardcoded prices are the providers' USD cards, fed into `Budget.used_eur` and shown with € signs — a systematic ~5-15% FX mislabel, and the codebase itself can't decide (USD vs EUR field names). **Fix:** pick one currency; apply an explicit FX rate if converting; unify the two fields. **Status:** confirmed.
- **L15 — `GET /runs/preview` interprets the goal into a symbol/strategy pool that `POST /runs` ignores — a goal-only run silently researches hardcoded AAPL.** `router.py:519-546`; `run.py:111-112`. `parse_goal_scope` runs only in preview; `run_research` defaults `assets=['AAPL']` with no goal parsing. **Fix:** apply `parse_goal_scope` in `POST /runs` when pools are empty (echo the resolved scope), or document goal_text as a label only. **Status:** confirmed.
- **L16 — The event-stream polling fallback can permanently drop the tail of a run's events (terminal status races the final DB flush) and duplicates events when polls overlap.** `hooks.ts:93-163`; `router.py:404,421`. Status turns terminal before the final flush commits; polling stops on the terminal status, and the single immediate poll can run before commit. **Fix:** keep polling until N empty batches after terminal (mirror the SSE drain); add an in-flight guard + id-based dedupe. **Status:** confirmed (confidence medium).
- **L17 — Alpha is reported/stored as a raw per-bar intercept, never annualized — misleadingly tiny and non-comparable across intervals.** `benchmarks/market.py:33-57,99-106`; `registry/models.py:161`. A daily alpha of 0.0005 (~13%/yr) is shown as 0.0005, and the same intercept means something different on weekly bars. **Fix:** annualize with the interval-derived `periods_per_year` (the C2 factor) and label it. **Status:** confirmed (confidence medium; `compute_market_benchmark` currently has no live caller).
- **L18 — Spread docstring says "half-spread" but every consumer divides by 2 again (2x ambiguity/understatement).** *(contested)* `costs/spread.py:11,47,52-61`; `model.py:51,65`; `cli.py:308`. `default_bps` is documented as the half-spread but `spread_half = price*(bps/10_000)/2` applies only a quarter-spread per side if the docstring is right. **Fix:** treat `default_bps` as the FULL bid-ask spread (keep the /2) and fix every docstring to say so; pin the round-trip cost in a test. **Status:** confirmed-contested (a lens argued the code implies full-spread so there's no numeric bug; tiebreak upheld the doc/convention ambiguity as a real latent defect).
- **L19 — The entire `costs/` "realism model" package is dead code with a rival inline implementation.** `costs/__init__.py:1-43`. `SpreadSimulator`, `SlippageModel`, `CostConfig`, `commission_callable`, and all sizers have zero non-test callers and zero tests; the real cost math is inline in `cli.py` and re-implemented again in the executor (which drops spread/slippage — H29/M55). **Fix:** wire `CostConfig.as_callable()` as the single cost source, or delete the package; test whichever remains. **Status:** confirmed.
- **L20 — Undocumented per-side commission doubling and mixed per-side/round-trip conventions in the cost formula.** `cli.py:306-309`. The scalar is charged on both legs; the formula halves spread but not commission/slippage, so `commission_pct` and `slippage_bps` are effectively doubled (2x round-trip) while spread becomes a full round-trip — with no per-side/round-trip note in the schema or runner docstring. **Fix:** document the per-side vs round-trip semantics or normalize to one convention. **Status:** confirmed.
- **L21 — Sizers floor share count to zero (silent no-trade) and are never wired into the engine.** `costs/sizing.py:47-48,76-78,135-139`. `math.floor(raw)` returns 0 for high-priced assets/small equity with no warning; `create_sizer` has no callers. **Fix:** round up to 1 (capped) or return a typed "insufficient equity"; wire `ISizer` in or delete. **Status:** confirmed.
- **L22 — `parse_criteria` never parses return/win_rate/profit_factor goals → they silently collapse to the default "Sharpe >= 1.0."** `ai/goals/criteria.py:12-28,51-95`. `METRIC_ALIASES` defines them but no regex emits them; a "profit factor > 2" goal falls to the Sharpe default. **Fix:** add regex branches (or an LLM parse) for each alias. **Status:** confirmed. **Cross-reference:** part of the goal-criteria cluster with C3/H30/M50.
- **L23 — Date-withholding anti-leakage is undermined by passing the raw user goal (which typically names the period) to the LLM strategist and critic.** *(contested)* `strategist.py:365-366`; `critic.py:255-256`. Regime prompts withhold dates but both agents receive `research_goal = self.goal` verbatim; a goal like "the 2022 hiking-cycle bear" re-identifies the hold-out window. **Fix:** scrub/flag date-like tokens in regime mode, or escalate the leakage marker to "dates disclosed via goal." **Status:** confirmed-contested (a lens judged the residual leakage negligible given other controls; tiebreak upheld the wiring gap). **Also found by:** `strategist-llm`, `critic-llm`.

---

## Per-area verdicts

- **engine-runner** — A mostly-sane thin wrapper around `backtesting.py 0.6.5`: correct signal-to-fill timing (decide bar-*t* close, fill *t+1* open), validated commission, NaN warm-up guarded in the shipped strategies (no same-bar look-ahead in the default path). Fragility is in the layers around the single run — walk-forward has three compounding defects (C1, H6) that can stamp `is_strategy_validated=True` on a strategy that never traded OOS; plus `finalize_trades` unset (H7), NaN bfill look-ahead (M1), and a non-leaky canary control (H8).
- **strategies** — Mechanically clean at the bar loop: causal `self.I` transforms, `crossover` with no peeking, next-open fills, long-only clean exits, Wilder RSI verified numerically. Problems are naming/wiring: `BollingerBreakout` is mean-reversion (M15), the event gate is honored by only one strategy (H13), `create_with_params` swallows typos (M14), and `MultiIndicator` carries the pre-F-014 RSI (M16).
- **indicators** — Splits in two. The legacy Decimal indicators are textbook-correct with reasonable tests. The pandas `BacktestIndicator` library the engine actually consumes is where the defects live: no warm-up masking → directional signals from bar 1 (H12), ADX strength→BUY (H11), zero-loss RSI NaN (M16), bar-0 spurious MACD SELL (L1), the generator crashes Optuna (M17), and there are zero tests (M18).
- **metrics** — A thin `backtesting.py` wrapper (correctly unit-normalized after F-013) plus broken custom re-implementations: Sortino downside deviation (H9), 999.99 sentinels (H10), Calmar arithmetic (M2). The DSR formula itself is a faithful Bailey & López de Prado implementation, but the runtime wiring feeds it the wrong (annualized) units (H1).
- **dsr-stats** — The DSR core formula is correct (expected-max-SR term, PSR denominator). The runtime wiring destroys the statistic: annualized variance into a per-period formula (H1), per-run *N* that resets (H2), a magic-number variance floor in the wrong units (M24). The gate architecture (ordered pipeline, provisional flags) is thoughtfully designed but its output is not honest to the formula.
- **gates** — Clean ABC/pipeline design (cost-ranked ordering, hard-fail short-circuit, `per_trade_t` with correct `sqrt(N)`). Fragile at the boundaries: units break where the docstring warns (H1), `gates.default.yaml` is unread (H4), the benchmark gate is near-vacuous (M19), presets don't bind below 0.5 (M20), the canary and lag gate are dead (M22, M23), and kill-cause attribution is wrong (M21).
- **optimizer** — Small, mostly-clean Optuna plumbing; walk-forward correctly sees only `train_df`, and the AI loop never invokes Optuna. But crashed trials become −inf COMPLETE trials (M8), the composite mixes units (M4) and ignores unknown keys (M9), walk-forward drops YAML settings (M10) and has an exploding overfitting score (M11), and seed/pruner plumbing is dead (M12, L4).
- **lockbox-oos** — The *ideas* are institutionally sound (separate DB, PASS/FAIL-only contract, terminal immutable results, per-lineage budget, fixed IS window). The *wiring* defeats nearly every safeguard: fresh lineage per candidate (H14), sign-only pass bar (H3), stale window (H15), swallowed AlreadyEvaluatedError (H16), error→terminal-FAIL (H17), cold-start (M26), auto-stamped human token (N9).
- **regime-holdout** — The P2 select-on-train core is genuinely well built (deterministic `train_end`, TRAIN slice to strategist/fallback/critic, hold-out t-stat on hold-out trades only, thin slices stay unvalidated). But the hold-out is reused across candidates and used for ranking (H18), `regime_validated` is near-unreachable (M27), goal_met counts failed ideas (M28), decay ratio blows up (M29), and there is no test of the wiring (M30).
- **marketdata** — Good bones (clean ABC, frozen-parquet determinism mode, content-hashed snapshots, honest capability registry). Fragile everything between: adjustment semantics never modeled (H21, H22), tz dedup bug (H23), survivorship gate bypassed (H24), Yahoo end-exclusive mismatch (M32), Tiingo duplicate columns (M33), CoinGecko ignores the window (M34).
- **executor** — The spec→config→metrics translation is largely faithful (templates match class attributes, params clamped to bounds, units consistent). Failure propagation is mostly clean. But it drops spread/slippage (H29/M55), records misnamed params (M14), and the DSR-annualization defect surfaces here too (H1).
- **loop-state** — The core state machine is genuinely well-built (one outcome per iteration by assert, single Director decision point, correct counter resets, spec-faithful rule ordering, persistent RNG). Fragility is at the seams: budget caps inert (H19), OOS error→FAIL (H17), pause burns budget (M51), goal_met counts unvalidated (M28), flush cursors before commit (H27).
- **persistence-results** — Architecturally thoughtful (per-user ownership, live-preferred/DB-fallback, append-only records, digit-free Reporter, honest `aggregate_stats`). The fragile core is the non-invasive flusher: flush-time stamps (M47), cursors before commit (H27), only a 120-point downsample survives with a dangling artifact id (L8, L7).
- **strategist-llm** — Better engineered than most: explicit JSON contract, system-fixed window enforced in code, bounded failure context that withholds numeric thresholds, shared dedup with the fallback, tokens billed before parsing. Seams: 700-token cap truncates reasoners (H25), critic reasoning dropped from feedback (M37), silent clamp/repair with no provenance (M38), goal text leaks the period in regime mode (L23).
- **critic-llm** — Better than most "LLM judge" code: real blind isolation on the LLM path (allowlist provably strips leaks), pre-call budget guard, kill verdict genuinely un-ignorable. The fragile half is around the LLM call: mode-unaware heuristic hard-rejects <30 trades (H26), accepts "high" without benchmark (M40), decorative confidence (M41), investigate==reject (L10), DG-1 invariant violation (L11).
- **reporter** — Core design is sound and better than most platforms: numbers live only in `numeric_fields`, the LLM sees digit-free descriptors (pinned by test), each section scanned before assignment, failure degrades to honest templates. The scanner itself is the weak spot: the `{{...}}` carve-out is a live bypass (H28), only 6 of 8 sections scanned (L12), spelled-out numbers slip through (L13), and the run-level OOS descriptor over-claims (M46).
- **director** — The rule-based Director is clean and well-pinned (sensible precedence, deterministic, evidence-carrying, T6 backstop). Fragility is in the integrations: budget subsystem is dead code (H19, H20), no rule for persistent skips (M48), plateau watermark polluted by gate-failed Sharpe (M49), inconsistent DSR registry inputs (M25).
- **llm-infra** — Better than typical: real API token counts (never estimated), correct per-1M arithmetic, EUR budget checks, rule-based fallback everywhere. But the safety nets fail *silently*: wrong model id → `models[0]` (M43), unpriced model → €0 and no cap (M44), errors/unparseable → heuristic with no trace (M39), free model → null pricing (M45), USD labeled EUR (L14), brittle JSON extraction (M42).
- **api-contract** — Thoughtful for honest presentation (leakage markers, UNVALIDATED firewalls, live-preferred reads, monotonic SSE cursor). Fragile at the edges: only mode/window validated (M52), flush cursors before commit (H27), tz-less timestamps (M53), paused-run zombies (M54), pause burns budget (M51), preview scope ignored by POST (L15).
- **fresh-quant (hostile end-to-end trace)** — The deterministic core is genuinely thoughtful and the digit-free report is better honesty engineering than most open-source backtesters. But a "validated/survived all gates" claim cannot be trusted today for cross-component reasons: DSR annualization (H1), warm-up gaps (C1/M26), OOS budget churn (H14), regime mislabeling (M60), inert budgets (H19).
- **fresh-institutional (practice gap)** — Good institutional instincts (ordered cheap-to-expensive gates, isolated critic, PASS/FAIL-only OOS, select-on-train, digit-free reporter, honest limitations text). Execution does not yet deliver: DSR never binds correctly (H1), no whole-search multiplicity accounting (H2/H18), OOS bar near-coin-flip (H3), default flow has no OOS (H5), robustness gates inert (M23), cold-start bias (M26).
- **fresh-oss-user (release-day skeptic)** — A far more self-aware release than most: README claims check out, UI labels regime UNVALIDATED, discloses two no-op gates, marks DSR provisional, enforces digit-free narratives, and the falsification-first framing is honest and rare. Fragile: DSR scale error (H1), OOS budget/window (H14/H15), cost model understated (M55/H29), silent LLM fallback, leakage docs not shipped (N26).
- **extra-benchmarks-annualization** — The benchmark layer is correct for daily equity but interval-blind now that 1wk/1h are supported: every Sharpe-like stat hardcodes `sqrt(252)` (C2), the gate compares incompatible estimators (M5/M6), AlphaVantage is unadjusted (M35), alpha is never annualized (L17), and two total-return conventions coexist (N16).
- **extra-cost-model-math** — A self-consistent-looking "E-6 cost & realism model" that is almost entirely dead (L19); the load-bearing math is inline in `cli.py`, and the paths already disagree — the AI executor drops spread/slippage (H29/M55), commission is doubled per-side without documentation (L20), the spread docstring contradicts the code (L18), sizers floor to zero (L21).
- **extra-goals-criteria-decorative** — The user's numeric goal criteria are decorative end-to-end: completion is decided on candidate count (C3), the criteria parser is dead code (M50), the live drawdown check is vacuous (H30), return/win_rate/pf are never parsed (L22), and the docstring claims a UI that doesn't exist (N27).
- **extra-leakage-marker-granularity** — The flagship 3-state leakage badge is correct as a per-provider key-management chip but is computed one granularity too coarse for a *run*: it rolls `mechanism_only` up over risk/unvalidated siblings and never records the model that executed (H31), and the roll-up precedence is optimistic (M56).
- **extra-determinism-repro-unwired** — `determinism.py` is well-written in isolation (two-tier hash, order-invariant strict, tolerant loose) but almost entirely inert: the fingerprint API has zero callers (M57), the CI gate can't run (M58), `apply_determinism_env` is a no-op (M59), the seed is dead (N28), and `h_config`'s data component is a constant (refuted as over-stated — R5).
- **extra-currency-fx-blind** — No operative currency awareness in returns, benchmark, or cash: alpha/beta regresses non-USD assets against SPY (H32), there is no currency field anywhere (M36), and cash is unit-less with no cross-currency normalization (N29) — relevant because the German `.DE` universe is first-class.

---

## Appendix A — Refuted findings

These claims were killed by verification and are recorded for completeness only.

- **R1 — "DSR provisional-pass below 20 trials is indistinguishable from a real pass downstream; test pins the bypass."** *(was high, gates)* — **Refuted:** the mechanical facts hold (unconditional provisional pass below 20 trials), but verification showed the `provisional` flag *is* surfaced downstream (quality.py, the digit-free report, the UI mark DSR "provisional"), so the central thesis — that the dossier shows a plain PASS and over-claims significance — is false. The underlying units/N problems remain real and are captured by H1/H2/M24.
- **R2 — "`get_or_fetch` tail-staleness refresh overwrites the head-backfill `fetch_start` — requested history silently never fetched."** *(was high, marketdata)* — **Refuted (tiebreak):** the code path is read correctly, but the head-shortfall and tail-staleness branches do not clobber each other in the way claimed; the requested history is fetched. The abstract principle (silently shorter window than configured) is valid but does not occur here.
- **R3 — "Default (robustness) Strategist/Critic prompts contain no mechanism-only / anti-recall framing."** *(was high, strategist-llm)* — **Refuted (tiebreak):** the prompt asymmetry is real (regime prompts have anti-recall framing, robustness prompts do not), but the quant case for treating it as a material high-severity leakage vector did not survive — the robustness window is fixed/public and the effect on results is not demonstrable at high severity.
- **R4 — "Critic infrastructure failure is booked as a research failure (`critic_rejection`), not an error — wrong breaker, wrong attribution, budget burn."** *(was medium, director)* — **Refuted:** the mechanical description is accurate, but the production critic's exception handling routes infra failures differently than the finding assumed, so the "wrong breaker / mis-attribution" conclusion does not hold.
- **R5 — "`h_config` data-snapshot component is a constant 'missing' in production, so it is not bound to the actual data."** *(was medium, determinism)* — **Refuted:** the literal observations are correct (`_data_snapshot_sha()` returns "missing" when the golden file is absent), but since the whole fingerprint subsystem is unwired (M57), there is no production run computing `h_config` at all, so the "degraded guarantee" is moot rather than a distinct live defect.

---

## Appendix B — Low-severity notes (unverified, not adversarially checked)

Recorded as plausible-but-unconfirmed; each was a low-severity observation that did not receive a verification lens.

- **N1** — `SentimentAwareRebound` measures TP/SL against the signal-bar close, not the actual next-open fill (`sentiment_aware_rebound.py:116-141,170-172`); tight ±0.8%/−0.5% brackets on 15m bars distort which exits fire on gaps.
- **N2** — Bollinger Bands use sample std (ddof=1) instead of the standard population std (ddof=0) (`volatility.py:49`; `bollinger_breakout.py:44,51`); bands ~2.6% wider than TA-Lib.
- **N3** — Ichimoku `compute_full` exposes `chikou = Close.shift(-kijun)` — a future-close column presented like any other indicator (`trend.py:259-267`); unused today but a look-ahead footgun for any consumer.
- **N4** — Legacy Decimal RSI returns 100 (SELL) for a perfectly flat series (`indicators/rsi.py:57-58`); a flat market is neutral, not maximally overbought.
- **N5** — `compute_alpha_beta` aligns strategy/benchmark by prefix truncation, not by date (`benchmarks/market.py:41-47,79-82`); misaligned series bias beta toward zero and can flip alpha's sign.
- **N6** — Trial-SR variance uses ddof=0 in production but ddof=1 in the integration test (`loop.py:640`); ~2.5% anti-conservative on sqrt at N=20, exactly where the DSR gate first binds.
- **N7** — `per_trade_t` fabricates `t=99.0` for identical positive trade returns (`basic_gates.py:39-41`); a fake statistic that can also mint `regime_validated`.
- **N8** — ATS-181 search knobs (timeout, n_jobs, early_stop_patience, warmup) are unreachable from any user surface; the early-stop callback is unsynchronized under `n_jobs>1` (`optimizer.py:81-84,254-285`).
- **N9** — The "human approval" promotion token is auto-stamped `approver="auto"` for every candidate (`loop.py:336-344,356-364`); the documented human-in-the-loop gate does not exist.
- **N10** — IS/OOS boundary inclusivity depends on the injected fetcher's end-exclusivity, with inconsistent `window_end` fallbacks (`loop.py:370,570`); an inclusive-end fetcher shares one boundary bar between train and OOS.
- **N11** — `iter_rolling_windows` hangs forever on a zero-step period and yields truncated final test windows (`marketdata/windows.py:51-72,139-155`).
- **N12** — `strategy_hash` omits window/bar_size, and the RuleBasedStrategist force-random fallback can re-propose an already-tried spec, double-counting toward the goal (`strategist.py:80-86,153-157`).
- **N13** — `total_valid_trials` counts skipped/error iterations, the DB-fallback `total_iterations = used_runs`, and the benchmark narrative over-claims in regime mode (`report_generator.py:135-138,156-159`).
- **N14** — Unknown `strategy_families` silently widen the search to ALL templates and the prompt then presents them as "allowed" (`strategist.py:199-208`).
- **N15** — Two total-return conventions across benchmark modules (close-ratio vs product-of-returns), and `backtesting.py`'s own buy&hold return is computed then overwritten (`market.py:93`; `buy_hold.py:53`; `runner.py:329,277`).
- **N16** — Regime confidence cap ("at most medium") is prompt-only; `_parse_verdict` passes "high" through (`critic.py:121,259-278`).
- **N17** — `_window_months` silently yields a "~0-month market window" prompt on unparseable dates, and regime months reflect the train slice, not the advertised window (`critic.py:87-94,156-160`).
- **N18** — The per-section `NumericClaimError` fallback is completely silent — no retry, no log, no user-visible provenance of LLM-vs-template narratives (`report_generator.py:335-346`).
- **N19** — Scanner false positives on legitimate digit-bearing terms ("S&P 500", "RSI(14)", "52-week") silently discard clean LLM narratives; redundant patterns duplicate claims (`reporter.py:17-22`).
- **N20** — The "Benchmark Comparison" section binds no benchmark number, so the comparison cannot be verified from the published report (`report_generator.py:124-138`).
- **N21** — `budget_exhausted` cause (runs vs seconds vs EUR) is not attributed, and the decision evidence omits EUR entirely (`loop.py:157-178`).
- **N22** — `config/cost.yaml` is dead configuration — nothing reads it; the real cap lives in `StartRunRequest.max_eur` (`config/cost.yaml:1-5`).
- **N23** — The pre-run frontend estimate assumes 200 completion tokens per call while the Critic budgets 4000 for reasoning models whose CoT is billed as completion tokens (`cost.ts:13-17,38`); per-call cost can be understated ~20x.
- **N24** — Stop can mislabel a naturally-completed run as "stopped"; stop/cancel status semantics diverge from what `/state` reports (`router.py:482-507`).
- **N25** — `/state` DB-fallback maps `total_iterations` to `used_runs`, changing the meaning of "Iter" after a restart; `types.ts` has drifted from the response models (`router.py:597-618`).
- **N26** — Leakage classification ("Validated in our research") cites evidence documents not shipped in the repo (`leakage-legend.tsx:5-29`; `ai/leakage.py:1-12`); an open-source reader cannot verify the headline differentiator.
- **N27** — `criteria.py` docstring claims the frontend shows parsed criteria for verification/editing, but no such surface exists (`ai/goals/criteria.py:1-6`).
- **N28** — `BacktestConfig.seed` is a dead parameter, not propagated by the optimizer (`engine/runner.py:50-64`); a seed knob that is silently ignored.
- **N29** — `cash` default is unit-less; a mixed-currency universe has no normalization (`config/schema.py:113`); absolute equity/P&L are denomination-ambiguous.

---

## Recommended fix roadmap (phased — most result-corrupting first)

The ordering prioritizes defects that corrupt the *result itself* over those that corrupt *presentation*, and presentation over dead-code hygiene. Phase 1 items must land before any published "validated" claim is credible.

### Phase 1 — Statistical wiring that corrupts accept/reject decisions
1. **Fix the Deflated Sharpe gate end-to-end (H1, H2, M24, M25, N6).** Feed per-period trial-SR variance (ddof=1) into the per-period formula; wire *N* to the event registry's cross-run `valid_research_trial_count()` scoped to the data snapshot; replace the magic-number variance floor with an explicit `sr_variance_defaulted` flag in per-bar units; make `n_trials` count only gate-evaluable backtests. Add a regression test asserting a realistic dispersion yields a non-degenerate DSR.
2. **Add indicator warm-up buffers to every out-of-window backtest (C1, M26, M3).** Walk-forward test windows, OOS lockbox, regime hold-out, and decay slices must fetch `window_start − max_lookback` and score only in-window trades. Require ≥1 trade before counting a window/verdict valid (fixes H6 in tandem).
3. **Make annualization interval-aware (C2, M5, M6, L17).** Derive `periods_per_year` from `BarInterval`, thread it into `compute_buy_hold`/`compute_market_benchmark`/`calculate_sortino`, and compute the benchmark Sharpe once with the same estimator/ddof/annualization as the strategy Sharpe.
4. **Fix the metric formulas the optimizer and gates consume (H9, H10, M2, M4).** Standard uncentered Sortino with an epsilon guard; winsorize/guard the 999.99 sentinels before optimization; CAGR-based Calmar; rescale the composite weights for fraction units.
5. **Replace count-only goal completion with real criteria (C3, H30, M50, L22).** Parse the goal at run start, persist on `GoalBrief`, count only criteria-satisfying candidates, and fix the vacuous drawdown-sign/scale/key bug.

### Phase 2 — Out-of-sample and validation discipline
6. **Strengthen the OOS/hold-out contract (H3, H14, H15, H16, H17, H18).** Real OOS pass bar (min trades + t-stat + benchmark excess); key the evaluation budget on the lineage root; recover stored verdicts on `AlreadyEvaluatedError`; make infra errors `UNEVALUATED` (not FAIL); apply multiplicity control (or one-shot) on the shared hold-out; derive the OOS window dynamically.
7. **Default OOS on / cap the tier when it is off (H5).** Either default `enable_oos=True` or cap the robustness tier at "moderate" and mark every in-sample-only run explicitly. Align README wording.
8. **Wire or honestly demote the inert gates (H4, H24, M19, M20, M22, M23, M21).** Load `gates.default.yaml` (or delete it); feed the real survivorship flags to `ProviderCapabilityGate`; make Path C risk-aware and forward `buy_hold_max_drawdown`; add `min_stressed_sharpe` to presets; wire the leakage canary and lag gate for survivors or set them `NOT_EVALUATED`; fix kill-cause attribution.

### Phase 3 — Data integrity
9. **Fix the market-data adjustment layer (H21, H22, H23, M32, M33, M34, M35, M36).** Stop incrementally merging back-adjusted prices (snapshot-replace or cache raw + events); fix the tz dedup; unify per-provider adjustment semantics and fallback only between compatible providers; fix Yahoo end-exclusivity, Tiingo duplicate columns, and CoinGecko windowing; add a `currency` field.
10. **Fix the persistence integrity defects (H27, M47, M53, M54).** Advance flush cursors only after commit; stamp events/candidates at emission time; emit offset-aware timestamps; include `paused` in the orphan sweep.

### Phase 4 — Cost realism and LLM honesty
11. **Unify the cost model (H29/M55, L19, L20, L18, L21).** Route the AI executor and CLI through one cost helper (commission + spread + slippage); document per-side vs round-trip; delete or wire the dead `costs/` package.
12. **Make LLM degradation and identity honest (H25, H26, H28, H31, M39, M42, M43, M44, M45, M56, M60, M37, M38, M41).** Raise strategist `max_tokens`; robust JSON extraction; surface llm-vs-fallback counts and per-critique source; record and badge the *effective* model and its leakage class; close the `{{digit}}` scanner bypass; compute regime labels from market returns; propagate critic reasoning; record proposal provenance.

### Phase 5 — Config/dead-code hygiene and disclosure
13. **Delete or wire the remaining dead subsystems (H19, H20, M8, M9, M10, M11, M12, M17, M57, M58, M59, L4, L6, N9, N22, N28).** Anti-brute-force budgets, optimizer failure handling, walk-forward config forwarding, the strategy generator, and the determinism fingerprint/CI/env machinery.
14. **Add the missing test coverage and disclosures (M18, M30, L6, N26, N27).** Reference-value tests for the pandas indicators; a select-on-train wiring test; a README "Data limitations" (survivorship + adjustment) section; ship or drop the leakage-classification protocol docs.
