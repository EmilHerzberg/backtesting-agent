# Coverage Grid Calibration — the signal-flip study (v2 grid)

**Date:** 2026-07-14. **Purpose:** replace the a-priori v1 grid resolutions (period 25%, threshold 5pts,
std_dev 0.5 — my guesses) with values **grounded in when a parameter change actually changes the strategy's
behaviour.** This is the number the v2 cross-run multiple-testing correction will rest on, so it must be
measured, not assumed. Harness: `scratchpad/calibrate_grid.py` (reproducible).

## Method
For each template × parameter, on **6 diverse real assets** (AAPL, MSFT, NVDA / KO, PG / SPY — trending tech,
mean-reverting staples, index) over the fixed window **2015-01-01 … 2023-12-31**:

- **Metric = position-state disagreement.** Reconstruct the discrete held-position vector (long / flat / short)
  from each setting's real backtest trades; the *disagreement* between two settings = fraction of bars where
  they hold a different state, normalised by the bars where at least one is in-market. (Return-*magnitude*
  disagreement was rejected — it saturates at ~1.0 because share-count/entry-price noise makes P&L differ even
  when both settings are simply "long"; the discrete **state** is the true signal.)
- **JND (just-noticeable-difference)** = the step at which median disagreement first crosses a target **T**.
  Primary **T = 0.05** (a 5%-of-in-market-days behaviour change = a meaningfully different strategy); T ∈
  {0.02, 0.05, 0.10} reported so the one judgement call is transparent.
- **Periods** swept as multiplicative **ratios** (checks the log-spacing premise); **thresholds / multiplier**
  as **absolute** steps. Other params held at canonical mid-values.

## Results (JND @ T=0.05)

| Kind | Parameter | Measured JND | a-priori v1 | v2 (applied) |
|---|---|---|---|---|
| period | sma fast_period | 0.33 (nearly inert) | 0.25 | **0.30** |
| period | sma slow_period | 0.16 | 0.25 | **0.16** |
| period | rsi period | 0.08 | 0.25 | **0.08** |
| period | bollinger period | 0.05 (very sensitive) | 0.25 | **0.06** |
| period | macd fast / slow / signal | 0.21 / 0.22 / 0.21 | 0.25 | **0.20 / 0.22 / 0.20** |
| period | multi sma_period / rsi_period | *(under-trades — no data)* | 0.25 | **0.16 / 0.08** (analog fallback) |
| threshold | rsi buy / sell | 1.5 / 2.5 | 5.0 | **2.0** |
| multiplier | bollinger std_dev | 0.15 | 0.5 | **0.15** |

## Findings
1. **The a-priori grid was too coarse on every axis** (period ~1.5×, threshold ~2.5×, multiplier ~3.3×). Too
   coarse = it silently *merged* meaningfully-different strategies → under-counted the distinct-strategy space →
   would have made the v2 multiple-testing correction **too lenient**. Calibration was worth doing.
2. **Sensitivity is very non-uniform** — short oscillators (rsi/bollinger period) flip on a ~5-8% change; sma
   fast is nearly inert (~30%). A single per-kind number mis-sizes both tails, so resolution is **per-parameter**.
3. **Log-spacing for periods is confirmed** — within a parameter the JND-*ratio* stays roughly constant across
   low/mid/high base values (e.g. sma slow: 0.12 / 0.16 / 0.16).
4. **The true meaningful space is much larger than v1 assumed.** Feasible-cell counts per asset:
   sma **130**, macd **196**, bollinger **364**, rsi **3,380**, multi_indicator **11,830** (was ~110 / … / ~324
   under v1). This is itself important: there are far more meaningfully-distinct strategies than the coarse grid
   implied — so "cover the whole space" is a large undertaking (coverage % stays low in normal use), and the v2
   DSR correction gets a **larger, more honest** trial-count N.
5. **Integer resolution correctly caps the fine grids** — where the calibrated ratio implies more period cells
   than the integer range supports, cells with no distinct integer representative have no drawable center and
   are correctly dropped from `feasible_cells` (so the drawable count reflects genuinely-distinct strategies).

## Limitations (honest)
- One metric (position disagreement), one primary threshold (T=0.05), 6 assets, one window. The values are
  **grounded but approximate** — good enough to size the grid, not a physical constant. `multi_indicator`
  under-trades on the canonical settings, so its params use indicator-analog fallbacks (sma→0.16, rsi→0.08).
- Cross-asset spread exists (a period JND on a calm staple differs from a volatile tech name); we take the
  median. A volatility-scaled resolution is a possible future refinement.

## Applied
`src/backend/ai/research/coverage.py`: per-parameter `_PERIOD_RATIO` / `_THRESHOLD_STEP` / `_MULTIPLIER_STEP`
tables + per-kind fallback; **`GRID_VERSION = "v2"`** (so any v1-persisted cells never collide). This grid is
the input the v2 cross-run deflated-Sharpe correction will use as its pre-registered sweep-size N.
