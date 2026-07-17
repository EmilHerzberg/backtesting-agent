# Coverage Memory v2 — the cross-run multiple-testing correction — Requirements, Technical Spec & Implementation Plan

> ⚠️ **PARTIALLY SUPERSEDED (2026-07-16) — read `COVERAGE-V2-RECONCILED-PLAN.md` first.** The safety pass corrected two items in this spec: **`V ≈ 1/T` is retired** (it loosens the bar ~30–40%; use a fixed conservative `V_null` with a stricter-direction check) and **the `1+(N−1)·ρ̄` reduction is retired** (it goes inert on a banded matrix; measure independence directly via ONC/eigenvalue effective-N). The firewall is re-anchored output-side. The monotone-stricter floor, selection-set scope, split `n_trials`, and flag-OFF invariance all stand. See the reconciled plan for the authoritative version + build order.

**Finding:** Coverage-Memory v1 ships a *plain-language caveat* (`CoverageMap.CROSS_RUN_CAVEAT`) admitting that each run's deflated-Sharpe (DSR) corrects only for that run's own trials — so a campaign that fills the grid across many runs/assets/templates and cherry-picks the best surviving cell carries an **uncorrected cumulative multiple-testing burden**. v2 replaces that caveat with an actual, firewall-safe correction: a grid-derived selection-set size **N** fed into the DSR hurdle `sr0`.
**Status:** DRAFT v2 (2026-07-15 — supersedes the DRAFT-v1 spec; folds in the 5-lens adversarial review: floors the anti-conservative N/V flips, widens N to the true campaign pool, pins N per-run, orders the C3/GRID_VERSION/backfill dependency, and re-anchors every AC on a concrete observable). Turns `COVERAGE-MEMORY-V2-PLAN.md`'s 5 blockers + 6-step recipe into numbered Requirements/Decisions; nothing built yet.
**Date:** 2026-07-15
**File location:** `docs/design/COVERAGE-MEMORY-V2.md` (direct successor to `COVERAGE-MEMORY-V2-PLAN.md`, co-located with `COVERAGE-MEMORY-V1.md` and `COVERAGE-CALIBRATION.md`; it borrows the `docs/specs/` SPEC *header style* but belongs to the `docs/design/COVERAGE-MEMORY-*` family).
**Related:** `docs/design/COVERAGE-MEMORY-V1.md` (AT-1..AT-10, the AT-7 overfitting-neutral firewall — **NB its §Persistence advertises `survived_count`/`died_count`/`best_sharpe`; those columns were NEVER built, the shipped `ResearchCoverageDB` is performance-free — §5.7 corrects this**), `docs/design/COVERAGE-MEMORY-V2-PLAN.md` (review verdict, B1-B5, C1-C5, F1, recipe), `docs/design/COVERAGE-CALIBRATION.md` (the signal-flip JND study + GRID_VERSION), the deflated-Sharpe machinery (`backtesting/gates/deflated_sharpe.py`, ATS-1744), `docs/specs/REGIME-VALIDATION-CONFIDENCE-SPEC.md` (house style; DSR = multiple-testing selection bias, distinct from the block-CI).
**Ticket:** staged locally under epic **ATS-1787 (quant-review-remediation)** as a sub-task — this feature remediates the shipped `CROSS_RUN_CAVEAT` honesty gap flagged by the quant review; alternative home is a Story under **ATS-1699** (falsification-engine epic that owns DSR gate ATS-1744). Jira token is expired (create/sync 401-blocked), so it gets its real key on push (see OD-7).

> **Scope (this slice):** ONE deliberate, tested, performance-free wire — a grid-derived **`search_size` N** (+ theoretical null V≈1/T) — from the AI/research coverage memory into the backtesting DSR gate's `sr0` hurdle, so a cross-run robustness *campaign* is penalised for the multiplicity it actually incurred. **Robustness mode only. Behind the coverage flag. Everything except this single seam stays coverage-blind (v1 AT-7 preserved). Enabling the flag can only ever make the verdict STRICTER, never weaker.**

---

## 0. What the review verdict changed (naive plan → v2 → this revision)

The naive v2 plan — "feed `len(feasible_cells)` in as N, keep this run's per-run variance V" — is **not sound** (V2-PLAN, 5 blockers). The DRAFT-v1 spec fixed those blockers but a 5-lens adversarial review found **residual anti-conservative flips** the first draft still left open. This revision closes them. The load-bearing principle is unchanged:

> **PRINCIPLE — N and V are ONE atomic, co-scoped swap, and they are the ONLY thing coverage feeds into significance.** `sr0 = √V · f(N)` is the *expected maximum of N draws from one null population*. v2 swaps in a campaign-scoped N **and** a matching theoretical null V≈1/T **together** (never N alone), keeps the realized-executed-trial count as the sample-adequacy guard, stores **no per-cell performance** anywhere, and **floors the verdict at v1's own hurdle so enabling the flag can never loosen the gate.**

Consequences (each ties to a blocker or a review finding):
- **N is the REALIZED cross-run VISITED count, not the full grid** (B1) — capped per-template at `reachable_cells(t)`. Justification is **honesty, not vacuity-avoidance**: the full grid counts thousands of hypotheses that were never tested. (Correcting the DRAFT's arithmetic: `3.90`/`2.53` are the `f(N)` *multiplier* values, not `sr0`; under the adopted V≈1/T even a full-per-template N≈4394 gives `sr0≈0.082/period ≈ 1.30 annualised` — demanding but **not** vacuous, so the realized-visited choice is justified on honesty grounds, and the caps keep the gate non-vacuous across the whole reachable grid.)
- **N spans the actual selection scope = the whole campaign pool** (B2) — cross-asset × cross-template × cross-run. **REVISED:** N is computed over **all assets ever visited for `(scope_key, window_key="")`**, not just this run's assets, because a campaign that varies its asset set across runs is still cherry-picked across all of them (review: current-run-assets-only under-counts — the anti-conservative direction).
- **V is co-scoped with N** (B3) — theoretical null V≈1/T (T = bar count), computed from the return-array *length* only → firewall-safe. Documented as a **Gaussian-IID approximation whose conservatism is not unconditional** (fat tails / autocorrelation inflate the true Var(SR̂) above 1/T); safety does **not** rest on that approximation — it rests on the v1-hurdle floor below.
- **`n_trials` is split** (B4) — a realized-executed-trials counter (`guard_n`) drives the `<2` auto-pass / `<20` provisional valve; a separate `search_size` N enters `sr0` only.
- **N is a conservative UPPER bound** (B5) — correlated adjacent cells (~0.9+ Sharpe correlation) mean the raw count over-states independent trials → over-rejects = the *safe* direction. Ship raw; reduce toward an effective-N only via a pre-registered correlation model; **never inflate**.
- **NEW — N is floored at the realized trial count** (`N_eff = max(search_size, guard_n)`): distinct-cell dedup can drop the campaign count *below* this run's own trial count (first/duplicate-heavy run), which would weaken the hurdle. The campaign pool is a superset of this run's own trials, so its multiplicity can never honestly be smaller.
- **NEW — the campaign verdict is floored at v1's own hurdle** (monotone-stricter guarantee): the gate takes the **stricter (lower) of** `DSR(N_eff, V≈1/T)` and the exact v1 pair `DSR(guard_n, V_measured)` (when V is measured). This closes the residual flip where V≈1/T < V_measured at N≈guard_n. It never forms the forbidden `(N_eff, V_measured)` combination — it takes the min of two internally-consistent hurdles.
- **NEW — N is pinned per-run** (order-independence): `N_base` is snapshotted **once at run start** over the full campaign pool; every candidate in the run sees the same N; the report recomputes the surfaced winner's N against the **end-of-run** campaign pool.
- **NEW — Phase 0 ordering is hard**: the C3 `GRID_VERSION` bump orphans the cross-run registry `load_coverage` reads (it filters on `grid_version`), so Phase 0 **must** re-run `backfill_coverage` under the new version before the flag is enable-able.

---

## 1. Context & problem statement

**Plain version.** Imagine you run the search a hundred times, each on a slightly different corner of the parameter space, and at the end you keep the single best-looking strategy. Even if *nothing* has real skill, the best of a hundred lucky draws looks impressive — that is multiple testing. Today each run's significance check only knows about the handful of strategies *that run* tried; it has no idea the campaign as a whole rummaged through hundreds. So the "best across the campaign" gets a pass it did not earn.

**Precise version.** The DSR gate (`deflated_sharpe.py`) computes an expected-maximum-Sharpe hurdle `sr0 = √V·[(1−γ)·Z(1−1/N) + γ·Z(1−1/(N·e))]` (lines 52-55) where **N = the number of trials the winner was selected from**. In the research loop, N (`ctx.n_trials_global`) is the count of *this run's* gate-evaluable per-period Sharpes, reset by a fresh gatekeeper each run. Coverage memory (v1) already accumulates the distinct cross-run **visited-cell set** in `research_coverage` (a performance-free spatial registry). The campaign winner is chosen over that whole visited set, but `sr0` only ever sees one run's N. v1 shipped a caveat instead of a fix; v2 supplies the fix.

**The honesty constraint (non-negotiable).** The correction must never make the coverage memory a performance-steering device. v1 deliberately stores no per-cell Sharpe/survived/died and the significance path is coverage-blind (AT-7). v2 opens **exactly one seam** — an integer cell-count into `sr0` — and must prove everything else stays blind.

---

## 2. Goals & non-goals

**Goals**
- **G1** — Penalise a cross-run robustness campaign for the multiplicity it *actually* incurred, by feeding a campaign-scoped selection size N into `sr0`.
- **G2** — Keep the correction **firewall-safe**: the only coverage→significance data is one integer (a cell count); V is derived from the bar count; `research_coverage` stays performance-free; `exemplar_hash` never joins into the counted N.
- **G3** — Keep the correction **conservative and non-vacuous**: realized-visited N (not full grid), capped at the grid total, `multi_indicator` excluded, raw count documented as an upper bound.
- **G4** — Preserve the sample-adequacy valve: tiny real-trial runs stay provisional/auto-pass, never a firm grid-size FAIL.
- **G5** — Deterministic (seeded), no LLM, €0, within the existing loop. Behind the coverage flag; **flag OFF ⇒ byte-identical to v1**; **flag ON ⇒ never a weaker verdict than flag OFF**.
- **G6** — Respect the module boundary: N/V computed on the AI/research side, passed to the backtesting gate as plain numbers (`ai` may import `backtesting`, never the reverse — `.importlinter` `backtesting-boundaries` contract stays green).

**Non-goals (explicitly OUT for this slice)**
- **N1 — No auto-stop on exhaustion.** v1 only *reports* saturation; v2 keeps it that way (AT-10 unchanged).
- **N2 — No regime-mode coverage.** Each regime window is its own space; v2 is robustness-only (`coverage_memory and mode=='robustness'`, run.py:270). Regime keeps its P2 within-window hold-out on the untouched per-run DSR path.
- **N3 — No B5 effective-N correlation reduction.** Ship the raw visited count as a conservative upper bound; the Galwey/Li-Ji/`1+(N−1)ρ̄` reduction is a pre-registered fast-follow, only invoked if the gate proves vacuous. **Never inflate past the raw count.** (A telemetry *vacuity canary* ships now — R14 — so a mature campaign never silently zero-passes without a flag.)
- **N4 — No firewalled per-trial-Sharpe (pooled-V) table.** V is purely theoretical (≈1/T) for this slice; a firewalled pooled-V estimator is the B3 alternative, deferred with pre-registered acceptance criteria (OD-2/OD-4).
- **N5 — No measurement of maximin box-extreme bias.** Left to the OOS lockbox as arbiter (v1 §Overfitting-neutrality note).
- **N6 — No new campaign-grouping id.** Use the natural, already-persisted `(scope_key=user_id, window_key="")` pool; no `campaign_id` column (OD-1). The conservative consequence — lumping a user's genuinely-unrelated robustness goals into one campaign — is the SAFE direction and honestly documented.
- **N7 — No variance-inflation of V.** A firewall-safe Newey-West/fat-tail multiplier on V is a pre-registered fast-follow (OD-2); this slice ships V≈1/T *documented as an approximation* and relies on the v1-hurdle floor (R9b) for safety, not on 1/T being conservative.

---

## 3. Requirements

| ID | Requirement |
|----|-------------|
| **R1** (B1) | The DSR multiplicity **N is the REALIZED cumulative cross-run VISITED-cell count**, restricted to the reachable set (`visited ∩ reachable_cells(t)`) and **capped per-template at `len(reachable_cells(t))`**. It is NEVER a silent full-grid `len(feasible_cells)`/`len(reachable_cells)` count. |
| **R2** (B2) | N is summed over the **whole campaign selection pool** — every visited `(template, asset)` pair for `(scope_key=user_id, window_key="")`, **including assets not in the current run** (cross-asset × cross-template × cross-run). N must **never be narrower** than the pool the winner could be chosen over. |
| **R3** (B3) | In campaign mode the campaign-term null variance is the **theoretical V ≈ 1/T** (T = candidate's `len(returns)`, computed from array length only). N and V are swapped **atomically**; **no code path forms `(N_eff, trial_sr_variance)`**. V≈1/T is documented as a Gaussian-IID approximation, not unconditionally conservative (see R9b for the safety guarantee that does not depend on it). |
| **R4** (B4) | `n_trials` is **split**. A realized-executed-trials counter `guard_n` (gate-evaluable per-period Sharpes, as today) drives the `<2` auto-pass and `<PROVISIONAL_BELOW=20` provisional guards. A separate `search_size` N enters `sr0` only. A 3-backtest run reports **provisional**, never a firm grid-size FAIL. |
| **R5** (B5) | N is a **documented conservative UPPER bound**. No effective-N reduction ships in this slice; any future reduction must use a *pre-registered* cell-Sharpe correlation model and may only **reduce**, never inflate past the raw visited count. |
| **R6** (C1) | `multi_indicator` (in `coverage._UNCALIBRATED`) is **excluded/floored from N** — its near-dead, uncalibratable cell count is never added as a distinct-hypothesis count. |
| **R7** (C3) | The grid resolutions N rests on must use a **conservative cross-asset aggregate of per-step DISAGREEMENT** (a high quantile / max of the per-asset `vals` inside `mean_disagree`, NOT `statistics.median`), because higher disagreement → the JND target crosses at a *smaller* step → finer grid → more cells → larger N = the safe direction. This requires a re-calibration (§9 Phase 0, gating prerequisite). |
| **R8** (firewall) | **Exactly one** coverage→significance seam exists: `GateContext.search_size` (a single `int | None`). `campaign_search_size` is a pure function of visited-cell geometry (references only `visited`/`reachable_cells`/`_UNCALIBRATED`; names no `exemplar_hash`, candidate/failure/sharpe/return/oos symbol). `load_coverage` routes `exemplar_hash` into `tried_hashes` **only** (exact dedup), never into the counted visited set. `research_coverage` stores no per-cell performance; `deflated_sharpe.py` (and every `backtesting` gate) imports nothing from `ai/research`. All testable (V2-AT-6). |
| **R9** (flag) | Behind the coverage flag. **`coverage_memory` OFF ⇒ `search_size` is `None` ⇒ the DSR inputs, value, verdict and details are byte-identical to v1** (same realized n_trials, same measured V, same `sr0`). The byte-identical guarantee is scoped to the **significance path with the grid held fixed** (Phase 0's grid re-calibration is a separate v1-grid change — §6 note). |
| **R9b** (NEW — monotone-stricter) | **Enabling the correction can only ever make the verdict STRICTER, never weaker.** N is floored at the realized trial count (`N_eff = max(search_size, guard_n)`), and when `trial_sr_variance` is *measured* the campaign verdict is floored at v1's own hurdle: `DSR_eff = min(DSR(returns, N_eff, 1/T), DSR(returns, guard_n, V_measured))`. When V is defaulted, the campaign term (V≈1/T, real) stands alone (v1 would have been provisional, so there is no firm v1 hurdle to floor against). No path forms `(N_eff, V_measured)`. |
| **R10** | The report/verdict surfaces **both** counts honestly: the realized executed-trials AND the `search_size` N used in `sr0`, with N labelled a *conservative upper bound* (replacing the v1 `CROSS_RUN_CAVEAT` placeholder). The surfaced **campaign winner's** N is recomputed against the **end-of-run** campaign pool (R12), not the mid-run partial N. |
| **R11** | Pin box `[low,high]` bounds + `grid_version`: N must not silently move when a range is widened — that is a `grid_version` bump (C5). N is a *frozen, data-informed, pre-registered* bound. |
| **R12** (NEW — order-independence) | N is pinned **once per run**: `N_base` is snapshotted at run start over the full campaign pool; every gated candidate in the run uses `N = max(N_base, guard_n)` (independent of within-run proposal order); `N ≥ N_base` always. The report recomputes the winner's N against the end-of-run pool. |
| **R13** (NEW — Phase-0 ordering) | The C3 `GRID_VERSION` bump orphans the cross-run registry (`load_coverage` filters `grid_version==GRID_VERSION`). Phase 0 **must** re-run `backfill_coverage` under the new version so N recovers the pre-bump cross-run cell count **before** the flag is enable-able. C3 + backfill are a **hard predecessor** to enablement (not a parallel prerequisite). |
| **R14** (NEW — vacuity canary) | Campaign mode emits a **telemetry flag** (`campaign_multiplicity_vacuity_warning`) when the campaign hurdle enters the documented known-vacuous regime (would reject a genuinely-strong candidate). Behaviour is unchanged (telemetry only); it exists so a mature campaign never silently zero-passes without surfacing that the raw upper-bound N has become over-strict. |

---

## 4. Plain-language summary

> Today, when the tool decides whether a strategy is "real," it corrects for how many strategies **this run** tried. But if you run the search over and over and keep the best one at the end, the real number of strategies you rummaged through is much larger — and the winner should have to clear a **higher bar**. v2 counts how many distinct strategies your whole campaign has actually visited (across runs, assets, and strategy types, including assets you explored in *other* runs), and raises that bar accordingly. To stay honest, we keep the memory "blind": it only ever hands the significance check **one number — a count of visited cells** — and nothing about which ones did well (so it can never quietly learn to steer you toward lucky corners). The count is a deliberate over-estimate (adjacent strategies are near-copies) — we err on the side of *too strict*, and we say so. If your campaign only ran three real backtests, we still say "provisional, not enough evidence" rather than a giant-campaign FAIL. Crucially: **turning this on can only ever make the bar higher, never lower** — we floor the new check against the old one. And with the feature switched off, nothing changes at all.

---

## 5. Technical specification

### 5.1 Inputs available today
- `coverage.reachable_cells(template_id) -> frozenset[str]` (coverage.py:216-244) — the canonical distinct-strategy count per template (F1: use this, NOT `feasible_cells`). **Counts are pre-C3 (GRID_VERSION="v2")** and will move under the C3/v3 re-calibration this spec mandates: sma 132, macd 196, bollinger 364, rsi 4394, multi 96. **Superseded by v3 — do not pin downstream reasoning to these; `multi_indicator` is floored from N regardless of whether it is 96 (coarse) or the 13,013 the fine analogs would imply.**
- `coverage.load_coverage(scope_key, assets, window_key="") -> CoverageMap` (coverage.py:350-373) — returns `cov.visited: dict[(template, asset) -> set[cell_id]]`, filtered to the run's `assets` and to `grid_version==GRID_VERSION`. Routes `exemplar_hash` into `tried_hashes` only (line 371-372). **A NEW campaign-pool loader (§5.2) drops the asset filter for the N count.**
- `coverage._UNCALIBRATED = frozenset({"multi_indicator"})` (coverage.py:65).
- `coverage.backfill_coverage(scope_key, window_key="")` (coverage.py:414-472) — idempotently re-derives visited cells from persisted candidates/failures under the current `GRID_VERSION` (used by Phase 0 after the v3 bump — R13).
- `_period_sharpe`/`_dsr_registry_inputs(period_sharpes) -> (n_trials, V, defaulted)` (loop.py:299-329) — the realized-executed per-period-Sharpe list and its ddof=1 variance (= `guard_n`, `V_measured`).
- `deflated_sharpe(returns, n_trials, trial_sr_variance)` (deflated_sharpe.py:21-63) — guards `n<3 or n_trials<1 or trial_sr_variance<=0 → 0.0` (line 41). Note `n_trials==1 → z(1−1/1)=z(0)=−inf` (a garbage auto-pass); the `>=2` campaign guard (§5.4) and R9's v1 path keep degenerate N out (V2-AT-13). `DeflatedSharpeGate.check` guards `n_trials<2` auto-pass (line 88), `<PROVISIONAL_BELOW=20` provisional (line 104). `n = r.size` is T.
- `GateContext` fields `n_trials_global`, `trial_sr_variance`, `trial_sr_variance_defaulted` (pipeline.py:70-72), field set frozen for the firewall whitelist (V2-AT-6).
- Flag: `run_research(coverage_memory=False, user_id=...)` (run.py:151-152); coverage loaded only when `coverage_memory and mode=='robustness'` (run.py:266-273).

### 5.2 New primitives — the campaign selection size (AI side, `coverage.py`)

`campaign_search_size` is a **`CoverageMap` method** (not a module-level function — it reads the visited set; matches the `mark`/`pct_covered`/`novelty_rate` convention where operations over `visited` are methods, calling the module-level grid geometry `reachable_cells`). **Pure geometry over the loaded visited set — reads no performance.**

```
def campaign_search_size(self) -> int:
    \"\"\"v2 DSR multiplicity N (B1/B2/R1/R2/R6): the REALIZED cross-run VISITED-cell count over the
    campaign pool, per-template capped at the reachable grid total, multi_indicator excluded. Never full grid.
    Pure function of self.visited geometry — references NO performance, NO exemplar_hash, NO candidate/failure.\"\"\"
    total = 0
    for (template_id, _asset), cells in self.visited.items():
        if template_id in _UNCALIBRATED:            # R6: multi_indicator floored out
            continue
        reach = reachable_cells(template_id)         # F1: reachable, not feasible
        total += min(len(cells & reach), len(reach)) # R1/R5: realized ∩ reachable (cap redundant-but-explicit)
    return int(total)
```
- **R2 (campaign pool):** the `CoverageMap` used for N is loaded over the **full campaign pool** via a new `load_campaign_pool(scope_key, window_key="")` that runs the same query as `load_coverage` **minus the `security_id.in_(assets)` filter** — so N counts every asset ever visited for the scope, not just this run's. (The sampler keeps using the asset-filtered `load_coverage`; it needs this run's assets only.)
- **Cap note (review):** `cells & reach ⊆ reach` always, so `min(…, len(reach))` never binds when N is the realized intersection — the anti-inflation work is done by the *intersection*, and the cap only becomes load-bearing if a non-realized/worst-case-bound N is ever substituted. Kept as explicit belt-and-suspenders.
- Empty pool ⇒ N = 0 ⇒ campaign mode inactive (falls back to the realized-trials guard; no divide-by-zero / `z(0)` into `sr0`).

### 5.3 The single seam — `GateContext.search_size` (pipeline.py:70-73)
Add one field (the ONLY new coverage→significance channel, R8):
```
search_size: int | None = None   # v2: campaign cross-run selection size for DSR sr0 (None = v1 path)
```

### 5.4 The split-`n_trials` + monotone-stricter contract in the gate (`DeflatedSharpeGate.check`, 77-139)
`deflated_sharpe()` itself is **unchanged** (still `(returns, N, V)`); the split + floor live in `check`:
```
def check(self, ctx):
    guard_n = ctx.n_trials_global                          # B4/R4: realized executed trials → guards ONLY
    v_meas = ctx.trial_sr_variance
    v_meas_defaulted = bool(ctx.trial_sr_variance_defaulted) or v_meas <= 0
    campaign = ctx.search_size is not None and ctx.search_size >= 2   # V2-AT-13: N in {None,0,1} => v1 path

    if guard_n < 2:                                        # B4: auto-pass keys on REALIZED count
        return self._pass(reason=\"too few trials for DSR, provisional pass\", provisional=True,
                          n_trials=guard_n, search_size=ctx.search_size, sr_variance_defaulted=True)
    if ctx.returns is None or len(ctx.returns) < 3:
        return self._fail(reason=\"insufficient return data for DSR\")

    if campaign:
        n_eff = max(int(ctx.search_size), guard_n)         # R9b: floor N at realized trial count
        n_bars = len(ctx.returns)
        v_theo = 1.0 / n_bars                              # B3/R3: theoretical null V=1/T, from LENGTH only
        dsr_campaign = deflated_sharpe(ctx.returns, n_eff, v_theo)
        if not v_meas_defaulted:                           # R9b: floor verdict at v1's own hurdle (measured V only)
            dsr_v1 = deflated_sharpe(ctx.returns, guard_n, v_meas)   # exact v1 pair — never (n_eff, v_meas)
            dsr = min(dsr_campaign, dsr_v1)                # stricter of two internally-consistent hurdles
        else:
            dsr = dsr_campaign                             # v1 would have been provisional; no firm floor
        is_provisional = guard_n < self.PROVISIONAL_BELOW  # campaign V=1/T is real, does NOT force provisional
        vacuity_warn = _campaign_vacuity(n_eff, n_bars)    # R14: telemetry only
        n_for_sr0 = n_eff
    else:                                                  # v1 path — byte-identical
        v_used, v_def = v_meas, v_meas_defaulted
        if v_used <= 0: v_used, v_def = 0.001, True
        dsr = deflated_sharpe(ctx.returns, guard_n, v_used)
        is_provisional = guard_n < self.PROVISIONAL_BELOW or v_def
        vacuity_warn = False
        n_for_sr0 = guard_n

    # PASS/FAIL exactly as today, emitting BOTH n_trials=guard_n AND search_size (=n_for_sr0 in campaign) (R10)
    ...
```
- **B4/R4 satisfied:** guards read `guard_n` (realized); a 3-backtest run → `guard_n=3 < 20` → provisional even if `search_size` is 400.
- **B3/R3 satisfied:** the campaign term sets N and V *together*; `v_theo=1/n_bars` touches no return *values*; there is no `deflated_sharpe(returns, n_eff, v_meas)` call anywhere.
- **R9b satisfied:** `n_eff ≥ guard_n`, and (when V measured) `dsr = min(campaign, v1)` ⇒ `dsr ≤` the flag-OFF value, so enabling never loosens. The defaulted-V branch cannot manufacture a firm FAIL from the floored `0.001` because it excludes the v1 floor term entirely.
- **Firm verdict:** requires `guard_n ≥ 20` (real evidence); a firm PASS/FAIL then honestly reflects cross-run multiplicity and can never be weaker than v1's.

`_campaign_vacuity(n_eff, n_bars)` (R14): returns True when `sr0 = sqrt(1/n_bars)·f(n_eff)` exceeds a documented annualised ceiling (a hurdle so high a genuinely-strong strategy — e.g. annualised Sharpe 2 — could not clear it). Pure arithmetic, no performance.

### 5.5 Threading (all AI side; gate receives plain ints — boundary-clean)
1. **loop.py:682 (`research_loop` signature)** — add a keyword-only param `coverage: CoverageMap | None = None`, alongside `lockbox`/`lineage_tracker` (same optional-component convention). Do **not** rely on `strategist.coverage` (absent on the primary `LLMStrategist` path in `full_ai` mode).
2. **run.py:266-273 + ~326** — inside the existing `if coverage_memory and mode=='robustness':` block, after `load_coverage` (sampler pool), also build the **campaign-pool** map `campaign_cov = await load_campaign_pool(scope_key, window_key="")` and pass it into the `research_loop(...)` call as `coverage=campaign_cov`. Snapshot `N_base = campaign_cov.campaign_search_size()` **once** here (R12).
3. **loop.py (loop entry)** — compute `N_base` once at run start (or receive it); at each `_dsr_registry_inputs` gate-eval site, `search_size = max(N_base, 0) if coverage is not None else None` — the same `N_base` for every candidate in the run (R12). Thread into `gatekeeper.update_registry_stats(..., search_size=search_size)`. When `coverage is None`: `search_size=None`.
4. **gatekeeper.py:114-121, 168-171** — `update_registry_stats(..., search_size: int | None = None)` stores `self.search_size`; `evaluate` passes it into `GateContext(...)`. `n_trials_global`/`trial_sr_variance` keep their current (realized) meaning.
5. **deflated_sharpe.py** — as §5.4. Gate stays a pure int sink; imports nothing from `ai`.
6. **Report-time winner recompute (R10/R12):** at report generation, recompute the surfaced winner's N against the **end-of-run** campaign pool (`N_base` + this run's `newly_visited` across the pool) and recompute its DSR against that final N.

### 5.6 Surfacing (R10)
- **quality.py:51-69** — the `dsr` overlay dict gains `search_size` alongside `trials`; the ValConf/robustness narrative reports both ("selected from N≈… across the campaign; N is a conservative upper bound") and surfaces `campaign_multiplicity_vacuity_warning` when set (R14).
- **report_generator.py:94, 174-187** — the DSR analysis section reports the real `search_size` N the hurdle used (reconciling the disconnect where it currently shows `state.total_iterations`), plus the realized trial count. The v1 `CROSS_RUN_CAVEAT` text is replaced by a statement that the cross-run correction is now applied (as an upper bound). The winner's N is the end-of-run campaign count.

### 5.7 Data-model / persistence
- **No change to `research_coverage`.** It already holds the distinct cross-run visited set, performance-free (the shipped `ResearchCoverageDB` has NO `best_sharpe`/`survived_count`/`died_count`; `exemplar_hash` is an exact-dedup key routed only into `tried_hashes`). The firewall requires it stays that way (R8). N is derived live from the loaded map.
- **Doc reconciliation (review):** `COVERAGE-MEMORY-V1.md` §Persistence still *advertises* `survived_count`/`died_count`/`best_sharpe` as "telemetry only" — **those columns were never implemented.** This spec states the shipped schema is performance-free; V1.md §54-62 must be annotated stale so a v2 implementer does not believe per-cell performance already exists and is fair game (a separate doc-only edit, out of this deliverable's file-write scope — flagged for the human).
- **Optional / deferred (N6):** a nullable `coverage_memory` bool on `research_runs` for post-hoc provenance. Additive, nullable, zero migration risk; not required for the first slice.
- **Deferred pooled-V table (OD-2/OD-4/N4) pre-registered acceptance criteria** (so "exactly one seam" cannot decay into two by omission): if ever added, it is written/read ONLY to estimate V over the SAME pool that defines N, never joined to selection/ranking/sampling; the sampler and strategist provably cannot read it (import + AST guard); it carries its own firewall AC analogous to a strengthened V2-AT-6.

### 5.8 C3 re-calibration (prerequisite, R7)
- **scripts/calibrate_coverage_grid.py** — refactor `mean_disagree` (line 108-114) to **return the full per-asset disagreement dict** rather than reducing to `statistics.median(vals)` inside it; aggregate at the `jnd_for` call site with a **high quantile / max of the per-asset DISAGREEMENT values** (higher disagreement → JND target crosses at a smaller step → smaller JND → finer grid → more cells → larger N = safe direction). Persist the **raw per-asset curves** so the quantile choice is auditable without re-running. (Review correction: the aggregate is over per-step *disagreement* (`vals`), NOT over per-asset *JND* — max-of-JND would be *coarser*, the wrong direction.)
- **coverage.py:42-53** — hand-transcribe the new (smaller) resolutions into `_PERIOD_RATIO`/`_THRESHOLD_STEP`/`_MULTIPLIER_STEP`.
- **coverage.py:38** — bump `GRID_VERSION "v2" → "v3"` (cell ids change; v2-persisted cells namespaced apart). `(rsi_reversion, period)` is integer-governed (insensitive to the quantile change); `multi_indicator` stays excluded regardless.
- **Backfill under v3 (R13):** run `backfill_coverage(scope_key, window_key)` under v3 so N recovers the pre-bump cross-run history for every active scope **before** the flag is enable-able.
- Ideally re-calibrate on assets/window **disjoint** from the evaluation set (C5) so N is data-informed-but-out-of-sample.

### 5.9 Integration points by file
`coverage.py` (new `CoverageMap.campaign_search_size` method + `load_campaign_pool`; `reachable_cells` 216-244; `_UNCALIBRATED` 65; `load_coverage` 350-373; `backfill_coverage` 414; C3 tables 42-53; `GRID_VERSION` 38) · `pipeline.py` (`GateContext.search_size` 70-73) · `gatekeeper.py` (`update_registry_stats` 114-121; `GateContext` build 168-171) · `deflated_sharpe.py` (`check` split + min-floor + vacuity 77-139) · `loop.py` (`research_loop` signature 682; `_dsr_registry_inputs` 315-329; call site) · `run.py` (coverage block 266-273; N_base snapshot; `research_loop(coverage=…)` call ~326) · `quality.py` (51-69) · `report_generator.py` (94, 174-187) · `scripts/calibrate_coverage_grid.py` (`mean_disagree` 108-114, persistence) · `.importlinter` (`backtesting-boundaries`, must stay green).

---

## 6. Status ↔ flag mapping (behaviour matrix)

| Condition | `search_size` | `sr0` uses | Guards use | Verdict behaviour |
|---|---|---|---|---|
| flag OFF (any mode) | `None` | realized n_trials + per-run V | realized n_trials | **Byte-identical to v1** (R9) |
| flag ON, regime mode | `None` (N2) | realized n_trials + per-run V | realized n_trials | Unchanged v1 DSR path |
| flag ON, robustness, `search_size ∈ {None,0,1}` | `None`/0/1 | realized n_trials + per-run V (v1 path) | realized n_trials | v1 path (degenerate-N guard, V2-AT-13) |
| flag ON, robustness, `guard_n < 2` | int (≥2) | — | realized n_trials | Auto-pass provisional (R4) |
| flag ON, robustness, `2 ≤ guard_n < 20` | int (≥2) | `min(campaign N_eff+V≈1/T , v1)` | realized n_trials | Provisional (R4) — never firm grid FAIL |
| flag ON, robustness, `guard_n ≥ 20` | int (≥2) | `min(campaign N_eff+V≈1/T , v1)` | realized n_trials | **Firm PASS/FAIL** reflecting cross-run multiplicity; **≤ flag-OFF DSR** (R9b) |

> **Note (review):** R9's "byte-identical to v1" is scoped to the **significance path with the grid held fixed**. Phase 0's C3 `GRID_VERSION v2→v3` re-calibration changes v1 *sampling/coverage%* (pick_cell/pct_covered/novelty all key on `GRID_VERSION`) for existing flag-ON v1 users regardless of the v2 wire — that is a deliberate v1-grid change, not covered by the byte-identical claim.

---

## 7. Decisions (recommended defaults from the recipe + review)

- **D1 (B1/R1) — N = realized cross-run VISITED count, capped at grid total.** `campaign_search_size` sums `min(|visited ∩ reachable(t)|, |reachable(t)|)`. NOT full grid. → §5.2.
- **D2 (B2/R2) — Selection scope = the full campaign pool** = every visited `(template, asset)` for `(scope_key=user_id, window_key="")`, **including assets not in the current run** (via `load_campaign_pool`, no asset filter). Cross-asset × cross-template × cross-run. → OD-1.
- **D3 (B3/R3) — Theoretical null V ≈ 1/T** (T = `len(returns)`), co-scoped atomically with N; documented as a Gaussian-IID approximation. Safety does not rest on it (→ D3b). Firewalled pooled V deferred → OD-2/OD-4.
- **D3b (NEW/R9b) — Monotone-stricter floor.** `N_eff = max(search_size, guard_n)`; verdict `= min(DSR(N_eff,1/T), DSR(guard_n,V_measured))` when V measured (campaign term alone when V defaulted). Enabling the flag can only tighten. → §5.4.
- **D4 (B4/R4) — Split into `guard_n` (realized, guards) and `search_size` (sr0 only).** → §5.3-5.4.
- **D5 (B5/R5) — Ship the RAW visited count as a conservative upper bound.** No effective-N reduction this slice; future reduction pre-registered + reduce-only; a vacuity canary (R14) surfaces over-strictness meanwhile. → N3.
- **D6 (C1/R6) — Exclude `multi_indicator` from N** via `_UNCALIBRATED`. → §5.2.
- **D7 (C3/R7) — Conservative cross-asset aggregate of per-step DISAGREEMENT (high quantile/max, not median)** + re-calibration + `GRID_VERSION` bump + **backfill under v3**, gating prerequisite. → §5.8, OD-3.
- **D8 (firewall/R8) — Exactly one seam: `GateContext.search_size` (int).** `campaign_search_size` pure geometry; `exemplar_hash` never into N; gate imports no `ai`; no cross-cell ranking. → §5.2, V2-AT-6.
- **D9 (flag/R9) — Flag OFF ⇒ `search_size=None` ⇒ byte-identical v1.** → §6, V2-AT-7.
- **D10 (C5/R11) — Pin box bounds + grid_version;** N moves only on a `grid_version` bump. → §5.8.
- **D11 (NEW/R12) — Pin N once per run** (`N_base` snapshot at run start over the campaign pool); winner recomputed at end-of-run N. → §5.5.
- **D12 (NEW/R13) — Phase 0 (C3 + v3 + backfill) is a hard predecessor to enablement.** → §9.

---

## 8. Honesty & validity notes (model-honesty principle + AT-7 firewall)

- **The single seam is the whole safety story.** The coverage memory hands the gate one integer (a count of visited cells). It never hands over a Sharpe, a rank, a "best cell," or `exemplar_hash`. V is derived from the bar *count*, not the returns. So the memory cannot learn to steer sampling toward lucky corners — v1's AT-7 overfitting-neutrality holds, with exactly one documented exception (the cell-count → `sr0` wire), tested by the positive-purity AC (V2-AT-6).
- **Conservative by construction, and we say so.** Realized-visited N (not full grid), the per-template cap, and excluding `multi_indicator` keep N honest and non-vacuous; the raw count over-states independence (correlated cells) so it errs toward *too strict*. All labelled an **upper bound** (R10), never sold as an exact effective-N.
- **Enabling the flag can only tighten (R9b).** N is floored at the realized trial count, and the campaign verdict is floored at v1's own hurdle. So the two anti-conservative flips the review found — (i) distinct-cell dedup dropping N below `guard_n`, (ii) V≈1/T understating the true null variance under fat tails/autocorrelation — cannot weaken any verdict below flag-OFF. V≈1/T is honestly documented as an approximation, not a guarantee; the guarantee is the floor.
- **We never manufacture a FAIL from thin evidence.** The realized-trials guard (B4) keeps a campaign that has only *executed* a few real backtests provisional even while its visited-cell N is large. Firm verdicts still require ≥20 real trials. A defaulted per-run V never drives a firm FAIL (the campaign term stands alone, R9b).
- **Order-independence (R12).** N is snapshotted once per run, so two identical candidates get the same verdict regardless of loop position, and the campaign cannot shave its own multiplicity penalty via proposal ordering (a `full_ai`-mode concern where proposal order is performance-influenced).
- **DSR complementarity preserved.** The block-CI (ValConf) addresses single-estimate sampling noise; the DSR addresses selection over many trials. v2 sharpens the *N* the DSR uses; it does not conflate the two.
- **Anti-conservative directions we guard against with tests:** N narrower than the campaign pool (B2 → V2-AT-2/16), campaign-N paired with per-run V (B3 → V2-AT-3), median cross-asset leniency on high-vol names (C3 → V2-AT-9), counting multi (C1 → V2-AT-8), N below realized trials / V≈1/T weakening the hurdle (R9b → V2-AT-14), a v3 bump orphaning the registry (R13 → V2-AT-17).

---

## 9. Implementation plan (phased, each PR-able + test-gated)

**Phase 0 — C3 re-calibration + v3 + backfill (HARD gating predecessor, separate PR).** Refactor `mean_disagree` to return per-asset disagreement; aggregate with a high quantile/max at the call site; persist raw per-asset curves; re-run the harness (needs yfinance/network); hand-transcribe new resolutions (coverage.py:42-53); bump `GRID_VERSION`→"v3"; **run `backfill_coverage` under v3 for active scopes so N recovers cross-run history (R13).** Update `COVERAGE-CALIBRATION.md` + annotate `COVERAGE-MEMORY-V1.md` §Persistence stale (§5.7). Tests: V2-AT-9, V2-AT-17. **The flag is not enable-able until Phase 0 + backfill land** (drop the DRAFT's "build against the current grid meanwhile, just don't enable it" caveat — the v3 bump re-zeroes N's input, so the wiring is not independently usable before Phase 0).

**Phase 1 — the selection-size primitive.** `CoverageMap.campaign_search_size` (realized ∩ reachable, capped, multi-excluded) + `load_campaign_pool`. Pure-function tests: V2-AT-1, V2-AT-2, V2-AT-5, V2-AT-8, V2-AT-11, V2-AT-16. *No behaviour change (not yet wired).*

**Phase 2 — the split + seam + floor.** `GateContext.search_size` (pipeline.py); `DeflatedSharpeGate.check` split + `N_eff` floor + `min`-hurdle floor + vacuity canary (deflated_sharpe.py); `deflated_sharpe()` unchanged. Tests: V2-AT-3, V2-AT-4, V2-AT-10, V2-AT-13, V2-AT-14.

**Phase 3 — threading + flag gating + per-run pin.** `research_loop` signature; run.py `N_base` snapshot → loop → gatekeeper → gate. Tests: V2-AT-6 (firewall), V2-AT-7 (flag OFF byte-identical), V2-AT-15 (order-independence), full-run integration (`run_research(coverage_memory=True, user_id=1)` asserts campaign N reaches `sr0`).

**Phase 4 — surfacing.** quality.py + report_generator.py (both counts + upper-bound label + vacuity warning + winner-at-final-N; replace CROSS_RUN_CAVEAT). Tests: V2-AT-12.

**Phase Z — adversarial review**, remediate, merge. Confirm `.importlinter` stays green (no `backtesting → ai` edge).

**Tests to rework (do not under-count — enumerated):**
- `tests/unit/ai/research/test_coverage_memory.py` — add a `@pytest.mark.finding("coverage-v2")` V2-AT block.
- **`test_at7_summary_ships_cross_run_honesty_caveat` (line 192-199)** — the **digit-free** assertion (line 199) must be deliberately RELAXED (N carries digits) *if* summary() ever carries N; but per §5.6 surfacing goes via the report_generator/quality overlay, so keep `summary()` unchanged and update this test only if the caveat text changes. If the caveat wording is replaced, update the "per"/"that run"/"out-of-sample"/"re-validate" assertions to the "correction now applied (upper bound)" wording.
- **`test_at8_run_surfaces_coverage_spread_telemetry` (line 378, assert line 401)** — the narrative "does not correct"/"re-validate" assertion flips: update to assert the report states the cross-run correction is now applied (as an upper bound) and surfaces both counts.
- **`test_at7_summary_is_spread_only_no_cherry_pick_menu` (line 152-158)** — pins the `summary()` key-set exactly; confirm surfacing does NOT add a campaign field to `summary()` (it goes via the report overlay) so this stays green, or update the exact-set if it must change.
- Any DSR gate test constructing a `GateContext` — new optional `search_size` field defaults `None` → existing tests unaffected.
- `report_generator`/`quality` DSR-narrative tests.

**Risks:** (a) raw N is an upper bound → the gate can be conservative/vacuous on very large campaigns — mitigated by realized-visited N + per-template cap + `multi` exclusion (caps N at ≈ sum of reachable, ~5k, where V≈1/T keeps a Sharpe-2 strategy passing) + the vacuity canary (R14) + reduce-only effective-N fast-follow (N3). (b) **V≈1/T can under-state the true null Var(SR̂)** under fat tails / autocorrelation / flat-bar dilution (anti-conservative) — neutralised by the R9b v1-hurdle floor (verdict never weaker than flag-OFF) and honestly documented; a firewall-safe variance inflation is a pre-registered fast-follow (OD-2). (c) co-scoping error if a future edit pairs campaign N with per-run V → prevented by the atomic swap + `min`-of-two-consistent-hurdles in `check` (§5.4) + V2-AT-3. (d) provisional-valve regression → V2-AT-4. (e) firewall regression (a performance column, an `exemplar_hash` join into N, or a coverage import into the gate) → import-linter + V2-AT-6. (f) **C3 v3 bump orphaning the registry** → Phase 0 backfill (R13) + V2-AT-17. (g) N under-counts coverage-OFF historical runs (never wrote `research_coverage`) unless `backfill_coverage` is run — honest known limitation. (h) N recompute cost per run → trivial (≤ a few thousand cells, snapshotted once).

**Rollback:** set `coverage_memory` OFF (the default) → `search_size=None` → the DSR path is byte-identical to v1. Zero migration (no `research_coverage` schema change; the optional `research_runs` column is additive/nullable). A `GRID_VERSION` bump namespaces new cells apart, so rollback never corrupts prior coverage.
