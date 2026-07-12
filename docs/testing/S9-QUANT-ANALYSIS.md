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

## 5. Regime matrix — EXECUTED 2026-07-12 (paid, €0.69 total, all 10 runs clean)

Approved & run: 2 regime windows × 5 reasoning models, full_ai, max_runs=20, target_candidates=3, each
hard-capped at max_eur=0.35. **No run degraded, no errors, none hit the cap.** This is the first data that
differentiates the *models* (S9 could not — see §3). Artifact: `scratchpad/regime_matrix_results.json`.

**trend_covid (trend_following · AAPL/MSFT/NVDA · 2020-01→2021-06)**

| Model | Cands | Templates used | Sharpes | €/run |
|---|---|---|---|---|
| o3 | 3 | macd_cross, sma_crossover | 1.19, 1.16, 1.24 | 0.208 |
| gemini-2.5-pro | 2 | macd_cross, sma_crossover | 1.24, 1.17 | 0.083 |
| deepseek-reasoner | 3 | macd_cross, sma_crossover | 1.24, 1.20, 1.13 | 0.016 |
| glm-5 | 2 | sma_crossover | 1.29, 1.24 | 0.050 |
| seed-2-0-pro | 3 | sma_crossover | 1.28, 1.24, 1.20 | 0.020 |

**mr_2018 (mean_reversion · KO/PG/JNJ · 2018-01→2019-06)**

| Model | Cands | Templates used | Sharpes | €/run |
|---|---|---|---|---|
| o3 | 3 | **bollinger_breakout**, rsi_reversion | 0.95, 0.43, 0.44 | 0.176 |
| gemini-2.5-pro | 3 | rsi_reversion | 1.26, 1.06, 0.52 | 0.053 |
| deepseek-reasoner | 1 | rsi_reversion | 1.00 | 0.017 |
| glm-5 | 1 | rsi_reversion | 0.38 | 0.052 |
| seed-2-0-pro | 3 | rsi_reversion | 1.14, 0.75, 0.38 | 0.015 |

### What the models actually differ on
1. **Template *exploration* is the clearest differentiator, not candidate quality.** Templates touched across
   both windows (of 4 possible): **o3 = 4/4** (the only model to try `bollinger_breakout`), gemini = 3,
   deepseek = 3, glm-5 = 2, byteplus = 2. Frontier/larger reasoners explore the proposal space wider; cheaper
   models tunnel onto the single most obvious template (`sma_crossover` / `rsi_reversion`).
2. **Winning configs converge.** The exact Sharpe **1.243** recurs across o3/gemini/deepseek/glm/byteplus on
   trend_covid — in a strong regime every model lands on the *same* optimal `sma_crossover` spec. Model choice
   changes the *breadth* of hypotheses far more than it changes the *winner*.
3. **deepseek-reasoner is the value winner:** €0.032 for both windows (12× cheaper than o3's €0.384),
   competitive breadth on trend (both templates, 3 candidates); weaker on MR (1 candidate).
4. **o3 is 55% of the total spend** for one marginal edge (the bollinger exploration). For this task its cost
   is hard to justify vs deepseek/byteplus.
5. **Honesty layer held across every model:** all candidates came back `low`/`very_low` confidence and
   `unvalidated` (regime-fit, not robustness-proven) — no model was allowed to oversell a regime-fit curio,
   and gemini's reporter now produces real prose (`degraded=False`), confirming the F-2 fix under load.

### Bottom line
The engine is functionally correct and honest across families, regimes, rigor, OOS, and 5 providers. For a
*production* selection model the relevant axis is **exploration breadth per €**, where **deepseek-reasoner and
byteplus** dominate; o3 buys marginally wider search at ~12× the cost. The mechanism-only production choice
(deepseek/byteplus, per the leakage research) is also the cost-efficient one here.

