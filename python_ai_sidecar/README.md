# python_ai_sidecar

> **狀態**: Phase 4 skeleton — 提供 Java API 呼叫的「AI/Executor」微服務。
> **Port**: `8050`
> **語言**: Python 3.11 + FastAPI

---

## 責任界線 (per SPEC §2.5)

這個 sidecar 保留所有**只能在 Python 跑**的邏輯：

- LangGraph Agent orchestrator (`agent_orchestrator_v2/`)
- Pipeline Builder Glass Box Agent (`agent_builder/`)
- Pipeline Executor (pandas / scipy / sklearn)
- Event Poller (MongoDB tail)
- NATS subscriber
- Python sandbox for user scripts

**不負責**：user / role / auth 認證、CRUD、audit — 這些都在 Java API (port 8001) 做。

---

## Contract

所有 endpoint 掛在 `/internal/*`，**只接受 Java API 呼叫**（由 `X-Service-Token` 擋住）。Frontend 不直接打 sidecar。

| Endpoint | 說明 | 回應型態 |
|---|---|---|
| `POST /internal/agent/chat` | LangGraph chat | SSE stream |
| `POST /internal/agent/build` | Pipeline Builder Glass Box Agent | SSE stream (`pb_glass_*` events) |
| `POST /internal/pipeline/execute` | Pipeline DAG 執行 | JSON |
| `POST /internal/pipeline/validate` | Dry-run 驗證 | JSON |
| `POST /internal/sandbox/run` | 跑使用者 Python code | JSON |
| `GET  /internal/health` | liveness | JSON |

### Authentication
所有 endpoint 必須帶：
```
X-Service-Token: <env SERVICE_TOKEN>
```
否則 401。

### User context
Java 會注入以下 header（不是 JWT）讓 sidecar 知道誰在呼叫，但 sidecar **不再做 auth 決策**（已在 Java 擋掉）：
```
X-User-Id: 42
X-User-Roles: IT_ADMIN,PE
```

---

## 本機啟動

```bash
cd python_ai_sidecar
pip install -r requirements.txt

# .env
export SERVICE_TOKEN="dev-service-token"
export SIDECAR_PORT=8050

uvicorn main:app --port 8050 --reload
```

健康檢查：
```bash
curl -H "X-Service-Token: dev-service-token" http://localhost:8050/internal/health
```

---

## Phase 4 Status

- [x] FastAPI skeleton + service-token guard
- [x] 6 endpoint routes with mock responses
- [x] SSE-capable `/agent/chat` and `/agent/build`
- [ ] Wire `agent_orchestrator_v2` into `/agent/chat` (Phase 4b stretch)
- [ ] Wire `pipeline_builder` into `/agent/build` (Phase 4b stretch)
- [ ] Wire `pipeline_executor.py` into `/pipeline/execute` (Phase 4b stretch)

Phase 5/6 會把實際 Python 業務邏輯從 `fastapi_backend_service/` 搬進來。Phase 4 只驗 contract + proxy work。
