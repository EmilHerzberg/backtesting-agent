# Layered Safety Architecture for the Coverage-Memory-v2 DSR Gate — FINAL

## 0. Purpose and the five non-negotiable invariants

Coverage-memory v2 will feed a **campaign-wide effective trial count `N`** into the Deflated-Sharpe hurdle
`sr0 = sqrt(V)·[ (1−γ)·Z(1−1/N) + γ·Z(1−1/(N·e)) ]` (verified live at `deflated_sharpe.py:52-55`), where a candidate passes only if its per-period Sharpe clears `sr0`. Enabling v2 flips this gate from near-inert (today `N` = per-run gate-evaluable trials, tens; `deflated_sharpe.py:88-120`) to potentially binding at large `N` — exactly when vacuity pressure peaks. This document is the safety envelope, designed **before** the code is written.

Every mechanism below is bound to five invariants that override any local design preference:

1. **Never loosen after seeing a result.** `N`, `V`, and the threshold are pre-registered and frozen (`PF5`). Estimation errors are forced to err **stricter / false-negative**. Vacuity is **reported**, never **retuned**.
2. **Cross-checks combine conservatively.** A pass requires the **stricter** verdict. No second method is ever an alternative "pass-if-either" path; second opinions can only **VETO** or **ANNOTATE**, never **upgrade**.
3. **Overfitting-neutral firewall + model-honesty.** No per-cell performance ever steers selection, the sampler, or mutation; no confidence number is manufactured beyond what the data supports.
4. **Defense-in-depth with a *quantified* ultimate arbiter.** The OOS lockbox is the terminal hard gate, hardened here so it only renders a terminal verdict when it has the statistical power and multiplicity control to do so — which is what makes "the in-sample DSR gate need not be perfect" actually true.
5. **Concrete pre-flight gates.** Both risks have a gating experiment that must PASS before implementation is allowed; a failure routes to a pre-designed fallback, never to a looser gate.

---

## 1. Plain-language summary (for the quant-literate non-statistician)

**The problem in one picture.** We try thousands of strategy settings and report the best. The best one always looks good *partly by luck* — the more settings you try, the luckier the winner looks. The Deflated Sharpe Ratio (DSR) is just a **bar that rises with how many things you tried**: try more, and the winner has to be better to be believed. `N` is "how many things you tried"; `V` is a noise-scaling knob; `sr0` is the bar.

**Two ways it breaks.**
- **Vacuity** — if we set the "things tried" count too high, the bar goes above what even a genuinely great strategy could clear, so *nothing ever passes*. That is a metal detector so sensitive it beeps at everyone; people respond by switching it off, or by quietly turning the sensitivity down after the fact. Both are failures.
- **The counting error** — our count treats near-identical settings as separate tries. It's like counting one coin flip ten times because you wrote it in ten notebooks. Two settings one "just-noticeable-difference" apart can have 90%+ identical profit-and-loss streams, so counting them as two independent tries inflates `N` in an **unknown** direction.

**What we actually do about it, in plain terms.**
1. **Count *genuinely different* bets, not *differently-labelled knobs*.** We look at how correlated the strategies' actual profit/loss streams are and count how many truly-independent bets that amounts to (this is the ONC / eigenvalue "effective number" method). Two strategies with 90%-identical returns count as roughly one bet, not two.
2. **We never lower the count after seeing who won.** The counting method, the noise knob `V`, and the bar are frozen and hashed before the campaign (`PF5`). If our count is uncertain, we round in the **stricter** direction.
3. **If the bar is genuinely too high to pass anything real, we say so out loud** and lean on a separate held-out test — we do **not** quietly shrink the count. Crucially, the "things tried" count is a *weak* lever: going from 1,000 to 10,000 tries only raises the bar ~15%. The bar is dominated by **how long your history is** (`T`) and the noise knob (`V`). So most "nothing passes" is really "your history is too short to be sure" — which you cannot fix by fiddling with the count, only by getting more data or deferring to the out-of-sample test. Our telemetry (`MON2`) shows the operator exactly which lever is binding, precisely so nobody is tempted to "fix" a short-history problem by shrinking `N`.
4. **The real judge is a held-out (out-of-sample) test.** It runs the strategy on future data it never saw. We found this judge had two flaws: it was often **under-powered** (too few future trades to tell skill from luck) yet still returned a confident "FAIL", and it was silently also demanding the strategy **beat buy-and-hold on raw return** — a bull-market bias, not a skill test. We fix the judge so "I can't tell" (UNEVALUATED, retryable) is kept distinct from "it failed" (FAIL, terminal), and so it grades **risk-adjusted skill**, not raw return.

The whole design is deliberately lopsided toward false-negatives: when in doubt, it refuses to confirm and pushes the decision to the held-out judge, rather than risk confirming a fluke.

---

## 2. The honest `N` and `V` transforms (the core)

### 2.1 `N` — measure independence, don't infer it from grid geometry

The draft's primary path (cell-count fed into the equicorrelation Kish design-effect `N/(1+(N−1)·ρ̄)` with an *adjacent-cell* `ρ̄`) is **retired as primary**. Adversarial analysis is correct and decisive: our grid correlation is **banded** (adjacent cells ~0.9, decaying to ~0 with grid distance), so the equicorrelation formula needs the **grand-mean** pairwise correlation, not adjacent `ρ̄`. Plugging adjacent `ρ̄≈0.9` makes `N_eff` saturate at ~`1/ρ̄≈1.1` for any large `N` — an artifact of the wrong input, which with the `N_run` floor would render cross-run accumulation **inert** while advertising a tightening. And an eigenvalue effective-count cannot be computed from a single scalar at all.

**Final `N` pipeline:**
- **Family definition (coverage-memory's job):** coverage-memory v2 supplies the *identities* of the visited cells across runs/assets/templates — the multiplicity family. It stores **no performance**.
- **Effective count (measured, primary):** at final evaluation, the return series of the family's cells (already reachable in the store) are pulled into a **run-scoped, ephemeral** computation, the correlation matrix is **Marcenko-Pastur denoised** (# trials can exceed `T`), and the **participation-ratio / ONC effective count** `N_eff = (Σλ)²/Σ(λ²)` (or ONC cluster count) is taken. This is the DSR-native answer (Bailey/López de Prado themselves cluster correlated trials).
- **Conservative by construction (RT1):** `N_used = max(N_eff, N_run)`. The lower floor at `N_run` guarantees enabling v2 is **monotone-stricter than today** and immune to any estimator collapse (a collapsed `N_eff` reverts to today's behavior, never toothless). `N_eff` is itself floored at an eigenvalue-Meff lower bound so the ONC path cannot **under-segment** (merge distinct-but-correlated strategies) into a too-small — hence too-lenient — count. **The standalone upper cap is removed** (a second, unjustified loosening lever worth only ~15% numerically); only a mechanistically-derived compute-guard well above any plausible `N_eff` remains, logged in `MON2` whenever it binds.
- **Firewall (output-side).** The invariant is re-anchored where it is actually enforceable: **only the single integer `N_used` exits** toward `sr0`/selection. The return matrix is used inside an isolated gate-time computation and is **never persisted** to any store the strategist/sampler reads. `PF6` is a hard leak-audit pass-gate proving this.

### 2.2 `V` — a fixed, conservative, firewall-safe null (not `1/T`)

The draft proposed `V = 1/T` as "firewall hardening." Adversarial analysis is right that this is **not reliably stricter** and is presented with an unchecked sign: today's measured cross-trial dispersion (`loop.py:328`) is typically *larger* than `1/T` on a wide grid, so switching to `1/T` would **shrink** `sr0` by ~`sqrt(2–3)` — a loosening wearing a firewall costume. `1/T` is also the wrong null under our conditions (serial-dependent, vol-clustered returns inflate the true Sharpe variance by the Lo factor; low-exposure cells are estimated from `n_trades`, not `T_bars`), each biasing **lenient**.

**Final `V` rule (`PF4`):** the firewall problem (measured `V` reads per-cell dispersion) is real and must be fixed, but the fix is **not** to adopt the smaller of two candidate `V`s.
- Use a **fixed, pre-registered `V_null`** computed on the **per-trade clock** the ValConf machinery already uses, inflated for serial dependence via the same Politis-White/block-bootstrap horizon the confidence code uses: `V_null = (1 + 2·Σρ_k)/T_eff`, and additionally set at/above the realized cross-trial dispersion measured **once** on the frozen grid at pre-flight (shape-channel/synthetic, no live per-cell Sharpe stored).
- **Mandatory direction check.** `PF4` REQUIRES `sr0(N_run, V_null) ≥ sr0(N_run, V_status_quo_typical)` on the frozen grid. If the firewall-safe `V_null` yields a *lower* hurdle, `V_null` is **raised** until the check passes — a lower hurdle under a "hardening" label is forbidden by Invariant 1.
- This makes the **joint** `(V, N)` change provably monotone-stricter than today **on the frozen grid, by construction** — closing the gap that the draft's fixed-`V` monotonicity proof left open.

---

## 3. The four-tier defense-in-depth stack

### Tier A — PRE-FLIGHT (all must PASS before v2 `N`-injection is enabled)
| id | mechanism | proves |
|----|-----------|--------|
| PF1 | Two-sided power/size calibration (real-shape) | a planted edge CAN pass; noise CANNOT; power reported as a **curve** at the campaign's real effect size |
| PF2 | Bridge validation (global + stratified) | JND↔return-correlation self-consistency incl. **non-adjacent / cross-asset** structure and **worst exposure stratum** |
| PF3 | Effective-N estimator recovery + **conservative** selection | the chosen estimator recovers known-K without **under-counting** (loosening) |
| PF4 | `V`-null hardening + **direction check** | firewall-safe fixed `V_null`, verified `≥` status-quo hurdle |
| PF5 | Pre-registration lock (hashed) | estimator/ρ̄/floor/thresholds frozen before the campaign |
| PF6 | Output-side firewall leak-audit gate | sampler/mutation invariant to all return-derived values; shape-probe AUC ≈ chance |

### Tier B — RUNTIME (composes on every candidate)
| id | mechanism | role |
|----|-----------|------|
| RT1 | Bounded effective-N transform (ONC-primary, floored, no cap) | applies §2.1; one integer exits |
| RT2 | DSR soft-in-robustness — **gated** | soft ONLY when OOS is enabled AND multiplicity-aware (FB4) AND canary-proven-vacuous; HARD otherwise |
| RT3 | SPA / Romano-Wolf cross-check — **veto-only, full-family, moment-aware** | N-free second opinion; can only veto/annotate |
| RT4 | PBO / CSCV overfitting veto — **over decorrelated medoids** | N-free overfitting probability; veto-only |

### Tier C — MONITORING
| id | mechanism | signal |
|----|-----------|--------|
| MON1 | Power canary at the **binding** gate | injects known-skill stream; instruments DSR **and the OOS lockbox**; uniform-campaign auto-soften |
| MON2 | Effective-N / `sr0` decomposition telemetry | `N_run/N_campaign/N_eff/ρ̄/sr0` + the `V`-lever and `T`-margin split; campaign-level, ephemeral |
| MON3 | Disagreement + **low-power** + UNEVALUATED banner | flags cross-method disagreement, low-power-agreement, and honest-absence rate |

### Tier D/E — GRACEFUL DEGRADATION & FALLBACK
| id | mechanism | trigger |
|----|-----------|---------|
| FB1 | ONC return-decorrelation clustering (floored at eigenvalue-Meff) | PF2 fails OR MON3 estimator divergence |
| FB2 | Vacuity fallback protocol (anti-back-door), incl. **OOS-off** case | canary fails after honest `N_eff` |
| FB3 | OOS lockbox — **hardened** ultimate arbiter | always terminal |
| FB4 | Campaign-wide OOS multiplicity control | whenever any candidate reaches the lockbox |

---

## 4. How the verdicts combine — conservatively (the crux)

After the gating logic, the composition is:
- **HARD gates that still bind (unchanged):** spec/provider/data-integrity, minimum-activity floor, benchmark-relative not-dominated. These are anti-garbage floors, not multiplicity checks — they stay HARD.
- **DSR is HARD by default.** It is softened **only** when *all three* hold: `oos_enabled=True`, the OOS stage is multiplicity-aware (`FB4` active), and the power canary (`MON1`) has proven the gate vacuous. When `oos_enabled=False` (regime mode force-disables OOS, `state.py:263-264`; robustness without a lockbox, `validated_count(oos_enabled=False)` returns raw satisfiers, `state.py:293-294`), **DSR stays HARD unconditionally** — it is the sole multiplicity gate there, and softening it (as regime mode does today, `gatekeeper.py:83`) is treated as a **pre-existing bug to fix**, not a precedent to mirror.
- **The soft evidence bundle** = {DSR verdict, SPA verdict, PBO probability, power-canary state, ValConf CIs}. **None of these can upgrade** a candidate. They can only **annotate** (a recorded weakness) or **veto** (SPA-fail or PBO>threshold or a confirmed leakage canary). An SPA-**pass** never promotes and never buys OOS budget.
- **Budget routing (OD6) requires the conservative conjunction:** a candidate spends a scarce OOS unit only if it clears the HARD floors **AND** is not SPA-vetoed **AND** is not PBO-vetoed **AND** is DSR-pass-or-provisional. No single in-sample test pass buys the arbiter's attention. This routing affects **only** budget allocation — never mutation seeding, lineage expansion, or the coverage next-cell pick (`PF6` invariance test).
- **The one hard arbiter is the hardened OOS lockbox (`FB3`) under campaign multiplicity control (`FB4`).** Its PASS is a genuine per-trade **risk-adjusted** significance test on a forward hold-out, it renders a terminal verdict only when it has the power to (else UNEVALUATED, no budget burned), and its family-wide false-discovery rate is controlled across the campaign, not just per lineage.

**Why this is still-conservative, not a softer bar:** SPA/PBO are used to *detect a vacuous DSR* and to *veto*, never as an alternative pass path; softening DSR moves the hard decision to a *stronger, multiplicity-aware, power-gated* arbiter, not to a weaker one. The terminal verdict is the conjunction of every un-veto plus an OOS PASS — a strict AND, never an OR.

---

## 5. Sequencing constraint (load-bearing)

Soft-DSR (`RT2`) and canary auto-soften (`MON1`) **may not ship** until `FB3` (power-floored, risk-adjusted lockbox) **and** `FB4` (campaign-wide OOS multiplicity control) are implemented and tested. Softening the one in-sample multiplicity gate before the OOS stage is multiplicity-aware would relocate best-of-many-tries risk onto a stage that does not control it — a net loosening. Until both land, the honest posture is: **DSR stays HARD, vacuity is handled by `FB2` (report + defer), and the reduced power is accepted and logged — never patched by coarsening `N`.**

---

## 6. Traceability

- **RISK 1 (vacuity):** `PF4` (remove the dominant `V` lever, verified stricter) + `MON2` (show that `N` is only a log-lever and most vacuity is `T`-driven) + `RT2`/`MON1` gated softening (a vacuous gate can't zero the engine, but only where a real backstop exists) + `FB2` (pre-registered non-retune response) + `FB3`/`FB4` (a *quantified* arbiter that actually confirms the edges the in-sample gate is too weak to confirm).
- **RISK 2 (bridge):** `PF2` (validate the bridge on global + stratified structure, not just adjacent pairs) + `PF3` (conservative estimator selection against known-K) + `RT1` (measure independence directly via ONC, sidestepping the JND bridge on the critical path) + `RT3`/`RT4` (N-free bootstrap/PBO that never depend on the bridge) + `FB1` (clustering fallback).
- **Both** terminate at the same independent, hardened arbiter (`FB3`+`FB4`), so even total in-sample mis-calibration is not fatal.

---

## 7. Open decisions and residual risks
See the structured `residual_open_decisions` and `residual_risks` fields. The most consequential open item is OD7 (whether the OOS total-return-vs-buy-and-hold floor is intentional product policy or an accidental beta bar), because it changes what "validated" means.


---

## Appendix A — Mechanism details

### PF1 — Two-sided power/size calibration on real-return-shape streams (power curve)
- **Protects against:** both | **When:** pre-flight
- **How it works:** Before v2 is enabled, a Monte-Carlo harness runs on the frozen grid N and realistic T. Streams are block-bootstrapped from REAL visited-cell return series (shape-only, output-scalar-contained) so empirical skew, kurtosis and autocorrelation drive the DSR denominator den=sqrt(1-g3*SR+((g4-1)/4)*SR^2) rather than a Gaussian den~1. Power arm: plant an edge and report a POWER CURVE over SR in [0.5,2.0] plus power at the campaign's pre-registered minimum-detectable-effect, planted at the POST-SELECTION (Harvey-Liu-haircut) Sharpe, not an idealized 1.5. Size arm: pure-noise ensembles under an INDEPENDENT, conservative correlation assumption (swept to the least-correlated / largest-effective-family case), decoupled from the gate's own rho-bar so the size certificate is not self-confirming. Both arms must hold or v2 ships with FB1 or not at all.
- **Honesty note:** Ships only if the gate demonstrably retains power AND controls size at the WORST correlation/exposure case, so the estimator cannot be tuned toothless and a power failure forces the FB2 report path, never a looser N. Real-shape streams stop the calibration from certifying power the fat-tailed real strategies do not have. Firewall: streams are shape-only and only pass/fail scalars exit; no live per-cell Sharpe is stored.
- **How tested:** The harness IS the acceptance test; assert both thresholds on committed seeds across the SR curve and exposure strata; re-run on any grid/estimator/V change; assert the size certificate holds at the least-correlated stress case.

### PF2 — Bridge validation — global, non-adjacent, exposure-stratified
- **Protects against:** risk2-bridge | **When:** pre-flight
- **How it works:** Sample grid-cell pairs NOT only adjacent but NON-adjacent, cross-template and cross-asset, so the dominant common-factor (market-beta ~0.6-0.8 shared by every cell on an asset) is measured, not just the local 1-JND curve. Validate the FULL-MATRIX effective rank (eigenvalue Meff on the whole visited-cell correlation matrix), not just a fitted disagreement<->rho curve. Measure position-disagreement in BOTH union-in-market-normalized and raw all-days variants against full-series return correlation via the existing block_bootstrap machinery. STRATIFY by exposure/trade-frequency; the pass criterion requires the WORST stratum to meet tolerance (a pooled fit is banned because it averages away the low-exposure flat-day-discard bias). Material failure falsifies the cell-count bridge and confirms ONC (RT1/FB1) as the load-bearing path.
- **Honesty note:** Because ONC measures independence directly, PF2 is now a DIAGNOSTIC/cross-check rather than the critical path, so a failed bridge tightens (routes to measured clustering) and can never license a looser N. Worst-stratum + global-structure sampling prevents a pass that hides a large N over-count. Firewall: return correlations encode co-movement, not a performance ranking; only pass/fail exits.
- **How tested:** Pre-registered tolerance band on both the full-matrix effective rank and per-stratum curves; the experiment is its own acceptance test; explicit probe that low-exposure strata are not averaged into a pass.

### PF3 — Known-K effective-N estimator recovery with a strictly conservative selection rule
- **Protects against:** both | **When:** pre-flight
- **How it works:** Generate synthetic ensembles with a KNOWN number K of independent return drivers (latent factors + controlled-correlation copies + banded-decay structure, across exposure levels). Run candidate estimators: ONC / participation-ratio Meff=(sum lambda)^2/sum(lambda^2) on a Marcenko-Pastur-denoised matrix, and eigenvalue Li&Ji/Galwey. BAN the adjacent-rho-bar equicorrelation Kish (wrong correlation quantity for a banded matrix; saturates to ~1/rho -> inert/toothless) and Gao (C-sensitive). PRIMARY selection rule, committed in PF5 BEFORE the run: among estimators whose K-recovery is within the pre-registered tolerance, pick the one that yields the LARGEST N (least reduction, most conservative) - NOT least-bias, which can pick an over-reducer that loosens in the live correlation regime.
- **Honesty note:** The largest-within-tolerance rule guarantees the estimator errs toward MORE trials (a higher bar), never fewer, so the direction of any residual error is stricter. Choosing by a frozen conservative criterion (not a post-hoc menu inspection) closes the forking-paths door. Firewall: synthetic returns; only the estimator identity (a config choice) exits.
- **How tested:** Recovery bias/RMSE vs K per estimator across K and exposure; ship only if the conservative winner is within tolerance AND never under-counts K in merge-prone regimes.

### PF4 — V-null hardening with a mandatory stricter-direction check
- **Protects against:** risk1-vacuity | **When:** pre-flight
- **How it works:** Replace the measured trial-Sharpe variance (loop.py:328 -> deflated_sharpe.py:52) with a FIXED, pre-registered V_null on the per-TRADE clock (matching ValConf), serial-dependence-inflated V_null=(1+2*sum rho_k)/T_eff using the same Politis-White/block-bootstrap horizon the confidence code uses, and set at/above the realized cross-trial dispersion measured ONCE on the frozen grid at pre-flight. MANDATORY direction check: require sr0(N_run, V_null) >= sr0(N_run, V_status_quo_typical) on the frozen grid; if V_null yields a LOWER hurdle, RAISE V_null until it passes. Assert unit consistency (V, sr_hat, sr0 all per-period as the code already is).
- **Honesty note:** This corrects a genuine firewall leak (measured V reads per-cell dispersion and adapts the bar to observed performance) WITHOUT adopting the smaller of two Vs: the direction check forbids shipping any V change whose measured effect is a lower hurdle under a 'hardening' label. A fixed conservative null neither reads nor stores per-cell Sharpe; it uses only return length and a pre-registered serial-dependence horizon.
- **How tested:** Unit test that sr0 matches a hand-computed reference at fixed (N,T); assert V is never sourced from realized trial Sharpes; assert the direction check gate on the frozen grid; re-run PF1 to re-anchor thresholds after the change.

### PF5 — Pre-registration lock (hashed frozen config)
- **Protects against:** both | **When:** pre-flight
- **How it works:** Freeze {estimator identity + conservative selection rule, denoising params, N floor=N_run, eigenvalue-Meff sub-floor, compute-guard, V_null, DSR threshold, power floor + power curve targets + MDE, reference edge, SPA/PBO params, budget-routing rule, OOS power floor} into a hashed, version-controlled config committed before the campaign. Any change requires re-running PF1-PF4/PF6 and a new hash; CI verifies the live gate reads the frozen hash.
- **Honesty note:** This is the anti-back-door control: N/V/threshold cannot be coarsened post-hoc without a visible config-hash change that invalidates the run, technically enforcing 'vacuity is reported, never retuned'. Firewall: the config holds no performance data.
- **How tested:** CI check that the running gate's config hash matches the frozen artifact; a mismatch fails the run loudly and is logged in MON2.

### PF6 — Output-side firewall leak-audit pass-gate
- **Protects against:** both | **When:** pre-flight
- **How it works:** Re-anchors the firewall guarantee on the OUTPUT side, because performance is already one join away in the store (coverage.exemplar_hash -> candidate.run_artifact_id/sharpe_annual) and the OD3 'shape-only input is profitability-blind' premise is false (sign/rank/z-scored returns carry directional/timing edge). Two hard checks: (1) a leak-audit that trains a cheap probe to predict candidate Sharpe rank from any values the SPA/PBO/ONC/rho-bar machinery emits toward selection, requiring probe AUC within a pre-registered band of chance; (2) an invariance test that the sampler's next-cell pick and mutation/lineage seeding are byte-identical when all SPA/PBO/ONC outputs are shuffled. The return matrix is recomputed on-demand in a run-scoped ephemeral scope, never persisted to any store the strategist reads; only scalars/verdicts (integer N, a PASS/FAIL/veto flag, one campaign-level rho-bar) may exit.
- **Honesty note:** Moves the firewall guarantee from an unprovable input-cleanliness claim to a provable output-containment invariant: only performance-free scalars steer selection, and the leak-audit + invariance test falsify any back-door. Language is downgraded everywhere from 'profitability-blind' to 'performance-attenuated, contained at the output'.
- **How tested:** The two checks ARE the gate; both must PASS in CI before v2 enables, and re-run on any change to the SPA/PBO/ONC surface; schema test that no return-derived per-cell value lands in a persisted column.

### RT1 — Bounded effective-N transform (ONC-primary, dual-floored, no upper cap)
- **Protects against:** both | **When:** runtime
- **How it works:** At the injection seam, N_eff = ONC/participation-ratio effective count on the Marcenko-Pastur-denoised correlation matrix of the visited-cell family (PF3-selected estimator), floored below at an eigenvalue-Meff lower bound to block ONC under-segmentation. Then N_used = max(N_eff, N_run). The standalone upper cap is REMOVED (a second unjustified loosening lever worth ~15% numerically); only a mechanistically-derived compute-guard well above any plausible N_eff remains, never below the eigenvalue count, logged in MON2 when it binds. Exactly one integer N_used exits into GateContext.n_trials_global.
- **Honesty note:** The N_run floor makes enabling v2 monotone-stricter than today AND immune to estimator collapse; the eigenvalue sub-floor blocks the too-lenient under-count direction; removing the cap removes a lever that could be set to whatever lets candidates pass. Honesty is stated relative to N_campaign (the transform is a MEASURED downward adjustment from the raw family size, conservative by construction via upper-bound correlation), not relative to today's near-inert gate. Firewall: one integer exits; N_eff derives from correlation structure, not Sharpe.
- **How tested:** Property test sr0(N_used) >= sr0(N_run) for all inputs; integration test that a collapsed N_eff reverts to N_run; test that N_eff never falls below the eigenvalue-Meff sub-floor; test that the compute-guard never produces N below the eigenvalue count and is logged when binding.

### RT2 — DSR soft-in-robustness — gated on a multiplicity-aware, enabled OOS stage
- **Protects against:** risk1-vacuity | **When:** runtime
- **How it works:** DSR is HARD by default. It softens to SOFT ONLY when ALL hold: oos_enabled=True AND the OOS stage is multiplicity-aware (FB4 active) AND the power canary (MON1) has proven the gate vacuous. When oos_enabled=False (regime mode force-disables OOS at state.py:263-264; robustness without a lockbox counts raw satisfiers at state.py:293-294), DSR stays HARD unconditionally as the sole multiplicity gate, and RT2/MON1 auto-soften are no-ops there. The current regime-mode 'DSR soft + OOS off' (gatekeeper.py:83) is treated as a pre-existing BUG to fix. Softening only ever moves the hard decision to the stronger arbiter; it never changes the DSR verdict itself.
- **Honesty note:** Softening does not loosen the significance verdict; it relocates the hard decision to a STRONGER, power-gated, multiplicity-aware OOS arbiter, and ONLY where that arbiter actually exists. Forbidding softening when OOS is off closes the pure-loosening hole where a candidate failing the sole multiplicity test would still count. Firewall: DSR still consumes only the one integer.
- **How tested:** Integration test that a forced DSR HARD-fail today yields zero candidates; that under RT2-with-OOS-on the same input yields a candidate carrying a recorded DSR weakness that reaches the lockbox; that with oos_enabled=False DSR remains HARD and the auto-soften is a no-op; regression test that regime mode no longer softens DSR while OOS is disabled.

### RT3 — Hansen SPA / Romano-Wolf cross-check — full-family, moment-aware, veto-only
- **Protects against:** both | **When:** runtime
- **How it works:** At final evaluation, bootstrap the JOINT return matrix of the FULL visited-cell family (or ONC cluster medoids that span the correlation structure), NEVER a uniform random subsample (which understates the family size and makes SPA too lenient); if compute forces subsampling, inflate the null max-statistic to the true family cardinality. Use a moment-aware studentized Sharpe statistic (Ledoit-Wolf robust / delta-method influence function) with a data-driven Politis-White block length, so SPA sits on the SAME higher-moment and serial-dependence scale as the DSR den term - otherwise their MON3 agreement is uninterpretable. For a single reported winner only the max-statistic (first Romano-Wolf stepdown step, = White RC / SPA) is consumed - not a rejection-set/FDR reading. SPA is VETO-ONLY: an SPA-fail can block; an SPA-pass NEVER promotes or grants OOS budget.
- **Honesty note:** Full-family (not subsample) bootstrapping keeps SPA conservative rather than lenient; moment-aware studentization keeps it on the DSR scale; veto-only status means it can only tighten, never open an alternative pass path. A SPA-pass on a DSR-fail only ANNOTATES suspected vacuity for the report/critic; the terminal verdict still flows through the lockbox. Firewall: returns cross only at final eval as a joint bootstrap input; nothing per-cell is stored or steers selection (PF6).
- **How tested:** On synthetic joint nulls assert empirical FWER control; assert SPA rejection rate does NOT increase as any forced subsample shrinks; assert SPA agrees with DSR in the non-vacuous regime and diverges (SPA-pass, DSR-fail) only in a constructed vacuous regime; assert an SPA-pass never grants budget.

### RT4 — PBO / CSCV overfitting veto over decorrelated medoids
- **Protects against:** both | **When:** runtime
- **How it works:** Combinatorially Symmetric Cross-Validation PBO is a POPULATION statistic requiring the N-strategy x time matrix; it is computed over a DECORRELATED representative set (ONC cluster medoids), not 'the candidate's own matrix' (undefined for one strategy) and not the raw near-degenerate 0.9-correlated set (which ties OOS ranks and biases PBO toward 0.5). It emits a probability (logit of the OOS rank of the IS-best), so it cannot go vacuous as trials grow. PBO > pre-registered threshold (~0.5) is a VETO regardless of DSR.
- **Honesty note:** PBO can only tighten (veto), never manufacture a pass; being orthogonal to N it cross-validates the DSR verdict without depending on the bridge. Decorrelated-medoid input prevents correlation degeneracy from spuriously tripping or suppressing the veto. Firewall: computed at evaluation on medoid return splits; stores no per-cell performance for selection.
- **How tested:** Recover PBO~1 on a known-overfit ensemble and PBO~0 on a known-genuine edge, AND calibrate on correlated-but-genuine ensembles to confirm the veto is not tripped by correlation degeneracy; assert the veto fires only above the pre-registered threshold.

### MON1 — Power canary at the binding gate (DSR and the OOS lockbox)
- **Protects against:** risk1-vacuity | **When:** monitoring
- **How it works:** At each gate evaluation, inject a synthetic known-skill stream (real-return-shape, drawn DIFFERENTLY from PF1 to break common-mode) at realistic T/N and report P(pass). Critically it instruments BOTH the DSR gate AND the OOS lockbox test at realistic forward-hold-out trade counts, since after RT2 the lockbox is the binding gate. If power at the pre-registered reference edge drops below the floor, emit a loud 'gate saturated' signal and (only where RT2's gating conditions hold) auto-fall DSR to SOFT. Any auto-soften is applied UNIFORMLY to the whole campaign (earlier candidates re-adjudicated under the same regime) and logged in MON2/PF5 - never a timeline forking-path where identical evidence is judged differently by arrival time.
- **Honesty note:** Vacuity becomes an observable, logged, self-correcting condition instead of a mysterious empty result, removing the incentive to hand-coarsen N. Instrumenting the ACTUAL binding gate (not just the softened DSR) means the canary watches where power is really lost. Uniform-campaign application prevents a biased surviving set. Firewall: synthetic real-shape streams; only power scalars and a soften flag exit.
- **How tested:** Unit test that the canary reports low power exactly when the hurdle exceeds the reference edge's deflated Sharpe, for BOTH DSR and the lockbox test; assert the auto-soft transition fires at the frozen floor, only under RT2's gating conditions, and re-adjudicates earlier candidates.

### MON2 — Effective-N / sr0-decomposition telemetry (campaign-level, ephemeral)
- **Protects against:** both | **When:** monitoring
- **How it works:** Surface, as run-report-only CAMPAIGN-LEVEL aggregate scalars (never per-cell or per-region maps, never persisted to research_coverage/research_candidates): N_run, N_campaign, N_eff, one rho-bar, sr0, the compute-guard-binding flag, and the decomposition hurdle = sr0(N,V) + fixed finite-sample T-margin (~1.645/sqrt(T-1)). Because sr0 grows only as the Euler-corrected E[max] (N is a weak log-lever: 1000->10000 raises the bar ~15%) while V and T dominate, the decomposition lets an operator attribute vacuity to T (unfixable by touching N) vs V vs N.
- **Honesty note:** Pure observability that explicitly discourages 'fix vacuity by shrinking N' when the cause is sample length T or the V null. Campaign-level-only, ephemeral, never-per-cell prevents the telemetry itself from becoming a performance-adjacent artifact an operator or the LLM strategist could read to steer toward 'more-independent regions'. Firewall: aggregate scalars only.
- **How tested:** Snapshot test that the reported decomposition reconstructs the gate's actual sr0 and threshold on the Euler-corrected formula (not the sqrt(2 ln N) shorthand); schema test that no MON2 quantity lands in a persisted per-cell column.

### MON3 — Disagreement + low-power-agreement + OOS-UNEVALUATED banner
- **Protects against:** both | **When:** monitoring
- **How it works:** In the final verdict/report, flag (a) disagreement among DSR/SPA/PBO; (b) a NEW low-power-agreement signal: whenever power at the reference edge (from MON1, for the binding gate) is below floor, tag any FAIL - and especially a DSR-fail AND OOS-fail agreement - as a LOW-CONFIDENCE rejection regardless of cross-method agreement (agreement among underpowered tests is not evidence of a true negative); (c) the rate of OOS UNEVALUATED and DSR provisional flags. Wire a 'gate saturation / low statistical power' banner off these, displaying MON2's sr0=f(N,V)+T-margin decomposition so vacuity is attributed to its real cause.
- **Honesty note:** It makes honest-absence and low-power signals LOUD rather than hidden. The banner is STRICTLY diagnostic: it never grants preferential OOS budget or a lighter bar, and it carries a standing note that the sanctioned response is FB2 (report + defer to OOS), never touching N - defusing the psychological on-ramp where a DSR-fail-that-SPA-passed reads as a false negative to be rescued. Firewall: status flags only.
- **How tested:** Assert the banner fires on a constructed vacuous/thin campaign and stays quiet on a healthy one; assert the low-power-agreement tag fires on a correlated-underpowered DSR-fail+OOS-fail pair even though the two tests 'agree'; assert the banner never alters budget or bar.

### FB1 — ONC return-decorrelation clustering (floored at eigenvalue-Meff)
- **Protects against:** risk2-bridge | **When:** fallback
- **How it works:** The DSR-native N (Lopez de Prado): build the trial return-correlation matrix, angular distance d=sqrt(0.5*(1-rho)), Marcenko-Pastur denoise (#trials can exceed T), run ONC (base K-means over K with high n_init scored by the silhouette t-stat q=E[S]/sqrt(Var[S]), then recursive re-clustering of below-average clusters); N := final cluster count, floored below at max(ONC count, eigenvalue-Meff participation-ratio lower bound) to block K-means UNDER-segmentation (merging distinct-but-correlated strategies -> too-small N -> lenient), and clamped per RT1. This IS the engine of RT1's primary path; as a distinct fallback it triggers when PF2 fails or MON3 shows estimator divergence. Same gate math, only the N source.
- **Honesty note:** It sidesteps the JND bridge with a measured effective count and is floored so it can never under-count below an independent effective-rank estimate (guarding the too-lenient merge direction the draft left unguarded) nor below N_run (never toothless). Firewall: returns cross via an output-contained gate-time computation; only the integer cluster count exits; nothing steers which cells are visited (PF6).
- **How tested:** PF3's known-K harness doubles as the ONC acceptance test including merge-prone regimes (ONC must not under-recover K); reproducibility test on fixed seed/n_init; PF6 leak-audit that only the integer exits.

### FB2 — Vacuity fallback protocol (anti-back-door), covering the OOS-off case
- **Protects against:** risk1-vacuity | **When:** fallback
- **How it works:** The pre-registered response when the gate is vacuous even after honest N_eff (MON1 below floor): (1) surface the 'low statistical power / gate saturated' banner; (2) where RT2's gating conditions hold, DSR goes SOFT / advisory and defers to the hardened, multiplicity-aware lockbox; (3) where oos_enabled=False, DSR STAYS HARD (no backstop exists to defer to) and the reduced power is accepted and reported, NOT patched; (4) NEVER coarsen N post-hoc. Marginal edges (Sharpe ~1, heavily haircut per Harvey-Liu) are by design deferred to OOS or left unconfirmed, never confirmed by loosening N.
- **Honesty note:** This is the explicit, frozen alternative to the back door: the honest scope of the in-sample gate (confirm strong edges; defer or decline marginal ones) is documented and followed. Covering the OOS-off case closes the hole where 'defer to OOS' is impossible - there the honest answer is 'we cannot confirm', not a looser N. Firewall: unchanged; nothing new crosses.
- **How tested:** Scenario test that a vacuous campaign produces the banner + (OOS-on) soft DSR routed to the lockbox / (OOS-off) HARD DSR + reported low power, and leaves N and the config hash untouched in both.

### FB3 — Hardened OOS lockbox — power-gated, risk-adjusted ultimate arbiter
- **Protects against:** both | **When:** fallback
- **How it works:** The terminal hard gate (state.py:289-296), hardened so it is a QUANTIFIED arbiter: (1) before any terminal FAIL, check the df-aware per-trade test's power at the pre-registered reference edge given the actual hold-out trade count; if power is below the floor (e.g. 80%), return UNEVALUATED (retryable), NOT a terminal FAIL, and spend NO write-once budget - an underpowered result is 'we cannot judge' (loop.py:560-563 today wrongly routes underpowered-but-ran per-trade tests to terminal FAIL). (2) The PASS quantity is RISK-ADJUSTED (excess Sharpe / information ratio / alpha vs buy-and-hold), matching the quantity DSR/ValConf certified, NOT total_return-minus-buy_hold_return (loop.py:562), which is a beta bar masquerading as a skill bar. (3) Keeps the separate DB, PASS/FAIL/UNEVALUATED-only contract (service.py:2-6), write-once terminal, forward hold-out, infra-failure->UNEVALUATED.
- **Honesty note:** Making an underpowered result UNEVALUATED (not FAIL) and not burning budget stops the arbiter from emitting confident terminal false-negatives on exactly the low-frequency edges the architecture defers to it - which is what lets us honestly claim 'the in-sample gate need not be perfect'. Risk-adjusting the PASS quantity stops a bull-market beta bar from silently rejecting genuine market-neutral skill. Firewall: PASS/FAIL/UNEVALUATED only; no metric steers selection.
- **How tested:** Integration test that a genuinely-skilled low-frequency edge with too-few hold-out trades yields UNEVALUATED (budget intact), not FAIL; that PASS keys off the risk-adjusted statistic not raw total-return dominance; that validated_count counts only on PASS; that a terminal result cannot be overwritten.

### FB4 — Campaign-wide OOS multiplicity control
- **Protects against:** both | **When:** fallback
- **How it works:** Gives the OOS stage its own multiplicity control so softening DSR does not relocate best-of-many-tries risk onto a multiplicity-blind stage. Apply a campaign-wide Romano-Wolf / Benjamini-Hochberg correction (or an alpha that shrinks as cumulative OOS terminal evals grow) ACROSS all OOS-tested candidates, and cap total terminal OOS evals per CAMPAIGN, not just the per-lineage budget of 3 (service.py:33). Treat the single forward hold-out (reused for every candidate, loop.py:648-655) as a DEPLETABLE global pool: each terminal eval spends from it; when exhausted, new candidates are UNEVALUATED, never freely re-tested against an already data-mined window. Soft-DSR (RT2) may not ship until FB4 is active.
- **Honesty note:** Without this, per-candidate significance at a fixed threshold throttled only by a per-lineage budget lets expected false OOS passes grow linearly with lineages - a false-discovery factory once DSR is softened. Campaign-wide correction + a global depletable hold-out budget make the terminal arbiter's PASS a genuine best-of-many-aware verdict, not a data-mined artifact. Firewall: operates on PASS/FAIL verdicts and eval counts only; no metric steers selection.
- **How tested:** Simulation that campaign-wide false OOS PASS rate stays at the target as lineage count scales; test that the global hold-out budget depletes and subsequent candidates go UNEVALUATED not re-tested; test that RT2 cannot enter SOFT while FB4 is inactive.

---

## Appendix B — Open decisions (owner's calls)

### OD1 — Should DSR be always-SOFT in robustness mode, HARD-by-default with auto-soft, or gated on the OOS backstop existing?
- Always SOFT (mirror regime mode)
- HARD-by-default, auto-SOFT the moment the power canary fires
- HARD by default; auto-SOFT ONLY when oos_enabled AND FB4-multiplicity-aware AND canary-proven-vacuous; HARD unconditionally when OOS is off
- **Recommendation:** Option 3.
- **Why:** Always-SOFT dumps every candidate onto the scarce OOS budget and, worse, softens even where OOS is off (no backstop) - a pure loosening. Bare HARD-by-default-plus-canary (draft's Option 2) still softens into a multiplicity-blind lockbox. Option 3 retains the cheap in-sample multiplicity filter when the gate is provably valid, fails safe to a STRONGER arbiter only where that arbiter genuinely controls best-of-many risk, and never softens the sole gate when OOS is disabled. The toothless direction is separately caught by PF1's size floor + RT4's PBO veto.

### OD2 — Which effective-N estimator is PRIMARY: cell-count + bounded reduction, or ONC/eigenvalue return-clustering?
- Cell-count + bounded reduction primary; ONC as fallback
- ONC/participation-ratio Meff primary (measures independence directly); cell-count as family-definition + lower-bound sanity
- Run both, take the larger N
- **Recommendation:** Option 2.
- **Why:** The cell-count-in-Kish path is statistically invalid for a banded matrix (wrong correlation quantity, saturates to ~1/rho, would be inert). ONC/eigenvalue measures the effective independent count directly from returns, sidestepping the JND bridge on the critical path. The firewall is preserved OUTPUT-side (only the integer exits; PF6). Cell-count survives as the multiplicity-family definition and a loose lower-bound sanity input, not as the number fed to sr0.

### OD3 — May per-cell RETURN series cross the firewall for SPA/PBO/ONC, and under what discipline?
- Strict input-side one-integer only (SPA/PBO/ONC impossible)
- Output-side containment: return matrix used in an ephemeral gate-time computation, only scalars/verdicts exit, PF6 leak-audit enforces it
- Allow full return series freely
- **Recommendation:** Option 2.
- **Why:** Strict input-side one-integer is already violated today (measured V crosses) and forecloses the statistically necessary ONC estimator and the N-free SPA/PBO cross-checks. Performance is already one join away, so the honest guarantee cannot rest on input cleanliness; it must rest on output containment (only performance-free scalars steer selection) proven by PF6's probe-AUC + shuffle-invariance tests. Drop the false 'shape-only is profitability-blind' claim.

### OD4 — Where to set the power-canary floor, the reference edge, and the minimum T for a HARD DSR?
- Single point: deflated Sharpe 1.5 on T>=~10y, power floor 50%
- Power CURVE over SR in [0.5,2.0], read at the campaign's pre-registered MDE and the post-selection-shrunk edge, floor 50% at T>=~10y, all frozen in PF5
- Reference 2.0, floor 80%
- **Recommendation:** Option 2.
- **Why:** A single high point (1.5, Gaussian) overstates real power (fat-tailed den>1 inflates the hurdle) and tests an effect size above many real post-cost edges (~0.5-1.0 after selection shrinkage). Reporting a curve at the real MDE and the shrunk edge shows the operator the true confirm-rate on the strategies the funnel actually surfaces. Freeze all of it in PF5.

### OD5 — Switch V from measured trial-Sharpe variance to a fixed null now, and to what?
- Keep measured per-run variance (status-quo firewall leak, adaptive)
- Switch to V=1/T (firewall-safe but sign-indeterminate / typically looser)
- Switch to a FIXED, pre-registered conservative V_null on the per-trade + serial-dependence clock, gated by a stricter-direction check (PF4)
- **Recommendation:** Option 3.
- **Why:** Measured variance reads per-cell performance (firewall violation, silent vacuity lever). 1/T is firewall-safe but not reliably conservative and wrong under serial dependence + heterogeneous exposure. A fixed conservative V_null on the per-trade clock, verified >= the status-quo hurdle on the frozen grid, is both firewall-safe AND provably stricter - the only option consistent with Invariant 1. Do it before shipping v2 and re-anchor PF1.

### OD6 — With DSR softened, how is the scarce OOS budget protected and allocated without becoming a pass-EITHER path?
- Raise the per-lineage budget
- Keep scarce budget; route only candidates that clear HARD floors AND are un-vetoed by every cross-check (conservative AND); feedback-isolated to budget only
- Tier the budget by evidence strength
- **Recommendation:** Option 2.
- **Why:** Raising the budget erodes the anti-farming scarcity. Tiering adds a gameable knob. The conservative-AND pre-filter (HARD floors AND not-SPA-vetoed AND not-PBO-vetoed AND DSR-pass-or-provisional) ensures no single in-sample pass buys the arbiter's attention - closing the SPA-pass-promotes hole - while keeping the strongest candidates reaching the true arbiter. The routing must affect only budget, never sampling/mutation (PF6 invariance).

### OD7 — Is the OOS PASS's total-return-beats-buy-and-hold requirement (loop.py:562, D5) intentional product policy or an accidental beta bar?
- Keep it folded into the significance PASS (status quo)
- Make the significance PASS risk-adjusted (excess Sharpe/IR/alpha); if a total-return floor is desired, add it as a SEPARATE, explicitly-labelled HARD floor with its own rationale
- Drop any total-return requirement entirely
- **Recommendation:** Option 2.
- **Why:** Folding total-return dominance into the significance PASS silently rejects genuine market-neutral / low-beta skill in bull markets - a beta bar masquerading as a skill bar, and it makes the arbiter certify a different quantity than every upstream gate. Separating the two lets 'skill' be judged risk-adjusted (matching DSR/ValConf) while preserving an explicit, defensible product floor if the business wants one. This changes what 'validated' means, so it needs an owner's call.

---

## Appendix C — Residual risks (accepted, not eliminated)

- Non-stationarity of the correlation structure: PF2/PF3/PF4 validate the estimator and V_null on the frozen grid + a pre-flight correlation sample; a grid-v3, a new template, or a new asset can shift the true rho distribution and silently invalidate the frozen estimator or push realized dispersion above the pre-registered conservative V_null. Mitigation is to re-run PF2/PF3/PF4 on any grid change, but between re-validations N_eff and the V direction-check can drift undetected.
- Residual over/under-count on strongly-correlated blocks: even ONC/eigenvalue-Meff never perfectly collapses a 0.9-correlated block to its true independent count, and K-means-style clustering can still merge or split it at the margin; the eigenvalue sub-floor bounds the under-count (lenient) direction but a few-x residual over-count (conservative) remains, so marginal edges stay deferred to OOS by design - honest, but the engine confirms few marginal strategies.
- Output-side firewall is process + audit, not cryptographic: the return matrix is reachable via a store join, so the guarantee rests on PF6's leak-audit + shuffle-invariance passing and on nobody persisting a return-derived per-cell value; a subtle future cache keyed by cell_id could reintroduce a leak that only the audit would catch.
- Hardened lockbox + campaign multiplicity control (FB3+FB4) TIGHTEN the terminal gate: power-flooring underpowered results to UNEVALUATED and adding a global depletable hold-out budget means MORE genuine edges can end the campaign UNEVALUATED (honest absence) rather than confirmed - a Type-II-flavoured cost the architecture accepts rather than papers over, and an auto-approver with no human-in-the-loop cannot rescue them.
- Soft-DSR depends on a substantial new build (FB4 campaign-wide OOS multiplicity + FB3 power-flooring + risk-adjusted PASS); if that build slips, DSR must stay HARD and the vacuity pressure returns. The honest posture (FB2: report + defer, never coarsen N) then yields a low-power in-sample gate that confirms few strong edges - reported, not retuned.
- Synthetic and block-bootstrapped-historical calibration cannot guarantee FORWARD power: real markets are non-stationary and their skew/kurtosis/autocorrelation (which inflate the DSR den and the true hurdle) may exceed any sampled past; the size/power guarantees hold only to the extent the calibration draws are representative of the live regime.
- SPA/PBO carry their own estimator assumptions (block length, CSCV split count, denoising, medoid selection); mis-set, a cross-check could itself be mis-calibrated - a wrong block length can make SPA over- or under-reject, and correlation degeneracy can bias PBO toward 0.5 despite the medoid mitigation.
- The fundamental low-power fact remains: in-sample multiple-testing correction on Sharpe~1 edges at realistic T is genuinely low-power, and the forward hold-out is the shortest, most-recent slice. A real-but-marginal edge with an exhausted or unlucky OOS shot can still go unconfirmed; the architecture's honest answer is to say so, not to lower a bar.

## Appendix D — Unresolved / reinterpreted critiques

- Reinterpretation, not rejection: the system-context invariant 'exactly ONE integer crosses the seam (input-side)' cannot coexist with a statistically valid effective-N estimator, because ONC/eigenvalue Meff provably needs the sampled correlation spectrum at gate-compute time. We re-anchor the invariant OUTPUT-side (only a scalar N exits toward selection, enforced by PF6). A reviewer insisting on strict input-side single-integer must accept the statistically-invalid cell-count-in-Kish path - there is no option that is both strict-input-side and valid.
- Deliberate departure from textbook DSR (lens-1 F1's premise): standard Bailey/Lopez-de-Prado DSR uses realized cross-trial dispersion as V; in our setting that reads per-cell performance and is a firewall violation. We consciously trade a small amount of theoretical fidelity for firewall integrity by using a fixed conservative V_null that PF4 empirically verifies is >= the realized dispersion the textbook would use - so we remain stricter-than-textbook in effect, not looser. This is a conscious tradeoff, not an oversight.
- Lens-4's 'the cap barely matters (~15%)' and lens-1's 'the cap is a dangerous loosening lever' are in surface tension but both conclude 'remove the standalone cap'; we adopt that conclusion. We note the numerical-weakness point (N is only a log-lever) as REINFORCING that vacuity is dominated by V and T, not N - which is why the honest response to vacuity is FB2/defer, not N-coarsening.
- Out of scope for this design pass (flagged, not solved): OD7 - whether the OOS total-return-vs-buy-and-hold floor is intentional product policy or an accidental beta bar - is a product-owner decision, not a purely statistical one; we implement the risk-adjusted significance PASS and leave the optional explicit total-return floor to the owner rather than unilaterally deleting a possibly-intended D5 behaviour.
