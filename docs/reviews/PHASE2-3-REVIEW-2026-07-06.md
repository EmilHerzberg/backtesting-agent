# Phase 2 + Phase 3 merge-readiness review — 2026-07-06

Adversarial multi-agent review (10 dimension reviewers → 2-lens verification of every finding).
**29 raw → 20 confirmed, 9 refuted. Zero critical, zero high** — the statistical/data core of Phases 2–3
holds. Confirmed findings are all **medium/low**, in four themes.

## Theme 1 — 3A fixes live in components the live data path doesn't invoke (the biggest finding)
The research loop fetches via `run.py:_default_fetch` → raw `yf.Ticker().history()` (full window, no
persistence); the CLI uses `create_provider("yahoo")` = bare `YahooProvider`. So:
- **cache-fixes-not-on-production-path** (H21/H23): `CacheManager` has no live caller — the fixes are
  correct but dormant. (The raw path refetches the full window each run, so H21's seam can't occur there.)
- **aggregated-provider-and-keyed-fixes-unwired** (H22/M33/M34/M35): `AggregatedDataProvider` + the keyed
  providers have no live caller; only bare Yahoo is used.
- **m32-research-loop-still-end-exclusive** (M32): the fix landed on `YahooProvider` (CLI path) but the
  research loop's `_default_fetch` still calls raw yfinance with an **exclusive** `end` → still drops the
  last bar, and now *diverges by one bar* from the CLI path. **This is a genuine live bug.**

→ **Action:** fix M32 on the research path; honestly annotate H21/H23/H22/M33/M34/M35 in the tracker as
"correct but the component is not wired into the live path — pre-positioned for future wiring".

## Theme 2 — honesty / disclosure gaps on the live path
- **pending-drops-oos-marker** (router.py:660): live `/candidates` defaults a missing OOS outcome to
  `"PENDING"`, which has **no headline branch** in `_robustness_tier` → the H5 "in-sample only (no hold-out)"
  marker is silently dropped (tier cap still holds). The DB-narrative path emits the marker; live doesn't.
- **h24-soft-surface-not-consumed-robustness**: the SOFT provider-capability FAIL is consumed only in
  *regime* mode; in the default *robustness* path the survivorship caveat is never attached to the
  candidate or the tier, so a default yfinance run can still read "strong" with no survivorship disclosure.
- **sidak-sequential-fwer-overclaim**: the `_sidak_t_star` docstring claims the online per-peek scheme
  "keeps it near the intended 5%" family-wise; the realized rate is ~17% at 20 peeks (a real mitigation
  from ~64%, but not 5%), and earlier-surfaced candidates keep their looser-bar verdict. **Docstring lies.**
- **lockbox-init-fallback-validates-in-sample**: `enable_oos=True` silently degrades to in-sample
  validation (validated_count/goal_met) if the lockbox fails to construct — disclosed only by a warning.
- **holdout-peek-count-not-persisted-crossrun** (H18): the peek count is per-run in-memory only; the
  cross-run hold-out mining H18 also named is uncorrected while the tracker reads DONE.

→ **Action:** fix the pending marker, surface survivorship in robustness, correct the Šidák docstring,
make the lockbox-init failure non-silent, and scope H18 as within-run in the tracker + docstring.

## Theme 3 — attribution plumbing
- **m21-errored-gate-not-plumbed** (gatekeeper.py): `GatePipeline` computes `errored_gate` for a hard-gate
  ERROR, but `ResearchGatekeeper.evaluate()` drops it from its return dict, so the graveyard/critic/report
  attribute an errored hard gate as `failed_gate=None`. (Terminal safety holds — not a mis-accept.)

→ **Action:** surface `errored_gate` through the facade; loop prefers it when `first_failed_gate` is None.

## Theme 4 — test-not-gating (tests exercise helpers, not the production wiring)
- **loop-peek-wiring-untested** (H18), **m23-wiring-not-pinned** (executor attach + gatekeeper allowlist),
  **m22-test-vacuous-vs-wiring** (canary ctx→gate data-flow), **m19-pathb-loop-forwarding-untested**,
  **m35-av-adjusted-endpoint-switch-untested** — each fix's *production wiring* would silently regress
  with the suite green.
- **h8-clears-clean-unasserted-and-false**: the H8 test's "clears the clean one" claim is never asserted
  **and is empirically false** (the clean control FAILs the canary at seed=99/n_paths=25). The genuinely
  gating half (leaky profits on noise) is sound.

→ **Action:** add wiring/gating tests; fix the H8 test's false "clears clean" claim.

## Low edge-cases (cache is dormant, so low priority)
- **h16-recovery-double-counts / oos-results-duplicate-count-inflation**: report OOS counts iterate the raw
  append-only `oos_results` with no per-hash dedup → duplicates inflate counts (goal-logic/badges unaffected).
- **h21-replace-only-covers-request-window**, **h21-nonatomic-replace-data-loss**: cache replace edge cases.

## Refuted (9) — not real
Included: "M35 premium-only endpoint" (get_daily_adjusted is free-tier), "M32 over-includes intraday bars",
"M34 ignores interval", "H21 makes the cache never serve reads", "lag tz-misalign to None", "canary
soft-fail only in gates dossier", "service.evaluate swallows all exceptions", the M19 duplicate, and
`test_pass_bar_uses_the_validation_t_star` (a constant assert — noted as low-value but harmless).

---
Full evidence + per-finding 2-lens verification: workflow `wf_ab1ee6b4-919` (39 agents).
