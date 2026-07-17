# Coverage v2 — Session Handoff (2026-07-16)

**Purpose:** everything a new agent needs to take over the coverage-memory-v2 workstream if this session's context is lost. **Read this first, then `COVERAGE-V2-RECONCILED-PLAN.md` (the source of truth).**

## TL;DR
Design-only; **nothing implemented yet.** We specified and adversarially hardened a plan to feed a campaign-wide multiple-testing correction (an effective trial count **N**) into the Deflated-Sharpe (DSR) significance gate of the backtesting-agent, so a cross-run "campaign" that cherry-picks the best surviving strategy is penalized for the multiplicity it actually incurred (v1 shipped only a plain-language caveat for this). Along the way we (a) designed a large survivorship-free grid-calibration study on the real price warehouse, (b) designed a layered safety architecture, and (c) **found and corrected real flaws** in the earlier plan and in the out-of-sample lockbox. Two owner decisions are locked. No source code changed — only new design docs.

## Repos & locations
- **Working repo:** the **standalone** `backtesting-agent` at `C:/Users/emilh/Documents/AI Investing/Git/AI-Investment/backtesting-agent` — a nested repo inside the AI-Investment monorepo, own git remote (`EmilHerzberg/backtesting-agent`). **Do NOT touch the parent monolith.** It is ~14 commits ahead of origin (unpushed) from prior work.
- **Price warehouse:** `<monorepo>/data/asset_prices.db` (see Warehouse gotchas).

## The design docs (all in `backtesting-agent/docs/design/`)
1. **`COVERAGE-V2-RECONCILED-PLAN.md`** — ★ SOURCE OF TRUTH: locked decisions + corrections + build order. Where docs disagree, this wins.
2. `COVERAGE-MEMORY-V2.md` — the gate-wiring spec (17 ACs). **Partially superseded** — see its header banner.
3. `COVERAGE-CALIBRATION-V3-PROTOCOL.md` — the pre-registered grid step-size measurement protocol (scope-updated header).
4. `COVERAGE-GATE-SAFETY-MECHANISMS.md` — the safety envelope (mechanism IDs PF1-6 / RT1-4 / MON1-3 / FB1-4).
- Predecessor context (already on disk): `COVERAGE-MEMORY-V1.md` (shipped v1), `COVERAGE-MEMORY-V2-PLAN.md` (the recipe + 5 blockers B1-B5), `COVERAGE-CALIBRATION.md` (the shipped v2 grid).

## Locked owner decisions (2026-07-16)
- **D1 — balance dial: strict-leaning.** Reference edge **~0.9–1.0 Sharpe** (weakest edge we insist the in-sample gate must reliably confirm); exact value finalized from the measured **power curve at pre-flight (PF1)**, then frozen. In-sample gate + out-of-sample judge **both apply, in sequence** (the reference edge does NOT toggle OOS). Higher reference edge = stricter.
- **D2 — "validated" = risk-adjusted skill** (excess Sharpe/IR/alpha). "Beats buy-and-hold on total return" is a **separate, optional, report-only-by-default toggle** (not folded into the skill verdict).

## Critical corrections — DO NOT implement the old versions
- **`V ≈ 1/T` is RETIRED** → use a fixed, pre-registered conservative `V_null` (per-trade clock, serial-dependence-inflated) with a MANDATORY check `sr0(V_null) ≥ sr0(status-quo)`. (1/T actually *loosens* the bar ~30–40%.)
- **The `1+(N−1)·ρ̄` (Kish/Galwey) reduction with adjacent ρ̄ is RETIRED** → measure independence directly: **ONC / participation-ratio effective count** on a Marčenko–Pastur-denoised return-correlation matrix of the visited-cell family; `N_used = max(N_eff, N_run)`; eigenvalue sub-floor; no upper cap. (The old formula goes inert — collapses to ≈1 for any N.)
- **Firewall re-anchored OUTPUT-side** (performance is already one join away: `coverage.exemplar_hash → candidate.sharpe`); only scalars/verdicts may steer selection; proven by leak-audit + shuffle-invariance (PF6).
- **OOS lockbox bugs to fix:** underpowered-but-ran per-trade OOS → **UNEVALUATED not terminal FAIL** (loop.py:560-563); PASS → **risk-adjusted not total-return-beats-buy&hold** (loop.py:562); regime-mode softens DSR while OOS off (gatekeeper.py:83) = pre-existing bug.
- **Headline reframe:** N is a WEAK log-lever (1k→10k tries ≈ +15% bar). Vacuity is dominated by **T (history length)** and **V**, not N — so the honest response to a too-high bar is report/defer, never coarsen N.

## Build order & next actions (from the reconciled plan)
- **Now, in parallel (independently valuable, no "enable" needed):** ① lockbox fixes (Track 1) · ② V_null fix (Track 2) · ③ freeze + run the V3 calibration (Track 3).
- **Then (needs ①②③):** ④ the effective-N wire (RT1 + B1/B2 selection scope + B4 split) · ⑤ pre-flight gates PF1/PF5/PF6 (⑤ is where the power curve is produced and D1's dial is set).
- **Deferred (gated):** ⑥ soft-DSR (RT2) only after FB4 (campaign-wide OOS multiplicity control).
- **Enable** the coverage-v2 flag only after ①–⑤ + all pre-flight gates PASS. **Flag OFF = byte-identical to today.**
- **Recommended first move:** ① + ③ in parallel. **User wants to eyeball the frozen ticket list before the calibration run kicks off**, and review before any implementation.

## Warehouse gotchas (for the calibration run)
- `asset_prices.db`: 2.7 GB SQLite (EODHD), 42.9M daily bars, 14,821 tickers, survivorship-free from ~2000; dotcom/GFC/COVID densely covered; 5,456 delisted names with pre-2000 history (LEH/Enron/Ambac present; WCOM/BSC/WaMu absent).
- **MUST use `adjc` (split+div adjusted) and scale O/H/L by `adjc/c`** — raw `c` injects fake split-day crashes. `asset_splits`/`asset_dividends` tables are empty (adjustment baked into adjc).
- bt-agent opens `../data/asset_prices.db` directly; a proven `warehouse_fetch(symbol,start,end)` loader returns the OHLCV frame `run_backtest` needs.
- **No ETFs, no growth/value** in the warehouse (stratify on sector × cap × vol × survivorship). Verified live pool counts: living 2,142 / pre-2000-delisted 4,684.

## Status / housekeeping
- All docs written; **no source code changed.** Uncommitted in the repo: the new design docs, plus a **stray whitespace edit in `docs/reviews/QUANT-REVIEW-2026-07-03.md`** (an accidental artifact worth reverting).
- A separate flagged doc-only fix: `COVERAGE-MEMORY-V1.md` §Persistence advertises `survived_count`/`died_count`/`best_sharpe` columns that were never built — annotate stale so nobody thinks per-cell performance exists.
- **User preferences:** explain stats/quant in plain language + analogy before asking to decide (not a statistician); do NOT implement until reviewed; autonomous execution once greenlit; watch the trading-system's LLM-API spend (irrelevant to this deterministic work — calibration is backtests, no LLM cost).

## Provenance
Three background workflows this session (spec → calibration-protocol → safety), each design→adversarial-review→revise. Their full outputs were distilled into the 4 docs above (the durable record); raw workflow outputs live in the session temp dir and may be ephemeral.
