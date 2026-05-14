# AIOps Platform v2.0

半導體製造廠的 **AI Agent 平台**。製程工程師透過自然語言對話完成異常根因分析、設備診斷、自動化巡檢。

---

## Architecture (current — 2026-05-14)

```
┌──────────────────────────────────────────────────────────────────┐
│  aiops-app  (Next.js 15 standalone · React 19)        Port 8000  │
│  ─ UI rendering + /api/ proxy routes only                        │
│  ─ Talks to java-backend :8002 and python_ai_sidecar :8050       │
└────────────────────────────┬─────────────────────────────────────┘
                             │ HTTPS (via nginx)
        ┌────────────────────┴────────────────────┐
        │                                         │
        ▼                                         ▼
┌──────────────────────────────┐    ┌─────────────────────────────┐
│  java-backend (Spring Boot)  │    │  python_ai_sidecar          │
│  Port 8002 — sole DB owner   │    │  Port 8050 — agents + exec  │
│                              │    │                             │
│  • Auth (JWT)                │    │  • Chat orchestrator (v2)   │
│  • PostgreSQL + pgvector     │    │  • Glass Box builder        │
│  • Pipeline / Skill registry │    │  • Block Advisor            │
│  • Alarm + role audit        │    │  • 50+ block executors      │
│  • /api/v1/* user-facing     │    │  • Pipeline executor        │
│  • /internal/* service-only  │    │  • Calls Java via JavaClient│
└────────┬─────────────────────┘    └────────┬────────────────────┘
         │                                    │
         │                                    │ HTTP (data fetch)
         ▼                                    ▼
   PostgreSQL                       ┌────────────────────────┐
   (sole owner: java-backend)       │  ontology_simulator    │
                                    │  Port 8012             │
                                    │  Synthetic process data│
                                    │  LOT/TOOL/SPC/APC/...  │
                                    │  MongoDB + NATS bus    │
                                    └────────────────────────┘
```

**Service ports (EC2 single-host)**:
| Service | Port | Manager |
|---|---|---|
| aiops-app | 8000 | systemd: aiops-app.service |
| aiops-java-api | 8002 | systemd: aiops-java-api.service |
| python_ai_sidecar | 8050 | systemd: aiops-python-sidecar.service |
| ontology-simulator | 8012 | systemd: ontology-simulator.service |
| (legacy) fastapi_backend_service | 8001 | decommissioned 2026-04-25 |

For K8s future deployment, each service builds its own Docker image (8080→80, service-name routing). See `docs/devOps_technique_guide_2.0.md`.

**aiops-contract**（獨立 package）定義 Agent ↔ Frontend 的共用型別（AIOpsReportContract）。

---

## Stack versions

- Java: **Temurin 17** + Spring Boot 3.5.14 + Maven
- Python: **3.11**
- Node.js: **20.18** (Next.js 15, React 19)
- PostgreSQL: **17** + pgvector
- LLM: Anthropic Claude (Opus/Sonnet routed by graph)
- Embedding: Ollama bge-m3

## Local dev quickstart

```bash
# 1. Postgres + simulator (one-time)
brew services start postgresql@17
createdb aiops

# 2. Each service in its own shell
cd ontology_simulator && bash start.sh           # :8012
cd java-backend && mvn spring-boot:run            # :8002
cd python_ai_sidecar && uvicorn main:app --port 8050  # :8050
cd aiops-app && npm run dev                       # :3000 (dev) or :8000 (prod build)
```

⚠️ The root `start.sh` is **DEPRECATED** — references the retired fastapi_backend_service.

## Deploy (EC2)

```bash
# Frontend + simulator
bash deploy/update.sh

# Java + sidecar
bash deploy/java-update.sh
```

systemd units in `deploy/aiops-*.service`. nginx config in `deploy/nginx.conf`.

---

## Projects

| Project | 說明 | Spec |
|---------|------|------|
| [fastapi_backend_service](fastapi_backend_service/) | Backend API + AI Agent | [SPEC.md](fastapi_backend_service/SPEC.md) |
| [aiops-app](aiops-app/) | Frontend (Next.js) | [SPEC.md](aiops-app/SPEC.md) |
| [ontology_simulator](ontology_simulator/) | 製程模擬器 (MongoDB) | [SPEC.md](ontology_simulator/SPEC.md) |

---

## Quick Start

### Prerequisites

- Python 3.11+, Node.js 20+
- PostgreSQL 17 + pgvector extension
- MongoDB（for ontology_simulator）
- Anthropic API key **or** Ollama

### 1. Clone

```bash
git clone https://github.com/gillggx/aiops-platform.git
cd aiops-platform
```

### 2. Backend

```bash
cd fastapi_backend_service
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env   # edit DATABASE_URL, ANTHROPIC_API_KEY, SECRET_KEY
uvicorn main:app --reload --port 8000
```

首次啟動自動建表 + seed（default users, system MCPs, event types）。
Default login: **admin / admin**

### 3. Frontend

```bash
cd aiops-app
npm install
cat > .env.local << 'EOF'
FASTAPI_BASE_URL=http://localhost:8000
INTERNAL_API_TOKEN=any-shared-secret
EOF
npm run dev
```

Open [http://localhost:3000](http://localhost:3000)

### 4. Simulator

```bash
cd ontology_simulator
pip install -r requirements.txt
PORT=8012 uvicorn main:app --port 8012
```

### All-in-one

```bash
bash start.sh
```

---

## Core Features

| Feature | 說明 |
|---------|------|
| **AI Agent (Copilot)** | 自然語言對話，LangGraph v2 orchestrator，6-stage pipeline |
| **Diagnostic Rules** | AI 兩階段生成診斷規則（step plan → per-step code），sandbox 試跑 |
| **Auto-Patrol** | 排程 / 事件驅動巡檢，condition_met → 自動建立 Alarm |
| **MCP System** | Agent 的工具集 — System MCP（資料源）+ Custom MCP + Automation MCP |
| **Experience Memory** | pgvector 向量搜尋 + 反思式生命週期（Write → Retrieve → Feedback → Decay） |
| **Analysis → Promote** | Agent ad-hoc 分析可一鍵提升為永久 Diagnostic Rule |
| **Contract Rendering** | AIOpsReportContract — Vega-Lite 圖表 + evidence chain + suggested actions |

---

## Environment Variables

See [`.env.example`](.env.example) for full list.

| Variable | 說明 |
|----------|------|
| `DATABASE_URL` | PostgreSQL 連線字串 |
| `ANTHROPIC_API_KEY` | Claude API key |
| `OLLAMA_BASE_URL` | Ollama endpoint (bge-m3 embedding) |
| `ONTOLOGY_SIM_URL` | OntologySimulator base URL (default: localhost:8012) |
| `SECRET_KEY` | JWT signing key |
| `INTERNAL_API_TOKEN` | Next.js ↔ FastAPI shared token |

---

## Documentation

- Historical specs and PRDs: [`docs/history/`](docs/history/)
- Per-project specs: each project's `SPEC.md`
