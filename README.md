# AIOps Platform

An AI-powered factory operations platform for automated process monitoring, anomaly detection, and diagnostic analysis.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  aiops-app (Next.js 15)                                 │
│  Admin UI · AlarmCenter · Agent Chat · Skill Designer   │
└──────────────────┬──────────────────────────────────────┘
                   │ REST / SSE
┌──────────────────▼──────────────────────────────────────┐
│  fastapi_backend_service (FastAPI)                       │
│  Auto-Patrol · Diagnostic Rules · MCP · Agent · Alarms  │
└──────────┬─────────────────────────────┬────────────────┘
           │ HTTP                         │ HTTP
┌──────────▼──────────┐     ┌────────────▼───────────────┐
│  OntologySimulator   │     │  LLM (Claude / Ollama)     │
│  /api/v1/events      │     │  Skill generation · Agent  │
│  /api/v1/context/... │     └────────────────────────────┘
└─────────────────────┘
```

## Core Features

| Feature | Description |
|---|---|
| **Auto-Patrol** | Scheduled/event-driven monitoring rules with LLM-generated Python logic |
| **Alarm Center** | Two-layer alarm view: Auto-Patrol trigger reason + Diagnostic Rule findings |
| **Diagnostic Rules** | Deep-dive analysis triggered by alarms; two-phase AI generation with live console |
| **MCP Builder** | Visual data pipeline builder — system MCPs connect to OntologySimulator APIs |
| **Agent** | Conversational AI for factory data analysis using registered MCPs as tools |
| **Skill Designer** | AI-powered skill builder for custom monitoring logic |

## Project Structure

```
fastapi_backend_refactored/
├── fastapi_backend_service/    # FastAPI backend
│   ├── app/
│   │   ├── models/             # SQLAlchemy ORM models
│   │   ├── repositories/       # DB access layer
│   │   ├── routers/            # FastAPI route handlers
│   │   ├── schemas/            # Pydantic request/response schemas
│   │   └── services/           # Business logic
│   ├── alembic/                # DB migrations
│   ├── main.py                 # App entry point + startup seeding
│   └── requirements.txt
├── ontology_simulator/         # Factory process simulator (data source)
│   └── frontend/               # Simulator UI (Next.js)
└── docker-compose.yml

aiops-app/                      # Main frontend (Next.js 15)
├── src/
│   ├── app/
│   │   ├── admin/              # Admin pages (skills, patrols, MCPs, alarms)
│   │   ├── api/admin/          # Next.js API routes (proxy to FastAPI)
│   │   └── operations/         # Operations pages (AlarmCenter, Agent)
│   └── components/
└── package.json
```

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 20+
- An Anthropic API key **or** a running Ollama instance

### 1. Backend

```bash
cd fastapi_backend_service
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Configure environment
cp ../.env.example .env
# Edit .env — at minimum set:
#   ANTHROPIC_API_KEY=sk-ant-...   (or OLLAMA_* if using local LLM)
#   SECRET_KEY=<random 32-char hex>
#   INTERNAL_API_TOKEN=<shared token with frontend>

uvicorn main:app --reload --port 8000
```

**First startup is fully automatic — no manual DB setup needed:**

| Step | What happens |
|---|---|
| `init_db()` | Creates all tables via SQLAlchemy `create_all` |
| `_safe_add_columns()` | Applies idempotent column migrations (safe to re-run) |
| `_seed_data()` | Seeds default users, event types, system MCPs |

Default accounts created on first run:

| Username | Password | Role |
|---|---|---|
| `admin` | `admin` | superuser |

> **New laptop / clean DB:** just start the server — everything initialises automatically. No `alembic upgrade` needed for SQLite dev setup.

### 2. Frontend

```bash
cd aiops-app
npm install

# Configure environment
cat > .env.local << 'EOF'
FASTAPI_BASE_URL=http://localhost:8000
INTERNAL_API_TOKEN=change-me-internal-token
NEXT_PUBLIC_APP_TITLE=AIOps Platform
EOF

npm run dev   # http://localhost:3000
```

> `INTERNAL_API_TOKEN` must match the value set in the backend `.env`.

### 3. OntologySimulator (optional — factory process demo data)

```bash
cd ontology_simulator/frontend
npm install && npm run dev   # http://localhost:8012
```

Once running, go to Admin → System MCPs and verify `get_process_context` and `get_process_history` point to `http://localhost:8012`.

## Environment Variables

See [`.env.example`](.env.example) for the full list. Key variables:

| Variable | Description |
|---|---|
| `DATABASE_URL` | SQLite (dev) or PostgreSQL (prod) |
| `SECRET_KEY` | JWT signing key — change in production |
| `LLM_PROVIDER` | `anthropic` or `ollama` |
| `ANTHROPIC_API_KEY` | Required when `LLM_PROVIDER=anthropic` |
| `ONTOLOGY_SIM_URL` | OntologySimulator base URL (default: `http://localhost:8012`) |
| `INTERNAL_API_TOKEN` | Shared token between Next.js proxy and FastAPI |

## Tech Stack

**Backend**
- FastAPI 0.115 + SQLAlchemy 2.0 (async)
- SQLite (dev) / PostgreSQL (prod) via aiosqlite / asyncpg
- Alembic migrations
- Claude (Anthropic) or Ollama for LLM features

**Frontend**
- Next.js 15 + React 19
- Inline styles (no Tailwind dependency)
- SSE streaming for AI generation console

## Docker

```bash
cp .env.example .env   # then edit .env
docker compose up
```

Services: `backend` (port 8000) · `frontend` (port 3000) · `simulator` (port 8012)

## API Docs

With the backend running, visit:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
