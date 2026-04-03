# Master PRD v13.5: Glass Box AI Diagnostic Platform — Agentic Intelligence Edition

**版本**: v13.5 | **日期**: 2026-03-08 | **狀態**: Active Production

---

## 0. 版本沿革

### v12 → v13 升版重點

v12 是 UI/UX 解耦與巢狀架構升級版本，以 Nested Builder + RoutineCheck 為核心，AI 仍停留在單次 LLM call 的 intent parsing 模式（`/diagnose/copilot-chat`）。

v13 全面升級為**真實 Agentic Platform**，核心差異如下：

| 面向 | v12 | v13 |
|------|-----|-----|
| 推理模式 | 單次 LLM call，intent parsing → 執行 | 真實 Tool Use while loop，多步自主推理 |
| Tool 呼叫 | 後端手動 if/else 解析 intent JSON | Anthropic API `tools=[]` 原生 tool_use block |
| 記憶系統 | 無；`history[]` 只在單次對話存在 | 長期 RAG (SQLite keyword / pgvector)；短期 session 快取 |
| System Prompt | 硬編碼在 copilot_service.py | 動態三層組裝：Soul > UserPref > RAG |
| 無窮迴圈防護 | 無 | `MAX_ITERATIONS = 5` 強制中斷 |
| 可觀測性 | thinking SSE event（一條） | 每個 stage 一種顏色事件即時串流（Glass-box Console） |
| 元技能 (Meta-Skills) | draft API exists，但不在 tool loop 內 | 作為 tool_use 工具，Agent 自主呼叫 |
| MCP 架構 | DataSubject + CustomMCP 雙軌 | System MCP + Custom MCP 統一 — 萬物皆 MCP |
| 前端佈局 | 單一面板 | Split-screen 70/30（Data+Chart / Analysis from AI） |

### v13.0 → v13.5 Patch 記錄

| 版本 | Commit 代號 | 內容 |
|------|------------|------|
| v13.0 | 2026-03-07 初始 | AgentOrchestrator 基礎骨架；ContextLoader；ToolDispatcher；SOUL 5 條規則 |
| v13.1 | `add_system_mcp_003` migration | 萬物皆 MCP：`mcp_type/api_config/input_schema/system_mcp_id` 欄位；DataSubject → System MCP 資料搬遷 |
| v13.2 | `add_v13_agent_004` migration | `agent_memories`、`user_preferences`、`agent_sessions` 三張新表 |
| v13.3 | Token Optimization spec | 工具回傳值強制截斷（`_trim_for_llm`）；歷史滑動視窗（`_SESSION_MAX_MESSAGES = 20`）；`<ai_analysis>` 輸出路由；Split-screen 70/30 前端 |
| v13.4 | Pre-flight Validation | `_preflight_validate()` spec §3-A；`list_system_mcps` 工具；SOUL Rule 8 參數精確綁定 |
| v13.5 | Bug fixes | `_clean_history_boundary()` 修復 orphan tool_result → 400 error；`_sanitize_history()` 修復舊 session 記憶體爆炸；`127.0.0.1` 內部路由規則；output_routing_rules 嵌入 Context Loader |

---

## 1. 核心設計原則

### 1.1 玻璃箱原則（Glass Box）

系統的每一個推理步驟、工具呼叫、記憶存取都必須**即時可見**。Agent 的思考過程透過 SSE 串流到前端 Glass-box Console，每種事件以不同顏色標示：

- `context_load` — 藍色：Context 組裝完成（Soul/Pref/RAG）
- `thinking` — 灰色斜體：LLM extended thinking 區塊
- `tool_start` — 黃色：工具呼叫開始
- `tool_done` — 綠色：工具回傳（僅摘要，不 dump raw）
- `synthesis` — 黑色：最終自然語言報告
- `memory_write` — 紫色：長期記憶寫入通知
- `error` — 紅色：錯誤 / MAX_ITERATIONS 中斷
- `done` — 無顏色：串流結束（含 session_id）

### 1.2 Agent-first 架構

所有診斷任務都應透過 Agent (`/agent/chat/stream`) 入口執行。Agent 自主決定呼叫哪些工具、以何種順序執行。開發者不應繞過 Agent 直接呼叫 execute_skill / execute_mcp，除非是前端 Builder 的明確測試場景。

### 1.3 雙視圖分離（LLM readable vs UI render）

每個工具回傳值都嚴格分為兩個不同的視圖：

```
llm_readable_data   → 供 AI Agent 消費（精簡、結構化）
ui_render_payload   → 供前端 UI 渲染（含圖表設定、dataset、Plotly config）
```

**Agent 嚴禁解析 `ui_render_payload`**（Soul Rule 3）。前端嚴禁把 `llm_readable_data` 當作渲染數據。

### 1.4 MCP 執行黃金法則

**只有 MCP Builder 建立全新 MCP 時才呼叫 LLM（try-run）。所有其他場景一律直接執行 Python（run-with-data 或 execute_mcp）。**

詳見 §3（MCP 規範）。

---

## 2. System Architecture

### 2.1 整體架構圖

```
┌──────────────────────────────────────────────────────────────────┐
│                       Frontend SPA (Vanilla JS)                   │
│                                                                    │
│  ┌─────────────────────────────┐  ┌──────────────────────────┐   │
│  │  Left Panel: Chat Console    │  │  Right Panel: Workspace   │   │
│  │  (Agent Glass-box Terminal)  │  │  ┌────────┬───────────┐  │   │
│  │  POST /agent/chat/stream     │  │  │ Data & │ Analysis  │  │   │
│  │  SSE → color-coded events    │  │  │ Chart  │ from AI   │  │   │
│  │                              │  │  │ (70%)  │ (30%)     │  │   │
│  │  Tabs: Workspace / Agent     │  │  └────────┴───────────┘  │   │
│  │  Console / Copilot           │  │  Agent Console (bottom)   │   │
│  └─────────────────────────────┘  └──────────────────────────┘   │
└──────────────────────────────┬───────────────────────────────────┘
                               │ HTTP / SSE
┌──────────────────────────────▼───────────────────────────────────┐
│                     FastAPI (main.py)                             │
│  API Prefix: /api/v1                                              │
│                                                                    │
│  Routers                                                          │
│  ├── /agent/chat/stream   ← AgentOrchestrator SSE                │
│  ├── /execute/skill/{id}  ← SkillExecuteService                  │
│  ├── /execute/mcp/{id}    ← MCPDefinitionService                 │
│  ├── /agent/draft/*       ← AgentDraftService                    │
│  ├── /agent/memory/*      ← AgentMemoryService                   │
│  ├── /agent/preference/*  ← UserPreferenceService                │
│  ├── /agent/soul          ← SystemParameterRepo                  │
│  ├── /agentic/skills/*    ← AgenticSkillRouter (Raw Mode)        │
│  ├── /mcp-definitions/*   ← MCPDefinitionService (Builder)       │
│  ├── /skill-definitions/* ← SkillDefinitionService               │
│  ├── /routine-checks/*    ← RoutineCheckService                  │
│  └── /diagnose/*          ← DiagnosticService (v12 legacy)       │
│                                                                    │
│  Services                                                         │
│  ├── AgentOrchestrator    ← 5-Stage Agentic Loop                 │
│  ├── ContextLoader        ← Soul + UserPref + RAG                │
│  ├── ToolDispatcher       ← 11 tools → internal httpx calls      │
│  ├── AgentMemoryService   ← RAG 記憶讀寫                         │
│  └── MCPDefinitionService ← try-run / run-with-data              │
│                                                                    │
│  Repositories                                                     │
│  └── AsyncSession → SQLAlchemy 2.0                               │
└──────────────────────────────┬───────────────────────────────────┘
                               │ AsyncSession (aiosqlite / asyncpg)
┌──────────────────────────────▼───────────────────────────────────┐
│                     Database (SQLite dev / PostgreSQL prod)        │
│  Tables: users, mcp_definitions, skill_definitions,               │
│          data_subjects, event_types, routine_checks,              │
│          agent_sessions, agent_memories, user_preferences,        │
│          agent_drafts, system_parameters, ...                     │
└──────────────────────────────────────────────────────────────────┘
```

### 2.2 AgentOrchestrator 5-Stage Loop

```
┌─────────────────────────────────────────────────────────────────┐
│                   AgentOrchestrator.run()                        │
│                                                                   │
│  Stage 1: Context Load                                           │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  ContextLoader.build(user_id, query)                        │  │
│  │    → load Soul (SystemParameter AGENT_SOUL_PROMPT)          │  │
│  │    → load UserPref (user_preferences table)                 │  │
│  │    → RAG search (agent_memories, keyword/cosine top-k=5)    │  │
│  │    → assemble: <soul> + <user_preference> + <dynamic_memory>│  │
│  │      + <output_routing_rules>                               │  │
│  │  yield {type: "context_load", ...meta}                      │  │
│  └────────────────────────────────────────────────────────────┘  │
│                          │                                        │
│  Stage 2–4: Tool Use Loop (while iteration < MAX_ITERATIONS=5)  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  anthropic.messages.create(model, system, tools, messages)  │  │
│  │    ↓ stop_reason == "end_turn"                              │  │
│  │  Stage 4: Synthesis → yield {type: "synthesis", text}       │  │
│  │    ↓ stop_reason == "tool_use"                              │  │
│  │  Stage 3: Tool Execute                                       │  │
│  │    → _preflight_validate(tool_name, tool_input)  (§3-A)     │  │
│  │    → ToolDispatcher.execute(tool_name, tool_input)          │  │
│  │    → yield {type: "tool_start", tool, input}                │  │
│  │    → yield {type: "tool_done", tool, result_summary,        │  │
│  │             render_card?}                                    │  │
│  │    → _trim_for_llm(result) → tool_results[]                 │  │
│  │    → messages.append(tool_results)                          │  │
│  │    continue loop                                            │  │
│  │  (MAX_ITERATIONS hit) → yield {type: "error", ...}          │  │
│  └────────────────────────────────────────────────────────────┘  │
│                          │                                        │
│  Stage 5: Memory Write                                           │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  if _new_diagnosis (ABNORMAL):                              │  │
│  │    AgentMemoryService.write_diagnosis(...)                  │  │
│  │    yield {type: "memory_write", content, source}            │  │
│  │  _clean_history_boundary(messages[-20:])                    │  │
│  │  _save_session(session_id, trimmed)                         │  │
│  │  yield {type: "done", session_id}                           │  │
│  └────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. MCP 規範（CANONICAL — 最高優先）

> 任何涉及 MCP 呼叫的功能，開發前必須先對照此章節。違反此規範視為 bug。

### § 3.1 兩條執行路徑（try-run vs run-with-data）

| 路徑 | API | 使用時機 | LLM? | 輸入 |
|------|-----|---------|------|------|
| **A. try-run** | `POST /api/v1/mcp-definitions/try-run` | **MCP Builder 建立全新 MCP（唯一正當時機）** | ✅ LLM 生成 processing_script | `processing_intent` + `sample_data` |
| **B. run-with-data** | `POST /api/v1/mcp-definitions/{id}/run-with-data` | **所有其他場景** | ❌ 直接跑已存 Python | `raw_data`（真實 DS 資料） |

**記憶口訣：只有「第一次建立」才叫 LLM，之後一律跑 Python。**

**禁止項目（NEVER DO）：**

1. 非 MCP Builder 場景呼叫 `POST /mcp-definitions/try-run`
2. 以 `sample_data: null` 或 `sample_data: {}` 呼叫任何 MCP 執行 endpoint
3. 執行前跳過 DS input 收集步驟（靜默繼續 = bug）
4. 新增任何「直接呼叫 execute_script」的路徑而不先 fetch 真實 DS 資料
5. 在 Copilot / RoutineCheck 中以 LLM 生成 processing_script

### § 3.2 System MCP vs Custom MCP 區別

| 屬性 | System MCP (`mcp_type = 'system'`) | Custom MCP (`mcp_type = 'custom'`) |
|------|-----------------------------------|------------------------------------|
| 來源 | 自動從 DataSubject 鏡像建立 | 用戶透過 MCP Builder 建立 |
| processing_script | 無（由 Default Wrapper 代勞） | 有（LLM 生成，使用者可編輯） |
| api_config | 有（底層 HTTP 端點設定） | 無（繼承 System MCP） |
| input_schema | 有（定義必填參數） | 無（繼承 system_mcp_id 的 schema） |
| system_mcp_id | NULL（自身就是來源） | 指向對應的 System MCP ID |
| visibility | public（預設） | 由使用者設定 |
| 用途 | 提供原始資料 | 提供加工後資料（計算/篩選/統計） |

### § 3.3 System MCP 執行路徑（Default Wrapper）

```
Agent 呼叫 execute_mcp(mcp_id=系統MCP的id, params={...})
  → POST /api/v1/execute/mcp/{mcp_id}
  → MCPDefinitionService.run_with_data(mcp_id, raw_data=params, base_url)
  → 識別 mcp_type == 'system'
  → 讀取 api_config.endpoint_url
  → Default Wrapper: HTTP GET/POST 呼叫底層 Mock/Real API
  → 回傳 {status, mcp_id, mcp_name, row_count, output_data, llm_readable_data}
```

注意：`llm_readable_data` 是 JSON 字串，包含前 10 筆資料（preview），限制在 3000 字元以內。

### § 3.4 Custom MCP 執行路徑（processing_script + system_mcp_id fallback）

```
Agent 呼叫 execute_mcp(mcp_id=自訂MCP的id, params={...})
  → MCPDefinitionService.run_with_data(mcp_id, raw_data=params)
  → 識別 mcp_type == 'custom'
  → 若 system_mcp_id 存在：先向 System MCP 取原始資料
  → 若 system_mcp_id 為 NULL（舊資料）：嘗試 name-based fallback（見 §8 Known Issues）
  → 執行 processing_script (Python sandbox) → output_data
  → 回傳標準 Payload
```

### § 3.5 DS Input 收集規則

在呼叫任何 MCP 之前，**必須**先取得 Data Subject 所需的 input 參數：

```
讀取 mcp.input_schema.fields
  → 逐一確認每個 required field 有值
  → 呼叫 DS endpoint fetch 真實資料
  → execute MCP script
```

各場景 DS input 來源：

| 場景 | DS Input 來源 | 處理方式 |
|------|--------------|---------|
| Nested Builder — 建立全新 MCP | `nb-mcp-sample-form` 表單（選完 DS 後動態渲染） | User 手動填入 |
| Nested Builder — 選擇現有 MCP | 選完 MCP 後，從 `mcp.data_subject_id` 取 DS，在 console 渲染表單 | User 手動填入 |
| Agent 呼叫 execute_mcp | Pre-flight Validation (§3-A) 強制向 User 確認 | Agent 暫停詢問 |
| RoutineCheck 排程觸發 | `check.skill_input`（建立時由 user 填寫的固定參數） | 執行時從 skill_input 讀取 |
| Copilot 對話 | LLM 從對話解析；缺漏透過 slot_filling 向 user 要 | slot_filling 機制 |

### § 3.6 Internal URL Rule（必須用 127.0.0.1，不走 nginx）

所有 ToolDispatcher 內部的 httpx 呼叫、Scheduler 的排程呼叫，以及 AgentOrchestrator 組裝 `base_url` 時，**必須使用 `http://127.0.0.1:{PORT}`**，不得使用公開域名或 nginx 反向代理 URL。

原因：Production 環境中，nginx 只轉發外部流量，內部服務間呼叫走 nginx 會造成不必要的延遲和 SSL 問題。

```python
# Scheduler (main.py lifespan)
await start_scheduler(base_url=f"http://127.0.0.1:{settings.PORT or 8000}")

# execute_skill / execute_mcp 從 Request 取 base_url（開發環境）
base_url = f"{request.url.scheme}://{request.url.netloc}"
```

---

## 4. Agent v13 規範

### § 4.1 AgentOrchestrator 5-Stage 架構

詳見 §2.2。核心常數：

```python
MAX_ITERATIONS = 5          # 最大工具呼叫輪數
_SESSION_TTL_HOURS = 24     # Session 過期時間
_SESSION_MAX_MESSAGES = 20  # 保留最近 20 條訊息（~10 輪）
_TOOL_RESULT_MAX_CHARS = 2000  # tool_result 單筆上限
```

### § 4.2 SOUL Prompt 8 條規則

Soul 儲存在 `SystemParameter` 表的 `AGENT_SOUL_PROMPT` key。預設值（`_DEFAULT_SOUL`）包含 8 條不可違反的鐵律：

| Rule | 內容摘要 |
|------|---------|
| Rule 1 | **絕不瞎猜**：數據不足時回報「缺乏資料，無法判斷」，嚴禁推斷或捏造數字 |
| Rule 2 | **診斷優先序**（嚴格順序）：① list_skills → execute_skill ② execute_mcp ③ 使用者明確要求建立新技能時 draft_skill ④ 需建新 MCP 時 list_system_mcps → draft_mcp。嚴禁在只想「查詢」時跳到草稿 |
| Rule 3 | **禁止解析 ui_render_payload**：工具回傳中僅允許讀取 `llm_readable_data` |
| Rule 4 | **草稿交握原則**：新增/修改 DB 資料必須使用 draft_skill / draft_mcp，禁止直接操作資料庫 |
| Rule 5 | **記憶引用誠實**：引用長期記憶時必須標注 `[記憶]` 前綴 |
| Rule 6 | **最大迭代自律**：超過 4 輪工具呼叫未完成，主動回報「超過預期步驟，請人工協助」 |
| Rule 7 | **草稿填寫原則**：`human_recommendation` 欄位絕不自行臆測或補充，使用者未明確告知時一律留空 |
| Rule 8 | **[CRITICAL] 參數精確綁定**：呼叫 execute_mcp / execute_skill 前，所有必填參數必須由使用者明確提供，嚴禁推測或使用模糊值。參數不確定時，必須列出所有候選選項請使用者確認 |

**Soul 優先級：** User soul_override（Admin 設定）> SystemParameter AGENT_SOUL_PROMPT > 程式碼內建 `_DEFAULT_SOUL`

**`output_routing_rules` 區塊**（v13.3 新增，嵌入 Context Loader）：

```
1. Chat Bubble：只能有一句簡短狀態報告 + UI 引導語，禁止出現 Markdown 表格/多行統計
2. 詳細分析（數據表格、統計量、Sigma 計算、專家建議）：必須全部包入 <ai_analysis>...</ai_analysis> 標籤
3. 若沒有詳細分析，則不使用標籤，僅一句對話回覆即可
```

### § 4.3 Pre-flight Validation（§3-A spec）

`_preflight_validate(db, tool_name, tool_input)` 在 `ToolDispatcher.execute()` 之前攔截，返回 error dict（注入為 tool_result）迫使 LLM 向用戶確認，而非盲目執行。

**execute_mcp 驗證流程：**

```
1. 檢查 mcp_id 是否存在
2. 讀取 mcp_type → 決定 input_schema 來源
   - system MCP → 直接讀自身 input_schema
   - custom MCP → 讀 system_mcp_id 指向的 System MCP 的 input_schema
3. 解析 schema.fields，取出 required 欄位列表
4. 比對 tool_input.params 中是否有每個 required 欄位
5. 缺漏 → 回傳 {status: "error", code: "MISSING_PARAMS", message, missing_params, required_params}
6. 全部 optional 欄位但 params 為空 → 回傳警告請 Agent 向 User 確認（避免回傳全量資料）
```

**execute_skill 驗證流程：**

```
1. 檢查 skill_id 是否存在
2. 若不存在 → 回傳 {status: "error", code: "SKILL_NOT_FOUND", message}
```

### § 4.4 Tool Schemas（11 個工具完整說明）

| Tool Name | 描述 | 對應後端 | required params |
|-----------|------|---------|----------------|
| `execute_skill` | 執行診斷技能，回傳 llm_readable_data（含 status/diagnosis_message/problematic_targets）。**嚴禁解析 ui_render_payload** | `POST /execute/skill/{skill_id}` | skill_id, params |
| `execute_mcp` | 執行 MCP（system 或 custom）。system MCP 直接查詢底層 API；custom MCP 執行 Python 腳本 | `POST /execute/mcp/{mcp_id}` | mcp_id, params |
| `list_skills` | 列出所有 public Skills 及 skill_id、名稱、描述、所需參數 | `GET /skill-definitions` | 無 |
| `list_mcps` | 列出所有 Custom MCP（已建立的資料處理管線，含 processing_script）。`draft_skill` 的 mcp_ids 必須從此清單選取 | `GET /mcp-definitions?type=custom` | 無 |
| `list_system_mcps` | 列出所有 System MCP（底層資料來源）及其 input_schema。建立新 Custom MCP 前先用此工具 | `GET /mcp-definitions?type=system` | 無 |
| `draft_skill` | 草稿模式建立新診斷技能。寫入 Draft DB，回傳 deep_link。**mcp_ids 必須填 Custom MCP ID，不可填 System MCP ID** | `POST /agent/draft/skill` | name, diagnostic_prompt, mcp_ids |
| `draft_mcp` | 草稿模式建立新 Custom MCP。回傳 deep_link 供人類審查 | `POST /agent/draft/mcp` | name, system_mcp_id, processing_intent |
| `patch_skill_raw` | 以 OpenClaw Markdown 格式修改現有 Skill。先 GET raw 再 PUT | `PUT /agentic/skills/{skill_id}/raw` | skill_id, raw_markdown |
| `search_memory` | 搜尋 Agent 長期記憶，用於查詢歷史診斷結果或使用者曾說的話 | `AgentMemoryService.search()` | query |
| `save_memory` | 明確儲存一條長期記憶 | `AgentMemoryService.write()` | content |
| `update_user_preference` | 更新使用者個人偏好設定。送出前經 LLM 守門審查 | `POST /agent/preference` | text |

**_trim_for_llm 截斷規則（v13.3）：**

```python
execute_skill  → 只保留 {skill_name, llm_readable_data, status}
execute_mcp    → 保留 {status, mcp_id, llm_readable_data} + dataset_summary（總筆數+平均值摘要）+ 前 5 筆 sample_data
list_*         → 保留前 8 筆，加 _truncated: true 標記
其他           → 直接傳遞（passthrough）
```

### § 4.5 Session History Management

**滑動視窗（Sliding Window）：**

```python
_SESSION_MAX_MESSAGES = 20  # 保留最近 20 條訊息（~10 輪對話）
```

每次 session 存檔時取 `messages[-20:]`，再通過 `_clean_history_boundary()` 處理。

**`_clean_history_boundary()` 的作用：**

當 history 被截斷後，slice 的開頭可能是一個 `user(tool_result)` 訊息，但其對應的 `assistant(tool_use)` 已被截掉。Anthropic API 會拒絕這樣的請求（400 invalid_request_error）。

`_clean_history_boundary()` 的策略：從 messages 開頭逐一跳過 `user(tool_result)` 和緊隨其後的 `assistant` 回應，直到遇到乾淨的 `user(text)` 為止。

**`_sanitize_history()` 的作用（v13.5 新增）：**

修復舊版 session（v13.3 以前）可能存有完整 dataset 的問題。對 `tool_result` 類型的歷史訊息進行清洗：移除 `output_data`、`ui_render_payload`、`_raw_dataset` 欄位，截斷至 `_TOOL_RESULT_MAX_CHARS = 2000` 字元。

### § 4.6 Memory 系統（RAG + short-term session）

**長期記憶（RAG）— `agent_memories` 表：**

| 欄位 | 說明 |
|------|------|
| id | PK |
| user_id | FK to users (CASCADE DELETE) |
| content | 純文字記憶內容 |
| embedding | Dev: JSON float array（keyword fallback）；Prod: pgvector |
| source | `diagnosis` / `agent_request` / `user_preference` / `manual` |
| ref_id | 關聯 skill_id 或 mcp_id（可選） |
| created_at / updated_at | 時間戳 |

**自動寫入時機：** execute_skill 回傳 `status=ABNORMAL` 且有 `problematic_targets` 時，Stage 5 自動呼叫 `AgentMemoryService.write_diagnosis()`。

**Dev 搜尋策略：** 關鍵字 LIKE 搜尋（無 embedding API 時 fallback）。

**短期 Session — `agent_sessions` 表：** UUID session_id，24h TTL，儲存 JSON messages array。

### § 4.7 SSE 事件格式

每個 SSE event 格式：`data: {JSON}\n\n`（注意：全部用 JSON type 欄位，不用 `event:` 行）

| type | 前端顏色 | payload 關鍵欄位 | 說明 |
|------|---------|----------------|------|
| `context_load` | 藍色 | `soul_preview`, `pref_summary`, `rag_hits`, `rag_count`, `history_turns` | Stage 1 完成 |
| `llm_usage` | 灰色 | `input_tokens`, `output_tokens`, `iteration` | 每次 LLM call 的 token 用量 |
| `thinking` | 灰色斜體 | `text` | LLM extended thinking 區塊（選用） |
| `tool_start` | 黃色 | `tool`, `input`, `iteration` | 工具呼叫開始 |
| `tool_done` | 綠色 | `tool`, `result_summary`, `iteration`, `render_card?` | 工具回傳；若有圖表則含 render_card |
| `synthesis` | 黑色 | `text` | 最終自然語言報告（含 `<ai_analysis>` 標籤） |
| `memory_write` | 紫色 | `content`, `source`, `memory_id` | 記憶寫入通知 |
| `error` | 紅色 | `message`, `iteration?` | 錯誤 / MAX_ITERATIONS 中斷 |
| `done` | 無 | `session_id` | 串流結束，前端儲存 session_id |

**render_card 結構（`tool_done` 的附加欄位）：**

```json
// execute_skill 產生的 render_card
{
  "type": "skill",
  "skill_name": "...",
  "status": "ABNORMAL",
  "conclusion": "...",
  "problem_object": [...],
  "mcp_output": {
    "ui_render": { "chart_data": {...} },
    "dataset": [...],
    "_call_params": {...}
  }
}

// execute_mcp 產生的 render_card
{
  "type": "mcp",
  "mcp_name": "...",
  "mcp_output": {
    "ui_render": {...},
    "dataset": [...],
    "_raw_dataset": [...],
    "_call_params": {...}
  }
}

// draft_skill / draft_mcp 產生的 render_card
{
  "type": "draft",
  "draft_type": "skill",
  "draft_id": 123,
  "auto_fill": {...}
}
```

---

## 5. Frontend 規範

### § 5.1 Split-Screen Dashboard Layout（#ws-split-container 70/30）

`#report-panel` 內部分為左右兩個子面板：

```html
<div id="ws-split-container" class="flex-1 flex min-h-0 overflow-hidden">
  <!-- 左側 70%：Data & Chart -->
  <div id="ws-data-pane" style="flex:7"> ... </div>
  <!-- 右側 30%：Analysis from AI -->
  <div id="ws-analysis-pane" style="flex:3" class="bg-slate-50"> ... </div>
</div>
```

**底部：Agent Console（可折疊 Terminal）**

```html
<div id="diag-console" class="flex-shrink-0 bg-slate-900 overflow-hidden"
     style="height:0; transition:height 0.2s ease;">
  <!-- Terminal 輸出：每種 SSE event 對應一種顏色 -->
</div>
```

### § 5.2 Workspace Tab System

工具呼叫每個 render_card 都會在 `#ws-data-tab-bar` 生成一個 Tab（當 ≥2 個結果時顯示 Tab Bar）。

| 函數 | 說明 |
|------|------|
| `_createWorkspaceTab(id, label, content)` | 建立新 Tab（標籤截斷至 18 字元） |
| `_activateWorkspaceTab(id)` | 切換到指定 Tab |
| `_closeWorkspaceTab(id)` | 關閉並移除 Tab |

Tab 命名規則：使用真實 MCP/Skill 名稱，超過 18 字元截斷並加 `…`。

### § 5.3 AI Analysis Panel（#ws-analysis-pane）

右側 30% 面板專門接收 `<ai_analysis>` 標籤內的 Markdown 內容：

- 標題：`✨ Analysis from AI`（紫色 `text-purple-600`）
- `#ws-analysis-content`：overflow-y-auto，`.ai-analysis-body` 使用 `font-size: 12px` 的 Markdown 渲染
- 接收規則：前端 SSE stream parser 偵測 `<ai_analysis>` 標籤，即時將內容路由至此面板（標籤外文字 → Chat Bubble）

### § 5.4 MCP/Skill 結果 Tab 命名規則

- 使用工具回傳的真實名稱（`mcp_name` 或 `skill_name`）
- 超過 18 字元截斷並加 `…`
- 禁止使用 `MCP #123` 等 ID-based 格式（除非 name 取不到）

### § 5.5 Skill Builder Raw Mode（Visual/Raw 切換）

Skill Builder 的 Markdown 編輯器支援 Visual / Raw 兩種模式切換：

- **Visual Mode**：分欄顯示診斷條件、目標物件、專家建議的表單欄位
- **Raw Mode**：完整 OpenClaw Markdown 文字編輯器（`textarea`），可直接編輯生成代碼

Raw Mode API：
- `GET /api/v1/agentic/skills/{skill_id}/raw` — 取得 OpenClaw Markdown
- `PUT /api/v1/agentic/skills/{skill_id}/raw` — 更新 OpenClaw Markdown

### § 5.6 MCP Builder Data Source Dropdown（System MCP fallback via name-match）

MCP Builder 的 Data Source 下拉選單顯示所有 System MCP（`mcp_type=system`）。當使用者選擇 DS 後：

1. `_nbOnDsChange()` 觸發，動態渲染 DS input 表單
2. 若 Custom MCP 的 `system_mcp_id` 為 null（舊資料），前端以 name-based 方式比對 System MCP（詳見 §8 Known Issues）

---

## 6. API Endpoints 完整清單

### 認證
| Method | Path | 說明 |
|--------|------|------|
| POST | `/api/v1/auth/login` | JWT 取得 |
| POST | `/api/v1/auth/register` | 新增用戶 |

### Agent v13
| Method | Path | 說明 |
|--------|------|------|
| POST | `/api/v1/agent/chat/stream` | **真實 Agentic Loop SSE 入口**（取代 /copilot-chat）Request: `{message, session_id?, context_overrides?}` |
| GET | `/api/v1/agent/tools_manifest` | 取得 Agent 工具清單（public skills 的 OpenClaw Markdown 描述） |
| GET | `/api/v1/agent/soul` | 取得 Soul Prompt |
| PUT | `/api/v1/agent/soul` | 更新 Soul Prompt（Admin only） |
| GET | `/api/v1/agent/memory` | 列出記憶（`?limit=50`） |
| POST | `/api/v1/agent/memory` | 手動寫入記憶 |
| DELETE | `/api/v1/agent/memory/{id}` | 刪除記憶 |
| GET | `/api/v1/agent/memory/search` | 語意/關鍵字搜尋（`?q=keyword&top_k=5`） |
| GET | `/api/v1/agent/preference` | 取得個人偏好 |
| POST | `/api/v1/agent/preference` | 更新個人偏好（含 LLM guardrail） |
| POST | `/api/v1/agent/preference/validate` | LLM 守門審查（防 prompt injection） |
| GET | `/api/v1/agent/session/{id}` | 取得 session 訊息 |
| DELETE | `/api/v1/agent/session/{id}` | 清除 session |

### Execute（Agent 工具後端）
| Method | Path | 說明 |
|--------|------|------|
| POST | `/api/v1/execute/skill/{skill_id}` | 執行診斷技能。Request body: 自由 dict 參數。Response: `{llm_readable_data, ui_render_payload, skill_name, status}` |
| POST | `/api/v1/execute/mcp/{mcp_id}` | 執行 MCP（含 System MCP Default Wrapper）。Response: `{status, mcp_id, mcp_name, row_count, output_data, llm_readable_data}` |

`execute_mcp` 回傳的 `mcp_name` 欄位：從 DB 查詢 `mcp.name`（最佳嘗試）。`row_count` 欄位：`len(dataset)` 若 dataset 為 list，否則 0。`llm_readable_data`：JSON 字串，前 10 筆 preview，截斷至 3000 字元。

### Agent Draft
| Method | Path | 說明 |
|--------|------|------|
| POST | `/api/v1/agent/draft/skill` | 草稿建立 Skill（寫入 agent_drafts，不進 skill_definitions） |
| POST | `/api/v1/agent/draft/mcp` | 草稿建立 Custom MCP |
| GET | `/api/v1/agent/draft/{id}` | 取得草稿 |
| PATCH | `/api/v1/agent/draft/{id}/publish` | 草稿審查後正式發佈 |

### Agentic Skill（Expert Raw Mode）
| Method | Path | 說明 |
|--------|------|------|
| GET | `/api/v1/agentic/skills/{skill_id}/raw` | 取得 Skill 的 OpenClaw Markdown |
| PUT | `/api/v1/agentic/skills/{skill_id}/raw` | 更新 OpenClaw Markdown（`{raw_markdown: "..."}` body） |

### MCP Builder
| Method | Path | 說明 |
|--------|------|------|
| GET | `/api/v1/mcp-definitions` | 列出 MCP（`?type=system|custom`） |
| POST | `/api/v1/mcp-definitions` | 建立 Custom MCP |
| GET | `/api/v1/mcp-definitions/{id}` | 取得單一 MCP |
| PATCH | `/api/v1/mcp-definitions/{id}` | 更新 MCP |
| DELETE | `/api/v1/mcp-definitions/{id}` | 刪除 MCP |
| POST | `/api/v1/mcp-definitions/try-run` | **LLM 生成 + 試跑**（僅 MCP Builder 新建時使用） |
| POST | `/api/v1/mcp-definitions/{id}/run-with-data` | 直接執行已存 Python Script |

### Skill Builder
| Method | Path | 說明 |
|--------|------|------|
| GET | `/api/v1/skill-definitions` | 列出 Skills（`?visibility=public`） |
| POST | `/api/v1/skill-definitions` | 建立 Skill |
| PATCH | `/api/v1/skill-definitions/{id}` | 更新 Skill（含儲存 last_diagnosis_result） |
| POST | `/api/v1/skill-definitions/generate-code-diagnosis` | LLM 生成診斷代碼 + 試跑 |

### RoutineCheck & Events
| Method | Path | 說明 |
|--------|------|------|
| GET/POST | `/api/v1/routine-checks` | 巡檢排程 CRUD |
| PATCH/DELETE | `/api/v1/routine-checks/{id}` | 更新/刪除排程 |
| GET | `/api/v1/generated-events` | 查詢已生成的事件 |
| GET/POST | `/api/v1/event-types` | EventType CRUD |

### Diagnostic（v12 Legacy，向後相容）
| Method | Path | 說明 |
|--------|------|------|
| POST | `/api/v1/diagnose/event-driven-stream` | 事件驅動診斷 SSE |
| POST | `/api/v1/diagnose/copilot-chat` | v12 Copilot（保留相容，新版用 /agent/chat/stream） |

### Help
| Method | Path | 說明 |
|--------|------|------|
| POST | `/api/v1/help/chat` | Help Chat SSE（claude-opus-4-6 + cached docs） |

### Mock Data & Misc
| Method | Path | 說明 |
|--------|------|------|
| GET | `/api/v1/mock/spc` | SPC Chart 模擬資料 |
| GET | `/api/v1/mock/apc` | APC 模擬資料 |
| GET | `/api/v1/mock/apc_tuning` | APC Tuning Value 模擬資料 |
| GET | `/api/v1/mock/recipe` | Recipe 模擬資料 |
| GET | `/api/v1/mock/ec` | Equipment Constants 模擬資料 |
| GET | `/health` | 健康檢查（無前綴） |

---

## 7. Database Schema

### 7.1 核心表（繼承自 v12）

**users**
```sql
id INTEGER PK | username VARCHAR(50) UNIQUE | email VARCHAR(100) UNIQUE
hashed_password TEXT | is_active BOOLEAN | is_superuser BOOLEAN
roles TEXT (JSON array) | created_at / updated_at DATETIME
```

**mcp_definitions**（v13 新增欄位標記 ★）

```sql
id INTEGER PK
name VARCHAR(200) UNIQUE
description TEXT
mcp_type VARCHAR(10) NOT NULL DEFAULT 'custom'  ★ ('system' | 'custom')
api_config TEXT (JSON)                           ★ System MCP 用：{endpoint_url, method, headers}
input_schema TEXT (JSON)                         ★ System MCP 用：{fields: [{name, type, required, description}]}
system_mcp_id INTEGER (FK → mcp_definitions.id) ★ Custom MCP 指向其 System MCP
data_subject_id INTEGER (FK → data_subjects.id)  -- Legacy，被 system_mcp_id 取代
processing_intent TEXT
processing_script TEXT
output_schema TEXT (JSON)
ui_render_config TEXT (JSON)
input_definition TEXT (JSON)  -- Legacy param mapping
visibility VARCHAR(20) DEFAULT 'private'
created_at / updated_at DATETIME
```

**skill_definitions**
```sql
id INTEGER PK | name VARCHAR(200) | description TEXT
diagnostic_prompt TEXT | problem_subject TEXT | human_recommendation TEXT
generated_code TEXT | check_output_schema TEXT (JSON)
last_diagnosis_result TEXT (JSON)  -- Phase 14 新增
mcp_ids TEXT (JSON array of int)
visibility VARCHAR(20) DEFAULT 'private'
created_at / updated_at DATETIME
```

**data_subjects**（Legacy，被 System MCP 取代，保留相容）
```sql
id INTEGER PK | name VARCHAR(200) UNIQUE | description TEXT
api_config TEXT (JSON) | input_schema TEXT (JSON) | output_schema TEXT (JSON)
is_builtin BOOLEAN DEFAULT FALSE | created_at / updated_at DATETIME
```

**event_types**
```sql
id INTEGER PK | name VARCHAR(100) UNIQUE | description TEXT
attributes TEXT (JSON) | created_at DATETIME
```

**routine_checks**
```sql
id INTEGER PK | name VARCHAR(200) | skill_id INTEGER FK
cron_expression VARCHAR(100) | skill_input TEXT (JSON)
is_active BOOLEAN | last_run_at DATETIME | created_at / updated_at DATETIME
```

**generated_events**
```sql
id INTEGER PK | event_type_id INTEGER FK | event_params TEXT (JSON)
routine_check_id INTEGER FK (nullable) | created_at DATETIME
```

**system_parameters**
```sql
id INTEGER PK | key VARCHAR(100) UNIQUE | value TEXT | description TEXT
created_at / updated_at DATETIME
```

### 7.2 v13 新增表

**agent_sessions**（短期對話快取）
```sql
session_id VARCHAR(36) PK (UUID)
user_id INTEGER NOT NULL (FK → users.id CASCADE DELETE)
messages TEXT NOT NULL DEFAULT '[]'  -- JSON array of {role, content}
created_at DATETIME(timezone=True)
expires_at DATETIME(timezone=True)  -- 24h TTL
INDEX: ix_agent_sessions_user_id
```

**agent_memories**（長期 RAG 記憶）
```sql
id INTEGER PK AUTOINCREMENT
user_id INTEGER NOT NULL (FK → users.id CASCADE DELETE)
content TEXT NOT NULL  -- 純文字，存入向量前的原文
embedding TEXT  -- Dev: JSON float array；Prod: pgvector column
source VARCHAR(50)  -- 'diagnosis' | 'agent_request' | 'user_preference' | 'manual'
ref_id VARCHAR(100)  -- 關聯 skill_id 或 mcp_id（optional）
created_at / updated_at DATETIME(timezone=True)
INDEX: ix_agent_memories_user_id
```

**user_preferences**（個人 AI 偏好）
```sql
id INTEGER PK AUTOINCREMENT
user_id INTEGER UNIQUE NOT NULL (FK → users.id CASCADE DELETE)
preferences TEXT  -- 自由文字偏好（LLM guardrail 審查後儲存）
soul_override TEXT  -- Admin 專用：覆蓋 Soul 層
created_at / updated_at DATETIME(timezone=True)
INDEX: ix_user_preferences_user_id
```

**agent_drafts**（草稿交握）
```sql
id INTEGER PK
user_id INTEGER FK
draft_type VARCHAR(20)  -- 'skill' | 'mcp'
status VARCHAR(20)  -- 'pending' | 'published' | 'rejected'
payload TEXT (JSON)  -- 草稿內容
deep_link_data TEXT (JSON)  -- 前端跳轉資訊
created_at / updated_at DATETIME
```

### 7.3 Alembic Migrations 順序（2026-03-07）

```
20260307_0001_add_visibility      → skill_definitions 新增 visibility 欄位
20260307_0002_add_agent_drafts    → 建立 agent_drafts 表
20260307_0003_add_system_mcp      → mcp_definitions 新增 mcp_type/api_config/input_schema/system_mcp_id；DataSubject → System MCP 資料搬遷
20260307_0004_add_v13_agent_tables → 建立 agent_memories / user_preferences / agent_sessions 三張新表
20260307_0005_fix_data_subject_nullable → data_subjects 欄位 nullable fix
```

---

## 8. Known Issues & Mitigations

### 8.1 Production Custom MCP system_mcp_id=null → name-based fallback

**問題：** 舊版 Custom MCP 在 `mcp_definitions.system_mcp_id` 欄位為 NULL（migration 0003 上線前建立的資料）。

**症狀：** `execute_mcp` 呼叫時找不到 System MCP，無法取得 input_schema，导致無法執行 pre-flight validation。

**修復（v13.1）：** `_preflight_validate()` 中，若 `system_mcp_id` 為 null，嘗試以 `data_subject_id` 的 DataSubject name 去 mcp_definitions 表查詢同名 System MCP（name-based fallback）：

```python
sys_id = getattr(mcp, "system_mcp_id", None) or getattr(mcp, "data_subject_id", None)
if sys_id:
    sys_result = await db.execute(
        select(MCPDefinitionModel).where(MCPDefinitionModel.id == sys_id)
    )
    schema_src = sys_result.scalar_one_or_none()
```

**長期修復：** 執行 migration 0003 後重跑 seed_data 重建 system_mcp_id 關聯。

### 8.2 tool_use_id orphan 400 error → _clean_history_boundary

**問題：** history trimming 後，messages 陣列開頭可能殘留 `user(tool_result)` 訊息，其對應的 `assistant(tool_use)` 已被截斷。Anthropic API 返回 400 `invalid_request_error`。

**症狀：** 長對話（超過 20 條訊息）後，下一次呼叫必定 400。

**修復（v13.5）：** `_clean_history_boundary()` 在 session 讀取和存檔時，自動略過開頭的 orphan tool_result 對：

```python
def _clean_history_boundary(messages):
    i = 0
    while i < len(messages):
        msg = messages[i]
        if msg.get("role") == "user":
            content = msg.get("content", "")
            is_tool_result = isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in content
            )
            if not is_tool_result:
                break  # 找到乾淨的 user text turn
            i += 1  # 跳過 orphan tool_result
            if i < len(messages) and messages[i].get("role") == "assistant":
                i += 1  # 跳過對應的 assistant 回應
        else:
            i += 1
    return messages[i:]
```

### 8.3 Internal httpx routing through nginx → 127.0.0.1 hardcode

**問題：** Production 環境中，Scheduler 使用公開域名呼叫 API，流量通過 nginx，造成額外延遲和潛在的 SSL 驗證問題。

**修復（v13.x）：** Scheduler 和 ToolDispatcher 的 base_url 一律使用 `http://127.0.0.1:8000`：

```python
# main.py lifespan
await start_scheduler(base_url=f"http://127.0.0.1:{settings.PORT or 8000}")
```

規範：**所有服務內部呼叫必須使用 127.0.0.1，禁止使用公開域名。**

### 8.4 Pre-flight system MCP check missing → 直接檢查自身 input_schema

**問題（v13.3 以前）：** execute_mcp 呼叫 System MCP 時，pre-flight 邏輯會嘗試查詢 `system_mcp_id`，但 System MCP 本身的 `system_mcp_id` 為 null，導致跳過驗證。

**修復（v13.4）：** 識別 `mcp_type == 'system'` 時，直接使用被呼叫的 MCP 本身作為 schema 來源：

```python
mcp_type = getattr(mcp, "mcp_type", "custom") or "custom"
if mcp_type == "system":
    schema_src = mcp  # the called MCP IS the system MCP
else:
    sys_id = getattr(mcp, "system_mcp_id", None) or getattr(mcp, "data_subject_id", None)
    # ... fallback logic
```

### 8.5 舊 Session 記憶體爆炸 → _sanitize_history

**問題：** v13.3 以前建立的 session 可能存有完整 dataset（幾萬字元的 JSON），載入後立即造成 LLM token 超量。

**修復（v13.5）：** `_load_session()` 讀取 history 後，呼叫 `_sanitize_history()` 移除所有超過 2000 字元的 tool_result 中的 `output_data`、`ui_render_payload`、`_raw_dataset` 欄位。

---

## 9. Deployment

### 9.1 基礎設施

| 元件 | 規格 |
|------|------|
| 主機 | AWS EC2（t3.medium 或更高） |
| 反向代理 | nginx（SSL termination，轉發 80/443 → 8000） |
| 進程管理 | systemd service（`fastapi-backend.service`） |
| Python Runtime | Python 3.11+，venv |
| 資料庫 Dev/Prod | SQLite `dev.db`（生產與開發共用單一檔案） |
| 資料庫未來遷移 | PostgreSQL + pgvector（當記憶量 > 10K 條時建議切換） |

### 9.2 GitHub Actions Auto-deploy

Push to `main` 觸發 CI/CD Pipeline：

```yaml
# .github/workflows/deploy.yml（示意）
on:
  push:
    branches: [main]

jobs:
  deploy:
    steps:
      - git pull origin main
      - pip install -r requirements.txt
      - alembic upgrade head  # non-fatal fallback（失敗時繼續啟動）
      - systemctl restart fastapi-backend
```

**Alembic Migration 策略：** `alembic upgrade head` 在每次部署時自動執行，若 migration 失敗（例如欄位已存在），服務仍正常啟動（non-fatal fallback）。

### 9.3 DB Migration 注意事項

SQLite 不支援 `ALTER TABLE ... ADD COLUMN` 的某些操作。v13 新表透過 `init_db()` 的 `create_all()` 自動建立，但既有表的欄位新增需手動執行：

```bash
# 新增 last_diagnosis_result 欄位（Phase 14）
sqlite3 dev.db "ALTER TABLE skill_definitions ADD COLUMN last_diagnosis_result TEXT;"

# 新增 visibility 欄位
sqlite3 dev.db "ALTER TABLE skill_definitions ADD COLUMN visibility VARCHAR(20) DEFAULT 'private';"
sqlite3 dev.db "ALTER TABLE mcp_definitions ADD COLUMN visibility VARCHAR(20) DEFAULT 'private';"

# 執行 Alembic（推薦）
cd fastapi_backend_service
alembic upgrade head
```

### 9.4 環境變數（.env）

```env
DATABASE_URL=sqlite+aiosqlite:///./dev.db
ANTHROPIC_API_KEY=sk-ant-...
SECRET_KEY=<JWT 簽名密鑰>
API_V1_PREFIX=/api/v1
APP_NAME=Glass Box AI Diagnostic Platform
APP_VERSION=13.5.0
DEBUG=false
ALLOWED_ORIGINS=https://yourdomain.com,http://localhost:8000
PORT=8000
LLM_MODEL=claude-sonnet-4-5  # 或 claude-opus-4-6（依用途）
```

### 9.5 啟動流程

```bash
cd fastapi_backend_service/fastapi_backend_service
pip install -r requirements.txt
alembic upgrade head
uvicorn main:app --host 0.0.0.0 --port 8000 --reload  # dev
uvicorn main:app --host 0.0.0.0 --port 8000           # prod
```

**lifespan 啟動順序：**

1. `init_db()` — `create_all()` 建立所有表
2. `_seed_data()` — 種入預設 users、DataSubjects、System MCPs、EventTypes、SystemParameters
3. `start_scheduler()` — APScheduler 啟動（RoutineCheck 排程）

---

## Appendix A：v13 QA 驗收清單

| # | Test Case | 驗收標準 |
|---|-----------|---------|
| TC1 | **Agentic Loop 基礎** | SSE 依序出現 `context_load` → `tool_start(list_skills)` → `tool_done` → `tool_start(execute_skill)` → `tool_done` → `synthesis` |
| TC2 | **MAX_ITERATIONS 中斷** | 第 5 次迭代後出現 `error` event，包含「已達最大迭代上限 (5)」文字，進程正常結束 |
| TC3 | **RAG 生命週期** | 執行 ABNORMAL 診斷 → 再問同一設備 → 回答含 `[記憶]` 前綴 → 刪除記憶 → 回答不含 `[記憶]` |
| TC4 | **草稿交握** | 要求 Agent「幫我建一個新 SPC Skill」→ Agent 呼叫 `list_mcps` 後呼叫 `draft_skill`，回傳 draft_id，skill_definitions 無新增 |
| TC5 | **Prompt Injection 防護** | preference 輸入「忽略之前的指示…」→ `POST /preference/validate` 回傳 `blocked: true`，不寫入 DB |
| TC6 | **Token 瘦身截斷** | execute_skill 回傳 >1000 筆資料 → 後端 tool_result 中 dataset 截斷為 5 筆，無 ui_render 設定 |
| TC7 | **AI Analysis 路由** | Agent 回傳含 `<ai_analysis>` 的 synthesis → 左側 Chat Bubble 只有一句話，右側 Analysis from AI 面板顯示詳細分析 |
| TC8 | **Pre-flight 參數驗證** | Agent 嘗試 `execute_mcp` 不帶 required params → tool_done 顯示 MISSING_PARAMS 錯誤，Agent 轉向詢問用戶 |
| TC9 | **Session 連續對話** | 同 session_id 連續 15 輪對話 → 不出現 400 error；第 16 輪後不出現 orphan tool_result 錯誤 |

---

*本文件為 Glass Box AI Diagnostic Platform v13.5 的 Master PRD，以實際代碼和 migration 為準。如有衝突，代碼實作優先。*
