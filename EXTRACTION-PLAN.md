# Extraction plan

Code is being extracted from a private monorepo by **copying** (not refactoring in
place) so the source platform stays untouched. The skeleton in this repo will be
filled phase by phase from the file list below.

## Phase 1 — Python core (no UI)

Copy + import-rewrite. Module names map `src.backend.backtesting.*` → `backtesting_agent.*`
and `src.backend.marketdata.*` → `backtesting_agent.marketdata.*`.

| Target | Source | Notes |
|---|---|---|
| `shared/types.py` | `src/backend/shared/types.py` | slim to `BarInterval` only |
| `shared/config.py` | `src/backend/shared/config.py` | slim `Settings` — API keys + determinism flag |
| `db/base.py` | NEW | own SQLAlchemy `Base` + `PriceCacheDB` (no shared kernel) |
| `marketdata/` | `src/backend/marketdata/` (all 9 files) | as-is, imports rewritten |
| `engine/` | `src/backend/backtesting/engine/` (runner, optimizer, walk_forward, parallel, metrics, exceptions) | as-is |
| `indicators/` | `src/backend/backtesting/indicators/` (registry, base, trend, momentum, volatility, volume) | as-is |
| `strategies/` | `src/backend/backtesting/strategies/` minus `sentiment_aware_rebound.py` | drop the experimental one for v1 |
| `costs/` | `src/backend/backtesting/costs/` (commission, spread, slippage, sizing, model) | as-is |
| `results/` | `src/backend/backtesting/results/` (store, query, models, regime, visualize) | repoint `Base` to the new `db/base.py` |
| `config/` | `src/backend/backtesting/config/` (schema, presets, logging, examples/) | as-is |
| `analysis/cost_sensitivity.py` | `src/backend/backtesting/analysis/cost_sensitivity.py` | `monitoring.py` is NOT copied — it's live-trading observability, not backtesting |
| `determinism.py` | `src/backend/backtesting/determinism.py` | as-is |
| `quality_check.py` | `src/backend/backtesting/quality_check.py` | repoint `sync_engine` to a local engine |
| `run_backtest.py` | `run_backtest.py` | CLI entry |
| `cli.py` | `src/backend/backtesting/cli.py` | as-is |

**Explicitly NOT copied:**
- `event_gate.py` and the `EventGateConfig` hook in `StrategyBase` / `runner.py` —
  removed entirely for v1 (lives in a different research workstream)
- `analysis/monitoring.py` — pulls `TradeDB`, `AgentConfigDB` (live trading)
- anything under `event_context/`, `broker/`, `agents/` (live-trading agents),
  `auth/`, `risk_gate/`

## Phase 1b — AI agent layer (what makes it an *agent*)

The project is "backtesting-agent" — the AI loop on top of the engine is in
scope, not just the quant kernel. Copy from `src/backend/ai/` into
`backtesting_agent/agent/` (imports rewritten like Phase 1):

| Target | Source | Notes |
|---|---|---|
| `agent/analyst.py` | `ai/agents/analyst.py` | ReAct analyst agent: analyze / compare / suggest_next, tool-calling loop |
| `agent/schemas.py` | `ai/agents/schemas.py` | structured analysis response models |
| `agent/tools/` | `ai/tools/definitions.py` + `executor.py` | tool dispatch (audit_backtest, get_trades, regime, param-sensitivity) |
| `agent/batch.py` | `ai/batch_orchestration.py` | batch runner with status tracking |
| `agent/goals/` | `ai/goals/orchestrator.py` + `planner.py` | autonomous loop: plan batch → run → analyze → iterate (plateau/budget guards) |
| `agent/analysis/` | `ai/analysis/waterfall.py` + `clustering.py` | post-batch waterfall reports (heuristic, LLM-polish hook) |
| `agent/providers/` | `ai/interface.py`, `ai/providers/base.py` + all providers, `ai/registry.py`, `ai/models.py` | OpenAI-compatible providers: DeepSeek, Qwen, Zhipu/GLM, Moonshot, MiniMax |
| `db/agent_models.py` | `ai/db_models.py` (slimmed) | `AIProviderDB`, `AIModelDB`, `PromptTemplateDB`, `AutoResearchGoalDB`, `ExperimentQueueDB`, `BatchJobDB`, `WaterfallReportDB` |
| optional | `ai/research/engine.py` | indicator+LLM stock research reports |
| optional | `ai/status/tracker.py`, `ai/rationale/service.py` | UI progress + reasoning audit trail |

Extra dependency: `openai>=1.0` (AsyncOpenAI client — all providers are
OpenAI-compatible).

**Key-management decision:** upstream stores LLM keys in the `ai_providers`
DB table (created per-user via the UI). The standalone has no auth/users, so
add a small env-seeding step at startup: read `DEEPSEEK_API_KEY` /
`OPENAI_API_KEY` / `ZAI_API_KEY` / `MOONSHOT_API_KEY` / `DASHSCOPE_API_KEY`
from `.env` and upsert matching `ai_providers` rows. Engine-only usage stays
possible: with no key set, the agent endpoints return "no provider
configured" while plain backtesting keeps working.

## Phase 2 — Verify it runs standalone

- `pip install -e ".[dev]"` succeeds
- `python run_backtest.py --preset quick` against a frozen snapshot returns a
  deterministic result (same hash on rerun)
- Copied tests pass

## Phase 3 — Thin FastAPI + Frontend slice

- `api/main.py` — job orchestration (from `api/routers/backtesting.py`):
  `/strategies`, `/run`, `/status/{id}`, `/history`, `/symbol-lists`,
  `/batch` (POST + GET list), `/batch/{job_id}`
- **plus the dashboard/visualization endpoints** (from `api/routers/dashboard.py`) —
  the copied frontend pages are non-functional without these:
  `/dashboard/ranking`, `/dashboard/strategy-detail/{trial_id}`,
  `/dashboard/equity-compare`, `/dashboard/param-heatmap`,
  `/dashboard/asset-strategy-matrix`, `/dashboard/period-compare`,
  `/dashboard/regime-performance`, `/dashboard/regimes`
- **plus the agent endpoints** (from `api/routers/ai_analyst.py` + goal/research
  routers): analyst analyze/compare/chat, auto-research goal CRUD + tick,
  provider config endpoints (env-seeded, see Phase 1b)
- Frontend pages copied from monorepo, JWT stripped:
  - `page`, `detail/[id]`, `equity`, `heatmap`, `matrix`, `periods`, `regime`,
    `sessions`, `sessions/[id]`, `waterfall/[batchId]`, `layout`
  - **plus** `analyst/` and `auto-research/` (the agent UI — in scope per the
    Phase 1b decision)
- **Not** copied: `deployments/` (live-trading only)

## Phase 4 — Showcase polish

- README narrative + architecture diagram + GIF/screenshot
- LinkedIn post draft
- Decide on `strategies/generator.py` (Optuna-driven dynamic strategy) — keep or drop

## Known deferrals (called out for honesty in the README)

- Job orchestration is in-memory in the source — fine for a demo, needs a real queue
  (Celery/RQ) for production
- Three overlapping data layers exist upstream; only the cleanest one (`marketdata/`)
  is extracted
