# Glass Box AI 診斷系統 — Master PRD v11.0

> **版本紀錄**：本文件整合 Phase 1–14 全部歷史規格，並透過程式碼考古補入所有尚未正式文件化的架構決策與血淚教訓。
> **維護原則**：本文件為「單一真相來源（Single Source of Truth）」，日後所有新增功能需同步更新此文件。
> **撰寫日期**：2026-03-05

---

## 目錄

1. [產品願景與背景](#1-產品願景與背景)
2. [技術堆疊](#2-技術堆疊)
3. [系統架構總覽](#3-系統架構總覽)
4. [資料庫 Schema](#4-資料庫-schema)
5. [API 端點全覽](#5-api-端點全覽)
6. [Phase 歷史與功能規格](#6-phase-歷史與功能規格)
7. [核心服務實作規格](#7-核心服務實作規格)
8. [前端 SPA 規格](#8-前端-spa-規格)
9. [安全模型](#9-安全模型)
10. [設定與環境變數](#10-設定與環境變數)
11. [部署指南](#11-部署指南)
12. [血淚教訓 — 程式碼考古](#12-血淚教訓--程式碼考古)

---

## 1. 產品願景與背景

**Glass Box AI 診斷系統**是一套針對半導體晶圓廠蝕刻製程（Etch CD）所設計的智能診斷平台。系統目標是將傳統「黑盒 AI」轉變為「透明可審計的玻璃盒」，讓製程工程師可以：

1. **自行設計資料加工邏輯**（MCP Builder）：透過自然語言描述資料加工意圖，由 AI 自動生成 Python 腳本並在沙盒中驗證。
2. **自行定義診斷規則**（Skill Builder）：在 MCP 結果上撰寫異常判斷條件，AI 負責判斷條件是否成立，人類專家負責撰寫建議動作。
3. **自動化巡邏監控**（RoutineCheck）：將 Skill 綁定排程，系統定期自動執行並觸發異常事件。
4. **即時事件驅動診斷**：SPC OOC 事件發生時，系統自動執行相關 Skill 並輸出結構化診斷報告。
5. **Copilot 介面**：透過自然語言 slash command，直接呼叫 MCP/Skill 並以對話形式呈現結果。
6. **Help Chat**：隨時可存取的 LLM 使用說明助理，基於產品規格與使用手冊回答操作問題。

### 核心域
- **製程**：半導體蝕刻（Etch）CD（Critical Dimension）SPC（Statistical Process Control）
- **主要事件類型**：`SPC_OOC_Etch_CD`、`Equipment_Down`、`Recipe_Deployment_Issue`
- **主要 Mock DataSubject**：SPC_Chart_Data（100 筆 SPC）、APC_tuning_value（100 筆 APC）、Recipe_Data、EC_Data、APC_Data

---

## 2. 技術堆疊

| 層次 | 技術 |
|------|------|
| **Web 框架** | FastAPI (Python 3.11+) |
| **ORM** | SQLAlchemy 2.0 (`AsyncSession`) |
| **資料庫（開發）** | SQLite + `aiosqlite` |
| **資料庫（生產）** | PostgreSQL（`DATABASE_URL` 環境變數切換）|
| **認證** | JWT（python-jose + passlib bcrypt）|
| **LLM** | Anthropic Claude (claude-opus-4-6) |
| **Anthropic SDK** | `anthropic >= 0.40.0` （Pydantic v2 物件回傳）|
| **排程** | APScheduler（async）|
| **HTTP Client** | httpx（async，DataSubject API 呼叫）|
| **資料處理（沙盒）** | pandas、plotly、matplotlib（沙盒注入）|
| **DB Migration** | Alembic（async mode）|
| **前端** | 純 HTML/CSS/Vanilla JS 靜態 SPA |
| **CSS 框架** | Tailwind CSS (CDN) |
| **圖表** | Plotly.js (CDN) |

### 套件版本重要注意事項

- `anthropic >= 0.40.0`：SDK 回傳 Pydantic v2 物件（`TextBlock`、`ToolUseBlock`），有 `extra` 欄位。**重新傳入 messages 前必須序列化**（`_serialize_content()` in `diagnostic_service.py`）。
- `pydantic-settings`：必須獨立安裝，`config.py` 的 `BaseSettings` 依賴此套件。
- `aiosqlite`：SQLite 非同步驅動，生產環境切換 PostgreSQL 時移除。

---

## 3. 系統架構總覽

### 3.1 Layer Structure

```
HTTP Request
    ↓
Router（app/routers/）
    ↓
Service（app/services/）
    ↓
Repository（app/repositories/）
    ↓
Database（AsyncSession → SQLite / PostgreSQL）
```

`app/dependencies.py` 透過 FastAPI `Depends` 工廠函式串接所有層次。

### 3.2 應用程式入口

**`main.py`** 負責：
1. **Lifespan**：`init_db()` → `_seed_data()` → APScheduler 啟動
2. **Middleware**：CORS、`RequestLoggingMiddleware`（X-Request-ID）
3. **Router 掛載**（`/api/v1` prefix）
4. **Static SPA**（`StaticFiles` 掛載於最後，確保 API 路由優先）

Router 掛載順序（`main.py` line 471–487）：
```
auth_router, users_router, items_router, diagnostic_router,
builder_router, mock_data_router, data_subjects_router,
event_types_router, mcp_definitions_router, skill_definitions_router,
system_parameters_router, routine_check_router,
generated_events_router, help_router
```

### 3.3 SSE 串流架構

系統有兩種 SSE 格式，前端必須分別處理：

| 格式 | 使用場景 | 前端解析函式 |
|------|---------|------------|
| **Event-driven**：`event: TYPE\ndata: {...}\n\n` | `POST /diagnose/event-driven-stream` | `_parseSSEChunk()` |
| **Copilot JSON**：`data: {"type":...}\n\n` | `POST /diagnose/copilot-chat`、`POST /help/chat` | `_parseCopilotChunk()` |

> **關鍵**：前端必須使用 Fetch API + `ReadableStream`（而非 `EventSource`），因為 `EventSource` 不支援帶 Authorization header。

### 3.4 Startup Seeding

每次啟動 (`_seed_data()`) 自動建立/更新：

1. **預設使用者**：`admin`（密碼 admin）、`gill`（密碼 gill），兩者均為超級管理員
2. **內建 DataSubject**（5 個，含 Mock API 配置）
3. **內建 EventType**（`SPC_OOC_Etch_CD`，含 11 個屬性欄位）
4. **SystemParameter** 預設值（3 個 prompt keys）

**強制更新**：`PROMPT_SKILL_DIAGNOSIS` 每次啟動強制同步最新值（`_FORCE_UPDATE_PARAMS`）。
**不強制更新**：`PROMPT_MCP_GENERATE`、`PROMPT_MCP_TRY_RUN`——若 DB 已有值則不覆蓋。若生產環境 prompt 過期，執行 `python3 scripts/reset_mcp_prompts.py dev.db` 刪除舊值。

---

## 4. 資料庫 Schema

### 4.1 users

| 欄位 | 類型 | 說明 |
|------|------|------|
| id | Integer PK | |
| username | String UNIQUE | |
| email | String UNIQUE | |
| hashed_password | String | bcrypt hash |
| is_active | Boolean | 預設 True |
| is_superuser | Boolean | |
| roles | Text (JSON) | `["it_admin","expert_pe","general_user"]` |
| created_at / updated_at | DateTime | |

### 4.2 data_subjects

| 欄位 | 類型 | 說明 |
|------|------|------|
| id | Integer PK | |
| name | String UNIQUE | |
| description | Text | |
| api_config | Text (JSON) | `{"endpoint_url", "method", "headers"}` |
| input_schema | Text (JSON) | `{"fields": [{name, type, description, required}]}` |
| output_schema | Text (JSON) | 同 input_schema 格式 |
| is_builtin | Boolean | 預設 False，內建 DS 標記 |
| created_at / updated_at | DateTime | |

### 4.3 event_types

| 欄位 | 類型 | 說明 |
|------|------|------|
| id | Integer PK | |
| name | String UNIQUE | |
| description | Text | |
| attributes | Text (JSON) | `[{name, type, required, description}]` |
| diagnosis_skill_ids | Text (JSON) | 新格式：`[{"skill_id": N, "param_mappings": [...]}]`；舊格式：`[N, ...]` |
| created_at / updated_at | DateTime | |

### 4.4 mcp_definitions

| 欄位 | 類型 | 說明 |
|------|------|------|
| id | Integer PK | |
| name | String | |
| description | Text | |
| data_subject_id | Integer FK | → data_subjects |
| processing_intent | Text | 自然語言加工意圖 |
| processing_script | Text | LLM 生成的 Python 腳本（`process(raw_data) -> dict`）|
| output_schema | Text (JSON) | `{"fields": [...]}` |
| ui_render_config | Text (JSON) | `{"chart_type", "x_axis", "y_axis", "series", "notes"}` |
| input_definition | Text (JSON) | `{"params": [{name, type, source, description, required}]}` |
| sample_output | Text (JSON) | 最近一次 try_run 的輸出 |
| created_at / updated_at | DateTime | |

### 4.5 skill_definitions

| 欄位 | 類型 | 說明 |
|------|------|------|
| id | Integer PK | |
| name | String | |
| description | Text | |
| mcp_ids | Text (JSON) | `[mcp_id, ...]`（目前取 [0]）|
| diagnostic_prompt | Text | 異常判斷條件（Expert PE 撰寫）|
| human_recommendation | Text | 建議處置步驟（Expert PE 撰寫）|
| param_mappings | Text (JSON) | Skill 層級的 event→mcp 映射（ET 層級優先）|
| last_diagnosis_result | Text (JSON) | 最近一次模擬診斷結果（Phase 14 新增）|
| created_at / updated_at | DateTime | |

**`last_diagnosis_result` 結構**：
```json
{
  "status": "NORMAL|ABNORMAL",
  "diagnosis_message": "...",
  "problem_object": {},
  "generated_code": "def diagnose(mcp_outputs): ...",
  "check_output_schema": {"fields": [...]},
  "timestamp": "2026-..."
}
```

### 4.6 routine_checks

| 欄位 | 類型 | 說明 |
|------|------|------|
| id | Integer PK | |
| name | String | |
| skill_id | Integer FK | → skill_definitions |
| skill_input | Text (JSON) | 固定輸入參數 `{key: value}` |
| trigger_event_id | Integer FK (nullable) | → event_types（後端自動建立）|
| event_param_mappings | Text (JSON) | `[{"event_field": ..., "mcp_field": ...}]`（identity mapping）|
| schedule_interval | String | cron 表達式或 interval（e.g., `*/5 * * * *`）|
| is_active | Boolean | |
| last_run_at | DateTime (nullable) | |
| last_run_status | String (nullable) | `"ok"` \| `"error"` |
| created_at / updated_at | DateTime | |

### 4.7 generated_events

| 欄位 | 類型 | 說明 |
|------|------|------|
| id | Integer PK | |
| event_type_id | Integer FK | |
| event_type_name | String | |
| event_params | Text (JSON) | |
| source | String | `"routine_check"` \| `"manual"` |
| created_at | DateTime | |

### 4.8 system_parameters

| 欄位 | 類型 | 說明 |
|------|------|------|
| id | Integer PK | |
| key | String UNIQUE | 參數名稱 |
| value | Text | 參數值 |
| description | Text | |
| updated_at | DateTime | |

**已知 Key**：
- `PROMPT_MCP_GENERATE` — MCP 設計時 4-task LLM 生成 prompt
- `PROMPT_MCP_TRY_RUN` — Try Run 沙盒安全 prompt（含繪圖規範）
- `PROMPT_SKILL_DIAGNOSIS` — Skill 模擬診斷 LLM prompt（每次啟動強制更新）

---

## 5. API 端點全覽

所有端點均以 `/api/v1` 為前綴（可透過 `API_V1_PREFIX` 設定調整）。

### 5.1 Auth & Users

| Method | Path | 說明 |
|--------|------|------|
| POST | `/auth/token` | 登入，回傳 JWT access token（30 分鐘預設）|
| GET | `/users/me` | 取得當前使用者資訊（JWT 必要）|
| POST | `/users` | 新增使用者（超級管理員）|
| GET | `/users` | 列出所有使用者 |
| PUT | `/users/{id}` | 更新使用者 |
| DELETE | `/users/{id}` | 刪除使用者 |

### 5.2 Diagnostic

| Method | Path | 說明 |
|--------|------|------|
| POST | `/diagnose/event-driven` | 事件驅動診斷（同步，回傳完整結果）|
| POST | `/diagnose/event-driven-stream` | 事件驅動診斷（SSE 串流，Progressive Skill Cards）|
| POST | `/diagnose/copilot-chat` | Copilot 意圖解析 + 工具呼叫（SSE）|
| GET | `/diagnose/event-types` | 列出可用事件類型（for Copilot UI）|

**`/event-driven-stream` SSE 事件序列**：
```
{"type":"start", "event":{...}, "skill_count": N}
{"type":"skill_start", "index": 0, "skill_name": "...", "mcp_name": "..."}
{"type":"skill_done", "index": 0, ...SkillPipelineResult.to_dict()}
{"type":"done"}
```

**`/copilot-chat` SSE 事件序列**：
```
{"type":"question", "message": "..."}           # slot filling 問題
{"type":"thinking", "message": "..."}           # 意圖解析中
{"type":"chat", "message": "..."}               # 純文字回應（串流）
{"type":"tool_call", "tool": "...", ...}        # 工具呼叫通知
{"type":"skill_result", "skill_id":..., "skill_name":..., "status":...,
  "conclusion":..., "evidence":[], "summary":..., "problem_object":{},
  "human_recommendation":..., "mcp_output":{...}, "tab_title":"..."}
{"type":"done"}
{"type":"error", "message": "..."}
```

### 5.3 MCP Builder

| Method | Path | 說明 |
|--------|------|------|
| GET | `/mcp-definitions` | 列出所有 MCP |
| POST | `/mcp-definitions` | 新增 MCP |
| GET | `/mcp-definitions/{id}` | 取得 MCP |
| PUT | `/mcp-definitions/{id}` | 更新 MCP |
| DELETE | `/mcp-definitions/{id}` | 刪除 MCP |
| POST | `/mcp-definitions/{id}/generate` | LLM 生成腳本（含 output_schema / ui_render_config / input_definition）|
| POST | `/mcp-definitions/check-intent` | LLM 意圖確認（是否清晰，回傳澄清問題）|
| POST | `/mcp-definitions/try-run` | LLM 生成 + 沙盒試跑（⚠️ 30–60 秒）|
| POST | `/mcp-definitions/{id}/run-with-data` | 使用已存腳本跑新 raw_data（Skill Builder 用）|

### 5.4 Skill Definitions

| Method | Path | 說明 |
|--------|------|------|
| GET | `/skill-definitions` | 列出所有 Skill |
| POST | `/skill-definitions` | 新增 Skill |
| GET | `/skill-definitions/{id}` | 取得 Skill |
| PUT | `/skill-definitions/{id}` | 更新 Skill（含 diagnostic_prompt、human_recommendation、param_mappings）|
| PATCH | `/skill-definitions/{id}` | 部分更新（儲存 last_diagnosis_result）|
| DELETE | `/skill-definitions/{id}` | 刪除 Skill |
| POST | `/skill-definitions/{id}/simulate` | 模擬診斷：LLM 分析 MCP 輸出 → 生成 Python 診斷碼 + check_output_schema |

**`/simulate` 回傳格式（`SkillGenerateCodeDiagnosisResponse`）**：
```json
{
  "status": "NORMAL|ABNORMAL",
  "conclusion": "...",
  "evidence": ["..."],
  "summary": "...",
  "problem_object": {},
  "generated_code": "def diagnose(mcp_outputs): ...",
  "check_output_schema": {"fields": [{...}]}
}
```

### 5.5 Routine Checks

| Method | Path | 說明 |
|--------|------|------|
| GET | `/routine-checks` | 列出所有排程巡檢 |
| POST | `/routine-checks` | 新增排程巡檢（自動建立 EventType）|
| GET | `/routine-checks/{id}` | 取得排程巡檢 |
| PUT | `/routine-checks/{id}` | 更新排程巡檢 |
| DELETE | `/routine-checks/{id}` | 刪除排程巡檢 |
| POST | `/routine-checks/{id}/run-now` | 立即執行（手動觸發）|

**POST `/routine-checks` 自動化流程**：
1. 讀取 `skill.last_diagnosis_result.check_output_schema.fields`
2. 建立新 EventType（`generated_event_name` 或 `{name} 異常警報`）
3. 設定 identity mapping：`event_field == mcp_field`
4. 不接受客戶端傳入 `trigger_event_id` / `event_param_mappings`（後端完全自動）

### 5.6 Event Types & Generated Events

| Method | Path | 說明 |
|--------|------|------|
| GET | `/event-types` | 列出所有 EventType |
| POST | `/event-types` | 新增 EventType |
| GET | `/event-types/{id}` | 取得 EventType |
| PUT | `/event-types/{id}` | 更新 EventType（含 diagnosis_skill_ids）|
| DELETE | `/event-types/{id}` | 刪除 EventType |
| GET | `/generated-events` | 列出所有自動觸發的事件記錄 |

### 5.7 Data Subjects

| Method | Path | 說明 |
|--------|------|------|
| GET | `/data-subjects` | 列出所有 DataSubject |
| POST | `/data-subjects` | 新增 DataSubject |
| GET | `/data-subjects/{id}` | 取得 DataSubject |
| PUT | `/data-subjects/{id}` | 更新 DataSubject |
| DELETE | `/data-subjects/{id}` | 刪除 DataSubject |

### 5.8 Mock Data

| Method | Path | 說明 |
|--------|------|------|
| GET | `/mock/spc` | SPC Chart Data（100 筆；`?chart_name=CD` 過濾）|
| GET | `/mock/apc_tuning` | APC 補償調整值（100 筆）|
| GET | `/mock/apc` | APC Data |
| GET | `/mock/recipe` | Recipe Data |
| GET | `/mock/ec` | EC Data |

**SPC Mock 資料特性**：
- 10 台機台（TETCH01–TETCH10）× 10 批貨 = 100 筆
- **TETCH01 前 4 批刻意 OOC**（value > UCL 46.5 nm）
- **APC tuning**：TETCH01 前 4 批 etchTime 異常偏低（5–6 sec vs 正常 10–15 sec）

### 5.9 System Parameters

| Method | Path | 說明 |
|--------|------|------|
| GET | `/system-parameters` | 列出所有 SystemParameter |
| POST | `/system-parameters` | 新增 SystemParameter |
| GET | `/system-parameters/{key}` | 取得特定 key |
| PUT | `/system-parameters/{key}` | 更新 SystemParameter |
| DELETE | `/system-parameters/{key}` | 刪除 SystemParameter |

### 5.10 Builder （Phase 6）

| Method | Path | 說明 |
|--------|------|------|
| POST | `/builder/auto-map` | LLM 自動映射 event 屬性 → DataSubject params |
| POST | `/builder/validate-logic` | LLM 驗證 Diagnostic Prompt 邏輯一致性 |
| POST | `/builder/suggest-logic` | LLM 建議 Diagnostic Prompt |

### 5.11 Help Chat（Phase 14）

| Method | Path | 說明 |
|--------|------|------|
| POST | `/help/chat` | Help Chat SSE（JWT 必要）|

**Request Body**：
```json
{"message": "如何建立 MCP?", "history": [{"role":"user","content":"..."},...]}
```

**SSE 格式**：與 Copilot 相同（`data: {"type":"chat","message":"..."}\n\n`）

---

## 6. Phase 歷史與功能規格

### Phase 1 — FastAPI 基礎架構
- JWT 認證（`/auth/token`）、RBAC 架構
- Users / Items CRUD
- StandardResponse 統一回應格式
- RequestLoggingMiddleware、AppException

### Phase 2 — AI 診斷代理人（Agent Loop）
- `DiagnosticService`：Agent Loop（LLM Tool Use → MCP Skills 呼叫）
- `BaseMCPSkill` 抽象類別
- `POST /diagnose/event-driven` 同步診斷

### Phase 3 / 3.5 — MCP Event Triage + SSE
- `EventTriageSkill`（`event_triage.py`）：強制第一呼叫，分類症狀
- SSE 串流架構建立

### Phase 4 — Glass Box Frontend SPA
- 純 HTML/CSS/Vanilla JS 靜態 SPA
- StaticFiles 掛載在 `main.py` 最底部

### Phase 5 — 文件補齊
- `docs/user_manual.md`、`docs/prod_spec_v5.md`
- 系統介紹 HTML

### Phase 6 — 半導體蝕刻製程領域
- SPC_OOC_Etch_CD 事件類型（11 個屬性）
- 3 個 Etch Skills（recipe_offset、equipment_constants、apc_params）
- Builder API（auto_map、validate-logic、suggest-logic）
- `BuilderService`：LLM 自動生成 ET → Skill 映射

### Phase 8 — 輕色主題 + 進階 SSE

**主題設計**：
- 側欄：`bg-slate-800`（dark）
- 內容區：`bg-slate-50`（light）
- 卡片：`bg-white`
- 文字：`text-slate-900`

**Progressive SSE Skill Cards**：
- 新增 `POST /diagnose/event-driven-stream` 端點
- `EventPipelineService.stream()` async generator
- 前端 `_launchEventDiagnosis()` 使用 fetch + ReadableStream
- `_appendSkillCard()` 每張 card 逐步渲染

**Standard Payload 格式**（MCP 輸出標準）：
```json
{
  "output_schema": {"fields": [...]},
  "dataset": [...],
  "ui_render": {
    "type": "trend_chart|bar_chart|table",
    "charts": ["Plotly JSON 字串 1", ...],
    "chart_data": "charts[0]（向下相容）"
  },
  "_is_processed": true,
  "_raw_dataset": [...],
  "_call_params": {}
}
```

### Phase 9 — Copilot Intent-Driven UI

**功能**：
- Slash Command Menu（`/` 觸發，列出所有 MCP/Skill）
- Slot Filling（AI 自動索取缺少參數）
- 直接呼叫 MCP/Skill，結果渲染到獨立 tab

**CopilotService 意圖解析流程**：
1. 解析 slash command 或自由文字
2. 比對 MCP/Skill（依 `_selected_tool_id`/`_selected_tool_type`）
3. 識別缺少必填參數 → 透過 SSE yield `question` 詢問使用者
4. 取得全部參數後呼叫 DataSubject → 執行 MCP script → LLM 診斷
5. SSE yield `skill_result`（含 `problem_object`）

**Slot Context**：
- `_selected_tool_id`、`_selected_tool_type` 儲存在 `slot_context`
- API 接收前先 strip（不傳入 LLM）

### Phase 10–13 — Skill Builder + RoutineCheck CRUD

- **Skill Builder 抽屜 UI**：從 MCP List 開啟，含 Diagnostic Prompt 編輯器、模擬診斷
- **RoutineCheck CRUD** API 及排程（APScheduler）
- **EventType 自動建立**：從 Skill `check_output_schema` 自動生成 ET
- **Skill simulate API**：LLM 生成 Python 診斷函式碼 + `check_output_schema`

### Phase 14 — Skill Standard Output + Help Chat

**Skill 標準輸出三元組**：
- `status`：`NORMAL` | `ABNORMAL`（嚴格二選一）
- `diagnosis_message`：一句話結論（對應 LLM `conclusion`）
- `problem_object`：觸發異常的具體識別符（ABNORMAL 時填入，NORMAL 時為 `{}`）

**`last_diagnosis_result` 持久化**：
- `PATCH /skill-definitions/{id}` 儲存最近模擬結果
- Skill Builder 抽屜開啟時預載（直接顯示上次結果）
- EventPipelineService 優先使用 `generated_code`（Python sandbox）診斷，無 code 才 fallback LLM

**RoutineCheck 自動 EventType 建立**：
- `check_output_schema.fields` → 逐一轉換為 ET attributes
- Identity mapping：`event_field == mcp_field`
- 前端 UI 改為「自訂事件名稱」輸入框（不再有 ET 下拉選單）

**Help Chat**：
- `POST /api/v1/help/chat` SSE（JWT 必要）
- `HelpChatService`：載入 `docs/user_manual.md` + `docs/Product_spec_V8/PRODUCT_SPEC_V8.md`
- Anthropic prompt caching（`cache_control: ephemeral`）於 system prompt
- 模型：`claude-opus-4-6`，`max_tokens: 2048`
- 前端：側欄 `?` 按鈕 → 360px 浮動面板（從左側滑入）
- 對話歷史跨頁籤/頁面切換保留（`_helpHistory` 全域變數）

---

## 7. 核心服務實作規格

### 7.1 Sandbox Service（`app/services/sandbox_service.py`）

沙盒是系統最關鍵的安全邊界，所有 LLM 生成的 Python 腳本均在此執行。

#### 安全架構

**雙層防護**：
1. **Static Check**（`_static_check()`）：Regex 掃描 forbidden patterns 清單
2. **受限命名空間**（`_run_sync()`）：僅注入白名單內的內建函式和模組

**Forbidden Patterns（靜態掃描）**：
```python
r"\bimport\s+(requests?|http|urllib|socket|subprocess|os|sys|pathlib|shutil|glob|pickle)\b"
r"\bfrom\s+(requests?|http|urllib|socket|subprocess|os|sys|pathlib|shutil)\b"
r"\b__import__\s*\("
r"\beval\s*\("
r"\bexec\s*\("
r"\bopen\s*\("
r"\bcompile\s*\("
r"\b__builtins__\b"
r"\bos\.\w+"
r"\bsys\.\w+"
r"\bsubprocess\.\w+"
```

**允許 import 的模組白名單**：
```python
_ALLOWED_BASE_MODULES = frozenset({
    # stdlib
    "json", "math", "statistics", "datetime", "collections",
    "itertools", "functools", "operator", "re", "string", "decimal",
    "io", "base64", "copy", "abc", "numbers", "types", "enum",
    "typing", "warnings", "heapq", "bisect", "struct", "csv",
    "time", "calendar",
    # approved data/viz
    "pandas", "plotly", "matplotlib",
    # CPython C-extensions (lazy auto-import by stdlib)
    "_strptime", "_decimal", "_json", "_datetime",
    "_collections_abc", "_functools", "_operator", "_io",
    "_statistics", "_heapq", "_bisect", "_struct", "_csv", "_abc",
})
```

> ⚠️ **`_strptime` 和 `_datetime` 必須在白名單**：`datetime.strptime()` 第一次呼叫會觸發 CPython 內部 `import _strptime`，若白名單缺少此條目會導致 `ImportError`。

**沙盒逾時**：10 秒（`asyncio.wait_for` + `loop.run_in_executor`）

#### 預注入全域變數

```python
global_ns = {
    "__builtins__": safe_builtins,
    "json", "math", "statistics", "datetime",
    "collections", "itertools", "functools", "io", "base64",
    # 別名注入（不需 import）
    "pd": pandas, "pandas": pandas,
    "go": plotly.graph_objects,
    "px": plotly.express,
    "plt": matplotlib.pyplot,
    "matplotlib": matplotlib,
    ...
}
```

#### 腳本重寫管線（Script Rewrite Pipeline）

腳本進入 `exec()` 前經過兩道重寫：

**Step 1 — 移除預注入 import**（`_strip_preinjected_imports()`）：
```python
# 移除 "import pandas", "from plotly import ..." 等（已在全域命名空間）
_PREINJECTED_IMPORT_RE = re.compile(
    r"^[ \t]*(import\s+(plotly|pandas|matplotlib)\b[^\n]*"
    r"|from\s+(plotly|pandas|matplotlib)\b[^\n]*)[ \t]*$",
    re.MULTILINE,
)
```

**Step 2 — Plotly 輸出格式強制轉換**（`_rewrite_plotly_output()`）：
```python
_TO_HTML_RE = re.compile(r"\b([a-zA-Z_]\w*)\.to_html\s*\([^)]*\)")
# fig.to_html(...) → fig.to_json()
```

> **為何用 `fig.to_json()` 而非 `json.dumps(fig.to_dict())`**：
> - `fig.to_json()` 使用 Plotly 自己的 JSON encoder，能正確處理 pandas `Timestamp` 和 numpy types
> - `json.dumps(fig.to_dict())` 使用 stdlib encoder，遇 `Timestamp` 會拋 `TypeError: Object of type Timestamp is not JSON serializable`
> - 生產環境曾因此踩坑，此為血淚教訓（見 Section 12）

#### JSON 序列化後處理（`_make_json_serializable()`）

`execute_script()` 呼叫 `process_fn(raw_data)` 後，對回傳值遞迴處理：
- `pd.Timestamp` → ISO 8601 string
- `pd.NaT`, `pd.NA`, `float nan` → `None`
- numpy scalar → `int` / `float`（via `.tolist()`）
- numpy ndarray / pandas Series → `list`
- pandas DataFrame → `list of dicts`

#### diagnose() 函式規格

Skill simulate 階段同時生成 Python 診斷函式，後續 EventPipeline 優先使用此路徑：

```python
def diagnose(mcp_outputs: dict) -> dict:
    # mcp_outputs = {"mcp_name": {"dataset": [...], "ui_render": {...}, ...}}
    return {
        "status": "NORMAL" | "ABNORMAL",  # 必填
        "diagnosis_message": "...",         # 必填
        "problem_object": {}               # 必填，ABNORMAL 時填入具體識別符
    }
```

`_run_diagnose_sync()` 執行後驗證 3 個 required keys，缺少任一拋 `ValueError`。

### 7.2 MCP Builder Service（`app/services/mcp_builder_service.py`）

#### 模型設定

```python
_MODEL = get_settings().LLM_MODEL  # 預設 "claude-opus-4-6"
```

> ⚠️ `_MODEL` 在模組載入時固定（`lru_cache` 的 `get_settings()` 只執行一次）。**修改 `.env` 後必須重啟 server**。

#### LLM 呼叫函式

| 函式 | 用途 | System Prompt 來源 |
|------|------|-----------------|
| `generate_all()` | MCP Builder 設計時生成（4 tasks） | `PROMPT_MCP_GENERATE`（DB）或 `_DEFAULT_GENERATE_PROMPT` |
| `generate_for_try_run()` | Try Run 安全生成 | `PROMPT_MCP_TRY_RUN`（DB）或 `_DEFAULT_TRY_RUN_SYSTEM_PROMPT` |
| `try_diagnosis()` | LLM 診斷（fallback，無 generated_code 時）| `PROMPT_SKILL_DIAGNOSIS`（DB，每次啟動強制更新）|
| `generate_diagnosis_code()` | Skill simulate：生成 Python diagnose() | `_DEFAULT_DIAGNOSIS_SYSTEM_PROMPT` |
| `summarize_diagnosis()` | Python diagnose 後 LLM 生成摘要 | inline system prompt |
| `triage_error()` | 分析沙盒執行錯誤 | inline system prompt |
| `check_intent()` | 意圖澄清（before try-run）| inline system prompt |

#### `_extract_json()` JSON 解析策略

三段式容錯解析：
1. 去除 ` ```json ``` ` markdown fence
2. 找到第一個 `{` 起始位置
3. `json.JSONDecoder().raw_decode(text)` — 只解析第一個合法 JSON 物件，忽略後續文字

#### Try Run 系統 Prompt 關鍵規則（`_DEFAULT_TRY_RUN_SYSTEM_PROMPT`）

完整包含：
1. 嚴格安全規範（5 條，違反即拒絕）
2. 沙盒可用環境（禁止 import 預注入庫、僅限白名單 stdlib）
3. 標準輸出規範（3 key：`output_schema`、`dataset`、`ui_render`）
4. 繪圖規範（`json.dumps(fig.to_dict())` — 禁止 `fig.to_html()`）
5. **SPC 多 trace 骨架**（4 add_trace：主值折線、UCL、LCL、OOC 散點）

> ⚠️ 注意：`_DEFAULT_TRY_RUN_SYSTEM_PROMPT` 中提到「禁止 `fig.to_json()`（可能產生二進位輸出）」，但沙盒 `_rewrite_plotly_output()` 將 `fig.to_html()` 重寫為 `fig.to_json()`——這兩者並不矛盾：prompt 是要求 LLM 不主動寫 `fig.to_json()`，而重寫是後處理保險。

### 7.3 MCP Definition Service（`app/services/mcp_definition_service.py`）

#### `_normalize_output()` — Standard Payload 正規化

處理 LLM 腳本回傳的多種格式，統一輸出 Standard Payload：
1. 已有 `ui_render` key → 原地修正（HTML sanitize、charts list 建立）
2. 回傳 `list` → 包裝為 `dataset`
3. 回傳 `dict`（partial）→ 提取 `dataset` 或包裝整個 dict

**HTML Sanitize**（`_is_html_chart()`）：
- 判斷 `chart_data` 或 `charts[]` 中是否有 `str.startswith("<")` 的值
- 若有，discard → 讓 `_auto_chart()` fallback 重新生成

#### `_auto_chart()` — 圖表自動生成 Fallback

當腳本沒有產生任何圖表時自動生成：
1. 從 `ui_render_config.x_axis`、`y_axis`、`series` 取得欄位名稱
2. 自動識別數值欄位（最多 4 個）
3. `go.Scatter(mode="lines+markers")` 生成折線圖
4. 回傳 `json.dumps(fig.to_dict())`（注意：此處用 `json.dumps`，因為 Plotly 已統一格式）

**Fallback 觸發條件**（Phase 14 修正後）：
```python
chart_type = ui_cfg.get("chart_type") or ""  # 空字串 != "table" → 觸發
if not ui_render.get("charts") and not ui_render.get("chart_data"):
    if chart_type != "table":  # 修正前錯誤：(chart_type or "table") != "table"
        chart = _auto_chart(dataset, ui_cfg)
```

> ⚠️ **舊錯誤**：`(None or "table") != "table"` 結果為 False → auto_chart 從不被呼叫。新邏輯：`"" != "table"` 為 True → 正確觸發。

#### Try Run 效能統計

`try_run()` 有精確計時 log：
```
try_run perf | stage=LLM_codegen elapsed=X.XXs raw_data_records=N
try_run perf | stage=sandbox_exec elapsed=X.XXs raw_data_records=N
```

典型延遲（claude-opus-4-6，100 筆 SPC 資料）：
- LLM_codegen：20–30 秒（95% 以上的延遲）
- sandbox_exec：< 0.5 秒

### 7.4 Event Pipeline Service（`app/services/event_pipeline_service.py`）

#### 完整執行鏈

```
event_type_name + event_params
    → 解析 ET 的 diagnosis_skill_ids（新舊兩種格式）
    → 對每個 Skill：
        1. 取得 mcp_id（skill.mcp_ids[0]）
        2. 載入 MCP、DataSubject
        3. 解析 param_mappings（ET 層級優先於 Skill 層級）
        4. 呼叫 DataSubject API（httpx GET + query params）
        5. execute_script(mcp.processing_script, raw_data)
        6. _normalize_output() + _auto_chart() fallback
        7. 診斷 Path A（Python code）或 Path B（LLM fallback）
        → SkillPipelineResult
```

#### `_parse_et_diagnosis_skills()` — 向下相容解析

同時支援兩種格式：
```python
# 舊格式（Phase 10 以前）
[1, 2, 3]

# 新格式（Phase 11 之後）
[{"skill_id": 1, "param_mappings": [{"event_field": "lot_id", "mcp_param": "lot_id"}]}]
```

#### 診斷雙路徑（Dual Path Diagnosis）

**Path A（優先）**：Python code sandbox
```python
last_dr = json.loads(skill.last_diagnosis_result)
generated_code = last_dr.get("generated_code", "")
if generated_code:
    py_result = await execute_diagnose_fn(generated_code, {"mcp_name": output_data})
    # py_result = {"status", "diagnosis_message", "problem_object"}
    summary = await self._llm.summarize_diagnosis(python_result=py_result, ...)
```

**Path B（Fallback）**：純 LLM 診斷
```python
llm_result = await self._llm.try_diagnosis(
    diagnostic_prompt=skill.diagnostic_prompt,
    mcp_outputs={"mcp_name": output_data},
)
```

#### `SkillPipelineResult` 欄位

```python
skill_id, skill_name, mcp_name,
status,           # "NORMAL" | "ABNORMAL"
conclusion,       # 一句話結論
evidence,         # list[str]
summary,          # 2-3 句說明
human_recommendation,  # Expert PE 撰寫的建議動作
problem_object,   # {"tool": [...], "recipe": "..."} 或 {}
error,            # None 或錯誤訊息
mcp_output        # Standard Payload（含 dataset, ui_render, _raw_dataset）
```

### 7.5 Help Chat Service（`app/services/help_chat_service.py`）

```python
_MODEL = "claude-opus-4-6"

class HelpChatService:
    # 模組層級快取（避免每次重新讀檔）
    _cached_system = None  # 完整 system prompt（user_manual + product_spec）

    async def stream_chat(message: str, history: List[Dict]) -> AsyncIterator[Dict]:
        # system: [{type:"text", text:..., cache_control:{"type":"ephemeral"}}]
        # messages: history + [{role:"user", content:message}]
        async with client.messages.stream(
            model=_MODEL, max_tokens=2048, system=..., messages=...
        ) as stream:
            async for text in stream.text_stream:
                yield {"type": "chat", "message": text}
        yield {"type": "done"}
```

**Prompt Caching**：系統文件（~58 KB）使用 `cache_control: ephemeral`，大幅降低重複呼叫成本。

### 7.6 Copilot Service（`app/services/copilot_service.py`）

#### `stream_chat()` 設計模式

```python
def stream_chat(self, ...):
    """同步函式，回傳 async generator"""
    return self._stream_chat_impl(...)

async def _stream_chat_impl(self, ...):
    """實際的 async generator"""
    yield {...}
```

> 注意：`stream_chat()` 是 **regular `def`**，不是 `async def`，回傳 `_stream_chat_impl()` 的 async generator 物件。

#### Skill Result 必要欄位

```python
yield {
    "type": "skill_result",
    "skill_id": ..., "skill_name": ..., "mcp_name": ...,
    "status": ..., "conclusion": ..., "evidence": [...],
    "summary": ...,
    "problem_object": llm_result.get("problem_object") or {},  # ⚠️ 不可省略
    "human_recommendation": skill.human_recommendation or "",
    "mcp_output": output_data,
    "tab_title": ...,
}
```

> ⚠️ `problem_object` 曾缺漏（commit `d98e1bf`），導致 Copilot Skill card 不顯示「有問題的物件」區塊。

---

## 8. 前端 SPA 規格

### 8.1 檔案結構

```
static/
├── index.html   # 主要 SPA HTML（含側欄、所有頁面容器、Help 面板）
├── app.js       # 主要 JS（診斷、Copilot、Help Chat）
├── builder.js   # MCP Builder + Skill Builder JS
└── style.css    # 自訂 CSS（slash menu、chat bubble、skill card 樣式）
```

### 8.2 全域狀態變數（`app.js`）

| 變數 | 說明 |
|------|------|
| `_helpPanelOpen` | Help Panel 開關狀態 |
| `_helpHistory` | Help Chat 對話歷史（跨頁面保留）|
| `_helpStreaming` | 防止重複送出 |
| `_selected_tool_id` | Copilot slot_context 選中工具 ID |
| `_selected_tool_type` | `"mcp"` \| `"skill"` |
| `_copilotStreaming` | 防止重複送出 |
| `_slotContext` | Copilot 累積 slot 值 |

### 8.3 SSE 消費模式（Fetch + ReadableStream）

```javascript
const resp = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
const reader = resp.body.getReader();
const decoder = new TextDecoder();
let buf = "";
while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const parts = buf.split("\n\n");
    buf = parts.pop();
    for (const part of parts) {
        const event = _parseCopilotChunk(part);  // or _parseSSEChunk()
        handleEvent(event);
    }
}
```

### 8.4 Try Run 120 秒逾時（`builder.js`）

```javascript
const _tryRunAbort = new AbortController();
const _tryRunTimer = setTimeout(() => _tryRunAbort.abort(), 120000);
try {
    const result = await _api('POST', '/mcp-definitions/try-run', {...}, _tryRunAbort.signal);
    clearTimeout(_tryRunTimer);
} catch (e) {
    if (e.name === 'AbortError') showError('⏱ 請求超時（已等待 120 秒）...');
}
```

Loading 訊息：`🧠 AI 正在深度編譯與驗證腳本，此過程約需 30–60 秒，請耐心等候...`

### 8.5 Plotly 圖表渲染規範

前端透過以下邏輯渲染 `charts[]`：

```javascript
if (typeof chartStr === 'string') {
    // JSON 格式（Plotly dict）
    const spec = JSON.parse(chartStr);
    Plotly.newPlot(container, spec.data, spec.layout);
} else if (chartStr && typeof chartStr === 'object') {
    // 已解析的 dict
    Plotly.newPlot(container, chartStr.data, chartStr.layout);
}
// 若 chartStr 以 "<" 開頭 → HTML，不渲染（已在後端 _normalize_output 過濾）
```

### 8.6 Help Panel UI

```
[側欄]
  ...
  [─ 分隔線 ─]
  [?] nav-btn  ← toggleHelpPanel()
  [⚙] settings
[/側欄]

[Help Panel]（id="help-panel", 360px, fixed, left=56px, z-30）
  [header: 🤖 使用說明 AI 助理 | ✕]
  [#help-chat-history 對話區（overflow-y-auto）]
  [input + 傳送 按鈕]
```

面板動畫：CSS `transform -translate-x-full` ↔ `translate-x-0`（transition-duration 300ms）

---

## 9. 安全模型

### 9.1 JWT 認證

- `Authorization: Bearer <token>` header
- Token 內含 `sub`（username）、`exp`
- `ACCESS_TOKEN_EXPIRE_MINUTES`：預設 30 分鐘
- `SECRET_KEY`：必須使用 `openssl rand -hex 32` 生成強密鑰

### 9.2 沙盒安全（詳見 Section 7.1）

- 靜態 pattern scan + 受限命名空間雙層防護
- 10 秒執行逾時
- 無法讀寫檔案系統、無法發起網路請求、無法反射執行

### 9.3 CORS 設定

- `ALLOWED_ORIGINS`：開發環境可設 `"*"`；生產環境應設特定 origin
- `allow_credentials=True`

### 9.4 預設帳號（開發/測試）

| username | password | 角色 |
|---------|---------|------|
| admin | admin | it_admin, expert_pe, general_user |
| gill | gill | it_admin, expert_pe, general_user |

> ⚠️ **生產環境必須立即修改預設密碼或停用預設帳號**。

---

## 10. 設定與環境變數

### 10.1 `app/config.py`（`pydantic-settings BaseSettings`）

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `DATABASE_URL` | `sqlite+aiosqlite:///./dev.db` | 資料庫連線字串 |
| `LLM_MODEL` | `claude-opus-4-6` | Anthropic 模型 ID |
| `SECRET_KEY` | （必填）| JWT 簽名金鑰 |
| `ALGORITHM` | `HS256` | JWT 演算法 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Token 有效期 |
| `ALLOWED_ORIGINS` | `"*"` | CORS origin（逗號分隔）|
| `ANTHROPIC_API_KEY` | （必填）| Anthropic API Key |
| `API_V1_PREFIX` | `/api/v1` | API 路由前綴 |
| `APP_NAME` | `FastAPI Backend Service` | |
| `APP_VERSION` | `0.1.0` | |
| `DEBUG` | `False` | |
| `HTTPX_TIMEOUT_SECONDS` | `30` | DataSubject API 請求逾時 |

`get_settings()` 使用 `@lru_cache` — **修改 `.env` 後必須重啟 server**。

### 10.2 `.env` 範例

```env
DATABASE_URL="sqlite+aiosqlite:///./dev.db"
LLM_MODEL="claude-opus-4-6"
SECRET_KEY="your-secret-key-change-this-in-production-use-openssl-rand-hex-32"
ALGORITHM="HS256"
ACCESS_TOKEN_EXPIRE_MINUTES=30
ALLOWED_ORIGINS="*"
ANTHROPIC_API_KEY="sk-ant-api03-..."
```

> ⚠️ **.env 常見錯誤**：value 兩端不可有多餘引號。例如 `LLM_MODEL="claude-opus-4-6""` （尾部多一個 `"`）會導致模型 ID 解析錯誤、API 回傳 404。

### 10.3 支援的模型 ID

| 模型 | ID | 備註 |
|------|----|------|
| Claude Opus 4.6 | `claude-opus-4-6` | 最強，Try Run 用 |
| Claude Sonnet 4.6 | `claude-sonnet-4-6` | 較快，但圖表合規性較差 |
| Claude Haiku 4.5 | `claude-haiku-4-5-20251001` | 最快 |

> ⚠️ `claude-3-5-sonnet-20241022` 是**無效**的舊 ID，會回傳 404。

---

## 11. 部署指南

### 11.1 開發環境

```bash
cd fastapi_backend_service
pip install -r requirements.txt
uvicorn main:app --reload
```

### 11.2 測試

```bash
pytest --cov=app --cov-report=term-missing
```

配置檔 `pytest.ini`：`asyncio_mode = auto`

### 11.3 資料庫遷移

**開發（SQLite）**：
```bash
# 新增欄位（create_all 不 ALTER 既有表）
sqlite3 dev.db "ALTER TABLE skill_definitions ADD COLUMN last_diagnosis_result TEXT;"
```

**生產（PostgreSQL）**：
```bash
alembic upgrade head
```

重要 Alembic 檔案：
- `alembic/env.py`：async mode，從 `config.py` 讀取 `DATABASE_URL`
- `alembic/versions/001_add_last_diagnosis_result.py`：Phase 14 `last_diagnosis_result` 欄位

### 11.4 生產環境 Prompt 管理

若生產環境 DB 的 `system_parameters` 有舊版 prompt，LLM 會使用過期設定。修復方式：

```bash
# 刪除舊 prompt，讓系統改用程式碼中的最新版本
python3 scripts/reset_mcp_prompts.py dev.db
```

腳本刪除 `PROMPT_MCP_GENERATE` 和 `PROMPT_MCP_TRY_RUN` 兩個 key（不影響 `PROMPT_SKILL_DIAGNOSIS`，因其每次啟動強制更新）。

---

## 12. 血淚教訓 — 程式碼考古

本節記錄在穩定性和圖表渲染上做過的關鍵修改，這些修改均已進入正式程式碼，但背後的理由值得文件化。

### 12.1 Plotly 輸出格式戰爭

**問題**：LLM 持續生成 `fig.to_html(full_html=False)` 即使系統 prompt 禁止。

**演進過程**：

| 版本 | 方案 | 問題 |
|------|------|------|
| Phase 8 | LLM prompt 禁止 `fig.to_html()` | LLM 忽略規則 |
| Commit `0f14c93` | Prompt 改為 `json.dumps(fig.to_dict())` | LLM 仍忽略 |
| Commit `7119396` | `_normalize_output()` 偵測並剔除 HTML chart | chart 被剔除後無 fallback |
| Commit `1b5252d` | 加入 `_auto_chart()` fallback | 條件 bug：auto_chart 從不觸發 |
| Commit `550443d` | 修正 auto_chart 觸發條件 | LLM 仍偶發 to_html() |
| Commit `16c6f32` | sandbox `_rewrite_plotly_output()` | 使用 `json.dumps(fig.to_dict())` → Timestamp 爆炸 |
| Commit `0cdefc0` | 改為 `fig.to_json()` | 正確解法：Plotly 自己的 encoder |

**最終架構（多層防護）**：
1. LLM prompt：明確要求 `json.dumps(fig.to_dict())`（prompt 層）
2. Sandbox pre-exec：`fig.to_html()` → `fig.to_json()`（rewrite 層）
3. `_normalize_output()`：剔除 HTML chart（sanitize 層）
4. `_auto_chart()` fallback：無圖表時自動生成（fallback 層）

### 12.2 `fig.to_json()` vs `json.dumps(fig.to_dict())`

**結論**：用 `fig.to_json()`，不用 `json.dumps(fig.to_dict())`。

**原因**：
- `fig.to_dict()` 內部可能包含 pandas `Timestamp` 或 numpy 物件
- `json.dumps()` 是 Python stdlib，不認識 Timestamp → `TypeError`
- `fig.to_json()` 使用 Plotly 自訂 encoder，能處理所有 pandas/numpy 類型

**例外**：`_auto_chart()` 中用 `json.dumps(fig.to_dict())` — 因為 `_auto_chart()` 的輸入是已經過 `_make_json_serializable()` 清理的 dataset，不含 Timestamp。

### 12.3 Auto Chart 觸發條件 Bug

**舊錯誤程式碼**：
```python
if (ui_cfg.get("chart_type") or "table") != "table":
    # 當 chart_type 為 None 或 "" 時，
    # (None or "table") == "table" → 條件 False → auto_chart 從不執行
```

**修正後**：
```python
chart_type = ui_cfg.get("chart_type") or ""
if chart_type != "table":
    # "" != "table" 為 True → 正確觸發
```

### 12.4 `_strptime` / `_datetime` 白名單問題

**問題**：sandbox `_ALLOWED_BASE_MODULES` 最初缺少 `_strptime` 和 `_datetime`。
LLM 腳本呼叫 `datetime.strptime()` 時 CPython 內部觸發 `import _strptime`，被攔截並拋出 `ImportError`。

**修正**：加入 `"_strptime"` 和 `"_datetime"` 到白名單（commit `d2cfd98`）。

**重要**：這些 `_xyz` 模組是 CPython 內部 C extension，**不具網路/檔案系統能力**，加入白名單是安全的。

### 12.5 生產環境 Stale Prompt 問題

**症狀**：本地圖表正常，生產環境圖表只顯示 UCL/LCL，無主值折線。

**根因**：`system_parameters` 表中的 `PROMPT_MCP_TRY_RUN` 是舊版本，不含多-trace 骨架規範。

**`_FORCE_UPDATE_PARAMS` 機制**：啟動時只強制更新 `PROMPT_SKILL_DIAGNOSIS`。
`PROMPT_MCP_TRY_RUN` 和 `PROMPT_MCP_GENERATE` 如果 DB 有值就不覆蓋，導致生產環境 prompt 過期。

**長期解法**：
1. 執行 `reset_mcp_prompts.py` 清除舊值
2. 考慮將 `PROMPT_MCP_TRY_RUN` 也加入 `_FORCE_UPDATE_PARAMS`

### 12.6 Anthropic SDK Pydantic v2 物件問題

**問題**：`anthropic >= 0.40.0` 的 `messages.create()` 回傳 Pydantic v2 物件（`TextBlock`、`ToolUseBlock`），有額外的 `__pydantic_extra__` 等欄位。直接將這些物件傳入下一次 `messages.create()` 的 `messages` 參數會失敗。

**解法**：`diagnostic_service.py` 的 `_serialize_content()` 函式，將 SDK 物件序列化為純 dict 再傳入。

### 12.7 Copilot `problem_object` 缺漏

**問題**：Event-driven 路徑的 `SkillPipelineResult.to_dict()` 包含 `problem_object`，但 Copilot 路徑的 `copilot_service.py` yield `skill_result` 時遺漏了此欄位。

**修正**（commit `d98e1bf`）：
```python
yield {
    ...
    "problem_object": llm_result.get("problem_object") or {},  # ← 補上
    ...
}
```

**教訓**：兩條路徑（Event-driven 和 Copilot）必須同步維護相同的輸出格式，建議提取成共用的 helper。

### 12.8 Model ID 404 問題

`claude-3-5-sonnet-20241022` 已廢棄，Anthropic API 回傳 404。
正確的 Claude Sonnet 4.6 ID 為 `claude-sonnet-4-6`。

**永遠向 Anthropic 官方文件確認 Model ID**，不要猜測。

### 12.9 Sonnet vs Opus 圖表合規性

**測試結論**（2025-Q4）：
- `claude-opus-4-6`：prompt 合規性較好，即使有 sandbox 保險層仍建議使用
- `claude-sonnet-4-6`：即使有英文 CRITICAL RULE 警告，仍偶發使用 `fig.to_html()`；圖表完整性（4-trace）也較差

**建議**：Try Run 等複雜 code generation 任務維持使用 Opus。

### 12.10 `create_all()` 不 ALTER 既有表

SQLAlchemy `Base.metadata.create_all()` 只建立**不存在的表**，不會更新已存在表的 Schema。

新增欄位時：
- **開發環境**：手動 `sqlite3 dev.db "ALTER TABLE ... ADD COLUMN ..."`
- **生產環境**：Alembic migration script（`alembic upgrade head`）

### 12.11 前端 120 秒逾時的必要性

Try Run API 的 LLM codegen 階段可長達 30–60 秒。瀏覽器預設 Fetch 無逾時，但使用 Nginx 反向代理的生產環境通常有 60 秒 `proxy_read_timeout`。

**前端 `AbortController`** 設定 120 秒（比 Nginx timeout 長），確保使用者看到友善錯誤訊息而非瀏覽器「連線重置」。

---

## 附錄 A：Event Triage 分類規則（`event_triage.py`）

優先權由上到下，第一個匹配即採用：

| 規則 | 關鍵字（含）| 事件類型 | 緊急度 | 後續 Skills |
|------|-----------|---------|--------|------------|
| SPC/AEI/CD | spc, ooc, etch, aei, apc, recipe, lot, chamber, 3sigma, ucl, lcl, 批號, 配方... | `SPC_OOC_Etch_CD` | high | check_recipe_offset → check_equipment_constants → check_apc_params |
| 停機 | down, crash, 掛了, 503, 500, alarm, 緊急停止... | `Equipment_Down` | critical | check_equipment_constants |
| 部署 | deploy, 部署, release, rollback, golden recipe... | `Recipe_Deployment_Issue` | medium | check_recipe_offset → check_apc_params |
| 其他 | （無匹配）| `Unknown_Fab_Symptom` | low | check_equipment_constants |

SPC_OOC_Etch_CD 事件自動萃取屬性：`lot_id`、`eqp_id`（正規式 `[A-Z]{2-4}\d{1-3}`）、`chamber_id`（PM/C + 數字）、`recipe_name`、`rule_violated`（3sigma/連續N點/UCL/LCL）、`consecutive_ooc_count`、`control_limit_type`（UCL/LCL）

---

## 附錄 B：Standard Payload 完整格式

```json
{
  "output_schema": {
    "fields": [
      {"name": "datetime", "type": "string", "description": "量測時間"},
      {"name": "value",    "type": "number", "description": "CD 量測值（nm）"},
      {"name": "UCL",      "type": "number", "description": "管制上限"},
      {"name": "LCL",      "type": "number", "description": "管制下限"},
      {"name": "is_ooc",   "type": "boolean","description": "是否超出管制"}
    ]
  },
  "dataset": [
    {"datetime": "2026-03-01T00:00:00", "value": 47.2, "UCL": 46.5, "LCL": 43.5, "is_ooc": true},
    ...
  ],
  "ui_render": {
    "type": "trend_chart",
    "charts": ["{ \"data\": [...], \"layout\": {...} }"],
    "chart_data": "{ \"data\": [...], \"layout\": {...} }"
  },
  "_is_processed": true,
  "_raw_dataset": [...],     // 原始 DataSubject API 回傳（未經 MCP 腳本處理）
  "_call_params": {"lot_id": "L001", "tool_id": "TETCH01"}  // 呼叫 DS 時實際使用的參數
}
```

---

## 附錄 C：常用維運指令

```bash
# 啟動開發伺服器
cd fastapi_backend_service && uvicorn main:app --reload

# 執行測試
pytest --cov=app --cov-report=term-missing

# 生產 DB 遷移
alembic upgrade head

# 清除過期 prompt（生產環境必要時）
python3 scripts/reset_mcp_prompts.py dev.db

# 手動新增 SQLite 欄位（開發用）
sqlite3 dev.db "ALTER TABLE skill_definitions ADD COLUMN last_diagnosis_result TEXT;"

# 檢查最近提交
git log --oneline -20

# 健康檢查
curl http://localhost:8000/health
```
