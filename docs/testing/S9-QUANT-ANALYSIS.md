# S9 Multi-Model Run — Quant Analysis & Testing-Coverage Assessment

**Date:** 2026-07-12 · **Input:** the S9 7-provider full_ai comparison (`results/e2e-model-comparison.json`)
plus a €0 `rule_based` diversity sweep (13 cells). **Purpose:** find functional errors, judge whether the
single-scenario S9 test was comprehensive, and decide what further runs are worth spending on.

## 1. Functional errors found (both fixed)

### F-1 — Silent AI→rule-based degradation on a hard LLM failure (M57)
`claude` (Anthropic 400, unfunded) and `moonshot` (401, bad key) each **completed as `full_ai` with a
narrative**, `used_eur=0` the only tell. The Strategist/Critic/Reporter caught the exception and fell back
to rule-based/templated **without recording it** — a run that never ran the AI reported a clean AI run.
**Fix:** `TokenLedger.record_failure` → `Budget.llm_failures` → `ResearchState.llm_degraded()`, surfaced as
`degraded`/`llm_failures` on `/state` (live + persisted, new column + migration), a digit-free "DEGRADED AI
RUN" report banner, and a red HUD chip. Live-verified (moonshot 401 → €0): `degraded=True, llm_failures=4`.

### F-2 — Paid-but-fully-templated report on a reasoning model (M57, reporter)
`gemini-2.5-pro` **spent €0.02 but returned a 100%-templated report** — its narrative was exactly **1261
chars, the pure-template length** (measured deterministically), while the four working models produced
distinct shorter prose (728/752/774/784). Two causes:
1. The Reporter used `max_tokens=900`. Reasoning models spend tokens on hidden chain-of-thought before the
   JSON, so 900 **truncated** them → unparseable → every section fell back to template while billing. The
   Strategist/Critic already had 4000-token reasoner headroom (H25); **the Reporter was missed.**
2. Even when parseable, if every section is rejected (digit-leak / malformed), the user got a rule-based
   report with no tell.

**Fix:** reasoners get 4000 tokens in the Reporter too; a billed reporter call that yields **zero** usable
sections is counted as a degradation. **Live-verified on real gemini-2.5-pro:** `narrative_len=1014` (real
prose, not 1261), `used_eur=€0.0196`, `degraded=False` — the reporter now works end-to-end.

### No crashes across 13 diverse `rule_based` cells
Every strategy family, every asset regime, standard/strict/exploratory rigor, OOS on, **and regime mode**
(select-on-train split + within-regime hold-out) ran without a single exception. The engine is functionally
robust across the diversity; the S9 issues were all in the **LLM-agent honesty layer**, now fixed.

## 2. The productivity surface (€0 rule_based sweep, max_runs≈20, seed=3)

| Cell | Mode | Candidates | Best Sharpe | Dominant gate kill |
|---|---|---|---|---|
| mr_staples / mr_trending / mr_index | robustness | **0 / 0 / 0** | — | minimum_activity |
| trend_staples / trend_trending / trend_index | robustness | **0 / 0 / 0** | — | minimum_activity, benchmark_relative |
| mf_staples / mf_trending | robustness | **0 / 0** | — | minimum_activity |
| mr_trending (strict) / trend_trending (exploratory) | robustness | **0 / 0** | — | minimum_activity, benchmark_relative |
| all_families_mixed | robustness | **0** | — | minimum_activity |
| **regime_trend_covid** (2020-01→2021-06) | regime | **3** | **1.19** | minimum_activity |
| **regime_mr_2018** (2018-01→2019-06) | regime | **3** | **1.44** | minimum_activity |

**Reading it:**
- **Robustness mode with modest run counts is a null-yield regime by design.** Daily-bar technical signals
  on liquid equities have low prior alpha, and the honest gates reject them — `minimum_activity` (strategies
  trade too rarely to be significant) is the dominant killer everywhere, then the buy-and-hold / performance
  floors. Finding nothing here is the *expected, correct* result (this is a falsification engine).
- **Regime mode reliably produces candidates** (3 per window at only 12–17 trials) — it fits to one window
  with a lower bar (select-on-train, no robustness-OOS), so the strategist's proposals actually clear.

## 3. Was S9 comprehensive? No — and here is the precise reason.

S9 used **one scenario: robustness mode, mean-reversion, staples, max_runs=5.** From §2 that is the
**worst possible setting for a *model* comparison**: robustness + low runs → **guaranteed 0 candidates** →
every model produces the same output (0 candidates, a "nothing survived" report). S9 therefore proved the
**wiring** works per provider (and surfaced F-1/F-2 — real value) but proved **nothing about model
discrimination**: no model ever had to generate a surviving strategy, so we cannot say whether o3, DeepSeek-R1,
or gemini find *better or different* candidates. The comparison table's identical "0 cands" rows are an
artifact of the scenario, not the models.

**What is untested after S9:**
- The candidate → dossier → OOS → report-with-real-content path **under full_ai** (never reached; 0 candidates).
- Whether models **diverge** — different templates, params, hypotheses, candidate quality — which only shows
  up when proposals actually clear the gates.
- Regime-mode LLM behaviour (select-on-train, hold-out narration) under real models.

## 4. Recommendation — a targeted paid regime matrix

To analyse the system *and the models* where their choices matter, run the **identical regime scenario**
(which yields candidates) across the models with **working keys**, and compare on: candidate count, candidate
quality (Sharpe / DSR / hold-out PASS), hypothesis/template diversity, report quality, cost, and the new
`degraded` flag.

**Proposed matrix:** 2 regime windows (the two productive cells above) × 5 working reasoning models
(o3, gemini-2.5-pro, deepseek-reasoner, glm-5, seed-2-0-pro), max_runs≈20, each hard-capped at `max_eur`.

**Per-run cost estimate** (S9 per-call costs scaled ~3× for the higher regime call count):

| Model | ≈ €/run | ×2 windows |
|---|---|---|
| o3 | 0.25 | 0.50 |
| glm-5 (zhipu) | 0.08 | 0.16 |
| gemini-2.5-pro | 0.06 | 0.12 |
| seed-2-0-pro (byteplus) | 0.02 | 0.04 |
| deepseek-reasoner | 0.01 | 0.02 |
| **Total** | | **≈ €0.84** |

Claude + Moonshot are excluded until the Anthropic account is funded and the Moonshot key replaced. The spend
is confirmed with the user before running (standing budget rule).
