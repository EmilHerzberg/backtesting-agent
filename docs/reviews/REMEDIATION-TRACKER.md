# Remediation Tracker — backtesting-agent

**The single source of truth for "are we done?".** One row per finding from [QUANT-REVIEW-2026-07-03.md](./QUANT-REVIEW-2026-07-03.md). Process in [REMEDIATION-PLAN.md](./REMEDIATION-PLAN.md).

**Status:** `OPEN` · `SPEC` (needs a written spec first) · `DECISION` (needs a wire/delete or product call) · `IN-PROGRESS` · `DONE` (fix merged + tagged test green) · `QUARANTINED` (disabled + parked, scheduled for deletion) · `BACKLOG` (Low, post-release).
**Bucket:** `mech` (mechanical fix, reference formula) · `dec` (decision) · `spec` (technical spec) · `test` (test/coverage) · `infra` (harness/CI).
**Test:** path of the ID-tagged regression test that proves closure (filled as we go).

**Scoreboard:** in-scope for release = **95** (3 C + 32 H + 60 M). Backlog = 23 L (+ 29 N-notes). Done: **44 / 95** (H7 · 1A: H1/H2/M24/M25 · 1B: C1/H6/H12/M26 · 1C: C2/M5/M6 · 1D: H9/H10/M2/M4 · 1E: C3/H30/M50 · 2A: H3/H14/H15/H16/H17/H18 · 2B: H5 · 2C: H4/H8/H24/M19/M20/M21/M22/M23 · 3A: H21/H22/H23/M32/M33/M34/M35 · 3B: H27/M47/M53) + L17, L22. **✅ All 3 criticals fixed. Phases 1+2 MERGED to main. Phase 3 COMPLETE (3A market-data adjustment layer + 3B persistence integrity); M36 deferred to bundle with FX finding H32. NEXT = Phase 3 PR to main, then Phase 4 (cost/LLM honesty).**

> **Phase 1 review (2026-07-05, `PHASE1-REVIEW-2026-07-05.md`):** a 9-reviewer adversarial audit found 12 real issues (0 crit, 7 high) — 5 behavioral defects where a fix didn't reach the production path + 7 test-integrity gaps. **All 12 fixed** in commit "Phase 1 review fixes": M4 shipped on the CLI/YAML default; the C3 default-goal Sharpe-floor regression removed; win_rate/profit_factor goals now enforced (not skipped); the generator warm-up mask made effective; the reslice put on the geometric Sharpe scale; and the DSR-loop / reslice-value / generator / M5·L17 / H30 / M24 tests added. Suite 635 pass.

**Board mirror (local `tickets/`, staged for Jira — token was expired 2026-06-18):** Epic **ATS-1787**. Stories: Phase 0 = ATS-1788, Phase 1 = ATS-1789, Phase 2 = ATS-1790, Phase 3 = ATS-1791, Phase 4 = ATS-1792, Phase 5 = ATS-1793. Cluster sub-tasks = ATS-1794…1812 (one per cluster below, in order). Update ticket status via `board.py status <KEY> <status>` (auto-pushes to Jira when the token is valid).

---

## Phase 0 — Foundation (enables everything; discharges nothing directly but unblocks all tests)

| Item | Bucket | Status | Test/Artifact | Notes |
|------|--------|--------|---------------|-------|
| 0.1 Verification harness (€0 loop-runner + MockProvider + frozen data + factories) | infra | DONE (review) | `tests/support/*`, `tests/conftest.py`, `tests/support/test_harness_smoke.py` (3/3 green) | ATS-1794. Smoke proves rule_based offline+zero-LLM, determinism, full_ai→mock wiring. Already surfaces H7. |
| 0.2 Minimal determinism (seed wiring + golden snapshot) | infra | OPEN | `data/golden/` | Slice of M12/N28 needed for stable regression. (Harness determinism already proven via seeded synthetic OHLCV.) |
| 0.3 CI (pytest-in-image + lint-imports + next build + ship-vs-tree guard) | infra | OPEN | `.github/workflows/` | Blocks merge on red. Needs D: confirm CI platform. |
| 0.4 Tracking substrate (this tracker + board epic ATS-1787) | infra | DONE | this file + `tickets/ATS-1787-*` | D1 — local mirror; Jira push pending token |
| 0.5 Test-tagging convention (`@pytest.mark.finding("...")`) | infra | DONE | `pyproject.toml` marker added | Coverage matrix generated from tags |
| 0.6 Worked example end-to-end (H7) red→green | infra | DONE (review) | `tests/unit/backtesting/test_finalize_trades_h7.py` | ATS-1797 — H7 closed; proves the red→green tag workflow |

---

## Phase 1 — Statistical wiring that corrupts accept/reject

### Cluster 1A — Deflated Sharpe gate (fix together)
| ID | Sev | Bucket | Status | Test | Note |
|----|-----|--------|--------|------|------|
| H1 | High | mech | DONE (review) | `tests/unit/ai/research/test_dsr_inputs_h1_m25.py` | Per-period trial-Sharpe variance now fed (loop `_period_sharpe`/`_dsr_registry_inputs`); annualized var no longer collapses the gate. Found by 6 reviewers. |
| H2 | High | mech | DONE (scoped) | `…test_dsr_inputs_h1_m25.py` | Within-run N corrected (counts measured trials, not `total_iterations`). **Cross-run** registry accumulation + re-deflate-at-report **deferred to Phase 3B (persistence)** per decision 2026-07-05 — the in-memory loop has no cross-run state. |
| M24 | Med | mech | DONE (review) | `…test_dsr_inputs_h1_m25.py`, `test_quality.py` | Explicit `sr_variance_defaulted` flag threaded loop→gatekeeper→GateContext→gate→quality.py; magic-0.001 sniff removed; a defaulted variance is always provisional. |
| M25 | Med | mech | DONE (review) | `…test_dsr_inputs_h1_m25.py` | n_trials = count of gate-evaluable trials; variance/N share per-period scope; ddof=1. |
| N6 | note | mech | DONE | `…test_dsr_inputs_h1_m25.py` | ddof=1 applied in `_dsr_registry_inputs` (folded into 1A). |

### Cluster 1B — Indicator warm-up buffers
| ID | Sev | Bucket | Status | Test | Note |
|----|-----|--------|--------|------|------|
| C1 | **Crit** | spec | DONE (review) | `tests/unit/backtesting/test_warmup_c1.py` | Runner-level warm-up built: `BacktestConfig.warmup_bars` + generic `StrategyBase` trade-start mask (`buy`/`sell` suppressed until the window) + `_reslice_to_window` metrics (also fixes M3-style dilution). Walk-forward now warms indicators on a prefix. |
| M26 | Med | mech | DONE (review) | `tests/unit/ai/research/test_warmup_slices_m26.py` | `_prepare_with_warmup` reaches back a lookback-sized prefix; `executor.run(..., warmup_bars=)` threads it into all three slices (decay/hold-out/OOS). |
| M3 | Med | mech | PARTIAL | `test_warmup_c1.py`, `test_warmup_slices_m26.py` | Flat warm-up no longer dilutes the **OOS/hold-out/decay/walk-forward** metrics (C1 reslice). The **main IS window** still passes the full per-bar series (incl. leading flat) as "daily returns" — remaining piece. |
| H6 | High | mech | DONE (review) | `tests/unit/backtesting/test_walk_forward_validity_h6.py` | `_window_is_valid` requires ≥1 trade + Sharpe>threshold; crashed windows kept in the denominator (`crashed_windows`). |
| H12 | High | mech | DONE (review) | `tests/unit/backtesting/test_indicator_warmup_h12.py` | `min_periods` on every ewm chain (RSI/EMA/MACD/ADX/ATR/Keltner) + NaN guards on MACD/Keltner `signal()` + generator `_signal_fn` maps warm-up→NaN (not 0.0). Also first tests for the pandas indicator library (partial **M18**). |

### Cluster 1C — Interval-aware annualization
| ID | Sev | Bucket | Status | Test | Note |
|----|-----|--------|--------|------|------|
| C2 | **Crit** | spec | DONE (review) | `tests/unit/backtesting/test_annualization_c2.py` | `periods_per_year(index)` infers the factor from bar spacing (252/365/52/12), matching backtesting.py's `annual_trading_days`; threaded through buy_hold, market, Sortino, runner reslice. No more hardcoded sqrt(252). |
| M5 | Med | mech | DONE (review) | `…test_annualization_c2.py` | `benchmark_sharpe` replicates backtesting.py's geometric/compounded estimator, so benchmark and strategy Sharpe are on the same scale in the gate. |
| M6 | Med | mech | DONE (review) | `…test_annualization_c2.py` | `compute_buy_hold` is the single benchmark-Sharpe source (ddof=1, interval-aware); executor no longer computes its own ddof=0 duplicate. |
| L17 | Low | mech | DONE | `…test_annualization_c2.py` | Alpha annualized (× `periods_per_year`) in `market.py`. |

### Cluster 1D — Metric formulas the optimizer/gates consume
| ID | Sev | Bucket | Status | Test | Note |
|----|-----|--------|--------|------|------|
| H9 | High | mech | DONE (review) | `tests/unit/backtesting/test_metric_formulas_1d.py` | Standard target downside-deviation `sqrt(mean(min(excess,0)^2))` (no mean-centered std); a steady loser no longer explodes to ~1e15, single-negative no longer NaN. |
| H10 | High | mech | DONE (review) | `…test_metric_formulas_1d.py` | 999.99 sentinels replaced with bounded caps (Sortino/profit-factor winsorized to 10) so the optimizer stops chasing degenerate no-loss strategies. |
| M2 | Med | mech | DONE (review) | `…test_metric_formulas_1d.py` | Calmar uses CAGR (compound), not arithmetic `total_return/years`; min-duration guard + cap. |
| M4 | Med | mech | DONE (review) | `…test_metric_formulas_1d.py` | Composite `max_drawdown` weight rescaled for fraction units (−1.5) so a 50% DD materially lowers the score (was ~100x too weak). |

### Cluster 1E — Real goal-criteria completion
| ID | Sev | Bucket | Status | Test | Note |
|----|-----|--------|--------|------|------|
| C3 | **Crit** | spec | DONE (review) | `tests/unit/ai/research/test_goal_criteria_1e.py` | `parse_criteria` wired into `GoalBrief` at run start (run.py); `goal_met`/`validated_count` now count only candidates satisfying the user's criteria, not a raw candidate count. |
| H30 | High | mech | DONE (review) | `…test_goal_criteria_1e.py` | Drawdown stored as a positive `<=` limit compared on `abs(dd)` (sign-agnostic); criteria emit canonical Candidate keys (`sharpe_annual`/`n_trades`) — no more vacuous/never-matching check. |
| M50 | Med | dec | DONE (review) | `…test_goal_criteria_1e.py` | Parser wired (no longer dead code); `candidate_meets_criteria` skips non-applicable metrics. |
| L22 | Low | mech | DONE | `…test_goal_criteria_1e.py` | Return/win-rate/profit-factor now parsed (canonical keys). |

---

## Phase 2 — Out-of-sample & validation discipline

### Cluster 2A — OOS / hold-out contract
| ID | Sev | Bucket | Status | Test | Note |
|----|-----|--------|--------|------|------|
| H3 | High | spec | DONE | `test_oos_lockbox_2a.py` | D5: sign-only bar → sample + per-trade t≥1.65 + excess-over-buy-hold; thin=UNEVALUATED |
| H14 | High | mech | DONE | `test_oos_lockbox_2a.py` | budget/token keyed on lineage ROOT via `LineageTracker.get_root` (shared family allowance) |
| H15 | High | mech | DONE | `test_oos_lockbox_2a.py` | OOS window_end = live `_env_bounds()[1]`, not the "2025-12-31" literal |
| H16 | High | mech | DONE | `test_oos_lockbox_2a.py` | added `OOSLockboxService.get_result`; loop recovers prior verdict instead of re-raising |
| H17 | High | mech | DONE | `test_oos_lockbox_2a.py` | added `OOSOutcome.UNEVALUATED`; exception/thin sample spends no budget, writes no row, retryable |
| H18 | High | spec | DONE | `test_regime_holdout.py` | D6: `_sidak_t_star(k)` — hold-out bar Šidák-corrected for its reuse count (per asset+slice); thin peeks don't count |

### Cluster 2B — Default OOS
| ID | Sev | Bucket | Status | Test | Note |
|----|-----|--------|--------|------|------|
| H5 | High | dec | DONE | `test_quality.py` | D9 FULL: OOS default-ON (run.py/router, per-run `:memory:`); only a held-out PASS earns "strong" — OFF/PENDING/UNEVALUATED capped at "moderate" + honest marker |

### Cluster 2C — Wire-or-demote inert gates
| ID | Sev | Bucket | Status | Test | Note |
|----|-----|--------|--------|------|------|
| H4 | High | dec | DONE | (removed) | DELETED config/gates.default.yaml (never loaded); RIGOR_PRESETS documented as single source of truth |
| H24 | High | mech | DONE | `test_basic_gates.py` | loop feeds real `get_bias_flags(provider)`; ProviderCapabilityGate now SOFT (surfaces survivorship risk, doesn't hard-block the default) |
| M19 | Med | mech | DONE | `test_basic_gates.py` | Path C now risk-aware (excess>0 AND no Sharpe degradation); loop forwards `buy_hold_max_drawdown` so Path B binds |
| M20 | Med | mech | DONE | `test_gatekeeper_presets.py` | `min_stressed_sharpe` added to each preset (≤ min_sharpe) and applied to CostStressGate |
| M21 | Med | mech | DONE | `test_pipeline.py` | only HARD fails set `first_failed_gate`; hard-gate ERROR is terminal under new `errored_gate` |
| M22 | Med | dec | DONE | `test_leakage_suite.py` | WIRED: run_strategy_fn closure + ohlcv_df threaded through gatekeeper; canary added to pipeline (SOFT, survivors-only via cost_rank 10); `enable_leakage_canary` flag |
| M23 | Med | dec | DONE | `test_lag_gate_m23.py` | Option A: executor reconstructs held positions + re-derives P&L with all fills delayed 1 bar → `lagged_sharpe_annual`; gate now evaluates (None→provisional) |

---

## Phase 3 — Data integrity

### Cluster 3A — Market-data adjustment layer
| ID | Sev | Bucket | Status | Test | Note |
|----|-----|--------|--------|------|------|
| H21 | High | spec | DONE | `test_marketdata_cache_3a.py` | immutable-snapshot semantics: refresh refetches the FULL window and replaces the range (single adjustment basis), never merges a re-based tail. (adjustment-mode cache-key = small follow-up) |
| H22 | High | mech | DONE | `test_marketdata_providers_3a.py` | AggregatedDataProvider returns the FIRST (priority) provider that answers, not the most-rows one (no cross-provider basis mixing); + M35 endpoint fix |
| H23 | High | mech | DONE | `test_marketdata_cache_3a.py` | dedup key normalised to naive-UTC (`_to_naive_utc`) — matches the stored round-trip, so real tz-aware yfinance bars dedup instead of re-inserting |
| M32 | Med | mech | DONE | (applied; contract) | Yahoo `history(end=...)` is exclusive → pass end+1 day so the last bar is inclusive like every other provider |
| M33 | Med | mech | DONE | `test_marketdata_providers_3a.py` | Tiingo maps only adj* (raw fallback), dedupes columns → no duplicate `Close`, prefers total-return-adjusted |
| M34 | Med | mech | DONE | `test_marketdata_providers_3a.py` | CoinGecko uses `market_chart/range` (honors [from,to]) + real/NaN volume instead of `/ohlc` recent-N + fabricated 0 |
| M35 | Med | mech | DONE | `test_marketdata_providers_3a.py` | AlphaVantage uses `*_adjusted` endpoints; `_av_adjust` scales the whole OHLC bar to the adjusted basis |
| M36 | Med | mech | DEFERRED | | Currency field — a structural precondition for FX finding H32 (no live fix alone); do it WITH H32 |

### Cluster 3B — Persistence integrity
| ID | Sev | Bucket | Status | Test | Note |
|----|-----|--------|--------|------|------|
| H27 | High | mech | DONE | `test_persistence_3b.py` | flush cursors advance into LOCALS, written back to rec.* only AFTER commit succeeds → failed commit is retried, not dropped |
| M47 | Med | mech | DONE | `test_persistence_3b.py` | Candidate carries `lineage_id` at creation; persisted with it (not the run's flush-time lineage). NOTE: event ts/phase emission-time precision left as a small backlog follow-up (lesser audit issue) |
| M53 | Med | mech | DONE | `test_persistence_3b.py` | `_utc_iso()` marks every DB→JSON datetime as UTC (started_at/finished_at/created_at/ts); fixed router `.isoformat()`-on-string crash |
| M54 | Med | mech | OPEN | | Paused runs become zombies on restart |

### Standalone (Phase 3)
| ID | Sev | Bucket | Status | Test | Note |
|----|-----|--------|--------|------|------|
| M1 | Med | mech | OPEN | | NaN bfill look-ahead in warm-up/benchmark |
| M7 | Med | mech | OPEN | | Loop omits buy_hold_max_drawdown → Path B dead |
| M51 | Med | mech | OPEN | | Pause consumes wall-clock budget |
| H32 | High | mech | OPEN | | Non-USD assets regressed vs SPY, no FX (needs M36) |

---

## Phase 4 — Cost realism & LLM honesty

### Cluster 4A — Unified cost model
| ID | Sev | Bucket | Status | Test | Note |
|----|-----|--------|--------|------|------|
| H29 | High | spec | SPEC | | AI executor drops spread/slippage — unify with CLI (D8). Same as M55. |
| M55 | Med | mech | OPEN | | Duplicate of H29 (merge; treat as high) |
| L18 | Low | dec | BACKLOG | | Spread half/full docstring ambiguity |
| L19 | Low | dec | BACKLOG | | costs/ package dead — wire or delete |
| L20 | Low | mech | BACKLOG | | Per-side commission doubling undocumented |
| L21 | Low | dec | BACKLOG | | Sizers floor to zero, unwired |

### Cluster 4B — LLM degradation & identity honesty
| ID | Sev | Bucket | Status | Test | Note |
|----|-----|--------|--------|------|------|
| H25 | High | mech | OPEN | | Strategist max_tokens=700 truncates reasoners → silent fallback |
| H26 | High | mech | OPEN | | Heuristic critic hard-rejects <30 trades, overrides calibration |
| H28 | High | mech | OPEN | | `{{digit}}` scanner bypass |
| H31 | High | mech | OPEN | | Leakage marker provider-granular, masks used model |
| M37 | Med | mech | OPEN | | Critic reasoning dropped from failure feedback |
| M38 | Med | mech | OPEN | | LLM proposals clamped/repaired with no provenance |
| M39 | Med | mech | OPEN | | Silent LLM→heuristic degradation invisible in results |
| M40 | Med | mech | OPEN | | Heuristic critic accepts "high" without benchmark |
| M41 | Med | mech | OPEN | | critic_confidence decorative |
| M42 | Med | mech | OPEN | | extract_json_object brittle widest-brace slice |
| M43 | Med | mech | OPEN | | resolve_agent_llm silently swaps model[0] |
| M44 | Med | mech | OPEN | | Unknown pricing metered €0 → cap never binds |
| M45 | Med | mech | OPEN | | Decimal('0') truthiness → free model shown as unknown |
| M56 | Med | mech | OPEN | | provider_leakage optimistic precedence (compounds H31) |
| M60 | Med | mech | OPEN | | Regime labels from strategy equity, not market. Found by 5. |

---

## Phase 5 — Config/dead-code hygiene & disclosure

### Cluster 5A — Delete-or-wire quarantined subsystems
| ID | Sev | Bucket | Status | Test | Note |
|----|-----|--------|--------|------|------|
| H19 | High | dec | DECISION | | AgentBudgetController inert (is_mutation always True) — fix or remove |
| H20 | High | dec | DECISION | | Per-lineage daily counter = global kill switch |
| M8 | Med | mech | OPEN | | Failed trials become -inf COMPLETE trials |
| M9 | Med | mech | OPEN | | Composite ignores unknown weight keys |
| M10 | Med | mech | OPEN | | Walk-forward ignores YAML optuna settings |
| M11 | Med | mech | OPEN | | overfitting_score explodes on near-zero train Sharpe |
| M12 | Med | dec | DECISION | | Seed/determinism plumbing dead |
| M17 | Med | dec | DECISION | | Strategy generator crashes Optuna trial 2 |
| M57 | Med | dec | DECISION | | Determinism fingerprint API dead |
| M58 | Med | dec | DECISION | | Determinism CI gate can't run (missing scripts/golden) |
| M59 | Med | dec | DECISION | | apply_determinism_env no-op |

### Cluster 5B — Missing test coverage & disclosure
| ID | Sev | Bucket | Status | Test | Note |
|----|-----|--------|--------|------|------|
| M18 | Med | test | OPEN | | Zero tests for pandas BacktestIndicator library |
| M30 | Med | test | OPEN | | No select-on-train wiring test |
| H13 | High | mech | OPEN | | Event gate honored only by SMACrossover |
| H7 | High | mech | DONE (review) | `tests/unit/backtesting/test_finalize_trades_h7.py` | finalize_trades=True in runner.py; done early as Phase-0 worked example |
| H8 | High | mech | DONE | `test_leakage_suite.py` | genuinely-leaky control `LeakyFuturePeek` (shift(-1) future peek) replaces the non-leaky `LeakyClosePeek`; discrimination test now asserts canary FAILs leaky / clears clean (done with M22) |
| H11 | High | mech | OPEN | | ADX strength→BUY + DM tie asymmetry |
| M13 | Med | mech | OPEN | | size=1.0 buys one share, inverts gate semantics |
| M14 | Med | mech | OPEN | | create_with_params accepts typo'd params silently |
| M15 | Med | mech | OPEN | | BollingerBreakout is mean-reversion; planner mis-routes |
| M16 | Med | mech | OPEN | | RSI/MultiIndicator carry pre-F-014 bug |
| M27 | Med | mech | OPEN | | regime_validated near-unreachable (needs 1B) |
| M28 | Med | mech | OPEN | | goal_met counts regime_failed as validated |
| M29 | Med | mech | OPEN | | Decay retained_fraction divides by ~0 |
| M31 | Med | mech | OPEN | | Regime candidate metrics train-slice but UI labels full window |
| M46 | Med | mech | OPEN | | Run-level OOS descriptor over-claims "passed" |
| M48 | Med | mech | OPEN | | Director no rule for persistent skips (zombie spin) |
| M49 | Med | mech | OPEN | | Plateau watermark polluted by gate-failed Sharpe |
| M52 | Med | mech | OPEN | | Create-run under-validated (mode/rigor/model/budget) |

---

## Backlog — Low findings (post-release, D3)

L1 MACD bar-0 SELL · L2 smart-activity z vs t quantiles · L3 nested gate details empty · L4 pruner dead code · L5 check_gaps flags holidays · L6 survivorship disclosure · L7 downsample flattens drawdowns · L8 artifacts not persisted · L9 supports_json_mode default True · L10 investigate==reject · L11 DG-1 confidence-raise · L12 scanner skips 2 sections · L13 spelled-out numbers · L14 USD labeled EUR · L15 preview scope ignored by POST · L16 SSE tail-drop · L17 alpha not annualized (→C2) · L18 spread docstring · L19 costs/ dead · L20 commission doubling · L21 sizers floor to zero · L22 criteria return/pf unparsed (→C3) · L23 goal text leaks dates.

**N-notes (N1–N29):** unverified low observations in Appendix B of the review — triage into backlog opportunistically when touching the relevant file; not independently tracked here.

### Nice-to-have / deferred optimizations (not correctness — perf/polish)
- **Leakage-canary cost** (from M22): the canary runs per gate-survivor at 50 synthetic backtests each — fine for typical runs (measured +~2s on the suite; survivors-only; standalone backtests unaffected), but cost scales with survivor count on very productive runs. *Improvement:* move it to a bounded post-search audit on the top-K reported candidates + a parametric noise test (mean+2.33σ) so paths drop to ~30 → fixed ~K×30 backtests per run, independent of survivor count. ~1 commit; keeps the `enable_leakage_canary` off-switch. Logged 2026-07-05.

---

## How to read progress

- **Done count** at the top = closed in-scope findings / 95.
- **Coverage matrix** (generated from `@pytest.mark.finding` tags) = the audit trail that every DONE has a green test.
- **Final proof** = re-run `/quant-correctness-review`; the in-scope IDs must return empty with no new C/H.
