# Backtesting Agent

An autonomous strategy-research agent: a backtesting engine wrapped in an AI
research loop that proposes hypotheses, runs robustness/hold-out validation, and
surfaces only statistically honest candidates. Deployed at
**backtesting-agent.prismgate.net**.

This is a standalone extraction of the research subsystem from the larger
AI-Investment platform. It keeps the `src.backend.*` namespace but ships only the
research keep-set — no live broker/trading, scheduler, or event-context code.

## What's inside

| Area | Package | Purpose |
|------|---------|---------|
| Delivery | `src/backend/api` | FastAPI app + routers (`/api/auth`, `/api/ai`, `/api/research`) |
| Auth | `src/backend/auth` | JWT auth, account settings, per-user API-key vault (Fernet at rest) |
| AI | `src/backend/ai` | Provider adapters (9 providers), the research loop, leakage classification |
| Backtesting | `src/backend/backtesting` | Optuna-optimised engine, strategies, quality/DSR stats |
| Market data | `src/backend/marketdata` | Yahoo (default) + Alpha Vantage/Alpaca fallbacks |
| Indicators | `src/backend/indicators` | Technical-indicator library |
| Kernel | `src/backend/shared`, `src/backend/db` | Config, logging, types, SQLAlchemy base |
| Frontend | `frontend/` | Next.js 15 dashboard (login, research console, account settings) |

### Module boundaries

Enforced by `import-linter` (`.importlinter`, 7 contracts). Blessed direction:
`ai → backtesting → {marketdata, indicators} → kernel`. The delivery layer
(`api`) is imported by nobody; `shared`/`db` import no feature module.

```bash
lint-imports          # requires: pip install import-linter
```

## Local development

### Backend

```bash
python -m venv .venv && .venv\Scripts\activate      # Windows
pip install -e ".[dev]"

cp .env.example .env                                 # fill SECRET_KEY, AI_KEY_ENCRYPTION_KEY
uvicorn src.backend.api.main:app --reload --port 8000

pytest                                               # full suite
```

### Frontend

```bash
cd frontend
npm install
npm run dev                                          # http://localhost:3000
```

## AI providers & data leakage

Users add provider keys in the settings UI (encrypted at rest). Each model is
classified into one of three leakage states, surfaced in onboarding and settings:

- **✓ mechanism-only** — no evidence of look-ahead recall (e.g. `deepseek-reasoner`).
  Safest for backtest research.
- **⚠ leakage risk** — training-rich models whose calibrated recall can
  contaminate backtest performance (e.g. GPT / Gemini / Claude frontier models).
- **· unrated** — not yet validated against the leakage protocol.

Only reasoning-capable models are recommended for the research loop.

## Deployment

Production runs three containers (`bt-backend`, `bt-frontend`, `bt-nginx`) under
the compose project `bt`. `bt-nginx` joins the host's shared `prodnet` network so
the existing Cloudflare tunnel routes the public hostname to it.

```bash
cp .env.example .env        # set SECRET_KEY, AI_KEY_ENCRYPTION_KEY, CORS_ORIGINS
docker compose -p bt -f docker-compose.bt.yml up -d --build
```

The SQLite database lives in the `bt-backend-data` volume (`/app/data`) and
survives rebuilds. See `deploy/DEPLOYMENT.md` for host-specific notes.
