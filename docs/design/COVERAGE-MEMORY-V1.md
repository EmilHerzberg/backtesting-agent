# Cross-Run Coverage Memory — v1 (design + ATDD contract)

**Status:** in development (ATDD). **Scope:** v1 only. **Author date:** 2026-07-14.
**Motive:** the strategist has no memory across runs — with the default fixed seed, every run re-tests the
identical strategies; with a random seed it re-explores randomly, never systematically covering new ground.
This adds **space-filling sampling + persistent cross-run coverage memory** so successive runs dig where no
prior run has dug — without touching how significance is judged.

## Non-goals (deferred to v2, after calibration)
- **No automatic stop** on "space covered" (v1 only *reports* progress).
- **No coupling of the coverage count into the significance math** (deflated-Sharpe `n_trials_global` stays
  per-run, exactly as today). v1 is deliberately **overfitting-neutral**.
- **No signal-flip calibration** of the grid resolution — v1 ships a-priori constants tagged `grid_version="v1"`.
- **No regime-mode coverage** — each regime window is its own space; v1 persists coverage for **robustness mode only**.

## The grid — "intervals that make sense" (per parameter KIND)
A continuous/integer parameter point is mapped to a discrete **cell**; two points in the same cell are the
"same strategy". Resolution is per-KIND because *meaningfully different* differs by kind:

| Kind | Params | Scale | v1 step | Rationale |
|---|---|---|---|---|
| period | all lookback windows (SMA/RSI/Bollinger/MACD periods) | **log / relative** | ratio **r = 0.25** (25%) | 42→43 (+2%) is noise; 5→6 (+20%) shifts the signal. A "day" is meaningless; a *percent* is not. |
| threshold | RSI buy/sell levels | **absolute** | **5 points** | RSI 30 vs 31 = noise; 30 vs 35 = different entries. |
| multiplier | Bollinger `std_dev` | **absolute** | **0.5** | effect on breakout frequency ≈ linear in the multiplier. |

Per-dim cell index (`v` clamped to `[low, high]` first):
- **period:** `c = floor( ln(v/low) / ln(1+r) )`, capped at `N-1`; `N = floor( ln(high/low)/ln(1+r) ) + 1`
- **threshold / multiplier:** `c = floor( (v-low)/step )`; `N = floor( (high-low)/step ) + 1`

`cell_id = "v1:" + "-".join(index per param, params sorted by name)`. The **cell center** (representative point
handed back to the backtest) is the geometric center for periods (`low*(1+r)^(c+0.5)`, rounded to int) and the
arithmetic center for threshold/multiplier. `grid_version` is stored so a v2 re-tuning never collides with v1 cells.

**Feasibility:** the only runtime-enforced constraint is SMA `slow ≥ fast+5` (`_repair_params`). `feasible_cells()`
enumerates the per-dim product, applies `_repair_params` to each cell center, and **drops cells whose center
repairs into a *different* cell** (the "dead corner" — the sampler must never target them). MACD and the RSI-pair
constraints are structural (disjoint ranges) so every product cell is feasible there.

## Method — greedy farthest-point (maximin) over the feasible cell grid
Each `propose()` picks the **unvisited feasible cell whose minimum distance to the already-visited set is
maximal** (distance in per-dim *bin-index* space, each dim normalized by its `N`, so period spread is relative and
threshold spread absolute — kind-correct by construction). Exact incremental argmax (the spaces are ≤ a few
thousand cells, trivially cheap). First pick (empty visited set) = the cell nearest the box center (deterministic).
Ties broken by the per-run RNG. **State is only the visited-cell set** — so a fresh run resumes purely by loading
that set; no sequence index, no radius. This is precisely "resume the search where it left off".

Sampling is deterministic **given (seed, loaded visited-set)** — reproducible, but *not* degenerate across runs,
because a later run loads more visited cells and its maximin therefore picks *farther, different* cells. That
directly fixes today's "same seed ⇒ identical sequence every run".

## Persistence
New table `research_coverage` (one upserted row per cell) in `db_models.py` — `create_all` builds it, **no
migration entry needed for a brand-new table**. Key = `(scope_key=user_id, template_id, security_id, window_key,
cell_id)`. `window_key = ""` for robustness (all robustness runs share the fixed default window → they pool).
Columns include `visit_count`, `survived_count`, `died_count`, `first_seen`, `last_seen`, `exemplar_hash` (join to
candidates/failures), `grid_version`, and `best_sharpe` — **TELEMETRY ONLY; the sampler MUST NEVER read it**
(reading it would be exploitation → overfitting). `backfill_coverage()` reconstructs cells from existing
`research_candidates` + `research_failures` rows, so history is honored and the table is a pure, rebuildable
accelerator. End-of-run flush (reuse `persistence._write_lock` / `async_session`).

## LLM integration (soft nudge only — no billed-call waste)
- `_render` gains an `unexplored_regions` block (a few unvisited cell centers) framed as "prefer proposing in an
  unexplored region unless your mechanism requires a tested one." Pure prompt nudge.
- `_build` is **unchanged** except it marks the chosen cell visited — it does **NOT** hard-reject a proposal that
  lands on a visited cell (that would turn full_ai into billed-but-discarded fallbacks — an M38/H25 regression and
  a budget-rule violation). Exact-hash dedup stays as today.

## Feature flag + backward compat
`run_research(coverage_memory: bool = False, user_id: int | None = None)`. **Default OFF** → `coverage=None` →
strategist behaves byte-identically to today (pure in-memory `_tried_hashes`, i.i.d.-uniform sampling). Existing
DBs gain an empty coverage table. Reproducibility semantics with the flag ON become "deterministic given (seed,
loaded coverage snapshot)"; with the flag OFF the old seed-only guarantee holds exactly.

## Overfitting-neutrality (the v1 quality gate — AT-7)
v1 changes only **where** we sample. It must be provable that:
1. the significance path is untouched — `gatekeeper` / DSR `n_trials_global` inputs are **identical ON vs OFF**;
2. `best_sharpe` is **never** consulted by the sampler;
3. **no** cross-cell / cross-asset "winner" ranking (a cherry-picking menu) is emitted anywhere.
The post-v1 focused review adversarially interrogates exactly this. (The full campaign-wide multiple-testing
correction is v2 — it needs the calibrated grid.)

## Functional acceptance tests (ATDD — written first, all must pass)
- **AT-1** grid: same-cell collapse of near-duplicates; meaningful step ⇒ different cell.
- **AT-2** feasibility: SMA dead-corner cells excluded; sampler never returns one.
- **AT-3** within-run space-filling beats uniform random on distinct-cell coverage.
- **AT-4** cross-run: run B (same seed) after loading run A's coverage visits **disjoint** cells from A; with the
  flag OFF + same seed the two runs are **identical** (the bug this fixes).
- **AT-5** flag OFF ⇒ proposals identical to the current baseline.
- **AT-6** LLM: `_render` carries `unexplored_regions`; a cell-collision does not increment the fallback counter.
- **AT-7** overfitting-neutral: DSR `n_trials_global` inputs identical ON vs OFF; sampler never touches
  `best_sharpe`; no cross-cell ranking emitted.
- **AT-8** novelty-rate computed + surfaced in the report.
- **AT-9** persist → load round-trips the visited set; backfill reconstructs cells from candidates/failures.
- **AT-10** saturated space raises a signal but does NOT auto-stop the loop.
