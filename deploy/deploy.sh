#!/bin/bash
set -e

echo "=== AI Trading Platform — Deployment ==="

# Check prerequisites
command -v docker >/dev/null 2>&1 || { echo "Docker nicht installiert. Bitte installieren: https://docs.docker.com/engine/install/"; exit 1; }
command -v docker compose >/dev/null 2>&1 || { echo "Docker Compose nicht installiert."; exit 1; }

# Check .env exists
if [ ! -f .env ]; then
    echo "FEHLER: .env Datei fehlt!"
    echo "Kopiere .env.example und trage deine Keys ein:"
    echo "  cp .env.example .env"
    echo "  nano .env"
    exit 1
fi

# Check critical env vars
source .env
if [ "$SECRET_KEY" = "dev-secret-key-change-in-production" ] || [ -z "$SECRET_KEY" ]; then
    echo "WARNUNG: SECRET_KEY ist noch der Default-Wert!"
    echo "Bitte in .env einen sicheren Key setzen."
    exit 1
fi

if [ -z "$CLOUDFLARE_TUNNEL_TOKEN" ]; then
    echo "WARNUNG: CLOUDFLARE_TUNNEL_TOKEN nicht gesetzt."
    echo "Tunnel wird nicht gestartet. Backend laeuft nur lokal."
fi

echo ""
echo "1/3 Building containers..."
docker compose build

echo ""
echo "2/3 Starting services..."
docker compose up -d

echo ""
echo "3/3 Checking health..."
sleep 5
docker compose ps

echo ""
echo "=== Deployment fertig ==="
echo "Backend: http://localhost:8000/docs"
echo "Frontend: http://localhost:3000"
if [ -n "$CLOUDFLARE_TUNNEL_TOKEN" ]; then
    echo "Tunnel: Aktiv (Zugang ueber deine Cloudflare Domain)"
fi
