# fastapi_backend_service — Spec

**Date:** 2026-04-25
**HEAD:** 17b9112
**Status:** **OFFLINE — Decommissioned 2026-04-25** — Living Document

> ⛔ **本 service 已關機**（Phase 8-A-1d 完成）。`fastapi-backend.service` 已 stop + disable。
> 所有流量走 [Java :8002](../java-backend/SPEC.md) + [Python sidecar :8050](../python_ai_sidecar/SPEC.md)。
> nginx `/api/v1/`, `/health`, `/docs`, `/openapi.json` 全 reroute 到 `:8002`。
> 此 codebase 留作 git history 與未來考古；**不准 PR**。

---

## 1. 定位（now）

| 任務 | 狀態（2026-04-25） |
|---|---|
| Frontend `/api/v1/*` CRUD | ❌ **已遷至 Java :8002**（Frontend 透過 NextAuth proxy 走 `FASTAPI_BASE_URL=http://localhost:8002`） |
| Agent build (Glass Box) | ❌ **已 native 至 sidecar**；fallback dropped (commit `6e472ce`) |
| Pipeline executor (27 blocks) | ❌ **已 native 至 sidecar** [pipeline_builder/blocks/](../python_ai_sidecar/pipeline_builder/blocks/) |
| MCP / Skill / Auto-Patrol CRUD | ❌ Java 接管（`/api/v1/mcp-definitions`, `/api/v1/skills`, `/api/v1/auto-patrols`） |
| Auth / users | ❌ Java 接管（`/api/v1/auth/login`, `/api/v1/admin/users`） |
| **Agent chat (LangGraph orchestrator_v2)** | ⚠️ **唯一還活的路徑** — sidecar `/internal/agent/chat` 的 `FALLBACK_ENABLED=1` 透傳到這裡 |
| DB ownership | ❌ Java Flyway 接管；alembic 不再執行 |

**結論：** 這個 service 只剩**一個職責** — 提供 chat agent fallback 給 sidecar。一旦 [orchestrator_v2 4 個 DB-coupled node](../python_ai_sidecar/SPEC.md#6-chat-orchestrator-v2目前走-fallback) 全部 rewire 到 Java client（估 4-6h），就可以關掉 :8001。

## 2. 技術棧（凍結 — 不再升級）

| Category | Tech | Version |
|---|---|---|
| Framework | FastAPI + Uvicorn | 0.115.0 / 0.32.0 |
| Database | PostgreSQL + pgvector | asyncpg 0.30, pgvector ≥0.4 |
| Migration | Alembic（**已停用**，DB 由 Java Flyway own） | 1.14.0 |
| Agent Framework | LangGraph StateGraph | ≥0.2.0 |
| LangGraph Checkpointer | langgraph-checkpoint-postgres | ≥2.0 |
| LLM | Anthropic Claude | ≥0.49 |
| LLM 替代 | openai | ≥1.58 |
| 長期記憶 | mem0ai | ≥0.1.29 |
| Embeddings | bge-m3 via Ollama | 1024-dim |
| Vector Search | pgvector HNSW (cosine) | – |
| Scheduler | APScheduler（已被 Java cron 取代） | 3.11 |
| Auth | python-jose + passlib + bcrypt 3.2.2（與 4.x 不相容） | – |

## 3. 模組樹

```
fastapi_backend_service/
├── main.py                      FastAPI entry — 38 routers + lifespan
├── alembic/, alembic.ini        ⚠️ DB migration（已停用）
├── requirements.txt
├── app/
│   ├── config.py                pydantic-settings
│   ├── database.py              async engine + Base
│   ├── dependencies.py          DI helpers
│   ├── middleware.py            request logging
│   ├── scheduler.py             APScheduler（被 Java 取代後仍 import 但停用）
│   ├── models/                  31 個 SQLAlchemy ORM
│   ├── schemas/                 Pydantic IO schemas
│   ├── repositories/            DB query 層
│   ├── routers/                 38+ router file
│   ├── services/                48 個 service（business logic）
│   ├── core/                    exceptions / logging / response / security
│   ├── generic_tools/           v15.3 generic tool runtime
│   ├── skills/                  Skill engine（已被 sidecar 取代）
│   └── utils/
└── docs/history/                歷史 SPEC 快照
```

**Source LOC：** 38 routers + 48 services — 總量 ~30k LOC，**只有 chat agent 路徑還活著**。

## 4. 還活著的 API

僅以下被 sidecar fallback 命中：

| Path | 說明 | 上游 caller |
|---|---|---|
| `POST /api/v1/agent/chat` | LangGraph chat | sidecar `/internal/agent/chat` `FALLBACK_ENABLED=1` 時 |
| `POST /api/v1/agent/chat/stream` | SSE 版 | 同上 |
| `POST /api/v1/agent/execute` | tool dispatch | （fallback 用，很少觸發） |

其餘 38 個 router、48 個 service **都還在 codebase**，但 nginx 不再 route 進來、Frontend 已切到 Java。`grep` Frontend code 不會有 `${FASTAPI_BASE_URL}/api/v1/<其他 path>` 命中。

⚠️ **不要刪這些檔案** — chat orchestrator_v2 透過 [services/agent_orchestrator_v2/](fastapi_backend_service/app/services/agent_orchestrator_v2/) 跑，它依賴 `services/context_loader.py` / `services/agent_memory_service.py` / `tool_dispatcher.py` 等 ~20 個檔案。要拆乾淨就是 Phase 8-A-1d 的工作。

## 5. 資料模型（DB by Java）

31 個 SQLAlchemy ORM 在 [app/models/](fastapi_backend_service/app/models/)，但 **Java JPA Entity 才是真正的 schema owner**（透過 Flyway V0~V3）。Python ORM 只是 read 端的 type；不再 `Base.metadata.create_all()` 也不再跑 alembic。

⚠️ 改 schema 必須在 Java 加 Flyway migration，**禁止**只改 Python model。

## 6. Build / Deploy

- **Local：** 已不建議使用；要重現 chat fallback 行為時：
  ```
  uvicorn main:app --port 8001
  ```
- **Prod：** systemd unit [deploy/fastapi-backend.service](deploy/fastapi-backend.service)
  ```
  /opt/aiops/venv_backend/bin/uvicorn main:app --host 127.0.0.1 --port 8001
  EnvironmentFile=/opt/aiops/fastapi_backend_service/.env
  ```
- **Frontend 到此 service 的舊路徑：** nginx `/api/v1/` 仍 proxy 到 :8001（為了 `/docs`, `/openapi.json` 等），但 Frontend NextAuth proxy 是直接走 server-side `FASTAPI_BASE_URL=:8002`。雙路徑並存。

## 7. 環境變數（精簡，只列 chat fallback 還用到的）

| Variable | 說明 |
|---|---|
| `DATABASE_URL` | Postgres 連線（與 Java 同一個 DB） |
| `ANTHROPIC_API_KEY` | LLM key（chat fallback 用） |
| `ANTHROPIC_MODEL` | Claude model |
| `OLLAMA_BASE_URL` | bge-m3 embeddings |
| `MEM0_API_KEY` | 長期記憶 |
| `JWT_SECRET` | （Phase 2 共用，Phase 8 已遷到 Java） |

## 8. Decommission Roadmap

### Phase 8-A-1d（pending）— rewire chat node 到 Java client

1. `load_context_node` → 從 Java `/internal/mcp-definitions` + `/api/v1/skills`；UserPreference 需要 Java 補新 endpoint
2. `memory_lifecycle_node` → 從 Java `/internal/agent-memories`（已有）
3. `tool_execute_node` → MCP dispatch 已是 httpx + Java client reachable
4. 每個 node 接 `ctx` 而非 `db: AsyncSession`

### Phase 8-A-3（chat）— drop sidecar fallback

把 [python_ai_sidecar/routers/agent.py](../python_ai_sidecar/routers/agent.py#L46-L65) 的 `_chat_stream` 改成 native-only（與 build 同 pattern）。

### Phase 8-D — 關 :8001

完成 8-A-1d + 8-A-3 後：
1. systemd `systemctl disable --now fastapi-backend.service`
2. nginx 移除 `/api/v1/` 的 :8001 fallback proxy（保留 /docs 改路由到 Java）
3. **Code 不必刪**（git history 留著）但 deploy/update.sh 不再啟動

估剩餘工時：4-6h 密集 session。

## 9. 已知缺口

1. **alembic versions 與 Java Flyway 沒同步機制** — 任何 PR 改 alembic 都是 noop（DB 不再執行 alembic upgrade）
2. **routers/services/ 大部分是 dead code** — 但 chat fallback 的依賴鏈靜默地穿過它們，無法直接刪
3. **`FALLBACK_ENABLED` 變數在 sidecar，不是這裡** — debug 時容易找錯地方
4. **bcrypt 3.2.2 鎖死** — passlib 1.7.4 與 bcrypt 4.x 不相容，是這個 service 才需要的束縛；Java 那邊 BCryptPasswordEncoder 沒這問題
5. **`docs/history/` 沒整理** — 歷代 SPEC 散落，要查設計脈絡得人工挖
6. **APScheduler 仍 import** — 主流程不啟用，但 import 鏈還在；移除有風險
7. **mem0 / Ollama 仍 hardcoded** — chat fallback 結束時這些依賴一起拔

## 10. 變更指南

### 對 fastapi_backend_service 的 PR 一律拒絕，除非：
- 修 chat fallback 的明顯 bug（影響使用者體驗）
- Phase 8-A-1d 的 rewire 工作（rewire 完就刪 file）
- Decomm 工作（拔依賴）

### 新功能：去寫 [Java :8002](../java-backend/SPEC.md) 或 [sidecar :8050](../python_ai_sidecar/SPEC.md)。

### 緊急 hotfix：fix-forward 後**同時**在 Java 補對應 endpoint，不准只改這邊。
