# AIOps Platform — Architecture Spec v21
**Date:** 2026-03-30
**Status:** Living Document (Current Implementation)
**Supersedes:** v17_architecture.md, v20_platform_architecture.md

---

## 1. 系統全景 (Five-Project Overview)

```
┌──────────────────────────────────────────────────────────────────┐
│  aiops-app  (Next.js)                                            │
│  ┌────────────────────────┐   ┌──────────────────────────────┐  │
│  │  Operations Center     │   │  Knowledge Studio (Admin)    │  │
│  │  - Alarm Dashboard     │   │  - Diagnostic Rules Builder  │  │
│  │  - Root Cause View     │   │  - Auto-Patrols Manager      │  │
│  │  - Agent Chat UI       │   │  - MCP Builder               │  │
│  └────────────────────────┘   └──────────────────────────────┘  │
│                  │ RenderMiddleware                               │
│                  │ reads output_schema → dispatches to           │
│                  │ scalar / table / badge renderer               │
└──────────────────┬───────────────────────────────────────────────┘
                   │ AIOps Report Contract (共同語言)
         ┌─────────▼──────────┐
         │  aiops-contract    │  ← Independent package
         │  Python + TS types │    No dependency on anyone
         │  output_schema     │
         │  SkillFindings     │
         │  ReportContract    │
         └─────────┬──────────┘
                   │
         ┌─────────▼──────────┐
         │  aiops-agent       │  ← AI reasoning microservice
         │  (FastAPI)         │    Knows nothing about UI
         │  LLM orchestration │    Only speaks MCP + Contract
         │  MCP tool calls    │
         └─────────┬──────────┘
                   │ MCP calls  (HTTP)
         ┌─────────▼──────────┐         ┌─────────────────────┐
         │  ontology          │  ─dev─▶  │  ontology-simulator │
         │  (FastAPI)         │  mirror  │  (FastAPI + Next.js) │
         │  Real fab data     │          │  Synthetic fab data  │
         └────────────────────┘          └─────────────────────┘
```

---

## 2. 各層職責與邊界

### 2.1 ontology — 資料服務層

**職責：** AIOps 平台的原始資料來源，封裝真實 FAB 資料庫的查詢邏輯。

- 提供 Lot 追蹤、Process Context (DC/SPC/APC)、設備健康狀態等 API
- 不知道 Agent 的存在，也不知道 UI 的存在
- 純粹的資料服務，無業務邏輯判斷
- 由 aiops-app 決定哪些 ontology API 包裝成 MCP 暴露給 Agent

**核心原則：ontology 是 aiops-app 的內部資產，Agent 永遠不直接呼叫 ontology。**

### 2.2 ontology-simulator — 開發用資料模擬層

**職責：** 開發與測試期間 mirror ontology 的介面，提供合成（synthetic）資料。

- 與 ontology 完全相同的 API 介面（可互換）
- 內建模擬製程狀態機（OOC 事件、Lot 流程、SPC 圖表）
- 提供 NATS event bus 模擬（取代真實 Kafka/Tibco）
- 附帶 Ontology Simulator Dashboard（Next.js）供開發者視覺化觀察合成資料

**在 dev 環境中，所有指向 ontology 的 MCP call 都被路由到 ontology-simulator。**
Production 切換只需改 `MCP.api_config.endpoint_url`，程式碼完全不變。

### 2.3 aiops-contract — 共同語言層（獨立 Package）

**職責：** Agent 與 AIOps App 之間的共同語言，不屬於任何一方。

```
Python package  (aiops-agent 使用)
TypeScript package  (aiops-app 使用)
```

**核心 Schema 定義：**

```
SkillFindings {
  condition_met: bool
  summary: str                      ← 一句話結論
  outputs: Dict[str, Any]           ← 由 output_schema 定義的結構化結果
  impacted_lots: List[str]
  schema_warnings: List[str]
}

OutputSchemaField {
  key: str
  type: "scalar" | "table" | "badge"
  label: str
  unit?: str
  columns?: [{key, label, type}]    ← table 專用
  description?: str
}

InputSchemaField {
  key: str
  type: "string" | "integer" | "boolean"
  required: bool
  default?: Any
  description: str
}
```

**output_schema 是 Render Spec，不是 Data Schema。** LLM 生成 Skill 時同步生成 output_schema，前端 `RenderMiddleware` 讀取它決定如何渲染每個 output 欄位。

### 2.4 aiops-agent — AI 推理微服務

**職責：** 純粹的 AI 推理引擎，完全不知道 UI 的存在。

- 接收 User 意圖（自然語言），透過多步 LLM 推理產出 ReportContract
- 所有外部資料存取只透過 MCP tool call
- MCP catalog 從 aiops-app 動態載入（`GET /api/v1/mcp-catalog`），**不 hardcode 任何 domain MCP 名稱**
- 輸出 AIOps Report Contract（SkillFindings / Vega-Lite spec），aiops-app 接收後渲染
- 可被替換（Claude → GPT → 自建），替換後 MCP catalog 與 Skill 定義不受影響

### 2.5 aiops-app — 應用與渲染層

**職責：** 同時是 User 的操作介面 和 Expert/Admin 的 Knowledge Studio，並持有 ontology 整合。

兩個面向：

| 面向 | 使用者 | 核心功能 |
|------|--------|---------|
| **Operations Center** | 值班 PE / Technician | Alarm Dashboard、Agent Chat、Root Cause View |
| **Knowledge Studio** | Senior PE / Domain Expert | Diagnostic Rules Builder、Auto-Patrols Manager、MCP Builder |

---

## 3. Skill / Diagnostic Rule — Domain Knowledge 的核心

Skill 是由 Domain Expert 在 Knowledge Studio 定義的「診斷函數」。它不屬於 Agent——Agent 只有「執行它」的能力，不擁有它的定義。

### 3.1 Skill 資料模型

```
skill_definitions {
  id, name, description
  source: "legacy" | "rule" | "auto_patrol"   ← discriminator
  trigger_event_id → FK event_types
  trigger_mode: "event" | "schedule" | "both"
  auto_check_description: str                   ← LLM 生成的原始 NL 描述
  steps_mapping: JSON [{step_id, nl_segment, python_code}]
  input_schema:  JSON [InputSchemaField]        ← LLM 定義：Skill 需要哪些 inputs
  output_schema: JSON [OutputSchemaField]       ← LLM 定義：outputs 如何渲染
  visibility: "private" | "public"
  is_active: bool
}
```

### 3.2 LLM 生成流程

```
Expert 輸入 auto_check_description (NL)
          │
          ▼ POST /api/v1/rules/generate-steps
     LLM (Claude)
          │
          ▼ 同時生成：
     ┌────────────────────────────────────────┐
     │ steps_mapping  — Python code steps     │
     │ input_schema   — 此 Skill 需要哪些欄位 │
     │ output_schema  — 每個 output 如何渲染  │
     │ proposal_steps — 人類可讀診斷計畫      │
     └────────────────────────────────────────┘
          │
          ▼
     Expert Try-Run (使用 input_schema 動態生成表單)
          │
          ▼
     儲存至 skill_definitions
```

**input_schema 決定 Try-Run 表單欄位。** 不再有 hardcoded 的 `equipment_id / lot_id / step` 欄位——LLM 根據診斷邏輯決定需要哪些 inputs，前端動態渲染。

### 3.3 _findings Contract (Skill Python Code 必須 assign)

```python
_findings = {
    "condition_met": True,           # Auto-Patrol 讀這個決定是否建立 Alarm
    "summary": "Machine EQP-01 had 4/5 OOC runs, threshold exceeded",
    "outputs": {
        "ooc_count":  4,             # scalar
        "checked":    5,             # scalar
        "records":    [...],         # table (columns defined in output_schema)
        "condition_summary": "超標",  # badge
    },
    "impacted_lots": ["LOT-001"],
}
```

### 3.4 Skill 可用的 MCP（目前）

```python
# 單點快照：取得某 Lot 在某 Step 的目前狀態
result = await execute_mcp('get_process_context', {
    'targetID': lot_id, 'step': step, 'objectName': 'SPC'  # or 'DC'
})

# 歷史快照：取得設備或 Lot 的歷史紀錄（最近 N 筆）
history = await execute_mcp('get_object_snapshot_history', {
    'targetID': equipment_id,  # or lot_id
    'objectName': 'SPC'
})
```

---

## 4. Auto-Patrol — 自動監控編排層

Auto-Patrol 是 Skill 的「排班系統」，決定 Skill 何時、對誰執行，以及執行後的行動。

### 4.1 兩種觸發模式

```
trigger_mode = "event"
  └── NATS/Kafka event 到來 → 找到匹配 event_type_id 的 patrol → 執行 Skill
      event_payload 直接傳入（equipment_id, lot_id, step, event_time）

trigger_mode = "schedule"
  └── cron_expr 觸發 → ContextBuilderService 根據 data_context 建立 payload
      data_context: "recent_ooc" | "active_lots" | "tool_status"
```

### 4.2 執行流程

```
Event arrives (NATS) / Cron fires
        │
        ▼
AutoPatrolService.trigger(patrol_id, event_payload)
        │
        ├── 1. ExecutionLog.create(status="running")
        │
        ├── 2. SkillExecutorService.execute(skill_id, payload)
        │         └── 執行 steps_mapping Python code
        │         └── 呼叫 MCP (→ ontology-simulator / ontology)
        │         └── 捕捉 _findings 變數
        │         └── 回傳 SkillFindings
        │
        ├── 3. ExecutionLog.finish(status, findings, duration_ms)
        │
        └── 4. if findings.condition_met:
                  AlarmService.create(severity, title, findings)
```

### 4.3 ExecutionLog

每次 patrol 執行（event/schedule/manual）都寫入 `execution_logs` 表，用於：
- History Viewer（前端右側 drawer）
- 診斷 Skill 執行狀況（condition_met 統計）
- 未來用於 Auto-Patrol 效能分析

---

## 5. RenderMiddleware — 渲染中介層

**RenderMiddleware 是連接 aiops-contract 與前端渲染的橋樑。** 它讀取 `output_schema`（Render Spec），對每個 output 欄位分派到對應的渲染元件。

```
SkillFindings.outputs
      +
OutputSchemaField[]  (從 skill_definitions.output_schema 來)
      │
      ▼
RenderMiddleware
      │
      ├── type: "scalar" → <strong>{value}</strong> + unit
      ├── type: "badge"  → 顏色 badge（判斷 ok/warn）
      └── type: "table"  → <table> 用 columns 定義表頭 label
```

**使用 RenderMiddleware 的場景：**
1. **Try-Run 結果** — Skill Builder / Diagnostic Rules Builder modal 內
2. **Auto-Patrol History Drawer** — 展開執行紀錄時顯示 findings
3. **Alarm 詳情面板** — Operations Center 點開 Alarm 時顯示 evidence（待實作）
4. **Agent Chat 回覆** — Agent 輸出 ReportContract 時（待實作）

---

## 6. 資料流總覽

### 6.1 Expert 建立 Skill

```
Expert: 輸入 auto_check_description
    → LLM: 生成 steps_mapping + input_schema + output_schema
    → Frontend: Try-Run (input_schema 動態表單)
    → Backend: 沙盒執行 Python steps → _findings
    → Frontend: RenderMiddleware 渲染結果
    → Expert: 確認後儲存
    → DB: skill_definitions (含 input_schema, output_schema)
```

### 6.2 Event 觸發 Auto-Patrol

```
OntologySimulator: 發出 SPC_OOC NATS event
    → NATSEventListener: 找到匹配的 auto_patrols
    → AutoPatrolService.trigger()
    → SkillExecutorService: 執行 Python steps
        → execute_mcp() → OntologySimulator REST API
        → 捕捉 _findings
    → ExecutionLog: 寫入結果
    → if condition_met: AlarmService.create()
    → Frontend (History Viewer): 可看到此次執行紀錄
```

### 6.3 Agent Chat (User)

```
User: 自然語言提問
    → aiops-app: 轉發給 aiops-agent
    → aiops-agent: S1 pull MCP catalog (GET /api/v1/mcp-catalog)
    → aiops-agent: LLM 推理 → 決定呼叫哪些 MCP
    → aiops-agent: execute_mcp() calls → ontology (data)
    → aiops-agent: 輸出 ReportContract (SkillFindings / Vega-Lite)
    → aiops-app: RenderMiddleware 渲染回覆
    → User: 看到結構化結果
```

---

## 7. 依賴關係 (Clean)

```
ontology            ← 無依賴（只有 FAB DB）
ontology-simulator  ← mirrors ontology interface（dev only）
aiops-contract      ← 無依賴（純 schema 定義）
aiops-agent         ← 依賴 aiops-contract
aiops-app           ← 依賴 aiops-contract；内部持有 ontology integration
```

**不允許的依賴：**
- `aiops-agent` → `ontology` (直接) ❌ 必須透過 MCP
- `aiops-agent` → `aiops-app` ❌ Agent 不知道 App 存在
- `ontology` → `aiops-agent` ❌
- `ontology` → `aiops-app` ❌ 資料層不依賴應用層

---

## 8. 架構決策記錄 (ADR)

| # | 決策 | 原因 |
|---|------|------|
| ADR-01 | Contract 作為獨立 package | 避免 Agent 與 App 互相依賴；任何前端只要實作 Contract 就能接 Agent |
| ADR-02 | Agent 只透過 MCP 存取資料 | ontology 是 AIOps 的內部資產，Agent 不應知道它的存在 |
| ADR-03 | output_schema 是 Render Spec | LLM 生成 Skill 時同步生成渲染描述，前端 RenderMiddleware 無需知道 Skill 的業務邏輯 |
| ADR-04 | input_schema 由 LLM 定義 | Skill 需要哪些 inputs 是 Skill 本身的知識，不應由前端 hardcode；LLM 根據診斷邏輯決定 |
| ADR-05 | trigger_alarm() 從 Skill 移除 | Alarm 建立決策屬於 Auto-Patrol，Skill 只負責診斷邏輯；分離關注點 |
| ADR-06 | ontology-simulator mirrors ontology | dev 環境與 production 切換只改 endpoint_url，程式碼不變 |
| ADR-07 | MCP catalog 動態注入 Agent system prompt | Agent 程式碼內不出現任何 domain-specific 工具名稱；換 domain 只需換 catalog |
| ADR-08 | source discriminator 在 skill_definitions | 同一張表儲存 Diagnostic Rules / Auto-Patrol skills / legacy skills，用 source 欄位區分，避免 schema 重複 |

---

## 9. 目前實作狀態

| 模組 | 狀態 | 備註 |
|------|------|------|
| ontology-simulator | ✅ 運行中 | NATS + REST API + Dashboard |
| aiops-app / Operations Center | ✅ 運行中 | Alarm Dashboard, Agent Chat |
| aiops-app / Knowledge Studio — Diagnostic Rules | ✅ 完成 | input_schema + output_schema + RenderMiddleware |
| aiops-app / Knowledge Studio — Auto-Patrols | ✅ 完成 | Edit + History Drawer + ExecutionLog + RenderMiddleware |
| aiops-app / Knowledge Studio — MCP Builder | ✅ 運行中 | |
| aiops-contract | ⏳ 尚未獨立 | 目前 schema 定義在 fastapi_backend_service 內 |
| aiops-agent (獨立微服務) | ⏳ 尚未獨立 | 目前 LLM 邏輯在 fastapi_backend_service 內 |
| ontology (真實) | ⏳ 尚未建立 | dev 使用 ontology-simulator |

*最後更新：2026-03-30*
