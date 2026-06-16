#!/bin/bash
# Backtesting Agent — server-side deploy script.
# Run from /root/backtesting-agent/ on the Contabo VPS (109.199.123.190).

set -e

echo "=== Backtesting Agent — Deployment ==="

command -v docker >/dev/null 2>&1 || { echo "Docker missing"; exit 1; }
command -v docker compose >/dev/null 2>&1 || { echo "Docker Compose missing"; exit 1; }

if [ ! -f .env ]; then
    echo "FEHLER: .env fehlt."
    echo "  cp .env.example .env && nano .env"
    exit 1
fi

# -- Verify the shared docker network the existing cloudflared lives on --
SHARED_NETWORK="${SHARED_NETWORK:-ai-investment_default}"
if ! docker network inspect "$SHARED_NETWORK" >/dev/null 2>&1; then
    echo "FEHLER: shared network '$SHARED_NETWORK' existiert nicht."
    echo "  Liste verfuegbarer networks:"
    docker network ls
    echo "  Setze SHARED_NETWORK in .env auf den richtigen Namen."
    exit 1
fi

# -- Verify Phase 1/2 actually populated the package --
if [ ! -f src/backtesting_agent/engine/runner.py ]; then
    echo "FEHLER: src/backtesting_agent/engine/runner.py fehlt — Phase 1 noch nicht eingespielt."
    echo "  Server-Deploy nur nach erfolgreichem 'python run_backtest.py --preset quick' lokal."
    exit 1
fi

echo ""
echo "1/3 Building containers..."
cd "$(dirname "$0")/.."
docker compose -f deploy/docker-compose.yml build

echo ""
echo "2/3 Starting services..."
docker compose -f deploy/docker-compose.yml up -d

echo ""
echo "3/3 Health check..."
sleep 5
docker compose -f deploy/docker-compose.yml ps

echo ""
echo "=== Deployment done ==="
echo "Next step (manual): Cloudflare Zero-Trust Dashboard"
echo "  Public Hostname  ->  http://bt-nginx:80   (on network: $SHARED_NETWORK)"
