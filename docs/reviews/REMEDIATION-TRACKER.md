# Remediation Tracker — backtesting-agent

**The single source of truth for "are we done?".** One row per finding from [QUANT-REVIEW-2026-07-03.md](./QUANT-REVIEW-2026-07-03.md). Process in [REMEDIATION-PLAN.md](./REMEDIATION-PLAN.md).

**Status:** `OPEN` · `SPEC` (needs a written spec first) · `DECISION` (needs a wire/delete or product call) · `IN-PROGRESS` · `DONE` (fix merged + tagged test green) · `QUARANTINED` (disabled + parked, scheduled for deletion) · `BACKLOG` (Low, post-release).
**Bucket:** `mech` (mechanical fix, reference formula) · `dec` (decision) · `spec` (technical spec) · `test` (test/coverage) · `infra` (harness/CI).
**Test:** path of the ID-tagged regression test that proves closure (filled as we go).

**Scoreboard:** in-scope for release = **95** (3 C + 32 H + 60 M). Backlog = 23 L (+ 29 N-notes). Done: **70 / 95** (1A-1E + 2A-2C + 3A-3B + 4A + 4B as before · 5A: H19/H20/M8/M9/M10/M11/M12/M17/M57/M58/M59). **✅ All 3 criticals fixed. Phases 1-4 MERGED to main. Phase 5 5A (delete-or-wire quarantined subsystems) DONE. Remaining = 5B (strategy/indicator correctness + test coverage: H11/H13/M13-M18/M27/M28/M60 …) + Low backlog.**

**Phase 4 COMPLETE:** 4A (unified cost model, H29/M55) + 4B (H25/H26/H28/H31 + M37–M45 mediums) all DONE. ~~⚠ H31 needs a one-line DB migration~~ **RESOLVED (P4-review H31-1): `model_id` added to `bootstrap._MIGRATIONS` → auto-migrates at next boot; no manual ALTER needed.**

**Phase 4 review (2026-07-07):** 7-dimension adversarial audit (26 agents) → **15 confirmed, 2 refuted, 0 net-refuted**; the 4A cost-model dimension came back CLEAN. Recurring theme (as in P2/P3, 5B): *fix correct in-component but off the live path* + test-gating gaps. Fixes on branch `quant-review/phase4-review-fixes` (folded into the rows below): **H31-1** the missing auto-migration (deploy-breaker: preserved-DB `research_runs` reads 500'd); **F1/H26** thin-sample no longer terminally killed; **F2** critic reasoning names the real critical cause (was `weaknesses[0]`, poisoning the M37 note); **F3** critic None/NaN-safe; **M56** unknown-model leakage fallback not optimistically `mechanism_only`; **M44** `cost_known` surfaced on the `/state` API; **H28-residual** digit-free carve-out; **M45/M38-2/H29** test-gating. Deferred (documented in the P4-review cluster): M38-1 (repaired[] dead metadata), H31-DEGRADE + TI-4B-H25 (degradation/fallback ratio not surfaced in a run artifact — server-log only), L10 (investigate==reject policy), frontend cost_known render + persist.

**Phase 2+3 review (2026-07-06, [PHASE2-3-REVIEW-2026-07-06.md](./PHASE2-3-REVIEW-2026-07-06.md)):** 10-dimension multi-agent audit → **20 confirmed, 0 critical, 0 high** (the P2/P3 stat/data core holds). Fixes applied (branch `quant-review/phase2-3-review-fixes`): M32 on the research path (`_default_fetch` end-inclusive); live `/candidates` PENDING → honest marker; H24 survivorship surfaced in robustness (candidate.weaknesses both modes); M21 `errored_gate` plumbed through the gatekeeper facade + loop; Šidák docstring corrected (online scheme ≈17% FWER at 20 peeks, NOT 5%); OOS report counts deduped per hash (H16); requested-OOS-that-can't-init now RAISES (no silent in-sample); H8 test's false "clears clean" claim removed; + M22/M23 live-wiring gating tests. H18's Šidák correction is **within-run only** (per-run in-memory peek count); cross-run hold-out mining remains a backlog item.

**PROVIDER LAYER NOW WIRED (2026-07-06):** the research loop's `run.py:_default_fetch` routes through the marketdata PROVIDER layer (`YahooProvider` by default, `settings.data_provider` to switch) instead of raw `yf.Ticker().history()` — so M32 (end-inclusive) + the adjustment conventions are LIVE on the research path (the CLI already used `create_provider("yahoo")`). Storage concern addressed by a 3-layer design: (1) provider fetch = stateless (no DB growth); (2) an always-on **in-memory per-run cache** on `_SimpleDataAgent` collapses the ~100+ redundant same-(asset,window) fetches per run into one (speed, no persistence); (3) the **persistent DB cache is opt-in** (`run_research(use_price_cache=…)`, default OFF) — reserved for paid providers / intraday where it conserves API quota; yfinance-daily stays persistence-free so the server DB doesn't grow (daily is ~MB-scale anyway; the blow-up risk is intraday, i.e. exactly the paid-provider scenario). Still backlog: routing through `AggregatedDataProvider` for multi-provider priority (H22 keyed-provider live use), test-gating for loop-peek/M19-PathB/M35-endpoint, cache replace-window + non-atomic edge cases.

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
| H29 | High | spec | DONE | `test_cost_model_4a.py` | D8: shared `effective_commission_pct()` (commission+half-spread+slippage) used by BOTH the CLI and the research executor; cost params on run_research/StartRunRequest (default ≈14.5 bps/side, not 10) |
| M55 | Med | mech | DONE | `test_cost_model_4a.py` | closed with H29 (same root — executor now on the realistic cost model, exposed on the run request) |
| L18 | Low | dec | BACKLOG | | Spread half/full docstring ambiguity |
| L19 | Low | dec | BACKLOG | | costs/ package dead — wire or delete |
| L20 | Low | mech | BACKLOG | | Per-side commission doubling undocumented |
| L21 | Low | dec | BACKLOG | | Sizers floor to zero, unwired |

### Cluster 4B — LLM degradation & identity honesty
| ID | Sev | Bucket | Status | Test | Note |
|----|-----|--------|--------|------|------|
| H25 | High | mech | DONE | `test_llm_honesty_4b.py` | reasoners get max_tokens=4000 (free for non-reasoners; billing is on actual tokens); billed-but-unparseable counted (`llm_calls`/`fallback_after_bill`) so degradation is visible |
| H26 | High | mech | DONE | `test_llm_honesty_4b.py`, `test_critic.py` | heuristic critic no longer CRITICAL-rejects on trade count (the gate already vetted it) — thin sample is a non-critical caveat. P4-rev (F1): the thin count was still a *weakness* → recommendation "investigate", which the robustness loop treats as a TERMINAL kill, so the *median* gate-passing candidate (~12 trades) was still killed. Now a verdict-neutral CAVEAT: a clean candidate is ACCEPTED (caveat surfaced, confidence capped). The broader "should a non-critical *concern* ever kill in robustness" (fully decoupling investigate from reject, L10) is an owner policy decision — H26's harm is closed. |
| H28 | High | mech | DONE | `test_reporter.py` | scanner carve-out restricted to binding identifiers — `{{1.2}}` no longer ships digits past the digit-free guarantee. P4-rev (residual): carve-out tightened to DIGIT-FREE `\{\{[A-Za-z_][A-Za-z_.]*\}\}` so identifier-shaped-but-digit-bearing tokens (`{{x2}}`, `{{year2020}}`, `{{sharpe_252}}`) are scanned too (real bindings are digit-free — verified). |
| H31 | High | mech | DONE | `test_llm_honesty_4b.py`, `test_bootstrap_migrations_h31.py` | per-MODEL leakage badge: `state.model_id` set+persisted, `_run_leakage(provider,model)` uses `model_leakage()`. P4-rev (H31-1): **✅ the manual ALTER is NO LONGER needed** — `model_id` was missing from `bootstrap._MIGRATIONS` (its sibling `provider_type` was there), so on a preserved prod DB every `research_runs` read 500'd and persist_snapshot silently no-op'd; the column is now in the idempotent auto-migrator (adds at next boot). Residual (H31-TEST): the persistence round-trip of model_id is still only partially test-covered. |
| M37 | Med | mech | DONE | `test_llm_honesty_4b.py` | strategist `_render` includes a bounded `critic_note` excerpt so critic kills carry substance. P4-rev (F2): the critic's reject/investigate *reasoning* used to quote `weaknesses[0]` (the thin-trade caveat, appended first), mislabeling the real critical cause and poisoning this critic_note — now quotes the actual critical weakness / the real concern. |
| M38 | Med | mech | DONE (partial) | `test_strategist_llm.py` | `_build` records `repaired[]` provenance on the spec; falls back when >half the params were system-invented. P4-rev (M38-2): added the gating tests for the >half fallback + the ≤half provenance record. RESIDUAL (M38-1, low): `repaired[]` is dead metadata — never read/persisted/surfaced (the one wholesale spec hand-off, to the critic, allowlists it out), so the ≤half case still runs clamped/invented params under the LLM rationale with no *visible* provenance. Surfacing it = follow-up. |
| M39 | Med | mech | DONE | `test_llm_honesty_4b.py` | critiques stamped `source=llm|heuristic` (+ strategist `llm_calls`/`fallback_after_bill` from H25) so degradation is visible |
| M40 | Med | mech | DONE | `test_llm_honesty_4b.py` | heuristic critic: non-positive return = critical reject; missing benchmark blocks accept; underperformance checked regardless of sign |
| M41 | Med | mech | DONE | (prompt) | dropped the unsatisfiable "walk-forward validated" high-confidence clause; confidence documented ADVISORY |
| M42 | Med | mech | DONE | `test_llm_infra_4b.py` | `extract_json_object` raw_decodes from each `{` (strict=False, fence-strip) — recovers billed output the slice discarded |
| M43 | Med | mech | DONE | (code) | `resolve_agent_llm` logs the model substitution (mismatched id has different pricing/leakage); effective model recorded |
| M44 | Med | mech | DONE | `test_llm_infra_4b.py` | pricing carried as `float\|None`; ledger `cost_known=False` + no fabricated €0 for unpriced models. P4-rev: the flag was computed but UNWIRED (HUD showed €0.0000 for an unpriced model, indistinguishable from free) — now propagated onto `Budget.cost_known` and surfaced on the `/state` API (`ResearchStateResponse.cost_known`). Follow-ups: frontend renders "cost unknown (N tokens)"; persist cost_known across the DB round-trip. |
| M45 | Med | mech | DONE | `test_models_pricing_m45.py` | `is not None` pricing check so `Decimal("0")` free models serve 0 (not null/unknown). P4-rev: added the missing round-trip contract test through the real `list_models` mapping (0→0.0, None→null); evidence was `(code)`. |
| M56 | Med | mech | DONE | `test_llm_honesty_4b.py` | P4-rev: the run-level leakage fallback (`_run_leakage` when model_id empty) no longer optimistically upgrades an unknown-model run to `mechanism_only` on the strength of a validated provider sibling — it surfaces a known provider-level `risk` (conservative) but downgrades an optimistic `mechanism_only` to `unvalidated`. Per-model badging unchanged. |
| M60 | Med | mech | DONE | `test_strategy_5b.py` | `_compute_regime_analysis` labels bull/bear/sideways from the ASSET (market) close-to-close returns; strategy per-window return/Sharpe reported separately. Found by 5. 5B-rev (TI-5): call-site no longer falls back to the strategy equity when ohlcv_df is missing (→ market_returns=None → no labels, not a re-mislabel); helper marks the strategy fields unavailable on a length mismatch instead of silently substituting the market's numbers. |

### Cluster 4B-review — adversarial-review remediation (findings on the Phase-4 work itself)
7-dimension audit (2026-07-07, 26 agents) → 15 confirmed. Fixed items are folded into the 4A/4B rows
above (H31-1→H31, F1→H26, F2→M37, F3→M40, M56, M44, H28-residual→H28, M45, M38-2→M38, H29→cost test).
Standalone / deferred items:
| ID | Sev | Bucket | Status | Test | Note |
|----|-----|--------|--------|------|------|
| H31-1 | High | mech | DONE | `test_bootstrap_migrations_h31.py` | `research_runs.model_id` added to `bootstrap._MIGRATIONS` — was omitted, so a preserved prod DB 500'd on every `select(ResearchRunDB)` (GET /runs, /stats, load_report) and persist_snapshot silently no-op'd. Auto-migrates at next boot; manual ALTER obsolete. |
| M38-1 | Low | mech | OPEN (follow-up) | | `spec["repaired"]` provenance is dead metadata — never read/persisted/surfaced (the one wholesale spec hand-off, to the critic, allowlists it out). Thread it onto the persisted Candidate + surface next to the LLM rationale, else the ≤half-invented case runs clamped/invented params with no visible provenance. |
| H31-DEGRADE | Low | honesty | OPEN (follow-up) | | The leakage badge reflects the configured `model_id` even when EVERY LLM call degraded to the heuristic (fully rule-based drove selection). Direction of error is conservative/neutral (a degraded risk model still shows risk); provenance over-attribution only. Fix: blank model_id for leakage when the run fully degraded. |
| TI-4B-H25 | Low | honesty | OPEN (follow-up) | | H25's `fallback_after_bill`/`llm_calls` degradation counters are read by NO run artifact (only a `logger.warning`); `state.agent_mode` stays the resolved "full_ai" even if 100% of billed proposals fell back. The substantive H25 fix (reasoner max_tokens=4000) IS live + gated; only the operator-facing fallback-ratio visibility is missing. Surface it on the state/report. |
| L10 | Low | dec | OPEN (policy) | | Whether a non-critical *concern* (not just the thin-trade caveat) should ever terminally kill in robustness — i.e. fully decoupling `investigate` from `reject` in loop.py. H26's specific harm is closed (F1); this broader policy is an owner decision. |

---

## Phase 5 — Config/dead-code hygiene & disclosure

### Cluster 5A — Delete-or-wire quarantined subsystems
| ID | Sev | Bucket | Status | Test | Note |
|----|-----|--------|--------|------|------|
| H19 | High | dec | DONE (test gap) | `test_budgets_5a.py` (controller only) | FIXED: is_mutation computed before the prev-template update; caps keyed on the stable lineage ROOT (not per-call uuid), so the anti-brute-force caps bind. 5B-rev (TI-2): the cited test exercises only `AgentBudgetController` (never the bug) and does NOT gate the inline loop.py wiring — see TI-2 in the 5B-review cluster. |
| H20 | High | dec | DONE | `test_budgets_5a.py` | per-lineage counter resets on family switch → no longer a global ~100/day kill switch; still binds within a family |
| M8 | Med | mech | DONE | `test_optimizer_5a.py` | failed trials are PRUNED (not COMPLETE -inf); non-finite objective pruned; all-failed study raises OptimizationError |
| M9 | Med | mech | DONE | `test_optimizer_5a.py` | unknown composite weight keys rejected up front (was silently weighted nothing) |
| M10 | Med | mech | DONE | `test_event_gate_wiring_5b.py` | WalkForwardConfig forwards objective_metric/composite_weights/seed to per-window optimize (was default-only). 5B-rev (M10-CLI): the CLI walk-forward branch now ALSO forwards `config.optuna.objective`/`composite_weights` into WalkForwardConfig (they were dropped there, so a YAML objective was still ignored in WF mode); determinism-seed reaches WF via env auto-inject. |
| M11 | Med | mech | DONE | `test_optimizer_5a.py` | overfitting ratio only above a 0.2 train-Sharpe floor (else NaN, excluded); aggregate is the MEDIAN. 5B-rev: WalkForwardResult/Window docstrings corrected (field is a MEDIAN of the measurable windows, not a "mean across windows"). |
| M12 | Med | dec | DONE | `test_optimizer_5a.py` | determinism mode now injects a fixed sampler seed (was TPESampler(seed=None)); seeded runs reproducible. 5B-rev (TI-1): added a gating test for the ACTUAL fix — `BACKTEST_DETERMINISM_MODE` + seed=None → reproducible (the prior explicit-seed test also passed pre-fix, so it did not gate the injection). |
| M17 | Med | dec | DONE | `test_optimizer_5a.py` | generate_strategy suggests from a FIXED indicator list + prunes conflicts post-hoc (was dynamic categorical → crashed trial 2); multi-indicator composition usable |
| M57 | Med | dec | DONE (honest-doc) | (docstring) | fingerprint API docstring downgraded from asserted guarantee to NOT-YET-ENFORCED (not wired into run_backtest/results store) |
| M58 | Med | dec | DONE (honest-doc) | (docstring) | documented that the golden-hash CI gate SKIPS (scripts/golden absent) — no longer implies enforcement. Wiring the golden gate = backlog |
| M59 | Med | dec | DONE (honest-doc) | (docstring) | apply_determinism_env docstring states the runtime-no-op limitation (PYTHONHASHSEED/BLAS caps too late; setdefault); real fix = launcher/threadpoolctl (backlog) |

### Cluster 5B — Missing test coverage & disclosure
| ID | Sev | Bucket | Status | Test | Note |
|----|-----|--------|--------|------|------|
| M18 | Med | test | DONE | `test_indicator_library_m18.py` | reference-value + signal-semantics tests for the pandas indicator lib (RSI/ADX); gates M16/H11 |
| M30 | Med | test | OPEN | | No select-on-train wiring test |
| H13 | High | mech | DONE | `test_strategy_5b.py`, `test_event_gate_wiring_5b.py` | added `StrategyBase._gated_buy()`; ALL templates (+ generator + base signal-handler) enter through it (strategy side). 5B-rev (F1) — completed the SECOND half the original H13 named: the gate config is now THREADED from the CLI through OptimizationConfig + WalkForwardConfig into the runner (symbol + event_gate + once-preloaded gates_df), so a YAML `event_gate.enabled` is honoured in real optimize/walk-forward runs (was inert in every entrypoint). Behavioral non-SMA gate tests added (F2/TI-4) + source-check now covers all 7 families incl. DynamicStrategy/Sentiment via the CALL token. NOTE: the AI research-loop executor path is NOT yet gate-wired (runs inside an async loop; needs async gate preload) — tracked as a 5B-rev follow-up below. |
| H7 | High | mech | DONE (review) | `tests/unit/backtesting/test_finalize_trades_h7.py` | finalize_trades=True in runner.py; done early as Phase-0 worked example |
| H8 | High | mech | DONE | `test_leakage_suite.py` | genuinely-leaky control `LeakyFuturePeek` (shift(-1) future peek) replaces the non-leaky `LeakyClosePeek`; discrimination test now asserts canary FAILs leaky / clears clean (done with M22) |
| H11 | High | mech | DONE | `test_indicator_library_m18.py` | ADX signal now DIRECTIONAL (+DI vs −DI; SELL a strong downtrend, was BUY on every bar); DM filtered from the RAW series (tie→both zero) |
| M13 | Med | mech | DONE | `test_strategy_5b.py` | `_gated_buy` maps a full-equity intent (>=1.0) → buy-max and a REDUCE fraction → fraction-of-equity; fixed the false size==1 comment/docstring |
| M14 | Med | mech | DONE | `test_strategy_5b.py` | create_with_params rejects unknown/typo'd param names (was inert attr → ran defaults under recorded params). 5B-rev (M14-1): added the gating test (reject typo, accept valid+empty) + a regression guard that every registered template's own default param-set is accepted; evidence was `(suite)` = untested. |
| M15 | Med | mech | DONE (preview-only) | `test_strategy_5b.py` | planner keyword "breakout" → trend_following (was mean_reversion); BollingerBreakout stays under mean_reversion. 5B-rev (M15-PROD-SCOPE): scope correction — `parse_goal_scope` feeds ONLY `GET /runs/preview`; the actual run path (POST /runs → run_research) selects by `strategy_families` (defaulting to all three), so the "breakout silently runs mean-reversion" harm was never realized in a live run. Fix is correct for the preview label; live strategy selection is governed by L15 (preview scope ignored by POST). |
| M16 | Med | mech | DONE | `test_indicator_library_m18.py` | RSI zero-loss → 100 (overbought), not NaN→HOLD; a perfect uptrend now registers overbought. 5B-rev (PATH-2/TI-3): the fix originally landed only on the generator-only library `RSIIndicator`; the LIVE `MultiIndicator._compute_rsi` copy still had the bug — now fixed (+ min_periods) and directly tested. EDGE-1: guard tightened to `avg_loss==0 & avg_gain>0` so a FLAT/zero-momentum series stays NaN→HOLD instead of RSI 100→spurious SELL. |
| M27 | Med | mech | OPEN | | regime_validated near-unreachable (needs 1B) |
| M28 | Med | mech | DONE (partial) | `test_strategy_5b.py` | regime_failed candidates excluded from _criteria_satisfying → goal_met/validated_count no longer count failed regime ideas. 5B-rev: ALSO fixed the secondary bug — a regime_failed idea no longer resets `consecutive_failures` (it increments it), so R4 (max_consecutive_failures) can fire on a stream of failed ideas. RESIDUAL (by design, flagged for the regime-workstream owner): `unvalidated` regime ideas STILL count toward goal_met/COMPLETED — regime mode is idea-surfacing, so tightening goal_met to `regime_validated`-only is a semantics decision, not applied unilaterally. See H19/M27. |
| M29 | Med | mech | OPEN | | Decay retained_fraction divides by ~0 |
| M31 | Med | mech | OPEN | | Regime candidate metrics train-slice but UI labels full window |
| M46 | Med | mech | OPEN | | Run-level OOS descriptor over-claims "passed" |
| M48 | Med | mech | OPEN | | Director no rule for persistent skips (zombie spin) |
| M49 | Med | mech | OPEN | | Plateau watermark polluted by gate-failed Sharpe |
| M52 | Med | mech | OPEN | | Create-run under-validated (mode/rigor/model/budget) |

### Cluster 5B-review — adversarial-review remediation (findings on the 5B work itself)
A 6-dimension adversarial workflow reviewed the 5B fixes and confirmed 19 issues (0 refuted→kept). The
dominant theme repeated Phase-2/3: *the fix was correct in its component but did not reach the live path*,
plus test-gating gaps. Fixed items are folded into the rows above (F1→H13, M10-CLI→M10, PATH-2/EDGE-1→M16,
TI-1→M12, M14-1→M14, TI-5→M60, M11-docstring→M11, M28-secondary→M28). New/standalone items:
| ID | Sev | Bucket | Status | Test | Note |
|----|-----|--------|--------|------|------|
| F3 | Low | mech | DONE | `test_strategy_5b.py` | `route_signal` SHORT entry was a raw `self.sell()` (ungated); added a symmetric `_gated_sell()` so short entries honour the gate too (latent — no shipped template opens shorts). |
| PATH-1 | High | dec | DONE (honest-doc) | `test_indicator_library_m18.py` | The pandas indicator LIBRARY (`RSIIndicator`/`ADXIndicator`, incl. the H11/library-M16 fixes) is reachable ONLY via `generate_strategy`→`DynamicStrategy`, which has NO production caller (`use_generator` is defined in schema but read nowhere in `src/`). The H11/M16 library fixes are correct but currently affect only tests + the (unwired) generator. The LIVE RSI copy is fixed separately (M16/PATH-2). Follow-up: wire `use_generator` into `run_pipeline` OR mark the generator explicitly test-only + delete `use_generator`. |
| F1-exec | Med | dec | OPEN (follow-up) | | Event-gate wiring covers the CLI optimize/walk-forward paths (F1). The AI research-loop `ResearchExecutor` path is NOT gate-wired: it builds `BacktestConfig` without `event_gate`, and it runs inside an async loop where the sync `_preload_gates_blocking` can't load gates. Needs an async gate preload + a request-level gate config before the research loop can honour the gate. |
| TI-2 | Med | test | OPEN (documented) | | H19's real fix lives INLINE in `loop.py` (is_mutation computed before the prev-template update; caps keyed on the lineage ROOT). `test_budgets_5a.py` only exercises `AgentBudgetController` (which was never the bug), so it passes on pre-fix budgets and does NOT gate the loop wiring. A genuine gating test would need to drive the fully-mocked loop; deferred rather than add a brittle test. The anti-brute-force cap could silently regress. |
| M28b | Med | dec | OPEN (owner decision) | | Regime `goal_met` still counts `unvalidated` ideas (see M28 residual). Whether to require `regime_validated` is a regime-workstream semantics call. |

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
