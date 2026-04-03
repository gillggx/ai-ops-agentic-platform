# AIOps — Manufacturing AI Agent Platform
**Product Spec v1.0 · 2026-03-27**

---

## 1. 產品定位

AIOps 是一個專為**半導體製造廠**設計的 AI 代理人平台，讓製程工程師、品質分析師在不需要寫程式的前提下，透過自然語言對話完成：

- 製程異常根因分析（RCA）
- 設備狀態診斷（SPC / APC / FDC）
- 自動化巡檢排程
- 客製化資料管道與分析腳本的設計

系統核心是一個**具備長期記憶、透明推理過程、可自我學習**的 AI Agent，所有工具呼叫與決策路徑都會即時顯示給使用者。

---

## 2. 使用者角色

| 角色 | 使用場景 |
|------|---------|
| **製程工程師 (PE)** | 查詢異常 lot、分析 OOC 根因、觸發 OCAP 處置 |
| **品質分析師** | 跑 SPC 趨勢分析、監控 Cpk/Cp 指標、查機台穩定性 |
| **IT/系統管理員** | 建立 System MCP（對接各資料源 API）、管理帳號與系統參數 |
| **資深工程師 / 專家** | 設計 Custom MCP（加工腳本）、建立 Skill（診斷規則）、設定巡檢排程 |

---

## 3. 系統架構

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Frontend Layer                              │
│  Next.js SPA (Port 3000)          Static SPA (Port 8000)            │
│  AIOpsLab · Dashboard · Nexus      Chat UI · MCP Builder            │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │ REST / SSE
┌──────────────────────────────────▼──────────────────────────────────┐
│                        FastAPI Backend (Port 8000)                   │
│                                                                      │
│  ┌──────────────┐   ┌──────────────┐   ┌───────────────────────┐   │
│  │ Agent Router  │   │ MCP Builder  │   │   Skill Builder       │   │
│  │ (SSE stream)  │   │ (LLM + Sbox) │   │ (Diagnosis Engine)    │   │
│  └──────┬───────┘   └──────────────┘   └───────────────────────┘   │
│         │                                                             │
│  ┌──────▼────────────────────────────────────────────────────────┐  │
│  │                   Agent Orchestrator                           │  │
│  │  Stage 1: Context Load → Stage 2: Planning → Stage 3: Tools  │  │
│  │  Stage 4: Reasoning   → Stage 5: Memory Write                │  │
│  └──────────────┬────────────────────────────────────────────────┘  │
│                 │                                                     │
│  ┌──────────────▼───────────┐  ┌───────────────────────────────┐   │
│  │     Tool Dispatcher      │  │      Context Loader           │   │
│  │ (22 tools · preflight    │  │  Soul + UserPref + RAG        │   │
│  │  validation · HITL gate) │  │  + MCP Catalog injection      │   │
│  └──────────────────────────┘  └───────────────────────────────┘   │
│                                                                      │
│  ┌──────────────┐  ┌─────────────┐  ┌──────────────────────────┐  │
│  │ Sandbox Svc  │  │  Mem0 + DB  │  │   LLM Client             │  │
│  │ (Python exec │  │  (Semantic  │  │  (Claude / Ollama)       │  │
│  │  10s timeout)│  │   memory)   │  │                          │  │
│  └──────────────┘  └─────────────┘  └──────────────────────────┘  │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │
┌──────────────────────────────────▼──────────────────────────────────┐
│                    Data Layer (SQLite / PostgreSQL)                   │
│  MCPDefinition · SkillDefinition · AgentSession · AgentMemory        │
│  EventType · RoutineCheck · UserPreference · SystemParameter         │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │
┌──────────────────────────────────▼──────────────────────────────────┐
│                   OntologySimulator (Port 8001)                      │
│         MongoDB-based fab data simulator (lot/wafer/tool)            │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 4. 核心概念

### 4.1 MCP — Measurement Collection Pipeline

MCP 是資料管道的基本單位，分兩層：

#### System MCP（IT 管理，底層資料源）
- 定義一個外部 API 的連線設定（endpoint URL、method、headers）
- 定義 input_schema（呼叫這個 API 需要哪些參數）
- 本身不做任何加工，只負責 raw data 的 fetch
- 由 IT Admin 建立，不可被一般用戶修改

#### Custom MCP（工程師建立，加工管道）
- 綁定一個 System MCP 作為資料源
- 包含 `processing_intent`（用自然語言描述加工目標）
- 包含 `processing_script`（LLM 自動生成的 Python 腳本，在 sandbox 執行）
- 產出標準 Payload：`{ dataset: [...], ui_render: {...}, output_schema: {...} }`
- 可設定 `prefer_over_system`：勾選後，底層 System MCP 從 AI 可見目錄中隱藏

```
System MCP (get_step_spc_chart)
    └─ Custom MCP (SPC - standard SPC chart)
            processing_script: def process(raw_data): ...
            → dataset: [{lot_id, value, ucl, lcl, status}, ...]
            → ui_render: {charts: [vega_lite_spec], type: "trend_chart"}
```

**MCP Try-Run 流程（設計期）**
1. 撈取 System MCP 樣本資料（5-10 筆）
2. LLM 根據 processing_intent 生成 processing_script
3. 在 sandbox 執行腳本，驗證輸出格式
4. 成功 → 存入 sample_output；失敗 → LLM 自動 triage 分類錯誤類型

**智能 Try-Run（已有 script 時跳過 LLM）**
- 重新開啟編輯器時，若 intent 未改變且已有 script → 直接跑 sandbox（秒出結果）
- Intent 有修改 → 顯示提示「意圖已變更，將重新生成」
- 手動強制重新生成的按鈕隨時可用

---

### 4.2 Skill — 診斷技能

Skill 是封裝完整診斷邏輯的工具，供 Agent 或巡檢排程呼叫。

```
Skill: "SPC 異常診斷"
  ├─ mcp_ids: [custom_mcp_66]        ← 要查哪些資料
  ├─ diagnostic_prompt: "若最近10批中OOC > 2筆 → ABNORMAL"
  ├─ problem_subject: "TETCH01 蝕刻機"
  └─ human_recommendation: "立即召集 PE 確認 recipe 參數..."
```

**執行流程：**
1. Agent 呼叫 `execute_skill(skill_id, params)`
2. 自動 fetch 所有綁定 MCP 的資料
3. LLM 套用 diagnostic_prompt 對資料做判斷
4. 回傳 `{status: "NORMAL"|"ABNORMAL", diagnosis_message, problematic_targets}`
5. 若 ABNORMAL → 顯示 human_recommendation 給工程師

**可見性：**
- `private`：只有建立者可用
- `public`：所有用戶 + 注入 Agent tools_manifest

---

### 4.3 Agent — AI 診斷代理人

#### 工具清單（22 個）

| 分類 | 工具 | 說明 |
|------|------|------|
| **資料** | `execute_mcp(mcp_name, params)` | 呼叫 Custom MCP，取得加工後資料 |
| **診斷** | `execute_skill(skill_id, params)` | 執行診斷 Skill（NORMAL/ABNORMAL） |
| **探索** | `list_mcps()` | 列出所有 Custom MCPs |
| | `list_system_mcps()` | 列出 System MCPs |
| | `list_skills()` | 列出所有 Skills |
| | `list_routine_checks()` | 列出巡檢排程 |
| | `list_event_types()` | 列出事件類型 |
| **建立資源** | `draft_mcp(...)` | 草稿模式建立 Custom MCP（需用戶確認） |
| | `draft_skill(...)` | 草稿模式建立 Skill（需用戶確認） |
| | `build_mcp(...)` | 自動建立完整 MCP（LLM 全自動） |
| | `build_skill(...)` | 自動建立完整 Skill |
| | `patch_mcp(mcp_id, updates)` | 修改 Custom MCP |
| | `patch_skill_raw(skill_id, markdown)` | 修改 Skill（需 HITL 審核）|
| **自動化** | `draft_routine_check(...)` | 建立定期巡檢（需 HITL 審核） |
| | `draft_event_skill_link(...)` | 連結 Skill 到事件觸發（需 HITL 審核） |
| **分析** | `execute_jit(python_code, ...)` | 執行自訂 Python 分析腳本 |
| | `analyze_data(mcp_id, template, params)` | 預建分析模板（不需寫 Python） |
| | `execute_utility(tool_name, params)` | 100+ 內建統計函式 |
| **記憶** | `save_memory(content, tags)` | 寫入語意記憶 |
| | `search_memory(query, top_k)` | 語意搜尋記憶 |
| | `delete_memory(memory_id)` | 刪除記憶 |
| **導航** | `navigate(target, id, message)` | 導覽至編輯器 |

#### Agentic Loop（5 Stage）

```
User Message
     │
     ▼
Stage 1: Context Load
  ├─ Soul prompt (global rules)
  ├─ UserPref (per-user tuning)
  ├─ RAG top-5 (semantic memory recall)
  └─ MCP Catalog (可用 MCP 列表 XML)
     │
     ▼
Stage 2: Planning
  └─ Agent 輸出 <plan> 描述行動路徑
     │
     ▼
Stage 3: Tool Execution (loop)
  ├─ Pre-flight 驗證 (mcp_name 存在? 必填參數齊全?)
  ├─ HITL Gate (破壞性工具暫停等待確認)
  ├─ Sandbox 執行 (Python 腳本 10s timeout)
  └─ Result 截斷 (max 8000 chars)
     │
     ▼
Stage 4: Reasoning
  └─ LLM synthesize 最終回應（資料蒸餾 → 摘要統計）
     │
     ▼
Stage 5: Memory Write
  └─ 成功模式 → Mem0（衝突時先刪舊再存新）
```

#### Token 管理
- Soft compaction at 40k tokens：LLM 摘要最舊的對話半段
- Hard compaction at 60k tokens：保留最近 3 輪 + 純文字存檔
- Session TTL：24 小時
- Max 12 iterations per request

#### SSE 事件串流
Agent 執行過程中以 SSE 即時推送：`stage_update` / `thinking` / `tool_start` / `tool_done` / `approval_required` / `synthesis` / `memory_write` / `token_usage` / `done`

---

### 4.4 Sandbox — Python 安全沙盒

- **執行限制**：禁用 eval / exec / open / import / subprocess / os / socket
- **時間限制**：10 秒 timeout（asyncio + thread executor）
- **預注入變數（無需 import）**：`pd`（pandas）、`np`（numpy）、`go`（plotly）、`px`（plotly.express）、`plt`（matplotlib）、`tools`（100+ 統計函式）
- **自動正規化**：bare list/dict → Standard Payload；Plotly HTML → JSON；缺 ui_render → 自動補空結構

---

### 4.5 Memory — 語意長期記憶

- **後端**：Mem0（語意向量搜尋）+ 本地 DB 備援
- **注入時機**：每次對話開始，RAG top-5 相關記憶注入 system prompt
- **衝突護欄**：存新記憶前若發現矛盾舊記憶 → 先呼叫 `delete_memory` 再存新的
- **記憶來源**：`mem0`（語意）/ `manual`（用戶明確要求） / `trap`（工具失敗陷阱） / `system`（系統啟動種子）
- **系統種子記憶**（startup 注入）：
  - `【SPC 限制】`：execute_jit 禁止畫 SPC（make_subplots 未安裝）
  - `【時間篩選鐵律】`：simulator 時間軸與現實無關，預設不帶時間篩選

---

## 5. 功能模組

### 5.1 MCP Builder（工程師工具）

**流程：4 步驟引導式設計**

| 步驟 | 內容 |
|------|------|
| Step 1 | 填入 MCP 名稱、說明；選擇 System MCP（資料源）；勾選「優先呼叫此 MCP」（隱藏底層 System MCP）；撈取樣本資料預覽 |
| Step 2 | 輸入 processing_intent（加工意圖）；可呼叫「AI 檢查意圖清晰度」，自動改寫更精確的 prompt |
| Step 3 | 執行 Try-Run：若已有腳本且意圖未改 → 直接跑 sandbox（快速）；否則 LLM 生成腳本再跑；可「強制重新生成」 |
| Step 4 | 確認摘要（名稱、資料源、輸出筆數、LLM 耗時）→ 儲存 |

**相似 MCP 偵測**：Step 1 提交時自動比對現有 MCP，若有高/中相似度 → 顯示警告防止重複建立

---

### 5.2 Skill Builder（診斷規則設計）

- 綁定一到多個 Custom MCP
- 填寫診斷條件（diagnostic_prompt）：「若最近 10 批 OOC > 3 → ABNORMAL」
- 選填專家建議（human_recommendation）
- Try Diagnosis：以樣本資料測試診斷邏輯，預覽 NORMAL/ABNORMAL 結果
- 匯出 OpenClaw Markdown 格式

---

### 5.3 Routine Check — 定期巡檢

- 綁定一個 Skill
- 設定排程：30 分鐘 / 1 小時 / 每日
- 自動執行診斷，結果記錄至 GeneratedEvent
- HITL 審核建立（破壞性操作）

---

### 5.4 Event-Driven Diagnosis — 事件觸發診斷

- 定義 EventType（如 ProcessEnd、SPC_OOC）
- 連結 Skill → 事件發生時自動執行診斷
- OntologySimulator 透過 HTTP 推送事件到 event_pipeline_service

---

### 5.5 Memory Management（管理介面）

- 查看所有記憶（依 source / tag 篩選）
- 手動刪除錯誤記憶
- 搜尋特定 topic 的記憶內容

---

## 6. API 摘要

### Agent
| Method | Path | 說明 |
|--------|------|------|
| POST | `/api/v1/agent/chat` | SSE 串流 agentic loop |
| POST | `/api/v1/agent/approve/{token}` | HITL 工具審核 |
| GET | `/api/v1/agent/tools_manifest` | 可用工具清單 |
| GET/DELETE | `/api/v1/agent/sessions/{sid}` | 對話管理 |

### MCP
| Method | Path | 說明 |
|--------|------|------|
| GET | `/api/v1/mcp_definitions` | 列出（?type=system\|custom） |
| POST | `/api/v1/mcp_definitions` | 建立 |
| PATCH | `/api/v1/mcp_definitions/{id}` | 更新（含 prefer_over_system） |
| DELETE | `/api/v1/mcp_definitions/{id}` | 刪除 |
| POST | `/api/v1/mcp_definitions/{id}/try_run` | LLM 生成 + sandbox 測試（streaming） |
| POST | `/api/v1/mcp_definitions/{id}/run_with_data` | 直接跑 sandbox（已有 script） |
| POST | `/api/v1/mcp_definitions/{id}/sample_fetch` | 撈取 System MCP 樣本資料 |
| POST | `/api/v1/mcp_definitions/check_intent` | 意圖清晰度 AI 檢查 |

### Skill
| Method | Path | 說明 |
|--------|------|------|
| GET | `/api/v1/agentic/skills` | 列出 |
| POST | `/api/v1/agentic/skills` | 建立 |
| PATCH | `/api/v1/agentic/skills/{id}` | 更新 |
| POST | `/api/v1/agentic/skills/{id}/try_diagnosis` | 測試診斷邏輯 |
| GET | `/api/v1/agentic/skills/{id}/raw` | 匯出 OpenClaw Markdown |

---

## 7. 資料模型（核心）

```
MCPDefinitionModel
  id, name, mcp_type (system|custom)
  api_config, input_schema          ← system MCP
  system_mcp_id, processing_intent,
  processing_script, output_schema,
  ui_render_config, sample_output   ← custom MCP
  prefer_over_system (bool)
  visibility (private|public)

SkillDefinitionModel
  id, name, description
  mcp_ids (JSON array)
  diagnostic_prompt, problem_subject
  human_recommendation
  visibility (private|public)

AgentSessionModel
  session_id, user_id
  messages (JSON conversation history)
  cumulative_tokens, workspace_state
  expires_at (24h TTL)

AgentMemoryModel
  id, user_id, content
  source (mem0|manual|trap|system)
  tags (JSON array)
  task_type, data_subject, tool_name
```

---

## 8. 安全與權限

| 機制 | 實作 |
|------|------|
| 認證 | JWT（python-jose），Bearer token，24h expiry |
| 密碼 | bcrypt hash |
| RBAC | roles 欄位（JSON array）：it_admin / expert_pe / general_user |
| HITL | 破壞性工具（patch_skill_raw / draft_routine_check / draft_event_skill_link）需用戶在 chat 中確認 |
| Sandbox | 禁用危險 builtins；allow-list 靜態掃描；10s timeout |
| CORS | 可設定 allowed origins（SystemParameter） |
| Internal API | 系統內部呼叫可繞過 OAuth2（X-Internal-Token header） |

---

## 9. 技術棧

| 層 | 技術 |
|----|------|
| Backend | FastAPI 0.109 + SQLAlchemy 2.0 (async) + Pydantic 2.6 |
| Database | SQLite（dev）/ PostgreSQL（prod）via asyncpg |
| LLM | Anthropic Claude（預設 claude-haiku-4-5-20251001）/ Ollama 相容 |
| Memory | Mem0（語意）+ SQLite（本地備援） |
| Scheduling | APScheduler 3.10 |
| Data Science | pandas / numpy / plotly / scikit-learn / scipy |
| Frontend | Next.js 14 (TypeScript) + Static SPA (Vanilla JS) |
| Container | Docker + Kubernetes (Helm) |
| CI/CD | GitHub Actions（test / build / deploy / security） |

---

## 10. 已知限制 / 設計決策

| 項目 | 說明 |
|------|------|
| scipy 未在 sandbox 預裝 | 需用 numpy 替代（np.polyfit 等） |
| make_subplots 未安裝 | execute_jit 不能直接畫 SPC 多子圖；用 Custom MCP + execute_mcp 替代 |
| Agent 禁止解析 ui_render_payload | 所有 UI 渲染由前端負責；Agent 只能讀 llm_readable_data |
| Session 24h TTL | 長時間專案需手動延續 session 或重開 |
| Max 12 iterations | 複雜多步驟查詢可能需分輪執行 |
| DataSubjectModel | Legacy 資料源，已被 System MCP 取代，僅為 backward compat 保留 |
