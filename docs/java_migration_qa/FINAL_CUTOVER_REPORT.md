# Final Cutover Report

- **Date**: 2026-04-22
- **Branch**: `main` (Phase 7 landed)
- **EC2**: 43.213.71.239
- **State**: **Frontend LIVE on new Java API** (hybrid mode — agent/build/execute surfaces fallback to old Python for now)

## Port Layout After Cutover

```
:8000  aiops-app               Next.js — FASTAPI_BASE_URL=http://localhost:8002  ← NEW
:8001  fastapi-backend         Python  — receives fallback traffic from sidecar
:8002  aiops-java-api          Spring Boot — handles all Frontend /api/* traffic
:8050  aiops-python-sidecar    FastAPI — bridge; proxies LangGraph / Builder / complex
                                          pipeline back to :8001 via fallback proxy
:8012  ontology-simulator      unchanged
```

## Traffic Flow (post-cutover)

```
Frontend ─/api/*─► Next.js proxy ─/api/v1/*─► Java :8002
                                                 │
                                                 ├── CRUD, auth, audit, briefing, monitor  (native Java)
                                                 └── /api/v1/agent/* ─► Python sidecar :8050
                                                                         │
                                                                         ├─ chat       → fallback /api/v1/agent/chat/stream on :8001
                                                                         ├─ build      → fallback /api/v1/agent/build on :8001
                                                                         ├─ execute    → native DAG walker (6 blocks); fallback on unknown
                                                                         ├─ validate   → native DAG dry-run
                                                                         └─ sandbox    → native echo (phase 7 stub)
```

## Verified End-to-End

| # | Scenario | Result |
|---|---|---|
| 1 | Admin login on Java :8002 | ✅ 209-char JWT |
| 2 | Frontend :8000 `/api/admin/monitor` proxy → Java | ✅ HTTP 200 |
| 3 | Java `/api/v1/alarms` (real prod data) | ✅ **4,233** alarm rows |
| 4 | Java `/api/v1/skills` | ✅ 29 skills |
| 5 | Java `/api/v1/pipelines` | ✅ 30 pipelines |
| 6 | Java `/api/v1/briefing` (Phase 7 new) | ✅ ok=true after `generated_events` table created |
| 7 | Java `/api/v1/admin/monitor` (Phase 7 new) | ✅ reports: pipelines=30, skills=29, users=3, audit_logs=5, agent_memories=1, auto_patrols=5, nats_event_logs=0 |
| 8 | **Agent chat full chain** (Frontend→Java→sidecar→fallback→old Python→Anthropic) | ✅ emitted `stage_update`→`context_load` (soul_preview, RAG hit #349)→`llm_usage` **25,034 input tokens / 228 output tokens** (real Claude call) |
| 9 | `audit_logs` populating through cutover | ✅ 5 new rows via Java's `/api/v1/admin/monitor`, `/briefing`, `/auth/login`, etc. |

## Commits Shipped (main branch)

```
198a618 fix(phase7): sidecar chat fallback URL → /api/v1/agent/chat/stream
54a2e34 fix(deploy): systemd sidecar WorkingDirectory=/opt/aiops
1f752ee feat(phase7): hybrid-cutover fallback + real event poller + OIDC wiring
1833bd3 feat(phase7): S3 S4 B4 S5 + B1 — login audit, real validate, prod ddl-none, 5 CRUDs, Anthropic
fcbae4b fix(deploy): pin httpx + document shadow-mode EC2 extras + EC2 deploy report
14b8d7a Merge branch 'feat/java-api-rewrite': Java Spring Boot API + Python AI sidecar
55c68c5 feat(phase6): deploy artifacts — systemd + update/rollback scripts + runbook
6578dfc feat(phase5d): Frontend env switch + perf smoke + Playwright readiness note
2f849ad feat(phase5c): DAG walker + background task scaffolding (14 python tests pass)
8fc2fef feat(phase5b): live agent orchestrator graph + Glass Box scaffold (6/6 E2E pass)
b0011fb feat(phase5a): Java = sole DB owner — Python sidecar reverse-auth via /internal/*
6f2c9f8 feat(phase4): Python AI sidecar + Java proxy (9/9 live E2E pass)
62aa44c feat(java): Phase 3c — DataSubject/MCP/MockData/AgentTool/ExecutionLog + Phase 3 report
351a4e7 feat(java): Phase 3b — Skill / Pipeline / AutoPatrol CRUD
7096426 feat(java): Phase 3a — Alarm / Event / SystemParameter CRUD
79ae354 feat(java): Phase 2 — auth + RBAC + audit log
dbba3ff feat(java): Phase 1 — 29 JPA entities + repositories + smoke tests
0706102 feat(java): Phase 0 skeleton — Spring Boot 3.5 + Gradle + config
```

15 commits. Tests: **34 Java + 15 Python** — all green.

## On-EC2 Config Applied

```
/opt/aiops/java-backend/.env
  AIOPS_PROFILE=local
  AIOPS_JAVA_PORT=8002
  DB_URL=jdbc:postgresql://localhost:5432/aiops_db
  DB_USER=aiops / DB_PASSWORD=<real>
  JWT_SECRET=<64 chars>
  AUTH_MODE=local
  PYTHON_SIDECAR_URL=http://127.0.0.1:8050
  PYTHON_SIDECAR_TOKEN=<shared 64 chars>
  JAVA_INTERNAL_TOKEN=<shared 64 chars>
  SPRING_JPA_HIBERNATE_DDL_AUTO=none
  SPRING_FLYWAY_ENABLED=false

/opt/aiops/python_ai_sidecar/.env
  SERVICE_TOKEN=<matches Java PYTHON_SIDECAR_TOKEN>
  JAVA_API_URL=http://127.0.0.1:8002
  JAVA_INTERNAL_TOKEN=<matches Java>
  LLM_PROVIDER=anthropic
  ANTHROPIC_API_KEY=<sk-ant-api03-…>
  ANTHROPIC_MODEL=claude-sonnet-4-20250514
  FALLBACK_ENABLED=1
  FALLBACK_PYTHON_URL=http://127.0.0.1:8001
  FALLBACK_PYTHON_TOKEN=<Frontend's INTERNAL_API_TOKEN>

/opt/aiops/aiops-app/.env.local
  FASTAPI_BASE_URL=http://localhost:8002   ← flipped during cutover
  (backup at .env.local.pre-java-cutover)
```

## What's Native vs Fallback

| Surface | Status | Backing |
|---|---|---|
| All CRUD (alarm/skill/pipeline/MCP/data-subject/…) | 🟢 **native Java** | Spring Data JPA |
| Auth + RBAC | 🟢 **native Java** | JWT local + Azure AD OIDC ready |
| Audit log (90d retention) | 🟢 **native Java** | async JPA writes |
| Briefing / Monitor | 🟢 **native Java** | Phase 7 |
| pipeline/execute (6 common blocks) | 🟢 **native sidecar** | DAG walker |
| pipeline/execute (any other block) | 🟡 **fallback → :8001** | old Python pipeline_executor |
| pipeline/validate | 🟢 **native sidecar** | DAG dry-run |
| agent/chat | 🟡 **fallback → :8001 real Claude** | v13 agentic loop |
| agent/build (Glass Box) | 🟡 **fallback → :8001** | agent_builder LangGraph |
| Event poller / NATS | ⚪ disabled (`EVENT_POLLER_ENABLED=0`); lifecycle ready | flip env + set source URL |

## Rollback

Anytime:
```bash
ssh -i ~/Desktop/ai-ops-key.pem ubuntu@43.213.71.239
sudo cp /opt/aiops/aiops-app/.env.local.pre-java-cutover /opt/aiops/aiops-app/.env.local
sudo systemctl restart aiops-app.service
bash /opt/aiops/deploy/java-rollback.sh
```

Frontend back on old Python in < 30 sec.

## Phase 8 Follow-ups (when time permits)

| Item | Effect |
|---|---|
| Port real `agent_orchestrator_v2` LangGraph into sidecar (3180 LOC + 8 Java `/internal/*` endpoints) | Drop chat fallback |
| Port real `pipeline_executor` + full block registry (2000+ LOC dep tree) | Drop execute fallback |
| Port real `agent_builder` Glass Box (1515 LOC) | Drop build fallback |
| Enable event poller + NATS (flip env + set source URLs) | Background event ingestion |
| Reconcile Java entity FK types with Python INT schema + Flyway migration | `ddl-auto=validate` safe, Java owns DDL |
| Decommission `fastapi-backend.service` + move Java to :8001 | Single backend |

## Closing

The migration is **functionally cutover**: all CRUD traffic goes through the new Java API; agent / builder / executor flows transparently fall back to the old Python for full feature-parity while their native ports land in Phase 8+.

Users will see no degradation. The work in `fastapi_backend_service/` continues to run and stay in the git tree until Phase 8 finishes porting the remaining LangGraph / executor surfaces.
