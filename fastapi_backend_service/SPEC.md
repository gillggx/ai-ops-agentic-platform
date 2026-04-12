# fastapi_backend_service — Spec 2.0

**Date:** 2026-04-06
**Status:** Living Document (Current Implementation)

---

## 1. 定位

AIOps 平台的 **Backend API + AI Agent 核心**。負責：

- AI Agent 對話 orchestration（LangGraph v2 + v1 fallback）
- MCP（Model Context Protocol）tool dispatch — 代理 Agent 呼叫外部資料源
- Skill / Diagnostic Rule 管理 — 定義、LLM 生成、sandbox 執行
- Auto-Patrol 自動巡檢排程
- 長期記憶系統（pgvector 向量搜尋 + 反思式生命週期）
- 使用者認證 / 系統設定

## 2. 技術棧

| Category | Tech | Version |
|----------|------|---------|
| Framework | FastAPI + Uvicorn | 0.115 / 0.32 |
| Database | PostgreSQL + pgvector | asyncpg 0.30 |
| Agent Framework | LangGraph (StateGraph) | >= 0.2.0 |
| LLM | Anthropic Claude | anthropic >= 0.49 |
| Embeddings | bge-m3 via Ollama | 1024-dim |
| Vector Search | pgvector HNSW | cosine similarity |
| Scheduler | APScheduler | 3.11 |
| Message Bus | NATS (optional) | nats-py >= 2.9 |
| Data Science Sandbox | numpy, pandas, scipy, scikit-learn | — |
| HTTP Client | httpx | 0.28 |
| Auth | JWT (python-jose) + bcrypt | — |

## 3. 目錄結構

```
fastapi_backend_service/
├── main.py                    # App startup, middleware, data seeding
├── app/
│   ├── config.py              # Settings (env-based via pydantic-settings)
│   ├── core/
│   │   ├── exceptions.py      # Custom exception classes
│   │   ├── logging.py         # Structured logging setup
│   │   ├── response.py        # StandardResponse wrapper
│   │   └── security.py        # JWT encode/decode, password hashing
│   ├── models/                # SQLAlchemy ORM models (§4)
│   ├── schemas/               # Pydantic request/response schemas
│   ├── repositories/          # DB query layer (Repository pattern)
│   ├── routers/               # FastAPI route handlers (§5)
│   └── services/              # Business logic (§6)
├── requirements.txt
└── docs/history/              # Archived documentation
```

## 4. 資料模型 (PostgreSQL)

### 4.1 核心 Models

| Model | Table | 說明 |
|-------|-------|------|
| `SkillDefinitionModel` | `skill_definitions` | 統一 Skill（source + binding_type 決定用途） |
| `MCPDefinitionModel` | `mcp_definitions` | System MCP（資料源端點）+ Custom MCP |
| `AutoPatrolModel` | `auto_patrols` | 自動巡檢定義（綁定 Skill + Alarm 規則） |
| `AlarmModel` | `alarms` | Auto-Patrol 產生的告警（severity + evidence） |
| `AgentExperienceMemoryModel` | `agent_experience_memory` | 反思式長期記憶（含 pgvector embedding） |
| `AgentSessionModel` | `agent_sessions` | 對話 session（滑動視窗 + 階層摘要） |
| `AgentMemoryModel` | `agent_memories` | Legacy RAG 記憶（v1） |

### 4.2 支援 Models

| Model | Table | 說明 |
|-------|-------|------|
| `UserModel` | `users` | 使用者帳號 + 角色 (JSON) |
| `DataSubjectModel` | `data_subjects` | 資料主題定義（input/output schema） |
| `EventTypeModel` | `event_types` | 事件類型登錄（SPC_OOC, RECIPE_CHANGE, etc.） |
| `CronJobModel` | `cron_jobs` | APScheduler Cron 排程紀錄 |
| `ScriptVersionModel` | `script_versions` | Skill 腳本版本管理（draft → active → archived） |
| `ExecutionLogModel` | `execution_logs` | Skill 執行歷史（duration, status, output） |
| `NatsEventLogModel` | `nats_event_log` | NATS 事件接收紀錄 |

> **Note (2026-04-09)：** `SkillAuthoringSessionModel` / `skill_authoring_sessions` table 已移除。原本的「多輪對話式 Skill 建立」流程改為 **inline clarification**（見 §6.6 Phase 0 + §5.2 skip_clarify），由既有的 generate-steps SSE endpoint 內嵌一次輕量 clarify 檢查，不再維護獨立 session。

### 4.3 Skill 資料結構（Unified Skill Architecture）

所有 source 類型共用相同 schema：

```
steps_mapping:  [{step_id, nl_segment, python_code}]
input_schema:   [{key, type, required, description}]
output_schema:  [{key, type, label, unit?, columns?, x_key?, y_keys?, group_key?, value_key?, ucl_key?, lcl_key?, highlight_key?}]
```

**source 欄位**（誰建立的）：
- `source="skill"` — 使用者透過 My Skills 建立（LLM 生成或手動）
- `source="rule"` — AI 兩階段生成（Phase 2a: step plan → Phase 2b: per-step code）
- `source="auto_patrol"` — 手動定義，嵌在 patrol 實體內
- `source="legacy"` — 通用 Skill

**binding_type 欄位**（綁定到什麼觸發方式）：
- `binding_type="none"` — My Skill / chat 中使用，不綁定觸發器
- `binding_type="event"` — 綁定為 Auto-Patrol（event-driven 觸發）
- `binding_type="alarm"` — 綁定為 Diagnostic Rule（alarm-driven 觸發）

**Skill 生命週期**：
1. Agent 對話分析 → 使用者點擊「儲存為我的 Skill」→ `source=skill, binding_type=none`
2. My Skill 可升級為 Auto-Patrol（`binding_type=event`）或 Diagnostic Rule（`binding_type=alarm`）

## 5. API Routers

### 5.1 Agent 對話

| Method | Path | 說明 |
|--------|------|------|
| `POST` | `/agent/chat/stream` | SSE 串流 Agent 對話（v1 orchestrator） |
| `POST` | `/agent/chat/stream?engine=v2` | SSE 串流 Agent 對話（LangGraph v2） |
| `GET` | `/agent/sessions/{sid}/workspace` | 讀取 canvas workspace state |
| `POST` | `/agent/approve/{token}` | HITL approval gate |

### 5.2 Knowledge Studio

| Method | Path | 說明 |
|--------|------|------|
| `GET/POST` | `/diagnostic-rules` | Diagnostic Rule CRUD |
| `POST` | `/diagnostic-rules/generate-steps/stream` | SSE 串流 LLM 生成 steps |
| `POST` | `/diagnostic-rules/{id}/try-run` | Sandbox 試跑 |
| `GET/POST/PATCH/DELETE` | `/my-skills` | My Skills CRUD |
| `POST` | `/my-skills/generate-steps/stream` | SSE 串流 LLM 生成 Skill steps |
| `POST` | `/my-skills/{id}/try-run` | My Skill sandbox 試跑 |
| `POST` | `/my-skills/{id}/bind` | 升級 Skill binding_type（none → event/alarm） |
| `GET/POST/PATCH` | `/auto-patrols` | Auto-Patrol CRUD |
| `POST` | `/auto-patrols/{id}/trigger` | 手動觸發巡檢 |
| `GET/POST/PATCH` | `/mcp-definitions` | MCP 定義 CRUD |
| `POST` | `/mcp-definitions/{id}/sample-fetch` | 測試 MCP 端點 |
| `GET/POST/PATCH` | `/skill-definitions` | Skill 定義 CRUD |

> **Note (2026-04-09)：** `/api/v1/skill-authoring/*` router（8 endpoints）已移除。改為 `generate-steps/stream` 內嵌 Phase 0 clarify 檢查 — request 支援 `skip_clarify: bool` 欄位，SSE 可 yield `clarify_needed` event（帶 1~2 questions）讓前端中斷、收集答案後帶 `skip_clarify=true` 重新呼叫。

### 5.3 Analysis（Ad-hoc）

| Method | Path | 說明 |
|--------|------|------|
| `POST` | `/analysis/run` | 執行 Agent 生成的 ad-hoc 分析腳本 |
| `POST` | `/analysis/promote` | 將 ad-hoc 分析儲存為 My Skill（source=skill, binding_type=none） |

### 5.4 Memory

| Method | Path | 說明 |
|--------|------|------|
| `GET/POST/DELETE` | `/experience-memory` | 反思式記憶 CRUD |
| `GET/POST/DELETE` | `/agent/memory` | Legacy RAG 記憶 CRUD |

### 5.5 System

| Method | Path | 說明 |
|--------|------|------|
| `POST` | `/auth/login` | JWT 登入 |
| `GET/PATCH` | `/users` | 使用者管理 |
| `GET/PATCH` | `/system-parameters` | 系統參數（LLM prompts 等） |
| `POST` | `/system-events/ingest` | Webhook 事件接收 |
| `GET/POST` | `/cron-jobs` | Cron 排程管理 |
| `GET` | `/alarms` | 告警列表 |

## 6. 核心 Services

### 6.1 Agent Orchestrator

兩個版本並存：

- **v1** (`agent_orchestrator.py`, ~98KB) — 單檔 monolith，6-stage pipeline：
  Context Load → Planning → Tool Calls → Reasoning → Self-Critique → Memory Write
- **v2** (`agent_orchestrator_v2/`) — LangGraph StateGraph 重構：
  - `state.py` — TypedDict state 定義
  - `graph.py` — StateGraph 節點串接
  - `nodes/` — load_context, llm_call, tool_execute, synthesis, self_critique, memory_lifecycle
  - `adapter.py` — LangGraph events → v1 SSE format 轉換
  - `session.py` — Session load/save (sliding window + hierarchical summarization)
  - `orchestrator.py` — v2 entry point (v1-compatible `.run()` interface)

Feature flag `?engine=v2` 切換。

### 6.2 Tool Dispatcher

`tool_dispatcher.py` (~43KB) — Agent 呼叫工具的統一入口：

- `execute_skill` — 執行 Skill（sandbox python）
- `execute_analysis` — 執行 ad-hoc 分析（Agent 生成的 steps_mapping）
- `execute_mcp` → 委派到 `mcp_definition_service.py`
- Preflight validation（必填參數、format check）
- render_card 生成（供前端渲染）
- 呼叫 ChartMiddleware 自動產生 chart DSL（取代過去的手動 _chart 組裝）

### 6.3 Context Loader

`context_loader.py` (~32KB) — 建構 LLM System Prompt：

- Soul Prompt（行為鐵律 §1.1 ~ §1.16）
- MCP Catalog 注入（DB 中 active 的 System + Custom MCPs）
- User Preference 載入
- RAG Memory 檢索（pgvector cosine + 關鍵字混合）
- Session History 注入

### 6.4 MCP Definition Service

`mcp_definition_service.py` (~65KB) — MCP 端點管理 + 呼叫代理：

- System MCP 代理呼叫（GET/POST → OntologySimulator endpoints）
- `since` 時間窗參數正規化（`24h` → ISO8601 start_time）
- `object_name/object_id` → `toolID/lotID` 參數映射
- SPC chart_name alias 正規化

### 6.5 Memory System

- **Experience Memory** (`experience_memory_service.py`) — Phase 1 反思式記憶：
  - Write: LLM 抽象化 → bge-m3 embedding → pgvector 儲存
  - Retrieve: hybrid filter（cosine + keyword + recency）
  - Feedback: confidence scoring（UP/DOWN/HUMAN_REJECTED）
  - Decay: STALE 標記 + 自動清理
- **Memory Abstraction** (`memory_abstraction.py`) — 記憶摘要模板

### 6.6 Diagnostic Rule Service

`diagnostic_rule_service.py` — AI 診斷規則生成（同一個 service 也負責 My Skill / Auto-Patrol 的 steps 生成）：

- **Phase 0 — `quick_clarify_check()`（2026-04-09 新增）：** 在正式生成前跑一次輕量 LLM 呼叫，判斷使用者的 NL description 是否真的缺少關鍵商業邏輯資訊。
  - 回傳 `None` → 資訊足夠，直接進入 Phase 1
  - 回傳 `{"questions": [...]}` → 1~2 個問題，每題含 `default` + `options`（button choices）+ 可選 freetext
  - **嚴格禁止詢問**：input 欄位來源、output 格式、要用哪支 MCP、使用者已明示的參數值。只針對真正模糊的商業邏輯（e.g. 時間窗口 N days、threshold、ID 比對 vs 值比對）
- Phase 1: MCP planner — 從 NL 描述規劃需要哪些 MCP 呼叫
- Phase 2a: Step planner — 拆解為多個 step（nl_segment）
- Phase 2b: Per-step code — 逐 step 生成 python_code
- SSE streaming 支援

**`generate_steps_stream()` 新流程：**

```
request (skip_clarify=false 預設)
  ↓
Phase 0 quick_clarify_check
  ├─ 需要澄清 → yield SSE event "clarify_needed" {questions: [...]} → 結束
  └─ 不需要 → 繼續
  ↓
Phase 1 → 2a → 2b（原流程）
```

Frontend 接到 `clarify_needed` 後彈出 `ClarifyDialog`，使用者回答後把答案 append 到 description 並以 `skip_clarify=true` 重新呼叫同一個 endpoint，跳過 Phase 0。

**Request schema：** `GenerateRuleStepsRequest` 新增 `skip_clarify: bool = False` 欄位，同時套用在 `/diagnostic-rules/generate-steps/stream`、`/my-skills/generate-steps/stream`、Auto-Patrol 建立流程。

### 6.7 其他 Services

| Service | 說明 |
|---------|------|
| `auto_patrol_service.py` | Auto-Patrol CRUD + manual trigger + 嵌入 Skill 建立 |
| `chart_middleware.py` | Registry-based 自動圖表生成（output_schema type → chart DSL） |
| `skill_executor_service.py` | Sandbox 執行 Skill python_code |
| `cron_scheduler_service.py` | APScheduler cron 排程管理 |
| `alarm_service.py` | Alarm 建立 + severity 判斷 |
| `nats_subscriber_service.py` | NATS event bus 訂閱 |
| `auth_service.py` | JWT token 生成 + 驗證 |
| `sandbox_service.py` | 安全沙盒執行環境（exec + 受限 globals） |

### 6.8 ChartMiddleware

`chart_middleware.py` — Registry-based 圖表自動生成中間層：

**定位**：LLM 生成的 Skill code 只需在 `_findings.outputs` 放入 raw data，ChartMiddleware 根據 `output_schema` 中的 `type` 欄位自動產生 chart DSL，前端直接渲染。

**架構變更**：
```
Before: Simulator → _charts (chart DSL) → Frontend
         LLM code → _chart manual assign → Frontend
After:  Simulator → pure data → Backend ChartMiddleware → chart DSL → Frontend
        LLM code → data in outputs + output_schema type → ChartMiddleware → chart DSL → Frontend
```

**Built-in Builders**：

| output_schema type | Builder | 說明 |
|--------------------|---------|------|
| `spc_chart` | `_build_spc_chart` | 依 `group_key` 拆分為獨立 SPC 管制圖（e.g. xbar/r/s/p/c），每圖獨立 UCL/LCL rule lines |
| `line_chart` | `_build_line_chart` | 單一折線圖，自動偵測 data 中的 UCL/LCL 加 rule lines |
| `bar_chart` | `_build_bar_chart` | 長條圖 |
| `scatter_chart` | `_build_scatter_chart` | 散佈圖 |
| `multi_line_chart` | `_build_multi_line_chart` | 依 `group_key` 拆分為多張折線圖 |

**spc_chart output_schema 範例**：
```json
{"key": "spc_data", "type": "spc_chart", "label": "SPC管制圖",
 "group_key": "chart_type", "x_key": "eventTime",
 "value_key": "value", "ucl_key": "ucl", "lcl_key": "lcl", "highlight_key": "is_ooc"}
```

**擴充方式**：
```python
from app.services.chart_middleware import register
register("heatmap", build_heatmap)
```

**Tolerant Input Normalize**：
- `_unwrap_chart_data()` — 自動 unwrap `{"data":[...]}` / `{"records":[...]}` 等 wrapper（line/bar/scatter/multi_line builders 共用）
- `_normalize_spc_input()` — SPC-specific deep search + nested-by-group flatten + parallel arrays zip
- `_deep_find_spc_list()` — ≤4 depth DFS 找第一個符合 SPC row pattern 的 list

**整合點**：
- `SkillExecutorService.execute()` — Skill 執行後自動呼叫 `chart_middleware.process()`
- `SkillExecutorService.try_run()` — saved rule try-run 後自動呼叫
- `SkillExecutorService.try_run_draft()` — Try-Run sandbox 執行後同樣呼叫
- `analysis.py` (`execute_analysis`) — Agent ad-hoc 分析執行後呼叫
- `render_card.py` (`execute_mcp`) — MCP result 經 classifier 後呼叫（每個 render option 各算一次）
- `alarms_router.py` — Alarm list API 對每個 DR result 呼叫（生成 alarm detail charts）

## 7. System MCP 定義（Seed）— MCP v3 三層架構

啟動時自動 seed 到 DB（create or update by name，刪除不在 canonical list 的舊記錄）。

### 7.1 三層資料 MCP（v3 架構）

Agent 透過三個層級的 MCP 漸進式深入調查：

| Layer | MCP Name | Endpoint | 說明 |
|-------|----------|----------|------|
| **L1 — Summary** | `get_process_summary` | `GET /process/summary` | 聚合統計（OOC rates、per-tool breakdown、recent OOC）。MongoDB aggregation pipeline，毫秒回應。適合全廠範圍掃描。 |
| **L2 — Investigation** | `get_process_info` | `GET /process/info` | 範圍調查。新增 `objectName` 參數可篩選 SPC/DC/APC/RECIPE。回應扁平化（不再有 `{event, objects}` 巢狀）。回傳 pure data，chart 生成由 Backend ChartMiddleware 負責。**一次呼叫取代過去 8 次呼叫。** |
| **L3 — Deep Dive** | `query_object_timeseries` | `POST /objects/query` | 單一參數深度時序 + 3σ OOC。SPC parameter 支援短格式 `xbar_chart`（自動 normalize 為 `charts.xbar_chart.value`） |

**已退役 MCP**：
- `get_process_events` — 被 `get_process_info` 取代
- `get_object_info` — 不再需要（data IS the schema）

### 7.3 已停用的 Agent Tools（從 TOOL_SCHEMAS 移除）

| Tool / MCP | 移除原因 |
|------------|----------|
| `analyze_data` | 被 `execute_analysis(mode='auto')` 取代 |
| `execute_jit` | 被 `execute_analysis` 取代，已下線 |
| `execute_utility` | 150 個 generic tool，從未被使用 |
| `execute_agent_tool` | Agent private tool chest，從未被使用 |
| `query_object_timeseries` | LLM 一致選此 MCP 做 SPC 查詢導致 5x 呼叫 + 編造 chart name。get_process_info(objectName='SPC') 一次拿到全部 5 種 chart。Simulator endpoint 保留但 DB MCP 定義已刪除 |

### 7.4 Render Intent Classifier

`render_intent_classifier.py` — 結構驅動的呈現方式分類器：

**設計原則**：
1. **不靠 user_query 關鍵字** — 純粹檢查 raw data 的結構
2. **Confirmation > Guessing** — 多種合理呈現時問使用者
3. **所有 alternative renders 預先計算** — 前端 instant switch，不需 backend roundtrip

**決策規則**：

| 資料結構 | Decision | Primary | Alternatives |
|---------|----------|---------|--------------|
| events[] + SPC.charts nested | `auto_chart` | SPC 5 chart | Table / OOC-only / APC multi-line / DC multi-line / Recipe table |
| events[] ≥ 5 筆 (no SPC) | `ask_user` | — | Table / OOC-only / Summary text |
| events[] < 5 筆 | `auto_table` | Flat table | — |
| catalog list (no time) | `auto_table` | Catalog table | — |
| scalar response | `auto_scalar` | Badge/scalar | — |

**整合點**：`render_card.py` 的 `execute_mcp` 路徑 → 呼叫 classifier → 建 contract.render_decision → 前端 ContractRenderer 讀取。

### 7.5 Chat Console SSE Event 格式

Agent chat 的 SSE events 包含以下改善欄位（方便 console debug）：

| Event | 新增欄位 | 範例 |
|-------|---------|------|
| `tool_start` | `params_summary` | `"get_process_info(equipment_id=EQP-01, since=7d)"` |
| `tool_done` | `result_summary`, `data_shape` | `"100 events (28 OOC)"`, `{"total":100, "ooc_count":28, "render":"auto_chart(5 charts, 5 alts)"}` |
| `plan` | `text` | `"Step 1: execute_mcp(...) → Step 2: analyze"` |

### 7.2 輔助 MCP

| MCP Name | Endpoint | 說明 |
|----------|----------|------|
| `list_tools` | `GET /tools` | 廠內機台清單 |
| `get_simulation_status` | `GET /status` | 模擬器系統狀態 |

## 8. 啟動流程

```
main.py → @app.on_event("startup")
  1. Create DB tables (SQLAlchemy metadata.create_all)
  2. Seed default users (admin, gill)
  3. Seed DataSubjects + EventTypes
  4. Seed System MCPs (create/update/delete stale)
  5. Seed System Memories (currently empty)
  6. Start NATS subscriber (if NATS_URL configured)
  7. Start APScheduler cron jobs
```

## 9. 環境變數

| Variable | Default | 說明 |
|----------|---------|------|
| `DATABASE_URL` | `postgresql+asyncpg://...` | PostgreSQL 連線字串 |
| `ANTHROPIC_API_KEY` | — | Claude API key |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama（bge-m3 embedding） |
| `ONTOLOGY_SIM_URL` | `http://localhost:8012` | OntologySimulator base URL |
| `NATS_URL` | — | NATS server（optional） |
| `JWT_SECRET_KEY` | — | JWT signing secret |
| `RESET_TO_ONTOLOGY_ONLY` | `false` | 啟動時清除非 canonical MCPs |
