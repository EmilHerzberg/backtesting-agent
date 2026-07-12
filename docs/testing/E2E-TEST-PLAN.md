# End-to-End Test Plan (Playwright)

**Status:** APPROVED (2026-07-11). Harness = **local stack**. S9 = **multi-model** (Gemini / Claude / ChatGPT / DeepSeek)
run for cross-model comparison; keys supplied at run time; per-model € confirmed before any paid run.
**Author:** pre-OSS-release hardening.

## 0. Why E2E (what it catches that our 749 unit tests can't)

Unit + mocked-integration tests prove the *pieces* (gate math, metrics, the research loop with every
dependency mocked). They prove almost nothing about the **seams** a real user hits:

- browser → API contract (response shapes, enum casing, date formats the UI compares against),
- the **SSE event stream** + its polling fallback,
- the **polling loops** (state → RUNNING→COMPLETED, candidates growing, report becoming available),
- **auth** on every request (incl. the SSE upgrade) + 401 recovery,
- the pages/chips themselves rendering real data (the OOS / hold-out / in-market chips, the dossier waterfall),
- the **preview → launch** flow, form validation, and run controls (pause/resume/stop).

A scenario E2E driving the *real running app* is the only thing that exercises these. Estimated to catch
~80% of the wiring bugs that currently slip past unit tests.

## 1. Harness (recommended)

Upgrade the existing plain-`node` scripts (which target a hardcoded deployed IP and are partly stale — they
reference the removed `/dashboard/simulation` route) to the **`@playwright/test` runner** against a **locally
launched stack**:

- `@playwright/test` gives auto-waiting, retries, trace-on-failure, and an HTML report — table stakes for a real suite.
- Playwright's `webServer` config launches, before the tests and tears down after:
  1. **backend**: `uvicorn src.backend.api.main:app --port 8000` with `DATABASE_URL` → a throwaway temp SQLite,
     `BROKER_MODE=mock`, `SECRET_KEY=<test>` (a fresh DB per run → deterministic, no prod pollution),
  2. **frontend**: `next start` on `:3000` (against the already-built app; `NEXT_PUBLIC_API_URL=http://localhost:8000`).
- Everything runs on the developer machine / CI runner. **The rule-based scenarios cost €0.**

Why local, not the deployed server: reproducible, CI-able, tests the exact code under test, and avoids the
"running-image ≠ git-checkout" drift. The existing deployed-server smoke can stay as a separate manual check.

Config lives in `tests/e2e/playwright.config.ts`; specs in `tests/e2e/specs/*.spec.ts`; a shared `login()` /
`register()` helper + a `startRun()` helper in `tests/e2e/helpers/`.

## 2. Cost policy

| Tier | Mode | Cost | Runs on CI? |
|---|---|---|---|
| **A — default suite** | `rule_based` | **€0** (no LLM calls; deterministic; <60s/run) | yes |
| **B — one smoke** | `full_ai` (real key) | **~€0.002–0.05** for a 5-backtest run (per §4) | **no** — manual / opt-in only, gated on a real key env var |

The real-LLM smoke never runs automatically. It requires `E2E_LLM=1` + a configured provider key, so CI and
casual runs never spend. This honours the standing budget rule (confirm + estimate before any paid run).

## 3. Scenario catalog

All Tier-A ($0, `rule_based`) unless marked **[B — paid]**.

| # | Scenario | Untested seam it covers | Key assertions |
|---|---|---|---|
| S1 | **Auth**: register a fresh user → land on `/dashboard/research` | login flow, JWT on requests, AuthGuard | after submit the email input disappears; dashboard renders; a protected fetch (e.g. `/research/runs`) returns 200 |
| S2 | **Start-run flow**: `/new` → fill goal + rule_based + quick budget → **Preview** → Launch | the preview interpretation (my recent fix), POST `/runs`, navigation | preview shows the agent's interpreted symbol/strategy pool + scope; Launch navigates to `/runs/{goalId}` |
| S3 | **Full run to completion** (the big one): from S2, poll the console | state RUNNING→COMPLETED, candidates growing, events accumulating, SSE/fallback | within ~90s: status badge reaches COMPLETED; ≥1 candidate card appears; the activity stream shows events; no duplicate events |
| S4 | **Candidate dossier waterfall**: click a candidate card | 4 parallel fetches (gates/critique/oos/artifacts), the chips | dossier page renders gates table + critique + OOS badge; the OOS / hold-out / in-market chips render when present; a bad hash shows the error state, not a crash |
| S5 | **Report**: open `/report`, wait for availability | `useReport` polling termination, section render | report transitions from "not yet" to rendered sections; polling stops |
| S6 | **Form validation**: submit `/new` with an invalid config (e.g. regime window start ≥ end) | 422 handling, error render | an error message shows; no navigation; the run is not created |
| S7 | **Run controls**: on a live run, Pause → Resume | POST pause/resume, state reconciliation | after Pause the next state poll shows `paused`; after Resume, `running` again |
| S8 | **Error boundary**: force a route error | the new `error.tsx` | the recoverable panel (Retry / Back to runs) shows instead of a white screen |
| **S9** | **[B — paid] Multi-model full_ai runs**: for EACH of {gemini, claude, chatgpt/openai, deepseek} with a real key — configure the provider → start a `full_ai` run (max_runs≈5, same goal/seed) | the LLM Strategist + Critic + Reporter wiring end-to-end per provider; cross-model comparison | each run reaches COMPLETED (or fails cleanly, recorded — not a crash); the final report is LLM-written (non-empty narrative); `used_eur` > 0 and ≤ the € cap; leakage/agent_mode surfaced; **a `results/e2e-model-comparison.json` artifact** captures per-model {status, candidates, used_eur, report length, leakage, errors} for later side-by-side review |

Priority order to implement: **S1 → S2 → S3** (these prove the core demo path), then S4–S8, then **S9** (paid, gated, multi-model).

### S9 as cross-model comparison (why multi-model)
Running the *identical* full_ai scenario across four providers does double duty: it (a) proves the LLM-agent wiring
works for each provider, and (b) surfaces cross-model discrepancies — a provider that crashes the wiring, returns
malformed JSON the parser chokes on, produces an empty/garbage report, mis-reports leakage, or diverges wildly in
candidates. The comparison artifact is the input to a later manual review ("which model broke, and how"). Keys are
read from env (`E2E_GEMINI_KEY`, `E2E_ANTHROPIC_KEY`, `E2E_OPENAI_KEY`, `E2E_DEEPSEEK_KEY`); a provider with no key is
skipped. The whole scenario is gated behind `E2E_LLM=1` so it never runs unattended.

## 4. The paid scenario (S9) — cost estimate

A `full_ai` run makes: `max_runs` Strategist calls + (gate-pass-rate × `max_runs`) Critic calls + 1 Reporter call
(token sizes calibrated in `frontend/src/lib/research/cost.ts`: strat ~700p/200c, critic ~1100p/200c, report ~700p/200c).

S9 uses **REASONING models** (the AI mode's real value), tiered by cost — mid-tier reasoning for the pricey
providers (NOT the frontier Opus/GPT-5), the frontier reasoner for DeepSeek. Reasoning models emit far more
output (hidden CoT), so the per-run cost is higher than a chat model but still small; each run is hard-capped
at the request's `max_eur`, so it cannot overrun. For **max_runs = 5, exploratory** (~7.5 LLM calls/run):

| Provider | Default model (override via `E2E_<P>_MODEL`) | $/1M in·out | **Est. run cost** |
|---|---|---|---|
| DeepSeek | `deepseek-reasoner` (frontier R1) | 0.28 · 0.42 | **≈ €0.01** |
| OpenAI | `o3` (reasoning; not gpt-5) | 2 · 8 | **≈ €0.12** |
| Gemini | `gemini-3-pro` (reasoning) | 2 · 12 | **≈ €0.17** |
| Claude | `claude-sonnet-4-6` (mid-tier reasoning; not Opus @ 15/75) | 3 · 15 | **≈ €0.22** |

→ **All four + the pause/resume run ≈ €0.5–0.75 total.** Hard-capped per run at `max_eur` (=1.0). Exact figures
depend on how much each model "thinks"; I confirm before running.

**S9 needs from you:** a real API key per provider (env vars `E2E_OPENAI_KEY` / `E2E_ANTHROPIC_KEY` /
`E2E_GEMINI_KEY` / `E2E_DEEPSEEK_KEY`), and go-ahead on the ~€0.5 spend. Any model can be swapped via
`E2E_OPENAI_MODEL` etc.

## 5. CI integration

- Tier-A suite → a GitHub Actions job that builds the frontend, launches the stack, runs Playwright headless.
  Deterministic + €0, safe to gate PRs on. **(Follow-up: the workflow is not added yet — the suite runs locally.)**
- S9 → excluded from CI (guarded by `E2E_LLM`); run manually before a release or when touching the LLM-agent wiring.

---

## 6. Implementation status (2026-07-11)

**Tier-A ($0) — IMPLEMENTED & PASSING (7 tests, ~1 min):** S1 auth (login UI + wrong-password), S2 preview→launch
(exercises the preview-interpretation fix), S3 full run→completion (candidates render), S4 candidate dossier
(gates + OOS verdict), S5 report (poll-until-available), S6 form validation (regime window). Harness:
`@playwright/test` + `playwright.config.ts` webServer (uvicorn + `next start`), helpers in `tests/e2e/helpers/`.

**S7 (pause/resume) — folded into S9.** rule_based runs are inherently fast (~10s — the strategist exhausts its
finite proposal space), so they finish before a pause can be issued. Pause/resume is only meaningful for a slow
run, so it lives in S9 (full_ai, LLM-latency-bound).

**S8 (error boundary) — dropped from E2E.** The boundary can't be triggered deterministically (the app is
defensive); it's a safety net whose existence is the point. Verified by build/typecheck, not a flaky E2E.

**S9 (paid multi-model) — RUN COMPLETED 2026-07-12 (7 providers, €0.139 total).** Runs the same full_ai
scenario across openai/anthropic(claude)/gemini/deepseek/zhipu/moonshot/byteplus, records each outcome to
`results/e2e-model-comparison.json`, and asserts each provider's wiring works (a broken provider fails its own
test but all are recorded). Still gated behind `E2E_LLM=1` + per-provider key env vars.

Reasoning models per provider: openai `o3`, claude `claude-sonnet-4-6`, gemini `gemini-2.5-pro`,
deepseek `deepseek-reasoner`, zhipu `glm-5`, moonshot `kimi-k2.5-thinking`, byteplus `seed-2-0-pro-260328`.

| Provider | Model | Status | used_eur | Cands | Narrative | Leakage | Notes |
|---|---|---|---|---|---|---|---|
| openai | o3 | completed | 0.0833 | 0 | 728 | risk | real LLM run |
| gemini | gemini-2.5-pro | completed | 0.0203 | 0 | 1261 | risk | real LLM run (fix verified) |
| zhipu | glm-5 | completed | 0.0261 | 0 | 774 | unvalidated | real LLM run |
| byteplus | seed-2-0-pro-260328 | completed | 0.0066 | 0 | 784 | mechanism_only | real LLM run |
| deepseek | deepseek-reasoner | completed | 0.0026 | 0 | 752 | mechanism_only | real LLM run |
| claude | claude-sonnet-4-6 | completed* | 0.0000 | 0 | 1261 | risk | **LLM 400 (unfunded acct) → rule-based fallback** |
| moonshot | kimi-k2.5-thinking | completed* | 0.0000 | 0 | 1261 | unvalidated | **LLM 401 (bad key) → rule-based fallback** |

\* "completed" but the LLM never actually ran — see finding #5. All 7 found **0 candidates** (the honest gates
reject the sampled mean-reversion strategies — consistent across every model, reasoning or not).

### Bugs the E2E surfaced (fixed in the same change)
1. **SQLite `database is locked` (500)** — the engine used the default rollback journal, so a request that wrote
   while a background run was writing raised a 500. A user registering/acting during a run would hit it. Fixed:
   WAL + `busy_timeout` + `synchronous=NORMAL` pragmas on connect (`src/backend/db/engine.py`).
2. **`DATABASE_URL` was dead config** — `get_database_url()` hardcoded `data/trading.db` and ignored the env, so
   the deploy's `DATABASE_URL` only "worked" by coincidence (and the E2E couldn't isolate its DB). Fixed: honor
   `settings.database_url` (env/.env); default unchanged.
3. **Demo finding (not a bug):** rule_based reliably finds **0 candidates** on trend-on-trending-stocks (the honest
   gates reject them — mostly `minimum_activity` + `benchmark_relative`). A demo that surfaces a candidate should
   use **mean-reversion on stable/mean-reverting assets** (e.g. staples KO/PG/JNJ/XOM) — the calibrated E2E config.
4. **Provider dead until restart** — `add_provider`/`toggle_provider` wrote the DB row but never populated the
   runtime `_INSTANCES` registry, so a newly-configured provider 404'd on `/chat` until the next server restart.
   Fixed: register/deregister the live instance on add/toggle/delete (`src/backend/api/routers/ai.py`).
5. **Gemini silent model-substitution** — a full_ai run requesting a model absent from the provider catalog was
   silently swapped to `models[0]`; for gemini that was the Vertex-only `gemini-3-pro`, which 404s on an
   AI-Studio key → silent rule-based fallback, `used_eur=0`. Fixed: `gemini-2.5-pro` is now the default catalog
   entry (`src/backend/ai/providers/gemini.py`).

### Open finding — silent LLM degradation (model-honesty gap, NOT yet fixed)
When a full_ai run's Strategist/Reporter LLM calls fail (claude 400 unfunded, moonshot 401 bad key), the run
**silently falls back to the rule-based strategist + templated narratives but still reports `status=completed`
and `agent_mode=full_ai`**. The only tell is `used_eur=0`. A user with a broken/unfunded key would believe the
AI ran when it never did. This violates the project's model-honesty principle. Recommended fix: track LLM-call
failures per run and surface a `degraded`/`llm_failures` flag in the run state + a report banner ("AI unavailable
— N calls failed (auth/credit); results are rule-based"). Scoped as a follow-up.

## 7. How to run

```bash
# one-time
cd tests/e2e && npm ci && npx playwright install chromium

# $0 rule_based suite (launches the stack automatically via playwright.config webServer)
npm test                          # or: npx playwright test

# paid multi-model comparison (provide your own keys; a few cents total)
E2E_LLM=1 \
  E2E_OPENAI_KEY=sk-... E2E_ANTHROPIC_KEY=sk-ant-... E2E_GEMINI_KEY=... E2E_DEEPSEEK_KEY=... \
  npx playwright test specs/s9-multimodel-llm.spec.ts
```

The backend uvicorn dep must be installed in the venv (`pip install -e ".[dev]"` or `pip install "uvicorn[standard]"`).
