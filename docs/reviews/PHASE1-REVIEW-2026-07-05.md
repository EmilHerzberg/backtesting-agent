# Phase 1 Remediation — Merge-Readiness Review

**Date:** 2026-07-05
**Branch under review:** `quant-review/phase0-harness-h7` vs `main`
**Repo:** `backtesting-agent`
**Scope:** The 19 Phase-1 remediation fixes (findings H1/H2/H6/H7/H9/H10/H12/H30, M2/M4/M5/M6/M24/M25/M26/M50, C1/C2/C3, L17/L22 and the C1/M3 warm-up work) plus the Phase-0 €0 verification harness that the whole review depends on.

---

## 1. Methodology

This is a synthesis of a two-stage adversarial review:

- **Nine specialist reviewers** across **five functional clusters**:
  - **1A** — Deflated-Sharpe gate (H1/H2/M24/M25)
  - **1B** — warm-up correctness, split into the *engine* (trade-mask + reslice, C1/M26/M3) and the *indicator library* (H12/H6)
  - **1C** — interval annualization + benchmark estimator (C2/M5/M6/L17)
  - **1D** — metric formulas (H9/H10/M2/M4)
  - **1E** — goal criteria (C3/H30/M50/L22)
- **The Phase-0 harness reviewer**, because the €0 MockProvider/frozen-data harness is the substrate the other reviewers trust for their empirical checks.
- **Two cross-cutting lenses**: (i) *regressions & side-effects a passing suite would miss*, and (ii) *test-suite integrity — are the 19 fixes genuinely protected?*

Every candidate finding was then subjected to **2-lens verification**: at least two independent verifiers re-derived the claim against the actual code (and, where relevant, ran the exact mutation/regression to see whether the test suite would catch it). A finding is recorded as:

- **confirmed / confirmed-contested** — a real issue that survived adversarial verification (contested = one verifier dissented on materiality but the majority upheld it);
- **refuted** — killed on verification (kept only as a short appendix);
- **unverified-low** — a low-value note not worth a verification round.

Findings that two lenses raised independently (H1 loop-wiring, the win-rate/profit-factor gap, and the unwired market-benchmark) have been **consolidated into a single issue each** to avoid inflating the count; the corroboration is noted inline.

I re-verified the four highest-impact behavioral claims directly against the branch while writing this report (M4 defaults, the win-rate/profit-factor Candidate gap, the generator indicator wiring, and the missing M5/L17 finding-tags) — all reproduced exactly.

---

## 2. Executive summary

Phase 1 is **substantively real work, not a paper exercise** — the core mathematics of every cluster is correct. The DSR gate now feeds byte-identical per-period Sharpe units on both sides (H1), the warm-up trade-mask suppresses only entries and cannot leak across runs (C1), the indicator library carries correct `min_periods` on all 13 `ewm` chains (H12/H6), `periods_per_year` reproduces backtesting.py 0.6.5's `annual_trading_days` exactly (C2), three of the four 1D metric fixes are correct with genuine red→green tests (H9/H10/M2), and the goal-criteria wiring for the core metrics (Sharpe, drawdown sign/unit) is real (C3/H30). The remediation test suite is largely honest: 41 `@pytest.mark.finding` tests pass, the marker is registered, and 459 research+backtesting unit tests still pass, confirming the contract changes did not silently break existing callers.

However, the branch is **not merge-ready as-is**. The review confirmed **five genuine behavioral defects** — not nits — where the bug Phase 1 claimed to fix is still live on the production path or a new regression was introduced. The M4 composite-objective rescale was applied only to an unused fallback constant; the CLI/YAML default the documented `--preset quick/full` path actually consumes is still `max_drawdown: -0.4`, so the objective still degenerates to Sharpe-maximization (verified: `schema.py:51`, `quick.yaml:30`, `full.yaml:53` all still `-0.4`). The H12 generator warm-up mask is inert because `DynamicStrategy` stores indicators in a list rather than as strategy attributes, so backtesting.py never warm-up-skips them and generated strategies still trade during the warm-up region. Goal criteria for win-rate, profit-factor and regime-pass-count are parsed but the `Candidate` dataclass carries no such fields, so those criteria are silently skipped and `goal_met()` over-counts — the exact C3 failure mode, resurfaced. The default-goal path now silently requires annual Sharpe ≥ 1.0 to complete, which is above every rigor preset's `min_sharpe` floor, so runs that used to complete now burn to budget — a behavioral regression. And the warm-up reslice recomputes strategy Sharpe with an arithmetic estimator ~20% off the geometric one the rest of the codebase (and the C2/M5 benchmark) deliberately standardized on.

Beyond the behavioral bugs, several fixes are **correct but unprotected**: the load-bearing loop→gate DSR wiring (H1/M25), the warm-up reslice *values* (C1/M26), and the generator warm-up path (H12) have no regression test that would fail if the fix were reverted, and two findings (M5, L17) carry no `finding` tag at all — so the coverage matrix the tracker treats as its audit trail is wrong, and L17's `compute_market_benchmark` is dead code with no caller. Two findings were correctly **refuted** (the M24 constructor default and the frozen-fetch window trap — both real observations but unreachable in the current code). Net: the maths is sound, but the wiring and the test coverage that would keep it sound are not, and there are concrete production-path bugs to fix before Phase 2 builds on this.

---

## 3. Merge-readiness verdict

> **RESOLVED (2026-07-05).** All 12 confirmed issues were fixed in the follow-up commit "Phase 1
> review fixes". The 5 behavioral defects: **P1-08** — the composite-weight rescale now ships on the
> schema default + both example YAMLs (`-1.5`), pinned by a test on `OptunaConfig().composite_weights`;
> **P1-11** — `parse_criteria` no longer injects a default Sharpe≥1.0 floor (empty criteria → count
> gate-passing candidates), with a regression test; **P1-09** — `win_rate`/`profit_factor` added to
> `Candidate` + `_candidate_metrics`, and an unmappable criterion is now a hard FAIL (not a silent
> skip), with an enforcement test; **P1-04** — generator indicators are registered as strategy
> attributes so backtesting.py warm-up-skips them, and the silent `except` is removed, pinned by a
> `DynamicStrategy` EntryBar≥warm-up test; **P1-03** — the reslice recomputes windowed Sharpe with
> `benchmark_sharpe` (geometric) and recomputes Calmar for consistency. All 7 test-integrity gaps
> closed (P1-01 loop→gate DSR wiring, P1-02 reslice values, P1-05 generator path, P1-06 tightened
> tolerance + M5 tag, P1-07 L17 tag + market-benchmark test, P1-10 H30-through-Candidate, P1-12 M24
> distinguishing case). Full suite **635 passed / 5 skipped**; module boundaries 7/7 kept.
>
> Original verdict (pre-fix):

> **NO — must fix first.**

Phase 1 should not merge until the five confirmed behavioral defects (P1-03, P1-04, P1-08, P1-09, P1-11) are addressed, and the highest-value regression tests are added so the correct-but-unprotected fixes cannot silently revert. The underlying maths is trustworthy; the problem is that the fixes are not fully *wired into the production path* and not *pinned by tests*. See the prioritized MUST-FIX list in §7.

**Confirmed-issue counts:** Critical 0 · High 7 · Medium 4 · Low 1 (12 unique issues after consolidating 3 dual-lens duplicates).

---

## 4. Severity table

| ID | Sev | Cluster | Title | Type | Status |
|----|-----|---------|-------|------|--------|
| P1-08 | High | 1D (M4) | Composite-weight rescale only touched an unused fallback; CLI/YAML default still `-0.4` | incomplete-fix (behavioral) | confirmed |
| P1-09 | High | 1E / xcut (L22/M50/C3) | win_rate/profit_factor/regime criteria parsed but vacuously skipped → `goal_met()` over-counts | incomplete-fix (behavioral) | confirmed |
| P1-11 | High | xcut-regression (C3) | Default-goal path silently requires Sharpe ≥ 1.0, above every preset floor | behavioral regression | confirmed |
| P1-04 | High | 1B-indicators (H12) | Generator `_signal_fn` NaN-mask is inert; generated strategies trade during warm-up | incomplete-fix (behavioral) | confirmed |
| P1-01 | High | 1A / xcut (H1/M25) | Loop→gate DSR wiring not pinned by any finding-tagged test | weak/tautological test | confirmed |
| P1-02 | High | 1B-warmup (C1/M26/M3) | Reslice tests assert equity-curve *length* only, never the recomputed metric values | weak/tautological test | confirmed |
| P1-05 | High | 1B-indicators (H12) | No test exercises the generator/`DynamicStrategy` warm-up path | weak/tautological test | confirmed |
| P1-03 | Medium | 1B-warmup (C1/M5) | Reslice recomputes strategy Sharpe with arithmetic estimator ~20% off the geometric scale | fix-incorrect (numeric) | confirmed |
| P1-06 | Medium | 1C (M6) | Benchmark-estimator scale test tolerance `abs=0.3` passes on the pre-fix arithmetic estimator | weak/tautological test | confirmed |
| P1-07 | Medium | 1C / xcut (M5/L17) | M5 & L17 untagged (coverage matrix wrong); L17's `compute_market_benchmark` is unwired & untested | weak test + dead code | confirmed |
| P1-12 | Medium | xcut-tests (M24) | Edited `test_quality.py` passes identically on the pre-fix magic-`0.001` sniff | weak/tautological test | confirmed-contested |
| P1-10 | Low | 1E (H30/C3) | Drawdown criterion never exercised through the wired `Candidate`→`goal_met` path | weak/tautological test | confirmed |

**Refuted (appendix §6):** M24 gatekeeper constructor default; frozen-fetch window trap.
**Low notes (appendix §6):** window-ignoring data-agent over-extension; HOLD-during-warmup 10-bar window; benchmark_sharpe n-vs-n-1 gmean off-by-one; reslice leaves `calmar_ratio` inconsistent.

---

## 5. Confirmed issues (detail)

### P1-08 (High) — M4 composite rescale only touched an unused fallback; production default is still `-0.4`
**File:** `src/backend/backtesting/engine/optimizer.py:38-41, 313` — with `config/schema.py:51`, `config/examples/quick.yaml:30`, `config/examples/full.yaml:53`, `cli.py:433`.

**What's wrong.** The M4 finding is that the composite objective silently degenerates to Sharpe-maximization because `max_drawdown` (a fraction in ~[0, 1]) is weighted far too weakly at `-0.4`. The fix rescaled `_DEFAULT_COMPOSITE_WEIGHTS['max_drawdown']` from `-0.4` to `-1.5`. But `optimizer.py:313` uses that constant only as a fallback: `weights = config.composite_weights or _DEFAULT_COMPOSITE_WEIGHTS`. The documented optimization path (`run_backtest.py --preset quick/full` → `cli.py:433`) always passes `composite_weights=config.optuna.composite_weights`, whose default is still the old weight. Verified against the branch: `schema.py:51` `default_factory` is still `{"sharpe": 0.6, "max_drawdown": -0.4}`, and both shipped example configs pin `max_drawdown: -0.4` (`quick.yaml` is the CLAUDE-documented `--preset quick`). The `finding("M4")` test validates only the fallback constant, so it is green while the shipped behavior is unchanged.

**Why it matters.** The single flagship "objective now actually penalizes drawdown" fix is effectively **not shipped** on the path users invoke. Optuna keeps selecting the highest-Sharpe / deepest-drawdown strategy.

**Fix.** Change `schema.py:51` `default_factory` to `{"sharpe": 0.6, "max_drawdown": -1.5}` and both example YAMLs to `-1.5` (or drop the schema default so the fixed fallback is used, or normalize each metric before weighting). Add a regression test that constructs `OptunaConfig().composite_weights` and asserts the shipped default, not the fallback constant.

**Status:** confirmed (re-reproduced at runtime by two verifiers and again while writing this report).

---

### P1-09 (High) — win_rate / profit_factor / regime criteria are parsed but vacuously skipped → `goal_met()` over-counts
**File:** `src/backend/ai/research/state.py:187-194` (`_candidate_metrics`), `state.py:159-184` (`Candidate`); `goals/criteria.py:84-102` (parse), `:127-129` (skip-on-None). *(Corroborated independently by cluster 1E and the xcut-tests lens as L22.)*

**What's wrong.** L22/M50 added parsing for `win_rate`, `profit_factor` and `regime_pass_count` criteria with canonical keys, and the tracker marks them DONE. But `_candidate_metrics` exposes only four keys — `sharpe_annual`, `total_return`, `max_drawdown`, `n_trades` (verified) — and the `Candidate` dataclass has no `win_rate`/`profit_factor`/`regime_pass_count` fields (verified). `candidate_meets_criteria` does `if val is None: continue`, so for a goal phrased purely on win-rate or profit-factor the criteria list is non-empty but *every* criterion is skipped, and the function returns `True` vacuously. Runtime check: `parse_criteria('Finde 3 Strategien mit Profit Factor > 1.5')` yields a `profit_factor` criterion, and a `Candidate(sharpe=0, dd=-0.9, n_trades=1)` that clearly violates intent is counted as satisfying it.

**Why it matters.** This is the C3 defect — `goal_met()`/`validated_count()` counting strategies that never met the user's stated bar — resurfacing for the newly-parsed metrics. The run reports success against goals it never verified.

**Fix.** Add `win_rate` and `profit_factor` to `Candidate` (populate from the executor metrics at `loop.py:797-814`) and to `_candidate_metrics`; for `regime_pass_count`, either derive it into `_candidate_metrics` or make `parse_criteria`/`candidate_meets_criteria` treat an unmappable metric as a **hard fail / fail-loud** rather than a silent skip. Add a `finding("L22")` test asserting a candidate that fails a profit-factor/win-rate criterion is *not* counted by `goal_met()`.

**Status:** confirmed.

---

### P1-11 (High) — default-goal path now silently requires Sharpe ≥ 1.0, above every preset floor
**File:** `src/backend/ai/research/run.py:145-158` (wiring); `state.py:230-255` (filter); `goals/criteria.py:107-112` (default criterion).

**What's wrong.** `run_research` *always* injects `parse_criteria(goal)['criteria']` into `GoalBrief`, and `parse_criteria` emits a default criterion `[sharpe_annual >= 1.0]` whenever nothing else matches. `goal_met()`/`validated_count()` now count only candidates satisfying it. But every rigor preset admits candidates below 1.0 (exploratory `min_sharpe` 0.3, standard 0.5, strict 0.8). So a default-goal run that previously reported `goal_met` at `target_candidates` now requires `target_candidates` with annual Sharpe ≥ 1.0; gate-admissible candidates in `[0.5, 1.0)` no longer count and the run instead runs to budget. Reproduced: with `crit = parse_criteria('Find good strategies for AAPL')['criteria'] == [('sharpe_annual','>=',1.0)]` and three candidates at Sharpe 0.6/0.7/0.8, `state.goal_met()` returns `False` and `validated_count(False)` returns 0 — versus `True`/3 under the old raw count. The C3 test that "covers" this only varies Sharpe *around 1.0*, so it does not reveal that the threshold is now hard-coded above the preset floors.

**Why it matters.** A **new behavioral regression** on the most common (default-goal) path: successful runs silently stop completing and burn full budget. Also a budget/cost concern given the standing spend constraint.

**Fix.** Make a product decision on whether the default goal should be `>= min_sharpe(preset)` rather than a fixed 1.0 (or should not inject a hard Sharpe floor at all). Add an integration test that wires the default-goal path exactly as `run.py` does and asserts candidates below the intended floor do not reach `goal_met` while those above do.

**Status:** confirmed.

---

### P1-04 (High) — generator `_signal_fn` NaN-mask is a no-op; generated strategies are not warm-up-protected
**File:** `src/backend/backtesting/strategies/generator.py:175-192`.

**What's wrong.** H12 lists `generator.py:152-184` as part of the fix and the tracker claims "generator `_signal_fn` maps warm-up→NaN" as done. The added mask (`arr[ind.compute(df).isna()] = np.nan`) is locally correct but has no effect on trading: `DynamicStrategy` stores each `self.I(...)` result in a **list** (`self._signals.append(sig)`, verified at `generator.py:191`), not as a strategy attribute. backtesting.py's `_strategy_indicators()` collects `_Indicator` values only from `strategy.__dict__`, so it finds **0** indicators for a `DynamicStrategy`; `_indicator_warmup_nbars()` returns 0 and no per-bar warm-up skip happens. Empirical: a single-EMA `DynamicStrategy` on 250 bars (EMA warms at bar 19) produces a trade with `EntryBar=2`; `len(list(_strategy_indicators(strategy))) == 0`. An attribute-stored `self.ema = self.I(...)` yields `_strategy_indicators == 1` and warm-up start 20.

**Why it matters.** Generated strategies — a primary output of the system — still act on not-yet-warm indicator values, i.e. the exact warm-up leakage H12 was meant to eliminate. The `try/except Exception: pass` around the mask also hides any failure silently.

**Fix.** Register each generator indicator array as a real backtesting.py indicator (assign each `self.I(...)` to a distinct strategy attribute, or otherwise make `_strategy_indicators()` detect them) so backtesting.py both warm-up-skips and per-bar-slices them. Verify with a test that a generated strategy's first trade is `>=` the max indicator warm-up (see P1-05).

**Status:** confirmed (verified against the installed backtesting.py source; every mechanical claim holds).

---

### P1-01 (High) — loop→gate DSR wiring (the actual H1/M25 fix site) is not pinned by any finding-tagged test
**File:** `tests/unit/ai/research/test_dsr_inputs_h1_m25.py:19-63`; fix site `src/backend/ai/research/loop.py:701-719`. *(Corroborated independently by cluster 1A and the xcut-tests lens.)*

**What's wrong.** The H1/M25 bug was that the *loop* fed the wrong quantities to the gate — `np.var(_sharpe_values)` (annualized) and `state.total_iterations` — instead of per-period Sharpe variance and the measured-trial count. The fix maintains a separate `_period_sharpe_values` list and passes `_dsr_registry_inputs(_period_sharpe_values)` + `variance_defaulted=_sr_defaulted` at `loop.py:716-719`. But every `finding("H1"/"M25")` test exercises the helpers (`_period_sharpe`, `_dsr_registry_inputs`) or calls `deflated_sharpe`/`DeflatedSharpeGate` in isolation; none asserts the loop passes those quantities. Verified by mutation: reverting `loop.py:716` to feed `_sharpe_values`/`total_iterations` (the exact original bug) leaves all cluster-1A/H1 finding tests green. The only loop-level check (`test_loop.py:366-377`) asserts `call_count >= 2` and `first_call n_trials == 1` — indistinguishable between `total_iterations`, `len(_sharpe_values)`, and `len(_period_sharpe_values)` on iteration 1.

**Why it matters.** The fix is correct but its single load-bearing seam is unprotected; a future refactor can silently reintroduce the annualized-variance DSR collapse.

**Fix.** Add a finding-tagged loop test with a mock executor returning a returns array whose per-period Sharpe differs materially from `sharpe_annual`, plus a skipped/error iteration, and assert the captured `update_registry_stats` args: `n_trials == number of measured trials (< total_iterations)` and `sr_variance == np.var(period_sharpes, ddof=1)` (not `np.var(annualized_sharpes)`).

**Status:** confirmed.

---

### P1-02 (High) — C1/M26 reslice tests assert only equity-curve length, never the recomputed metric values
**File:** `tests/unit/backtesting/test_warmup_c1.py:34-69` (esp. 51-59); `tests/unit/ai/research/test_warmup_slices_m26.py:66-76`.

**What's wrong.** The purpose of `_reslice_to_window` (C1/M3) is that the flat warm-up prefix must not dilute the *recomputed* Sharpe/return/drawdown/sortino. But the tests only assert the equity-curve **length** (`abs(len - (len(data)-warmup)) <= 3`) and the trade entry time. No test asserts `warm.total_return`, `warm.sharpe_ratio`, `warm.max_drawdown`, or `warm.sortino_ratio`. A regression in the reslice math (wrong offset, `ddof=0`, missing `sqrt(ppy)`, sign flip, wrong window) that still yields a right-length curve passes all seven tests. This gap is exactly why the ~20% estimator error in P1-03 went undetected.

**Why it matters.** The dilution fix — the load-bearing part of C1/M3 — is numerically unverified.

**Fix.** Add a value assertion: build data with a flat/zero-return warm-up prefix and a trending window, and assert `warm.total_return == pytest.approx(eq_window[-1]/eq_window[0]-1)`, `warm.sharpe_ratio > cold-diluted-sharpe`, and a hand-computed `max_drawdown` on the window slice.

**Status:** confirmed.

---

### P1-05 (High) — no test covers the generator/`_signal_fn` warm-up wiring
**File:** `tests/unit/backtesting/test_indicator_warmup_h12.py:21-56`.

**What's wrong.** Both `finding("H12")` tests call `indicator.compute()`/`indicator.signal()` directly on a DataFrame. Neither exercises `generate_strategy`/`DynamicStrategy`, so the generator half of the H12 fix (`generator.py:152-184`) is entirely unverified — precisely why the inoperative mask in P1-04 went undetected. `grep` confirms no test references `generate_strategy` or `_signal_fn`.

**Why it matters.** A green suite proves the indicator library is NaN during warm-up but proves nothing about whether a generated strategy actually avoids trading during warm-up (it does not — P1-04).

**Fix.** Add a `finding("H12")` test that builds a `DynamicStrategy` via `generate_strategy` (FixedTrial), runs it through backtesting.py, and asserts the first trade's `EntryBar >= indicator warm-up length`. This currently fails, exposing P1-04.

**Status:** confirmed.

---

### P1-03 (Medium) — reslice recomputes strategy Sharpe with an arithmetic estimator ~20% off the geometric scale
**File:** `src/backend/backtesting/engine/runner.py:351-352` (reslice), `:383` (non-warmup source); `walk_forward.py:204-207`.

**What's wrong.** For a warm-up run, `_reslice_to_window` overwrites `result.sharpe_ratio` with `rets.mean()/rets.std(ddof=1)*sqrt(ppy)` (arithmetic). But the non-warmup path stores backtesting.py's geometric/compounded "Sharpe Ratio" (`runner.py:383`), and `benchmark_sharpe` was deliberately written (C2/M5) to replicate that same geometric estimator so strategy and benchmark Sharpe sit on one scale in the gate. So every warm-up run (OOS / hold-out / decay / walk-forward) puts strategy Sharpe on a *different* scale than both the non-warmup strategy Sharpe and the benchmark Sharpe. Measured on identical window equity: reslice arithmetic Sharpe `1.3176` vs geometric `1.0936` — a **20.5%** relative gap. Walk-forward then divides an arithmetic warm-up test Sharpe by a geometric non-warmup train Sharpe.

**Why it matters.** It partially undoes the C2/M5 scale-matching the review otherwise credits, and it silently biases every warm-up-path gate comparison and the walk-forward decay ratio.

**Fix.** In `_reslice_to_window`, compute the windowed Sharpe with the same estimator the rest of the codebase uses on an equity path — e.g. `benchmark_sharpe(pd.Series(eq_full[warmup_bars:], index=<window DatetimeIndex>))` — so warm-up, non-warmup, and benchmark Sharpe stay on one scale.

**Status:** confirmed (verified against installed backtesting.py 0.6.5 and a live run; also flagged as a self-contradiction with the C2/M5 ticket ATS-1800).

---

### P1-06 (Medium) — M6 estimator-scale test tolerance (`abs=0.3`) passes on the pre-fix arithmetic estimator
**File:** `tests/unit/backtesting/test_annualization_c2.py:64-71`.

**What's wrong.** `test_benchmark_sharpe_matches_strategy_estimator_scale` is the only test comparing `benchmark_sharpe` against a real backtesting.py strategy Sharpe, and its docstring claims it proves the estimator is "not off by a `sqrt(252/ppy)` or ddof mismatch." But the fixture is *daily* (`make_ohlcv days=400`), so `ppy=252` for old and new code, `ddof 0-vs-1` is negligible at n≈399, and arithmetic-vs-compounded on small daily returns is tiny. Measured: backtesting.py `0.27178`, new `benchmark_sharpe 0.28591` (diff `0.0141`), old arithmetic-ddof0×√252 `0.40257` (diff `0.13079`) — both `< 0.30`, so the assertion passes even with the reverted arithmetic estimator. The compounded formula is only actually pinned by the *weekly* test that compares against a local re-implementation.

**Why it matters.** The one test meant to pin the M5/M6 estimator on the daily path (where users mostly run) does not.

**Fix.** Add a weekly/monthly variant (where the interval factor bites and arithmetic diverges), and/or tighten the daily case to `abs≈0.05`, and/or assert `benchmark_sharpe(close)` matches backtesting.py's `stats['Sharpe Ratio']` for a fully-invested strategy at `rel<=0.02`. Re-tag with `finding("M5")` (see P1-07).

**Status:** confirmed (reproduced on the test's own fixture by two verifiers).

---

### P1-07 (Medium) — M5 & L17 carry no finding-tag (coverage matrix wrong); L17's `compute_market_benchmark` is unwired and untested
**File:** `src/backend/backtesting/benchmarks/market.py:60-115`; test file `tests/unit/backtesting/test_annualization_c2.py`. *(Corroborated by cluster 1C and the xcut-tests lens.)*

**What's wrong.** The tracker marks M5 and L17 DONE with test `test_annualization_c2.py`, and states the coverage matrix (its audit trail) is generated from `@pytest.mark.finding` tags. But no test carries `finding("M5")` or `finding("L17")` — verified: the full tag inventory is H1, M24, M25, C2, M6, H7, M50, H30, C3, H9, H10, M2, M4, C1, H12, H6, M26 (plus a stray template `finding("<ID>")`), with **no M5 and no L17** — so the matrix would show both as uncovered. Worse, L17's fix (`alpha *= periods_per_year`, interval-aware residual/market Sharpe) lives in `compute_market_benchmark`, which has **zero callers in `src/`** (verified — only its own definition) and zero test references, so the change is entirely unexercised and always runs at the default `periods_per_year=252`.

**Why it matters.** Two of the 19 "DONE + tested" claims are untagged/untested, so the audit trail Phase 1 leans on overstates coverage; and L17 is a change to dead code (overlaps OPEN M19 "benchmark gate Path B dead").

**Fix.** Add `finding("M5")` to the estimator-scale test and `finding("L17")` to a new test that calls `compute_market_benchmark` with a weekly `ppy` and asserts alpha and residual/market Sharpe scale by 52, not 252. If `compute_market_benchmark` is genuinely dead, mark L17 **wire-or-delete** rather than DONE.

**Status:** confirmed.

---

### P1-12 (Medium, contested) — edited `test_quality.py` (M24) passes identically on the pre-fix magic-`0.001` sniff
**File:** `tests/unit/ai/research/test_quality.py:73-82`.

**What's wrong.** M24's core change is that `quality.py` stopped inferring "defaulted variance" by sniffing the magic value `0.001` (`abs(sr_var-0.001)<1e-9`) and now reads the explicit `sr_variance_defaulted` flag. The edited test only adds `sr_variance_defaulted: True` to a report whose `sr_variance` is *also* `0.001` (→ `provisional=True`), and a `solid` case with `sr_variance=0.02` (→ `provisional=False`). Both outcomes are identical under the old magic-sniff logic: reproduced `old_provisional(50, 0.001)=True`, `old_provisional(50, 0.02)=False`. The distinguishing case — a genuinely-measured `0.001` with the flag `False`, which must *not* be provisional — is absent, so the test would pass unchanged on the buggy pre-fix code.

**Why it matters.** The M24 flag-vs-sniff fix is unprotected; a revert to the magic sniff is invisible. *(Contested: one verifier judged this immaterial because the fix itself is clearly correct; the majority upheld it as a real test-integrity gap. The fix is fine — the test is not the pin the tracker claims.)*

**Fix.** Add `measured = quality_summary(_report(dsr={'dsr':0.97,'n_trials':50,'sr_variance':0.001,'sr_variance_defaulted':False}), mode='robustness'); assert measured['dsr']['provisional'] is False`. This fails on the magic-sniff code and passes on the flag-based code.

**Status:** confirmed-contested.

---

### P1-10 (Low) — H30/C3 tests never exercise the drawdown criterion through the wired `Candidate` path
**File:** `tests/unit/ai/research/test_goal_criteria_1e.py:32-53`.

**What's wrong.** The H30 test calls `candidate_meets_criteria` directly with hand-built raw dicts (`{'max_drawdown': 0.30}` / `{-0.30}`), and the C3 test only varies Sharpe. No test drives a real `Candidate` with the executor's negative-fraction `max_drawdown` convention (`executor.py:113`) through `_candidate_metrics → candidate_meets_criteria → goal_met`. So the sign/unit wiring — the crux of H30 in production — is asserted only against a stubbed dict.

**Why it matters.** A regression that dropped/renamed `max_drawdown` in `_candidate_metrics`, or changed the executor's sign convention, would pass the H30 test. Low severity because the core H30 formula is correct and separately tested.

**Fix.** Add a test that builds `Candidate`s with `max_drawdown=-0.30` and `-0.15`, parses a "drawdown < 20%" goal into `GoalBrief.criteria`, and asserts `goal_met()`/`_criteria_satisfying` filters out the `-0.30` candidate — exercising `_candidate_metrics` + the executor convention end-to-end.

**Status:** confirmed.

---

## 6. Appendix — refuted findings & low notes

### Refuted (killed on verification)

- **M24 gatekeeper constructor default (`gatekeeper.py:89-99`).** The constructor seeds `trial_sr_variance=0.001` with `trial_sr_variance_defaulted=False`, so a probe with `n_trials_global=50` and no `update_registry_stats` yields a FIRM PASS on the magic floor. Factually accurate, but **not reachable**: `loop.py` always calls `update_registry_stats` (which sets the flag `True`) before `evaluate`. Immaterial as a bug; valid low-value hardening (default the flag to `True`, or treat the `0.001` seed as defaulted). Two verifiers refuted materiality; recorded as refuted.

- **`frozen_fetch` ignores the requested window (`tests/support/frozen_data.py:45-57`).** The harness fixture returns the full 900-bar series regardless of `window_start`/`window_end`, so a *future* window-sensitive test using it could silently score the wrong slice (interacts with `loop.py:333-339`, which zeroes warm-up when the frame doesn't start near `window_start`). A real latent trap, but **not currently sprung** — `frozen_ohlcv` is used only by the 3 smoke tests, none window-sensitive, and none of the 19 fixes is corrupted by it. Recommended hardening: make `frozen_fetch` honor the window by default or add an explicit `ignore_window` opt-in. Recorded as refuted (no current defect).

### Low notes (unverified-low)

- **`_prepare_with_warmup` over-extends the scored slice for a window-ignoring data agent (`loop.py:333-340`).** If a custom `fetch_fn`/frozen agent ignores `window_end`, the OOS/hold-out/decay slice scores `[window_start .. end-of-frame]` with no error; the safety guard `if warmup >= len(data)-2: warmup = 0` also leaves the reach-back prefix in `data`. The real `_SimpleDataAgent`/yfinance path respects the window. Suggest clipping the frame to `<= window_end`.

- **HOLD-during-warmup assertion only checks the first 10 bars (`test_indicator_warmup_h12.py:52-55`).** ADX warms ~bar 26, MACD signal ~bar 33, Keltner ~bar 20; a regression re-emitting BUY/SELL in bars 10..warmup for those indicators still passes. Assert HOLD over the full per-indicator warm-up region.

- **`benchmark_sharpe` drops the leading `pct_change` NaN — off-by-one gmean denominator (`metrics.py:228-232`).** backtesting.py divides the log-sum by `n` (counting the leading NaN→0), `benchmark_sharpe` by `n-1`, giving a ~0.4–0.8% relative gap vs the strategy Sharpe it claims to match byte-for-byte. Negligible for the gate; contradicts the "same way backtesting.py computes it" docstring.

- **`_reslice_to_window` leaves `calmar_ratio` inconsistent (`runner.py:333-358`).** It recomputes total_return/sharpe/max_dd/sortino on the window but not `calmar_ratio`, which stays computed from the full (flat-diluted) window. Harmless today (no consumer reads calmar on a warm-up run), but the returned `BacktestResult` is internally inconsistent. Recompute calmar from the windowed values.

---

## 7. Per-cluster verdicts

- **1A — Deflated-Sharpe gate (H1/H2/M24/M25): substantively correct.** H1 is properly fixed — `_period_sharpe` (loop.py:260-273) is byte-identical to the gate's `sr_hat` and operates on the same `returns` object, so trial-SR variance and `sr_hat` share per-period units (verified numerically). The old annualized/`ddof=0` + `total_iterations` path is gone; the collapse test is a genuine formula demo with comfortable margins. **Gaps:** the load-bearing loop wiring is unprotected (P1-01) and the M24 test is not a real pin (P1-12). One refuted note (constructor default). **Verdict: correct maths, under-pinned.**

- **1B — warm-up engine (C1/M26/M3): core sound, one real numeric bug + a blind test.** The generic buy/sell mask suppresses only entries and cannot leak across runs; window alignment is off-by-one clean. **But** the reslice Sharpe is on the wrong estimator scale (P1-03) and no test asserts the resliced *values* (P1-02); a low note on window-ignoring agents. **Verdict: needs the estimator fix + value assertions.**

- **1B — indicator warm-up (H12/H6): library half solid, generator half inoperative.** All 13 `ewm` chains carry correct `min_periods`; `min_periods` only masks the leading region (post-warmup values bit-identical). **But** the generator warm-up mask is inert (P1-04) and completely untested (P1-05), plus a 10-bar assertion note. **Verdict: library good; generated strategies still leak — must fix.**

- **1C — annualization + benchmark estimator (C2/M5/M6/L17): largely sound.** `periods_per_year` reproduces backtesting.py exactly across 252/365/52/12 and the sub-daily resample path; `benchmark_sharpe` implements the compounded estimator and the M5 gate compares like-for-like. **But** the M6 test tolerance is too loose (P1-06) and M5/L17 are untagged with L17 on dead code (P1-07); a low off-by-one gmean note. **Verdict: correct, with a coverage/audit-trail hole to close.**

- **1D — metric formulas (H9/H10/M2/M4): three of four excellent, M4 not shipped.** H9 (uncentered target downside deviation), H10 (sentinel/cap removal), and M2 are correct with genuine red→green tests (verified the steady-loser and single-negative cases truly distinguish the code paths). **But** M4's rescale only touched an unused fallback (P1-08). **Verdict: strong cluster, but the M4 flagship must reach the CLI/YAML default.**

- **1E — goal criteria (C3/H30/M50/L22): core wiring real, secondary metrics vacuous.** C3 wiring is genuine and not bypassed; H30 max_drawdown sign/unit handling is correct. **But** win_rate/profit_factor/regime criteria are parsed yet vacuously skipped (P1-09), and the H30/C3 drawdown path is only tested via stub dicts (P1-10). **Verdict: Sharpe/drawdown solid; win-rate/profit-factor goals must be enforced or fail-loud.**

- **Phase 0 — €0 harness: sound and trustworthy.** MockProvider faithfully implements `IAIProvider`, meters €0, and returns a superset JSON both the Strategist and Critic parsers accept; the zero-call assertion is not foolable in the tested paths. The only finding (frozen-fetch window) was refuted as a non-current defect. **Verdict: the substrate the review relies on is safe.**

- **Cross-cutting — regressions & side-effects: mostly clean, one new regression.** `_trade_start` cannot leak across runs; `calculate_calmar`'s pct→fraction change is a docstring correction with the sole caller already passing fractions. **But** the default-goal Sharpe≥1.0 injection is a real behavioral regression (P1-11), plus the calmar-inconsistency low note. **Verdict: one regression to resolve.**

- **Cross-cutting — test-suite integrity: substantially genuine, with named gaps.** 41 `finding` tests pass, the marker is registered, and 459 pass / 5 skip confirm the contract changes didn't break callers; most tests are real red→green pins. **But** the H1 loop seam (P1-01), M24 pin (P1-12), L22 enforcement (P1-09), and M5/L17 tags (P1-07) are the enumerated holes. **Verdict: honest suite, but the highest-value wirings are unprotected.**

---

## 8. MUST-FIX before Phase 2 (prioritized)

**Behavioral defects (production path is wrong today):**

1. **P1-08 (M4)** — Ship the composite-weight fix on the path the CLI uses: set `schema.py:51` default and both example YAMLs to `max_drawdown: -1.5` (or normalize metrics before weighting). Add a test on `OptunaConfig().composite_weights`, not the fallback constant. *Without this, the drawdown-penalty fix is not shipped.*
2. **P1-09 (L22/M50/C3)** — Add `win_rate`/`profit_factor` to `Candidate` + `_candidate_metrics` (populate from executor metrics), and make an unmappable criterion (e.g. `regime_pass_count`) a hard-fail, not a silent skip. Add a test that a candidate failing a profit-factor/win-rate goal is not counted by `goal_met()`. *Fixes C3 over-counting on secondary metrics.*
3. **P1-11 (C3 default goal)** — Decide and implement the default-goal Sharpe policy (tie to preset `min_sharpe` or remove the hard 1.0 floor) so default runs stop silently gating above every preset. Add a wired default-goal test. *Fixes a new completion/budget regression.*
4. **P1-04 (H12 generator)** — Register generator indicators so backtesting.py warm-up-skips them (assign each `self.I(...)` to a strategy attribute); remove the silent `except Exception: pass`. *Stops generated strategies trading during warm-up.*
5. **P1-03 (C1/M5 reslice)** — Recompute the windowed strategy Sharpe with the geometric estimator (`benchmark_sharpe` on the window equity) so warm-up, non-warmup, and benchmark Sharpe stay on one scale. *Restores the C2/M5 scale-matching for all warm-up paths.*

**Test-integrity fixes (correct fixes that would silently revert; Phase 1 is sold as "verified"):**

6. **P1-05 & P1-02** — Add the generator warm-up test (first `EntryBar >= max indicator warm-up`, currently red → exposes P1-04) and the reslice *value* assertions (return/Sharpe/drawdown on a flat-prefix + trending window).
7. **P1-01** — Add the loop→gate DSR wiring test (assert `update_registry_stats` receives per-period variance and the measured-trial count, not annualized variance / `total_iterations`).
8. **P1-07** — Tag M5 and L17 (fix the coverage matrix) and either wire `compute_market_benchmark` with a `periods_per_year` test or mark L17 wire-or-delete.
9. **P1-06** — Add a weekly/monthly variant to the benchmark-estimator test and tighten the daily tolerance so the pre-fix arithmetic estimator fails it.
10. **P1-12 & P1-10** — Add the M24 distinguishing case (measured `0.001`, flag `False` → not provisional) and the H30 drawdown test through the wired `Candidate`/`goal_met` path.

The two **refuted** findings (M24 constructor default, frozen-fetch window) and the four **low notes** are optional hardening — worth a follow-up ticket but not blockers.
