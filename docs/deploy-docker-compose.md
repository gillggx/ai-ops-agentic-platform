# Docker Compose Deployment

Single-host setup. Brings up all 4 application services + 3 databases
on one machine in ~5 minutes (most of that is the first build).

## Prerequisites

- Docker Engine ≥ 24 + Docker Compose v2 (`docker compose` subcommand)
- 8 GB RAM available for the stack (peak ~6 GB)
- 10 GB free disk

## 1. Prepare env file

```bash
cp deploy/docker/.env.example deploy/docker/.env

# Generate required secrets:
echo "INTERNAL_API_TOKEN=$(openssl rand -hex 32)" >> deploy/docker/.env
echo "NEXTAUTH_SECRET=$(openssl rand -base64 32)" >> deploy/docker/.env
echo "POSTGRES_PASSWORD=$(openssl rand -hex 16)" >> deploy/docker/.env
# Then edit deploy/docker/.env and:
#   1. delete the empty REQUIRED= lines at the top
#   2. add your ANTHROPIC_API_KEY (or switch LLM_PROVIDER)
```

## 2. Build + start

```bash
docker compose -f deploy/docker-compose.yml \
  --env-file deploy/docker/.env \
  up -d --build
```

First build takes 5-10 minutes (Maven + npm install). Subsequent rebuilds
hit the layer cache and finish in seconds.

## 3. Verify

```bash
# All 8 services should report healthy:
docker compose -f deploy/docker-compose.yml ps

# Health checks:
curl -s localhost:8002/actuator/health   | jq .status   # → "UP"
curl -s localhost:8012/api/v1/tools      | jq 'length'  # → number > 0
curl -s localhost:8000/api/health        | jq .status   # → "ok"

# Sidecar requires the service token:
TOKEN=$(grep '^INTERNAL_API_TOKEN=' deploy/docker/.env | cut -d= -f2)
curl -s -H "X-Service-Token: $TOKEN" localhost:8050/internal/health
```

Open <http://localhost:8000> in a browser and log in (bootstrap account is
seeded by the java-api on first start — see `BootstrapSeeder.java`).

## 4. Stop / reset

```bash
# Stop (keep data):
docker compose -f deploy/docker-compose.yml down

# Full reset (drop all DB data):
docker compose -f deploy/docker-compose.yml down -v
```

## Architecture

```
                                 ┌──────────────────┐
   :8000  Browser ───────────────┤    aiops-app     │  Next.js standalone
                                 │   (port 8080)    │
                                 └─────────┬────────┘
                                           │ /api/* proxy (X-Internal-Token)
                                           ▼
   :8002  ───────────────────────┌──────────────────┐
   curl debugging                │  aiops-java-api  │  Spring Boot 3.5
                                 │   (port 8080)    │
                                 └────┬─────────┬───┘
                          /internal/* │         │ /internal/scheduler/*
                                      ▼         ▼
                  ┌─────────────────────┐ ┌─────────────────────────┐
                  │ aiops-python-sidecar│ │  aiops-java-scheduler   │  Spring Boot 3.5
                  │   (port 8080)       │ │   (port 8080)           │
                  └────┬────────────┬───┘ └────┬────────────────────┘
                       │            │          │
                       ▼            ▼          ▼
              ┌─────────────┐  ┌─────────┐ ┌─────────┐
              │ ontology-   │  │postgres │ │ redis   │ (job locks)
              │ simulator   │  │pgvector │ │         │
              │ (port 8080) │  │         │ │         │
              └──────┬──────┘  └─────────┘ └─────────┘
                     │
                     ▼
                ┌─────────┐
                │ mongodb │
                └─────────┘
```

All service-to-service URLs use Compose's bridge-network DNS
(`http://aiops-java-api:8080`). The exposed host ports (8000/8002/8050/8012/8003)
are for your `curl` / browser only.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `aiops-app` build fails: `Cannot find module 'aiops-contract'` | Docker build context is wrong | Build from repo root: `docker build -f aiops-app/Dockerfile .` (already correct in compose) |
| Java pods crashloop with `Connection refused: postgres` | Postgres not healthy yet | `docker compose logs postgres` — check init errors, then `docker compose restart aiops-java-api` |
| Sidecar 401s from java-api calls | `INTERNAL_API_TOKEN` mismatch | All 4 services must read the same value — compose already wires this from `.env` |
| Browser login redirects loop | `NEXTAUTH_URL` wrong | Set in `.env` to match your access URL (e.g. `http://localhost:8000`) |
| `aiops-app` build fails at `npm run build:prod` | Missing `INTERNAL_API_TOKEN` build arg | Confirm `.env` has all 3 required values; rebuild with `--no-cache` |

## What's not covered

- **TLS** — terminate at a reverse proxy (Caddy / Traefik / nginx) in front
- **Backup** — Postgres + MongoDB volumes are local; mount them on real disk for prod-ish use
- **Log aggregation** — JSON logs go to container stdout; pipe `docker compose logs -f`
  through `jq` or forward to your log stack

For multi-host / K8s deployment see [deploy-kubernetes.md](deploy-kubernetes.md).
