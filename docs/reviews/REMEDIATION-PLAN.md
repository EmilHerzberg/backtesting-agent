# Remediation Plan — backtesting-agent quant review

**Date:** 2026-07-05 · **Owner:** Emil · **Basis:** [QUANT-REVIEW-2026-07-03.md](./QUANT-REVIEW-2026-07-03.md) (118 confirmed findings)
**Goal:** bring the system to a quality bar defensible for an open-source release to the quant community, in a controlled and *provable* way.

This plan is one of a triad:
- **QUANT-REVIEW-2026-07-03.md** — the evidence (what is wrong, where, why, and the suggested fix). Immutable record.
- **REMEDIATION-PLAN.md** (this file) — *how* we fix it: principles, phases, decisions, definition-of-done.
- **REMEDIATION-TRACKER.md** — *state*: every finding ID → cluster → status → the test that proves it closed. The single source of "are we done?".

---

## 1. Principles

1. **Fix by root-cause cluster, sequenced by result-corruption — not by severity number.** The review already groups findings into clusters that share one root cause and one code location (DSR wiring, warm-up, annualization, OOS discipline, adjustment layer, dead-code, LLM honesty). We fix a cluster once, coherently, instead of touching the same file for five separate IDs. Ordering follows *impact on the result itself* (accept/reject correctness) before *presentation* before *hygiene*.
2. **Nothing is "done" without a test that fails now and passes after.** Every in-scope finding is discharged by a regression test tagged with its ID. For "no test exists" findings the test *is* the deliverable. This is the mechanism that lets us prove progress rather than assert it.
3. **Quarantine dead code; don't delete in place (yet).** Advertised-but-dead machinery is first *disabled at runtime* (so it stops falsely claiming a guarantee), moved to a clearly-tagged parking area, and kept until the improved iteration is finished — then rewired if it earns its place, or deleted. The end state ships **zero** dead code and **zero** false guarantees.
4. **Test in the artifact we ship.** Per the testing-concept review, release gates run the suite inside the built image, not just the working tree (two bugs already shipped from git-ignored/uncopied files).
5. **Cheap by default.** The whole automated suite runs at €0 — LLM providers mocked, market data a frozen snapshot. Real-provider runs are a separate opt-in, budgeted tier. (Respects the spend-watch rule.)

## 2. Decision register

### Resolved (2026-07-05)
| # | Decision | Choice |
|---|----------|--------|
| D1 | Tracking substrate | **Repo matrix is the working source of truth**, mirrored to a Jira epic *if the token is valid*; if not, the Jira tree is staged locally and pushed when the token returns. |
| D2 | Sequencing | **Harness-first (Phase 0)** before fixing findings. |
| D3 | Release bar | **Critical + High + Medium (95 findings) fixed or honestly disabled**; the 23 Low go to a tracked backlog. |
| D4 | Dead-code policy | **Quarantine → rewire-if-useful → delete.** Disable at runtime immediately; park tagged; remove before release. Only code directly useful to the improved iteration survives. |

### Open — must be decided *before* the phase that needs them (not now)
| # | Decision | Needed for | Recommendation |
|---|----------|-----------|----------------|
| D5 | The real **OOS / hold-out pass bar** — exact rule (min trades + per-trade t-stat threshold + benchmark-excess condition?) | Phase 2 (H3, H18) | Reuse the hold-out bar: min-trades + one-sided t ≥ 1.65 **and** positive excess over buy-and-hold; else `UNEVALUATED`. |
| D6 | **Multiplicity control** on the shared hold-out — Šidák/Bonferroni-corrected t\* vs one-shot-per-run vs a persisted evaluation budget | Phase 2 (H18) | Evaluate the hold-out once per run on the single top-ranked-on-train candidate (simplest honest option). |
| D7 | **Annualization factors** for non-daily/non-equity — crypto 365 vs 252, RTH-hourly (~1638) | Phase 1 (C2) | Derive from `BarInterval` + an asset-class flag; 365 for crypto daily, 52 weekly, RTH-hours for hourly. |
| D8 | **Default cost model** — what commission/spread/slippage ships as default, and is it a `StartRunRequest` knob | Phase 4 (H29) | Match the CLI (commission + spread + slippage ≈ 14.5 bps/side) and expose as a request field with that default. |
| D9 | **Default `enable_oos`** — flip to on, or keep off but cap the tier and mark in-sample-only | Phase 2 (H5) | Default on (the lockbox is a free local backtest); cap tier at "moderate" whenever off. |
| D10 | Per-item **wire-vs-delete** for each quarantined subsystem (leakage canary, lag gate, `costs/` package, budget caps, determinism fingerprints, `gates.default.yaml`, generator) | Phases 2/4/5 | Decide at the cluster; default under D4 is disable-then-delete unless it serves the improved iteration. |

## 3. Phase 0 — Foundation (must land first)

Phase 0 builds the machine that makes every later fix provable. It also discharges several findings directly.

- **0.1 Verification harness (€0, deterministic).** An in-process research-loop runner + a `MockProvider` (`IAIProvider` that records calls and returns canned JSON the parser accepts, with a cost meter) + a frozen market-data snapshot fixture + seeded-user/provider factories. Enables API/loop/gate testing without real keys or network. *(This is the harness the testing-concept review found missing.)*
- **0.2 Minimal determinism.** Wire a seed through the backtest/optimizer path far enough that a fixed-seed rule-based run is bit-reproducible, and commit a golden snapshot, so regression tests are stable. (Full determinism cluster M12/M57–M59/N28 remains Phase 5; this is only the slice the harness needs.)
- **0.3 CI.** A pipeline that runs `pytest` **inside the built backend image** + `lint-imports` + `next build`, with the ship-vs-tree and image-asset guards from the testing concept. Blocks merge on red.
- **0.4 Tracking substrate.** This plan + the tracker committed; Jira epic created or staged (D1).
- **0.5 Test-tagging convention.** Every fix's test is tagged with the finding ID (marker `@pytest.mark.finding("H1")` or an ID in the test name) so the coverage matrix is *generated*, not hand-maintained.

**Phase 0 exit:** a red/green harness exists, CI runs it, one worked example (pick H7 `finalize_trades` — small and mechanical) goes red→green through the whole pipeline to prove the loop.

## 4. Phases 1–5 (from the review roadmap, annotated)

Sequencing follows the review's own roadmap (§ "Recommended fix roadmap"). Each workstream in the tracker is annotated with a **bucket** — `mechanical` (reference formula, no decision), `decision` (wire-vs-delete / product toggle), or `spec` (needs a short written technical spec before coding).

- **Phase 1 — Statistical wiring that corrupts accept/reject.** DSR gate end-to-end (H1/H2/M24/M25/N6); warm-up buffers (C1/M26/M3/H6); interval-aware annualization (C2/M5/M6/L17); metric formulas (H9/H10/M2/M4); real goal-criteria completion (C3/H30/M50/L22). *Spec items: goal-criteria grammar; the annualization-factor table (D7).*
- **Phase 2 — OOS & validation discipline.** OOS/hold-out contract (H3/H14/H15/H16/H17/H18); default-OOS decision (H5); wire-or-demote inert gates (H4/H24/M19/M20/M21/M22/M23). *Spec items: OOS pass bar (D5) + multiplicity (D6).*
- **Phase 3 — Data integrity.** Market-data adjustment layer (H21/H22/H23/M32–M36); persistence integrity (H27/M47/M53/M54). *Spec item: adjustment-layer design (raw+events vs immutable snapshots).*
- **Phase 4 — Cost realism & LLM honesty.** Unified cost model (H29/M55/L18–L21); LLM degradation & identity honesty (H25/H26/H28/H31/M37–M45/M56/M60). *Spec item: cost defaults (D8).*
- **Phase 5 — Config/dead-code hygiene & disclosure.** Delete-or-wire the quarantined subsystems (H19/H20/M8–M12/M17/M57–M59 + parked lows); missing test coverage + README data-limitations disclosure (M18/M30/L6/N26/N27).

## 5. Definition of Done

**Per finding:** (a) a regression test tagged with the ID that failed before and passes after; (b) the fix merged via a cluster PR; (c) tracker row → `DONE` with the test path; (d) for `decision`/`spec` findings, the decision recorded here and the spec linked.

**Per release (the bar):** all 3 Critical + 32 High + 60 Medium are `DONE` **or** `QUARANTINED` (feature disabled + marked, tracked for deletion); CI green in-container; the coverage matrix shows a tagged test for every in-scope ID; and — the objective proof — a **re-run of `/quant-correctness-review` returns those findings empty with no new criticals/highs**. The 23 Low + 29 N-notes are a documented, tracked backlog, not release blockers.

## 6. Cadence & mechanics

- **Branching:** one branch/PR per cluster (this is a standalone git repo with its own remote). Small, reviewable, test-first.
- **Order:** strictly Phase 0 → 1 → 2 → 3 → 4 → 5. Within a phase, clusters can run in parallel; across phases, do not start N+1 until N's result-integrity items are green (later phases depend on earlier fixes — e.g. annualization must precede trusting the benchmark gate).
- **Proof of progress:** the tracker's status counts + the generated coverage matrix answer "how far are we" at any moment; the periodic re-audit answers "is it actually fixed."
