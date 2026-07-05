# Backtesting Agent — Testing Concept (user / use-case / scenario centered)

**Status:** draft v1 · **Scope:** the standalone `backtesting-agent` system as deployed at
`backtesting-agent.prismgate.net` (auth + API-key vault, onboarding/key-gating, the autonomous
research loop, live console, results/dossier/graveyard/report, leakage surfacing).
**Audience:** whoever writes and maintains the test suite (and reviews releases).
**Verification:** the factual claims below (thresholds, endpoints, leakage classes, isolation) were
code-checked against the repo at review time; cross-user isolation was confirmed *already enforced*
(`router._owned_run` → 404 on mismatch + `user_id`-scoped persistence on every endpoint).

This document is deliberately **scenario-first**: it starts from *who the user is* and *what they are
trying to do*, then derives the concrete checks. Implementation-level unit tests exist and are valuable,
but they are the *bottom* of this pyramid, not the organizing principle.

---

## 0. How to read this

- **Personas** (§2) — the people the system serves (plus one adversary and one operator).
- **Use cases** (§4) — grouped user journeys. Each has a **scenario table**: `Given → When → Then`,
  a **priority** (P0 critical … P3 nice-to-have), and a **test layer** (where the check lives).
- **Cross-cutting invariants** (§5) — properties that must hold across *all* scenarios (security,
  data-integrity, **honesty**, cost, resilience, i18n).
- **Test layers & tooling** (§6), **test-data/environment strategy** (§7), **release gates** (§8),
  **traceability & phasing** (§9).

**Test-layer legend**

| Tag | Layer | Tool |
|-----|-------|------|
| **E2E** | Browser end-to-end, real UI + real API + DB | Playwright (see `dev/qa/regime_liveverify.py` as the seed harness) |
| **API** | HTTP against the FastAPI app, no browser | `httpx`/`pytest`, in-container preferred |
| **UNIT** | Pure function / module | `pytest` |
| **MAN** | Manual / exploratory (hard to automate cheaply, e.g. real-LLM behavior) | checklist |

---

## 1. Testing philosophy

1. **Scenario-first, risk-weighted.** A scenario earns automation by *user impact × likelihood*, not by
   how easy it is to write. Auth, money (LLM cost), and **honesty of results** are the three highest-risk
   axes and get the deepest coverage.
2. **The system's whole value is not lying.** This is a research tool whose selling point is that it
   refuses to overclaim (model-honesty principle). Therefore a first-class category of tests asserts the
   system **degrades to "we don't know" rather than a fake number** — the numeric-claim scan, the
   `UNVALIDATED` amber styling, the 3-state leakage marker, and DSR "provisional" flags are all *tested
   invariants*, not cosmetics. See §5.3.
3. **Test in the artifact you ship, not the tree you edit.** The container is built from `git` — a
   git-ignored source file or an un-`COPY`-ed config dir is invisible to a local `pytest`. Two such bugs
   already shipped (see §8.1). Release gates run the suite **inside the built image**.
4. **Cheap by default, real on demand.** The user actively watches LLM spend. The automated suite must
   run at **€0** — LLM providers are mocked and market data is a frozen snapshot. Real-provider runs are a
   separate, opt-in, budgeted **MAN** tier (§7).
5. **Deterministic where it claims to be.** Rule-based runs with a fixed `seed` must be reproducible;
   this is itself a test (§4.RUN).

---

## 2. Personas

| # | Persona | Who | Primary goals | What they must never experience |
|---|---------|-----|---------------|--------------------------------|
| **P1** | **Nadia — first-time, keyless** | Signs up, no API key yet | Understand the tool, run *something* for free | A dead-end ("can't do anything without a key"); silent failure |
| **P2** | **Ravi — returning researcher** | Has keys, runs regularly | Configure & launch runs, read results, manage keys | Losing runs on restart; mis-reading an UNVALIDATED result as robust |
| **P3** | **Bea — budget-conscious** | Cost-sensitive, cheapest-model habit | Know the cost *before* launch; hard cap on spend | A run that blows past the € budget; a hidden charge |
| **P4** | **Sven — skeptic/rigor** | Wants honest, non-overfit results | Regime/hold-out validation, adversarial critique, graveyard | A system that flatters a bad strategy; a fabricated number |
| **P5** | **Mallory — adversary** | Tries to break auth / see others' data | (attacker) | *Any* success: cross-user data leak, key exfiltration, auth bypass |
| **P6** | **Otto — operator** | Deploys, restarts, migrates | Zero data loss, clean restart, no touching the monolith | DB loss on redeploy; orphaned "running" runs; missing runtime assets |

Personas map to use-case areas: P1→ONB/RUN, P2→RUN/AIR/CON/RES/KEY, P3→COST, P4→REG/RES/honesty,
P5→SEC, P6→REL/deploy.

---

## 3. System-under-test at a glance (surface the scenarios exercise)

- **Auth/account** (`/api/auth`): register (+optional key), email-verify gate, login (JWT in
  `localStorage["token"]`), change-password, delete-account (hard cascade `purge_user`).
- **Key vault** (`/api/ai`): add/list/toggle/delete providers; **keys encrypted at rest** (`enc::v1::`
  Fernet), **always masked** on read. 9 provider types.
- **Leakage marker** (3-state): `mechanism_only` (deepseek-reasoner, byteplus seed-2-0-pro) ·
  `risk` (gemini measured; openai/anthropic assumed) · `unvalidated` (everything else, incl.
  deepseek-chat). Surfaced in ≥6 UI locations + on API responses.
- **Research loop** (`/api/research`): Strategist → Executor → Gatekeeper → Critic → OOS → Director →
  Reporter. Modes: **rule_based / ai_assisted / full_ai**; **robustness** (fixed 2015–2023) vs
  **regime** (user window, `UNVALIDATED`, decay instead of OOS) + **P2 within-regime hold-out**.
  Rigor presets exploratory/standard/strict.
- **Console & results**: live pipeline/activity/evidence; candidates, **dossier** (gates/critique/OOS/
  artifacts), **graveyard** (killed, by cause), **lineage**, **report** (template-bound, numeric-claim
  scanned).
- **Resilience**: on boot → create tables · **mark orphaned runs interrupted** · **migrate-encrypt keys**
  · **restore providers**. 2 s heartbeat persistence with idempotent cursors; SQLite write-lock.

> **Out of scope (this iteration):** the raw `/api/ai/chat`, `/chat/stream`, `/voices`, `/tts` endpoints
> exist but aren't part of the end-user research journey (the console never exposes a chat box). They are
> covered only by SEC-1 (must be auth-gated); behavioral testing is deferred until/unless a UI surfaces them.

---

## 4. Use cases & scenarios

> Notation: **G**iven / **W**hen / **T**hen. Each row is one testable scenario.

### 4.ACC — Account lifecycle  *(P1, P2, P5)*

| ID | Scenario (G→W→T) | Prio | Layer |
|----|------------------|------|-------|
| ACC-1 | New email → register (no key) → account created, `verify_url` returned, cannot log in until verified | P0 | API, E2E |
| ACC-2 | Register with `provider_type`+`api_key` → account created **and** provider seeded (encrypted) | P1 | API |
| ACC-3 | Unverified account → login → rejected with clear message | P0 | API |
| ACC-4 | Valid verify token → GET `/verify/{token}` → verified; then login → `access_token` | P0 | API, E2E |
| ACC-5 | Duplicate email register → rejected, no partial account | P1 | API |
| ACC-6 | Weak password (<8) → rejected client- and server-side | P2 | UNIT, E2E |
| ACC-7 | Change password: wrong `current_password` → rejected; correct → succeeds, **old token/login invalid**, redirect to login | P0 | API, E2E |
| ACC-8 | Delete account: correct password + typed `DELETE` → user + **all** research/keys purged (cascade), logged out; token now 401 | P0 | API, E2E |
| ACC-9 | Delete account with wrong password → rejected, nothing deleted | P0 | API |
| ACC-10 | After delete, the freed email can register again cleanly | P2 | API |

**Key invariants:** ACC-8 must leave **zero** rows for that `user_id` across every `user_id`-bearing table
and every `goal_id`-scoped research table (assert row counts = 0). ACC-7/8 must invalidate the session.

### 4.KEY — API-key vault  *(P2, P5)*

| ID | Scenario | Prio | Layer |
|----|----------|------|-------|
| KEY-1 | Add key → stored **encrypted** (`enc::v1::` prefix in DB, never plaintext) | P0 | API, UNIT |
| KEY-2 | List keys → only **masked** value returned (first4…last4); full key never leaves server | P0 | API |
| KEY-3 | Toggle active off → provider not used by runs; on → usable again | P1 | API |
| KEY-4 | Delete key → removed from DB **and** evicted from runtime registry (not reusable mid-session) | P0 | API |
| KEY-5 | Boot with plaintext legacy key → `migrate_encrypt_keys` rewrites to `enc::v1::` in place (idempotent) | P1 | API, UNIT |
| KEY-6 | `AI_KEY_ENCRYPTION_KEY` unset → graceful plaintext + one-time loud warning (dev only) | P2 | UNIT |
| KEY-7 | Each key row shows correct 3-state **leakage badge** for its provider type | P1 | E2E, UNIT |
| KEY-8 | Add key with unknown/garbage provider_type → rejected cleanly | P2 | API |

### 4.ONB — Onboarding & key-gating  *(P1)*

| ID | Scenario | Prio | Layer |
|----|----------|------|-------|
| ONB-1 | First login, **no keys**, not skipped → OnboardingModal appears explaining free rule-based vs key-needed AI | P0 | E2E |
| ONB-2 | Onboarding "Später" (skip) → modal closes, `bt_onboarding_skipped=1` set, does not reappear | P1 | E2E |
| ONB-3 | Onboarding inline "Key speichern & los" → key created, modal closes, AI modes now available | P1 | E2E |
| ONB-4 | User **with** keys → onboarding never shows | P2 | E2E |
| ONB-5 | Keyless user on New-Run form clicks an **AI mode** → **key-gate modal** ("AI-Modus braucht einen API-Key") with "Regelbasiert nutzen" / "Zu den Einstellungen →" | P0 | E2E |
| ONB-6 | Key-gate → "Regelbasiert nutzen" switches mode to rule_based and closes | P1 | E2E |
| ONB-7 | Key-gate → "Zu den Einstellungen" navigates to `/settings` | P2 | E2E |
| ONB-8 | Rule-based is **never** blocked for a keyless user (can configure+launch end-to-end) | P0 | E2E |

### 4.RUN — Rule-based research run (keyless, €0, robustness)  *(P1, P2, P4)*

| ID | Scenario | Prio | Layer |
|----|----------|------|-------|
| RUN-1 | Configure (universe + ≥1 family) → **Preview** shows resolved config + WILL/WILL-NOT boxes → launch → run created `running` | P0 | E2E, API |
| RUN-2 | Launch disabled when no assets / no families / invalid regime dates | P1 | E2E |
| RUN-3 | Unknown ticker marked ⚠ but still attempt-able; known ticker ✓ | P2 | E2E |
| RUN-4 | Run progresses through phases (Strategist…Reporter); events stream; at least the pipeline advances | P0 | API, E2E |
| RUN-5 | Run reaches a terminal state (`completed`/`stopped`) within budget; candidates and/or graveyard populated | P0 | API |
| RUN-6 | **Determinism:** same `seed` + same config (mock/frozen data) → identical candidate hashes & metrics | P1 | UNIT, API |
| RUN-7 | Rule-based run cost is **€0** and no LLM call is made (mock provider asserts zero calls) | P0 | API |
| RUN-8 | Budget cap: `max_runs`/`max_seconds` respected → Director returns `budget_exhausted`, run stops | P0 | API, UNIT |
| RUN-9 | Zero survivors → honest empty state ("No survivors.") not an error | P1 | E2E, API |

### 4.AIR — AI-assisted / full-AI run (provider/model, LLM stages)  *(P2, P3)*

| ID | Scenario | Prio | Layer |
|----|----------|------|-------|
| AIR-1 | AI mode selected → provider auto-defaults to first active, model auto-selects cheapest | P1 | E2E |
| AIR-2 | `ai_assisted` → **only** the Critic (+Reporter) calls the LLM; Strategist stays rule-based (assert call sites) | P0 | API |
| AIR-3 | `full_ai` → Strategist **and** Critic call the LLM; each with correct isolation | P0 | API |
| AIR-4 | Critic **never** sees the Strategist's rationale (leakage isolation, C-2) — assert prompt inputs | P0 | UNIT |
| AIR-5 | Provider/model persisted on the run for reproducibility (`agent_mode/provider/model/seed`) | P1 | API |
| AIR-6 | LLM failure/timeout mid-run → graceful fallback (rule-based path) or recorded error, run not corrupted | P1 | API |
| AIR-7 | Run started with a `risk`/`unvalidated` model → run proceeds but is **marked** accordingly (see LEAK-5) | P1 | API, E2E |

> AIR-2/3/4 run against a **MockProvider** that records calls — this validates *wiring* at €0. Real-model
> behavior (does deepseek-reasoner actually reason?) is a **MAN** budgeted check (§7).

### 4.REG — Regime-fit + within-regime hold-out (honesty core)  *(P4)*

| ID | Scenario | Prio | Layer |
|----|----------|------|-------|
| REG-1 | Regime mode requires **both** `window_start` & `window_end` (atomic) → missing one rejected | P0 | API, E2E |
| REG-2 | `window_start ≥ window_end` → rejected | P1 | API, UNIT |
| REG-3 | Regime run → OOS forced **off**, **decay** reported instead | P1 | API |
| REG-4 | Every regime candidate starts `validation_status="unvalidated"` | P0 | API, UNIT |
| REG-5 | P2 hold-out (select-on-train): survivor re-tested on forward slice → `regime_validated` (≥20 trades & t≥1.65) or `regime_failed` | P0 | UNIT, API |
| REG-6 | Regime quality tiers render **amber** (`UNVALIDATED · …`), never green; `validated`=teal, `failed`=red | P0 | E2E, UNIT |
| REG-7 | Decay chip shows before/after retained-edge %; a strategy that only works inside the window shows large decay | P1 | UNIT, E2E |
| REG-8 | Smart-activity gate: thin idea (few trades) is **labeled low-confidence**, not silently rejected, in regime | P1 | UNIT |

### 4.CON — Live console & run control  *(P2)*

| ID | Scenario | Prio | Layer |
|----|----------|------|-------|
| CON-1 | Console shows pipeline rail advancing, activity stream newest-first, evidence panel candidates | P1 | E2E |
| CON-2 | Pause → run pauses; Resume → continues; buttons gated by status | P0 | API, E2E |
| CON-3 | Stop (report=true) → terminal + report generated; Cancel → hard stop | P0 | API |
| CON-4 | Failure loop-back rendered ("↳ back to Strategist · failure ctx #N") | P2 | E2E |
| CON-5 | Circuit-breaker: ≥N consecutive failures → warning shown, Director may switch asset/stop | P1 | API, UNIT |
| CON-6 | BudgetHUD meters (runs/€/time/iterations/failures) match backend state | P1 | E2E |
| CON-7 | Terminal run → polling stops (no infinite fetch), "View Report" appears | P2 | E2E |
| CON-8 | SSE event stream drops → hooks fall back to 2 s polling; no lost/duplicated events on reconnect | P2 | E2E, API |

### 4.RES — Results interpretation (dossier / graveyard / lineage / report)  *(P2, P4)*

| ID | Scenario | Prio | Layer |
|----|----------|------|-------|
| RES-1 | Candidate dossier leads with **trust** (gates, critique, OOS); Sharpe demoted | P1 | E2E |
| RES-2 | Dossier statistical section: per-trade t-stat + tier, benchmark excess, OOS verdict, DSR (**provisional** if <20 trials **or** Sharpe-variance unmeasured) | P0 | E2E, UNIT |
| RES-3 | Graveyard aggregates killed strategies **by cause**; filter chips work; each shows failed gate value vs threshold | P1 | E2E, API |
| RES-4 | Lineage tree renders parent→child mutations; live-only 404 keeps last | P2 | E2E |
| RES-5 | Report available only when complete; honest-framing banner ("NOT YET FALSIFIED") present | P1 | E2E |
| RES-6 | **Numeric-claim scan:** report narrative containing a raw number that isn't a template binding → `NumericClaimError` (never ships a fabricated figure) | P0 | UNIT |
| RES-7 | Deep-links to `runs/{id}`, `/report`, `/graveyard`, `/lineage`, `/candidates/{hash}` all resolve (no 404s — regression guard for the gitignore incident) | P0 | E2E |

### 4.LEAK — Leakage & reasoning surfacing  *(P1, P4)*

| ID | Scenario | Prio | Layer |
|----|----------|------|-------|
| LEAK-1 | 3-state badge renders correct state/color/glyph per provider (✓ teal / ⚠ amber / · gray) | P0 | UNIT, E2E |
| LEAK-2 | LeakageLegend visible + expandable; explains "leakage" and "mechanism-only" | P1 | E2E |
| LEAK-3 | Badge/legend present in: registration, onboarding, settings, new-run picker, console HUD | P1 | E2E |
| LEAK-4 | Only **reasoning** models recommended for AI research (✦ indicator; guidance text) | P2 | E2E |
| LEAK-5 | Run using a `risk` provider → amber "leakage risk" chip on console HUD + on run list | P0 | E2E, API |
| LEAK-6 | Classification matches source-of-truth: deepseek-reasoner/byteplus=mechanism_only; gemini/openai/anthropic=risk; rest=unvalidated (incl. deepseek-chat) | P0 | UNIT |
| LEAK-7 | An **unvalidated** model is never presented as "clean/safe" (no false green) | P1 | UNIT, E2E |

### 4.COST — Cost estimation & budget enforcement  *(P3)*

| ID | Scenario | Prio | Layer |
|----|----------|------|-------|
| COST-1 | New-run form shows pre-launch estimate: rule_based "€0 — no AI"; free model "€0 — free"; priced "≈ €X — up to your €cap"; no pricing "unknown" | P0 | UNIT, E2E |
| COST-2 | Estimate math matches `estimateEur` (token counts × gate-pass rate by rigor) | P1 | UNIT |
| COST-3 | Hard cap: run stops at `max_eur` even if target not met (Director `budget_exhausted` by cost) | P0 | API, UNIT |
| COST-4 | `used_eur` on state/HUD reflects actual metered LLM spend (mock meter) | P1 | API |
| COST-5 | full_ai "bills for all trials" disclosure shown; estimate ≥ ai_assisted for same config | P2 | E2E, UNIT |

### 4.REL — Resilience, persistence, deploy  *(P6)*

| ID | Scenario | Prio | Layer |
|----|----------|------|-------|
| REL-1 | Kill process mid-run → on boot, that `running` row → `interrupted` (no zombie "running") | P0 | API |
| REL-2 | Restart → active providers restored from DB (decrypted); logged count correct | P0 | API |
| REL-3 | Restart mid-run → GET endpoints fall back to DB snapshot; no data loss vs last heartbeat | P1 | API |
| REL-4 | Heartbeat idempotency: no duplicate events/candidates/failures after repeated snapshots | P1 | UNIT |
| REL-5 | Concurrent writes serialized (SQLite write-lock) — no "database is locked" crash under load | P1 | API |
| REL-6 | **Redeploy preserves the DB** (volume reuse): users/providers/runs counts unchanged after `up -d --build` | P0 | MAN/API |
| REL-7 | Built image contains all runtime assets (`config/` present; no source file git-ignored) | P0 | API (in-container) |

### 4.SEC — Security & data isolation  *(P5)*

| ID | Scenario | Prio | Layer |
|----|----------|------|-------|
| SEC-1 | Every non-public endpoint returns 401 without a valid token | P0 | API |
| SEC-2 | Expired/invalid/deleted-user token → 401, client clears token & redirects to `/` | P0 | API, E2E |
| SEC-3 | **Cross-user isolation:** A cannot GET/pause/stop B's `goal_id` (runs, candidates, hypothesis, lineage, graveyard, report, dossier) → **404** (existence not leaked). *Already enforced via `_owned_run`; test locks it in.* | P0 | API |
| SEC-4 | User A cannot see/delete user B's providers/keys | P0 | API |
| SEC-10 | Director `/stats` reflects **only the caller's** runs — no global/other-user aggregate leak | P1 | API |
| SEC-5 | Full API key never returned by any endpoint or embedded in any response/log | P0 | API, UNIT |
| SEC-6 | Auth rate-limit (nginx `/api/auth/` zone) throttles brute force (429) | P1 | API |
| SEC-7 | Prompt/goal_text injection can't escape into unbounded LLM spend or break the loop (bounded by budget/gates) | P2 | API, MAN |
| SEC-8 | Scanner paths (`/.env`, `/.git`, `wp-login`) blocked (404) by nginx | P2 | API |
| SEC-9 | JWT `sub` tampering / forged token rejected (signature) | P0 | API |

---

## 5. Cross-cutting invariants (must hold across all scenarios)

### 5.1 Security & privacy
- No endpoint (except register/login/verify/token) works without a valid JWT.
- All list/detail/mutation of runs, candidates, providers is scoped by `user_id`/`goal_id` ownership.
- Keys: encrypted at rest, masked on read, evicted on delete, never logged.

### 5.2 Data integrity & durability
- `PRAGMA integrity_check = ok` after any lifecycle op.
- Delete cascade leaves **zero** orphan rows.
- Redeploy/restart never loses committed research data; idempotent persistence never double-writes.

### 5.3 Honesty invariants  *(the differentiator — test explicitly)*
- **Never a fabricated number.** Reporter narratives are numeric-claim-scanned (RES-6).
- **UNVALIDATED can never look robust.** Regime tiers are amber; only true `regime_validated` is teal (REG-6).
- **No false "clean".** Unvalidated models are never labeled safe; `risk` is always surfaced (LEAK-5/7).
- **Statistical caveats survive.** DSR shows `provisional` on thin trials; thin activity is labeled, not hidden (RES-2, REG-8).
- **Empty is honest.** Zero survivors reads as "no survivors", not an error or a padded result (RUN-9).

### 5.4 Cost governance
- Automated suite spends **€0** (mock LLM). Any test that would call a paid provider must be tagged `MAN`
  and gated behind an explicit opt-in + budget estimate (respects the owner's spend-watch rule).
- `max_eur`/`max_runs`/`max_seconds` are hard ceilings (COST-3, RUN-8).

### 5.5 Internationalization
- UI is German-facing; assert key user-visible strings (buttons, gate modal, legend) in the expected
  language and that dynamic content (tickers, metrics) renders correctly.

### 5.6 Accessibility (baseline)
- Interactive controls reachable/operable by keyboard; status conveyed by text+glyph, not color alone
  (important because leakage/quality lean on color — the glyph/label is the accessible fallback).

---

## 6. Test layers & tooling

```
        ▲  fewer, slower, highest-confidence
   E2E  │  Playwright: full journeys (register→onboard→run→results), gating, honesty rendering
   API  │  httpx + pytest against the app (in-container): endpoints, lifecycle, isolation, budget
  UNIT  │  gatekeeper thresholds, quality/DSR, cost math, leakage classification, numeric-claim scan,
        │  keycrypto, purge_user, persistence idempotency, Director decisions
        ▼  many, fast, run on every change
   MAN  ─  real-LLM behavior, real-provider cost sanity, exploratory UX  (opt-in, budgeted)
```

- **E2E seed:** `dev/qa/regime_liveverify.py` already drives the browser with a minted JWT injected into
  `localStorage["token"]` and a browser User-Agent (Cloudflare 403s default UA). Grow it into a
  persona-organized suite.
- **API in-container:** `docker exec bt-bt-backend-1 python -m pytest` is the authoritative runner
  (catches ship-vs-tree gaps). Mint a test JWT via `auth.security.create_access_token({"sub": ...})`.
- **MockProvider:** an `IAIProvider` that records calls and returns canned reasoning — enables AIR/COST
  wiring tests at €0 and asserts *zero* calls for rule-based (RUN-7).

## 7. Test-data & environment strategy

- **Ephemeral DB per test run** (temp SQLite) for API/UNIT; never touch the production volume.
- **Frozen market data** (`BACKTEST_DETERMINISM_MODE`/golden snapshot) so backtests are bit-exact and
  offline — required for RUN-6 determinism.
- **Seed users/providers** via factory helpers (verified user + 1 mechanism_only + 1 risk + 1 unvalidated
  provider) to cover leakage rendering without real keys.
- **No real API keys in the repo or CI**; the encryption key for tests is a throwaway Fernet key.
- **Real-provider MAN runs**: a tiny, explicitly-budgeted matrix (e.g. one deepseek-reasoner `ai_assisted`
  run) to confirm live wiring + cost metering, executed only with owner go-ahead and a pre-estimate.

## 8. Release gates (CI / pre-deploy)

**Blocking gate (must pass before deploy):**
1. `lint-imports` — module boundaries (7 contracts).
2. **Full `pytest` inside the built backend image** (not the working tree).
3. `next build` (frontend compiles) + type-check.
4. **Smoke after deploy:** root 200, protected endpoints 401, authed `GET /research/runs` 200,
   DB `integrity_check=ok` + row-count preserved, the recovered run-detail routes 200.

### 8.1 Regression guards born from real incidents
- **Ship-vs-tree guard:** CI asserts no source file is git-ignored — fail if
  `git ls-files --others --ignored --exclude-standard -- src frontend/src` returns any `.py/.ts/.tsx`.
  *(Root cause of the `results/` + `runs/` outage: unanchored gitignore patterns.)*
- **Image-asset guard:** assert `config/` (and any `Path(__file__).parents[...]` runtime dir) exists in
  the built image. *(Root cause of the missing `provider_capabilities.yaml`.)*
- **Determinism guard:** if `BACKTEST_DETERMINISM_MODE=true`, the golden snapshot must be present.
- **Monolith-safety guard (deploy):** the deploy script only touches the `bt` compose project /
  `/root/backtesting-agent`; never `/root/AI-Investment`.

## 9. Traceability & phasing

**Coverage matrix (persona × area):**

| Area | P1 Nadia | P2 Ravi | P3 Bea | P4 Sven | P5 Mallory | P6 Otto |
|------|:--:|:--:|:--:|:--:|:--:|:--:|
| ACC | ● | ● | | | ● | |
| KEY | | ● | | | ● | |
| ONB | ● | | | | | |
| RUN | ● | ● | | ● | | |
| AIR | | ● | ● | | | |
| REG | | | | ● | | |
| CON | | ● | | | | |
| RES | | ● | | ● | | |
| LEAK | ● | | | ● | | |
| COST | | | ● | | | |
| REL | | ● | | | | ● |
| SEC | | | | | ● | |

**Suggested build order (by risk):**
1. **Phase 1 — safety net (P0 API+UNIT):** ACC, SEC (auth+isolation), KEY (encryption/mask), RUN-7/8
   (€0 + budget), REL-1/2/6/7, honesty units (RES-6, LEAK-6, REG-4/5). *These protect money, privacy,
   and data.*
2. **Phase 2 — core journeys (P0 E2E):** ONB (gating), RUN (keyless happy path), RES-7 (route regression),
   REG-6 (UNVALIDATED never green), LEAK-5.
3. **Phase 3 — depth (P1):** AIR wiring (MockProvider), CON controls, COST estimation, RES dossier/
   graveyard, resilience idempotency.
4. **Phase 4 — MAN + non-functional:** one budgeted real-LLM run, rate-limit/injection, a11y/i18n sweep.

**Definition of "adequately tested" for a release:** all P0 rows green in-container + the §8 smoke passes
on the live URL, with the §8.1 guards active in CI.

---

### Appendix — scenario ID index
`ACC` account · `KEY` key vault · `ONB` onboarding/gating · `RUN` rule-based run · `AIR` AI run ·
`REG` regime/hold-out · `CON` console · `RES` results/honesty · `LEAK` leakage · `COST` cost/budget ·
`REL` resilience/deploy · `SEC` security. Priorities `P0…P3`; layers `E2E/API/UNIT/MAN`.
