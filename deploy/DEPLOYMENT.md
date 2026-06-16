# Deployment — Backtesting Agent

> **Status:** files prepared locally — server-side deploy is **gated** on
> Phase 1 + 2 (Python core copied + `python run_backtest.py --preset quick`
> reproduces a deterministic result locally). Do not run `deploy.sh` on
> the server before that.

This document is the runbook for the live deploy on the Contabo VPS
(`109.199.123.190`) when the time comes. The stack lives alongside the
existing AI-Investment stack and **reuses the prismgate Cloudflare Tunnel**
(`tunnel-prismgate` service in the AI-Investment compose) — no own tunnel
container in this repo.

> **Domain decision (2026-06-07):** domain is `prismgate.net`, registered in
> its own Cloudflare account. Hostnames: `trade.prismgate.net` (main stack)
> and `backtesting-agent.prismgate.net` (this stack). The old tunnel for
> `trader001.wallsignal.com` (different CF account) runs in parallel for a
> 1-2 week transition, then gets removed.

## Topology

```
tunnel-prismgate (cloudflared, lives in the AI-Investment compose)
├── trade.prismgate.net             ─► main nginx ─► frontend:3000 / backend:8000
└── backtesting-agent.prismgate.net ─► bt-nginx   ─► bt-api:8000  (+ bt-frontend:3000 in Phase 3)
                                          │
                                          └── shared docker network: ${SHARED_NETWORK}

tunnel (old, wallsignal CF account — transition only)
└── trader001.wallsignal.com        ─► main nginx
```

The CF Tunnel is token-based, so ingress rules are managed in the
Cloudflare Zero-Trust Dashboard — no `config.yml` edit on the server.

## Shared network

The new compose attaches `bt-nginx` to two networks:
- `bt-internal` — private bridge for bt-api ↔ bt-nginx ↔ bt-frontend
- `shared` (external) — the network the existing `cloudflared` container is
  attached to, so the tunnel can reach `bt-nginx:80`

Find the right `shared` name on the server with:
```bash
docker network ls
docker inspect <cloudflared container> --format '{{json .NetworkSettings.Networks}}'
```
Set `SHARED_NETWORK` in `.env` accordingly. Default is `ai-investment_default`.

## Server-side steps (DO NOT RUN YET)

When Phase 2 is green locally:

### 1. Doku — pflicht vor jedem Server-Touch
- Update `docs/SERVER-INVENTORY.md` in the AI-Investment repo:
  - Add row to "Permanente Services": `bt-api`, `bt-frontend` (Phase 3), `bt-nginx`
  - Add row to "Zugang (von außen)": `<new hostname>` → `bt-nginx:80`
  - Add Update-Protokoll row
- Open Jira subtask under "Server Tools Inventory" story.

### 2. Clone + .env
```bash
ssh -i ~/.ssh/id_ed25519_contabo_claude root@109.199.123.190
cd /root
git clone https://github.com/EmilHerzberg/backtesting-agent.git
cd backtesting-agent
cp .env.example .env
nano .env   # set SHARED_NETWORK + API keys
```

### 3. First deploy (API-only — Phase 2)
```bash
bash deploy/deploy.sh
```
The script:
- verifies `.env` exists and `SHARED_NETWORK` resolves to a real docker net
- verifies `src/backtesting_agent/engine/runner.py` exists (Phase 1 sanity)
- builds + starts `bt-api` + `bt-nginx` (Phase 2 default — no frontend)
- prints next-step instructions

### 4. Cloudflare hostname (manual, one-time)
In the **prismgate** CF account → Zero-Trust Dashboard → **Networks** →
**Tunnels** → `prismgate` tunnel → **Public Hostname** → **Add**:
- Subdomain: `backtesting-agent` / Domain: `prismgate.net`
- Type: HTTP
- URL: `bt-nginx:80`

(May already exist if it was added together with `trade.prismgate.net`
during the main-stack switch — then this step is done.)

### 5. Smoke test
```bash
curl -sf https://backtesting-agent.prismgate.net/health    # bt-api health endpoint
curl -sf https://backtesting-agent.prismgate.net/docs      # FastAPI Swagger
```

### 6. Phase 3 — enable the frontend
Once `../frontend/` contains the copied Next.js slice:
- Set `PUBLIC_API_URL=https://backtesting-agent.prismgate.net/api` in `.env`
- Update `nginx.conf`: repoint `location /` from `bt-api` to `bt-frontend:3000`
- Redeploy with the full profile:
  ```bash
  docker compose -f deploy/docker-compose.yml --profile full up -d --build
  ```

## Rollback

```bash
docker compose -f deploy/docker-compose.yml down
```
Then in Cloudflare Zero-Trust Dashboard delete the Public Hostname row.
The AI-Investment stack is untouched throughout — rollback affects only
the Backtesting Agent.

## Resource footprint (estimate)

| Service | RAM | CPU |
|---|---|---|
| bt-api (FastAPI + pandas + optuna) | ~500–800 MB idle, spikes to 2–3 GB during batch optimization | 1-N cores via ProcessPoolExecutor |
| bt-frontend (Next.js standalone) | ~150 MB | low |
| bt-nginx | ~10 MB | negligible |

VPS has 24 GB RAM — plenty of headroom next to the existing stack.
