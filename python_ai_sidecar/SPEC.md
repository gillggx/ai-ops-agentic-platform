# python_ai_sidecar — Spec

**Date:** 2026-04-25
**HEAD:** 5114b9b
**Status:** Living Document（依 code 實況萃取）

---

## 1. 定位

「**內部 AI / Executor sidecar**」— 只接 Java API 反向呼叫，所有對外流量都經過 Java :8002。
- LLM Agent runtime：Glass Box builder（native）+ chat orchestrator_v2（fallback）
- Pipeline Builder executor：27 個 pandas-based block 在這裡跑
- Sandbox：Skill Python 代碼執行
- Background：event_poller、NATS subscriber（env-gated，預設關）

**邊界：**
- 不接 Frontend（沒有 public CORS）
- 不直接 own DB（理論上：`_sidecar_deps._get_session_factory` raise NotImplementedError；實際上：legacy seedless registry path 仍透過 Java `/internal/*` 取資料）
- LLM key（Anthropic）只放在 sidecar 端，Java 看不到
- 所有 Java DB read/write 都走 [clients/java_client.py](python_ai_sidecar/clients/java_client.py)（Phase 5a 反向方向）

## 2. 技術棧

| Category | Tech | 版本 |
|---|---|---|
| Lang | Python | 3.11+ |
| Framework | FastAPI + Uvicorn | 0.115.4 / 0.32.0 |
| SSE | sse-starlette | 2.1.3 |
| LLM | anthropic（Claude） | ≥0.42 (httpx 0.28 compat) |
| HTTP | httpx | 0.28.1 |
| DataFrames | pandas / numpy / scipy | 2.2.3 / 2.1.3 / 1.14.1 |
| Validation | pydantic | 2.9.2 |
| ORM（only as transitive） | SQLAlchemy | 2.0.36（保留供 block_registry import 不爆，不開 session） |

**沒在 requirements 但 grep 有用：** mem0ai（agent_memory_service）、asyncpg / pgvector — Phase 8-A chat native 才會用到；目前 chat 走 fallback 不需要。

## 3. 模組樹

```
python_ai_sidecar/
├── main.py                       FastAPI entry + lifespan
├── config.py                     SidecarConfig dataclass（從 env load）
├── auth.py                       require_service_token + CallerContext
├── requirements.txt
├── routers/
│   ├── health.py                 GET /internal/health
│   ├── agent.py                  POST /internal/agent/{chat,build} （SSE）
│   ├── pipeline.py               POST /internal/pipeline/{execute,validate}
│   └── sandbox.py                POST /internal/sandbox/run
├── agent_builder/                ★ Glass Box builder — native
│   ├── orchestrator.py           Anthropic Claude tool-use loop
│   ├── prompt.py                 system prompt
│   ├── registry.py               builder tools
│   ├── session.py                in-memory session
│   └── tools.py                  add_node / connect / rename / generate_pipeline_json
├── agent_orchestrator_v2/        ★ Chat orchestrator — LangGraph (fallback to :8001 by default)
│   ├── orchestrator.py           graph runner
│   ├── graph.py                  StateGraph definition
│   ├── state.py                  AgentState TypedDict
│   ├── helpers.py                contract emit + chart middleware（含 hardcode `"$schema": "aiops-report/v1"`）
│   ├── adapter.py                schema 轉換
│   ├── render_card.py            card rendering
│   ├── session.py                LangGraph checkpointer
│   └── nodes/                    6 個 node：load_context / llm_call / tool_execute / self_critique / synthesis / memory_lifecycle
├── agent_helpers/                ★ Agent 共用工具（從舊 backend port 過來，DB-coupled）
│   ├── _model_stubs.py           SQLAlchemy model stubs（避免 import 爆）
│   ├── agent_memory_service.py   mem0 + pgvector long-term memory
│   ├── context_loader.py         讀 MCP / Skill / UserPreference 餵給 Agent
│   ├── task_context_extractor.py 從訊息抽 toolID / lotID / step
│   └── tool_dispatcher.py        分派 MCP / Skill 呼叫
├── pipeline_builder/             ★ Pipeline executor — 27 native blocks
│   ├── _sidecar_deps.py          shim：get_settings / get_session_factory / Repo stubs
│   ├── block_registry.py         BlockRegistry（DB-loading 路徑；目前 fallback 用 BUILTIN_EXECUTORS）
│   ├── block_schema.py           block spec dataclass
│   ├── pipeline_schema.py        pipeline DSL
│   ├── executor.py               DAG runner
│   ├── cache.py / column_aliases.py / doc_generator.py / prompt_hint.py
│   └── blocks/__init__.py        ★ BUILTIN_EXECUTORS dict — 27 blocks
├── executor/                     ★ 簡化版 6-block runtime（早期 Phase）
│   ├── block_runtime.py          REGISTRY: load_inline_rows / filter_rows / count_rows / group_count / render_table / render_line_chart
│   ├── dag.py
│   └── real_executor.py          DataFrame-aware
├── clients/
│   └── java_client.py            JavaAPIClient — sidecar → Java /internal/* 反向 fetch
├── fallback/
│   └── python_proxy.py           SSE stream proxy → :8001（fastapi_backend_service）
├── background/
│   ├── event_poller.py           輪詢 ontology /events
│   └── nats_subscriber.py        訂閱 OOC events
└── tests/
```

## 4. API Surface（全部 `/internal/*`）

| Method | Path | 流向 | 說明 |
|---|---|---|---|
| GET | `/internal/health` | – | health probe（不檢 token） |
| POST | `/internal/agent/chat` | SSE | **Native** — `AgentOrchestratorV2`（LangGraph）跑 in-process；DB 都走 Java client。Fallback 仍存但 prod `.env` 預設 `FALLBACK_ENABLED=0` |
| POST | `/internal/agent/build` | SSE | **Native only** — Glass Box builder（Phase 8-A-3 已 drop fallback；失敗就 SSE error event） |
| POST | `/internal/pipeline/execute` | sync | DAG runner — 跑 pipeline_json，回 row data |
| POST | `/internal/pipeline/validate` | sync | block 驗證（不執行） |
| POST | `/internal/sandbox/run` | sync | Skill Python sandbox 執行 |

**Auth：** 所有 `/internal/*`（除 health）都過 `ServiceAuth = Depends(require_service_token)`：
1. `X-Service-Token` 必須等於 env `SERVICE_TOKEN`
2. caller IP 在 `ALLOWED_CALLERS`（默認 `127.0.0.1,::1`）
3. Java 注入的 `X-User-Id` + `X-User-Roles` 解析成 `CallerContext`

## 5. Glass Box Agent Builder（native）

[agent_builder/](python_ai_sidecar/agent_builder/) — Anthropic Claude SDK ≥0.42 直驅。

**流程：** SSE event sequence
1. `pb_glass_start`（session_id, goal）
2. `pb_glass_op`（LLM 每呼一個 builder tool — add_node / connect / rename / etc.）
3. `pb_glass_chat`（LLM 自然語言段落）
4. `pb_glass_done`（status, summary, pipeline_json）

**Tools（[tools.py](python_ai_sidecar/agent_builder/tools.py)）：** add_node / connect_nodes / rename_node / list_blocks / generate_pipeline_json

Block catalog 從 Java `/internal/blocks` 拉（透過 [JavaAPIClient](python_ai_sidecar/clients/java_client.py)）。

## 6. Chat Orchestrator v2（native，Phase 8-A-1d 完成）

[agent_orchestrator_v2/](python_ai_sidecar/agent_orchestrator_v2/) — LangGraph StateGraph，6 個 node：

| Node | 任務 | DB / 外部依賴 |
|---|---|---|
| `load_context` | 讀 MCP / Skill / UserPreference / SystemParameter catalog | ✓ Java `/internal/*`（透過 `JavaAPIClient`） |
| `llm_call` | Claude tool-use | sidecar [llm_client](python_ai_sidecar/agent_helpers_native/llm_client.py)（Anthropic SDK） |
| `tool_execute` | 分派 MCP / Skill / build_pipeline_live | Java `/internal/pipelines`、`/internal/agent-sessions`、ToolDispatcher 透過 Java client |
| `self_critique` | 自我批判 / 重試 | sidecar llm_client |
| `synthesis` | 組 AIOpsReportContract | – |
| `memory_lifecycle` | abstract memory（LLM）+ Java pgvector 寫入 | sidecar [memory_abstraction](python_ai_sidecar/agent_helpers_native/memory_abstraction.py) + Java `/internal/agent-experience-memories` |

**Wiring：** [routers/agent.py:_chat_stream_native](python_ai_sidecar/routers/agent.py) 直接 instantiate `AgentOrchestratorV2(db=None, ...)`。`db=None` 觸發每個 node 走 Java client 路徑。

**Fallback：** 仍存在於 [fallback/python_proxy.py](python_ai_sidecar/fallback/python_proxy.py)，但 prod `.env` 預設 `FALLBACK_ENABLED=0`，因此實際從不命中。Phase 8-D 會徹底刪掉 + 關 :8001（已關，2026-04-25）。

## 7. Pipeline Builder Executor（27 blocks native）

[pipeline_builder/blocks/](python_ai_sidecar/pipeline_builder/blocks/) — 每個 block 一個 file，繼承 [BlockExecutor](python_ai_sidecar/pipeline_builder/blocks/base.py)，在 [`__init__.py`](python_ai_sidecar/pipeline_builder/blocks/__init__.py#L33-L61) 統一登錄到 `BUILTIN_EXECUTORS`：

```
block_process_history    block_filter           block_join             block_groupby_agg
block_shift_lag          block_rolling_window   block_threshold        block_consecutive_rule
block_delta              block_weco_rules       block_linear_regression block_histogram
block_sort               block_unpivot          block_union            block_cpk
block_any_trigger        block_correlation      block_hypothesis_test  block_ewma
block_mcp_call           block_mcp_foreach      block_count_rows       block_chart
block_alert              block_data_view        block_compute
```

Block 邏輯與 fastapi_backend_service 完全一致（為了 git blame 乾淨），DB / config 依賴透過 [_sidecar_deps.py](python_ai_sidecar/pipeline_builder/_sidecar_deps.py) 蓋 shim。

DB-touching block（`block_mcp_call`, `block_mcp_foreach`）走 [JavaAPIClient](python_ai_sidecar/clients/java_client.py) → Java `/internal/mcp-definitions`。

## 8. Fallback Path

[fallback/python_proxy.py](python_ai_sidecar/fallback/python_proxy.py) — 把任何 sidecar 處理不了的 SSE 流透傳給 :8001（fastapi_backend_service）。

| Env | Default | 行為 |
|---|---|---|
| `FALLBACK_ENABLED=1` | ✓ | 開啟（chat 走這） |
| `FALLBACK_ENABLED=0` | – | 關閉 — chat 直接走 native（會因 DB session 缺失炸） |
| `FALLBACK_PYTHON_URL` | `http://127.0.0.1:8001` | 舊 backend |
| `FALLBACK_TIMEOUT_SEC` | `600` | LangGraph 慢 query 上限 |

## 9. Background Tasks（lifespan-managed）

| Task | Env flag | 行為 |
|---|---|---|
| `event_poller` | `EVENT_POLLER_ENABLED=1` | 輪詢 ontology `/api/v1/events`，抓新 event 觸發 Auto-Patrol |
| `nats_subscriber` | `NATS_SUBSCRIBER_ENABLED=1` | 訂閱 `aiops.events.ooc`，event-driven Auto-Patrol |

兩者都預設 `0`（關閉），ops 端按需開啟 — 不要兩個一起開（會雙觸發）。

## 10. Build / Deploy

- **Local：** `uvicorn python_ai_sidecar.main:app --port 8050 --reload`
- **Prod：** systemd unit [deploy/aiops-python-sidecar.service](deploy/aiops-python-sidecar.service)
  ```
  /opt/aiops/venv_sidecar/bin/uvicorn python_ai_sidecar.main:app \
    --host 127.0.0.1 --port 8050 --workers 1
  ```
  - **Workers=1** — 因為 background task 不能跑兩份
  - `Requires=aiops-java-api.service` — sidecar 開機順序在 Java 之後
- **deploy 入口**：`bash deploy/update.sh`

## 11. 環境變數（[deploy/aiops-python-sidecar.env.example](deploy/aiops-python-sidecar.env.example)）

| Variable | Default | 說明 |
|---|---|---|
| `SERVICE_TOKEN` | `dev-service-token` | Java → sidecar 的 `X-Service-Token` |
| `ALLOWED_CALLERS` | `127.0.0.1,::1` | 白名單 IP |
| `SIDECAR_PORT` | `8050` | listen port |
| `JAVA_API_URL` | `http://localhost:8002` | sidecar → Java 反向呼叫 |
| `JAVA_INTERNAL_TOKEN` | `dev-internal-token` | sidecar → Java `X-Internal-Token` |
| `JAVA_TIMEOUT_SEC` | `30` | – |
| `LLM_PROVIDER` | `anthropic` | stub 或 anthropic |
| `ANTHROPIC_API_KEY` | – | Claude |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-20250514` | – |
| `ANTHROPIC_MAX_TOKENS` | `1024` | – |
| `EVENT_POLLER_ENABLED` | `0` | – |
| `NATS_SUBSCRIBER_ENABLED` | `0` | – |
| `FALLBACK_ENABLED` | `1` | chat fallback 開關 |
| `FALLBACK_PYTHON_URL` | `http://127.0.0.1:8001` | fastapi_backend_service |
| `FALLBACK_TIMEOUT_SEC` | `600` | – |

## 12. 已知缺口

1. ~~**Chat 還在 fallback**~~ — ✅ 解決（Phase 8-A-1d, 2026-04-25）：chat 完全 native，:8001 已關
2. **`agent_helpers/_model_stubs.py`** — sqlalchemy model 是 stub，僅給 in-process 測試 fallback 用
3. **`block_registry.py` 改走 Java** — `load_from_db` 變成 alias 到 `load_from_java`，DB 路徑已拔；可以再清掉 sqlalchemy import
4. **`executor/block_runtime.py` 是 6-block 玩具版** — pipeline_builder/ 有 27 blocks 是真實版；兩套 registry 並存容易誤用
5. **`hardcode "$schema": "aiops-report/v1"`** in helpers.py L321/L413 — 應 import `aiops_contract.SCHEMA_VERSION`
6. **`fallback/python_proxy.py`** 仍在 — prod `FALLBACK_ENABLED=0`，下波清理徹底刪掉

## 13. 變更指南

### 加 endpoint
- 放 `routers/`，prefix 必為 `/internal/<scope>`
- handler 第一個 dep 必是 `caller: CallerContext = ServiceAuth`
- SSE 用 `EventSourceResponse`

### 加 block
1. 新增 `pipeline_builder/blocks/<name>.py`，繼承 `BlockExecutor`
2. 在 [`blocks/__init__.py`](python_ai_sidecar/pipeline_builder/blocks/__init__.py) 加 import + 加進 `BUILTIN_EXECUTORS` dict
3. 同步在 Java DB 加 PbBlock row（透過 admin API 或 deploy script）
4. **block 邏輯與 fastapi_backend_service 對應檔案保持 byte-equal**（除 `from app.*` import）

### 接 Java endpoint
- 不要 `import httpx` 自幹；用 [JavaAPIClient](python_ai_sidecar/clients/java_client.py)
- 新增 method 命名 `await client.list_xxx() / get_xxx_by_id()`，內部組 path + headers

### LLM key 管理
- 只放 sidecar `.env`，**禁止**放 Java env 或 Frontend
- prompt cache 上限：`ANTHROPIC_MAX_TOKENS=1024`（chat），builder 在 [orchestrator.py](python_ai_sidecar/agent_builder/orchestrator.py) 自定
