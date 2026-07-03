# Deployment Guide — AI Trading Platform

## Architektur

```
User → Cloudflare (HTTPS) → Tunnel → Docker Host
                                      ├── Frontend (Next.js :3000)
                                      ├── Backend  (FastAPI :8000)
                                      └── SQLite   (Volume)
```

- Keine offenen Ports noetig (Cloudflare Tunnel)
- HTTPS automatisch via Cloudflare
- Alle Secrets nur in .env auf dem Server

---

## Voraussetzungen

- Ein VPS/Server (z.B. Hetzner, DigitalOcean, ab 4 EUR/Monat)
- Docker + Docker Compose installiert
- Ein Cloudflare-Konto mit einer Domain
- Git

---

## Schritt 1: Server vorbereiten

```bash
# Auf dem Server (z.B. Ubuntu 22.04):
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git
sudo usermod -aG docker $USER
# Neu einloggen damit Docker ohne sudo funktioniert
```

## Schritt 2: Repo klonen

```bash
git clone https://github.com/DEIN-USERNAME/AI-Investment.git
cd AI-Investment
```

## Schritt 3: Cloudflare Tunnel einrichten

1. Gehe zu **dash.cloudflare.com → Zero Trust → Networks → Tunnels**
2. Klick **Create a tunnel**
3. Name: `ai-trading`
4. Connector: **Docker** waehlen
5. Kopiere den **TUNNEL_TOKEN** (langer String)
6. Unter **Public Hostnames** zwei Eintraege erstellen:

| Subdomain | Domain | Service |
|-----------|--------|---------|
| `trading` | your-domain.com | `http://frontend:3000` |
| `api` | your-domain.com | `http://backend:8000` |

## Schritt 4: .env konfigurieren

```bash
cp .env.example .env
nano .env
```

Mindestens ausfuellen:
```
SECRET_KEY=<zufaelliger-langer-string>
CLOUDFLARE_TUNNEL_TOKEN=<dein-tunnel-token>
CORS_ORIGINS=["https://trading.your-domain.com"]
```

Tipp fuer SECRET_KEY:
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

## Schritt 5: Starten

```bash
chmod +x deploy/deploy.sh
./deploy/deploy.sh
```

Oder manuell:
```bash
docker compose build
docker compose up -d
```

## Schritt 6: Pruefen

```bash
# Container Status
docker compose ps

# Logs
docker compose logs backend -f
docker compose logs tunnel -f

# Backend Health
curl http://localhost:8000/docs
```

Deine App ist jetzt erreichbar unter:
- **Frontend**: `https://trading.your-domain.com`
- **API Docs**: `https://api.your-domain.com/docs`

---

## Updates deployen

```bash
cd AI-Investment
git pull
docker compose build
docker compose up -d
```

## Backup

```bash
# SQLite Datenbank sichern
docker compose cp backend:/app/data/trading.db ./backup/trading.db
```

## Stoppen

```bash
docker compose down          # Stoppen (Daten bleiben)
docker compose down -v       # Stoppen + Daten loeschen
```

---

## Sicherheitscheckliste

- [ ] SECRET_KEY geaendert (kein Default!)
- [ ] .env NICHT im Git
- [ ] Cloudflare Tunnel aktiv (keine offenen Ports)
- [ ] CORS_ORIGINS auf deine Domain beschraenkt
- [ ] BROKER_MODE=mock (bis du bereit fuer Live bist)
- [ ] AI Provider Keys ueber die /setup UI eingeben (nicht in .env noetig)
