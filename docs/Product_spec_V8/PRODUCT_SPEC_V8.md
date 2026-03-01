# Glass Box AI 診斷引擎 — Product Spec V8

> Version: 8.0 | Date: 2026-03-01 | Status: Production

---

## 1. 產品定位

Glass Box AI 診斷引擎是為**半導體製程工程師**（Process Engineer, PE）設計的
**事件驅動式 AI 診斷平台**。當生產線發生 SPC OOC（Out-of-Control）警報或設備異常時，
系統自動調度一組預設的「診斷技能（Skill）」，每個技能透過 MCP（Machine Context Provider）
工具查詢真實數據，再由 LLM 進行推論，最終以可追溯的結構化報告呈現診斷結論。

### 1.1 核心價值主張

| 痛點 | Glass Box 解法 |
|------|--------------|
| 資料散落多個系統（APC/MES/SPC/EC） | MCP 統一查詢介面，一個事件觸發自動取資料 |
| 資深工程師經驗難以傳承 | Skill 系統將 SOP 封裝為可複用的 AI 診斷單元 |
| 診斷等待時間長（需人工集資料） | SSE 漸進串流，每個技能完成立即推播結果 |
| AI 結論無數據依據，不可信 | 每張報告卡片內嵌 MCP 實際查詢資料表格 |
| 非工程師難以建立 AI 工具 | No-Code MCP Builder + LLM Auto-Map |

---

## 2. 技術架構

### 2.1 整體架構

```
┌─────────────────────────────────────────────────────────────┐
│                     瀏覽器 (SPA)                            │
│  ┌──────────────┐  ┌──────────────────────────────────────┐ │
│  │  Chat 區（30%）│  │     診斷報告區（70%）                  │ │
│  │  事件通知卡    │  │  Summary Bar ＋ 逐技能 Tab ＋ 報告卡  │ │
│  └──────────────┘  └──────────────────────────────────────┘ │
└────────────────────────┬────────────────────────────────────┘
                         │ SSE fetch + JWT Bearer
┌────────────────────────▼────────────────────────────────────┐
│              FastAPI Backend (uvicorn)                       │
│  /api/v1/diagnose/event-driven-stream  (SSE)                │
│  /api/v1/builder/auto-map              (LLM)                │
│  /api/v1/builder/validate-logic        (LLM)                │
│  /api/v1/builder/suggest-logic         (LLM)                │
│  /api/v1/mcp-definitions/*             (CRUD)               │
│  /api/v1/skill-definitions/*           (CRUD)               │
│  /api/v1/data-subjects/*               (CRUD)               │
│  /api/v1/event-types/*                 (CRUD)               │
└────────────────────────┬────────────────────────────────────┘
                         │
        ┌────────────────┼────────────────────┐
        ▼                ▼                    ▼
  SQLite / PG      Anthropic API         Mock Data APIs
  (SQLAlchemy)   claude-opus-4-6         /api/v1/mock/*
  AsyncSession     LLM Inference         (APC/SPC/EC/Recipe)
```

### 2.2 Tech Stack

| 層 | 技術 |
|----|------|
| Frontend | Vanilla JS + Tailwind CSS（CDN）+ Plotly.js |
| Backend | FastAPI 0.111 + Python 3.10+ |
| ORM | SQLAlchemy 2.0 (AsyncSession) + aiosqlite |
| Auth | JWT (python-jose) + bcrypt (passlib) |
| LLM | Anthropic SDK (`claude-opus-4-6`) |
| Streaming | Server-Sent Events via `StreamingResponse` |
| Sandbox | Python RestrictedPython sandbox (`sandbox_service.py`) |

### 2.3 DB Models（SQLite/PostgreSQL）

| Model | 用途 |
|-------|------|
| `UserModel` | 使用者帳號 + JWT |
| `DataSubjectModel` | 資料主題（API endpoint + Schema） |
| `MCPDefinitionModel` | MCP 工具（processing_script + output_schema） |
| `SkillDefinitionModel` | Skill（mcp_ids + param_mappings + diagnostic_prompt） |
| `EventTypeModel` | 事件類型（attributes schema） |
| `SystemParameterModel` | 系統參數（LLM Prompts 等） |

---

## 3. 核心元件

### 3.1 四層元件金字塔

```
          ┌─────────────────────┐
          │   🚨 Event Type     │  ← 觸發點，定義診斷情境與參數結構
          └────────┬────────────┘
                   │ 綁定 N 個 Skill
          ┌────────▼────────────┐
          │   🧠 Skill          │  ← AI 診斷單元（診斷 Prompt + 映射規則）
          └────────┬────────────┘
                   │ 呼叫 1 個 MCP
          ┌────────▼────────────┐
          │   🔧 MCP Tool       │  ← Python 腳本（資料查詢 + 加工）
          └────────┬────────────┘
                   │ 對應 1 個 DataSubject
          ┌────────▼────────────┐
          │   📊 Data Subject   │  ← 資料語意定義（Schema + API endpoint）
          └─────────────────────┘
```

### 3.2 Event Type（事件類型）

**已內建事件：** `SPC_OOC_Etch_CD`

屬性欄位（10 個）：

| 屬性 | 型別 | 必填 | 說明 |
|------|------|------|------|
| `lot_id` | string | ✓ | 觸發事件的批次 ID |
| `tool_id` | string | ✓ | 異常蝕刻機台代碼 |
| `chamber_id` | string | ✓ | 異常腔體編號（CH1/CH2） |
| `recipe_id` | string | ✗ | 當時執行的 Recipe ID |
| `operation_number` | string | ✓ | 站點代碼（e.g., 3200） |
| `apc_model_name` | string | ✗ | 觸發時使用的 APC 模型名稱 |
| `process_timestamp` | string | ✓ | 製程完成時間戳記（ISO 8601） |
| `ooc_parameter` | string | ✓ | 超出管制界限的量測參數（e.g., CD_Mean） |
| `rule_violated` | string | ✓ | 違反的 SPC 管制規則 |
| `consecutive_ooc_count` | number | ✓ | 連續超出管制點位次數 |

### 3.3 Data Subject（資料主題）

**已內建 5 個：**

| 名稱 | API Endpoint | 說明 |
|------|-------------|------|
| `APC_Data` | `/api/v1/mock/apc` | APC 控制器補償參數 |
| `Recipe_Data` | `/api/v1/mock/recipe` | Recipe 參數 + 修改時間 |
| `EC_Data` | `/api/v1/mock/ec` | 機台 Equipment Constants |
| `SPC_Chart_Data` | `/api/v1/mock/spc` | SPC 管制圖數據（100筆） |
| `APC_tuning_value` | `/api/v1/mock/apc_tuning` | APC etchTime 調整值 |

每個 DataSubject 包含：
- `name`：識別名稱
- `description`：業務語義說明
- `api_config`：`{ endpoint_url, method, headers }`
- `input_schema`：查詢所需的輸入參數
- `output_schema`：返回欄位定義（`{ fields: [{ name, type, description }] }`）
- `is_builtin`：是否為內建（不可刪除）

### 3.4 MCP Definition（MCP 工具定義）

每個 MCP 工具由以下欄位組成：

| 欄位 | 說明 |
|------|------|
| `name` | 工具識別名稱（snake_case） |
| `description` | 工具用途說明 |
| `data_subject_id` | 關聯的 DataSubject FK |
| `processing_intent` | 自然語言處理意圖（LLM 生成腳本的輸入） |
| `processing_script` | Python 腳本（由 LLM 生成，在沙箱執行） |
| `output_schema` | 腳本輸出欄位定義 |
| `ui_render_config` | 視覺化建議（chart_type/x_axis/y_axis） |
| `input_definition` | 腳本所需輸入參數清單 |

**LLM 生成腳本流程（`PROMPT_MCP_GENERATE`）：**
1. 輸入：DataSubject 名稱 + output_schema + 處理意圖
2. LLM 生成 4 個產物：`processing_script` / `output_schema` / `ui_render_config` / `input_definition`
3. 腳本符合沙箱安全限制

**沙箱限制（`PROMPT_MCP_TRY_RUN`）：**
- ✓ 可用：pandas、plotly、math、statistics、json、datetime
- ✗ 禁用：os、sys、subprocess、requests、open()、eval()、exec()

**MCP 腳本標準輸出格式：**
```python
{
  "output_schema": { "fields": [...] },
  "dataset": [ { col: val, ... }, ... ],
  "ui_render": {
    "type": "table" | "trend_chart" | "bar_chart",
    "chart_data": null | "<Plotly HTML>" | "data:image/png;base64,..."
  }
}
```

### 3.5 Skill Definition（診斷技能定義）

每個 Skill 由以下欄位組成：

| 欄位 | 說明 |
|------|------|
| `name` | Skill 名稱（顯示於 Tab） |
| `description` | 技能用途說明 |
| `event_type_id` | 綁定的 EventType FK（觸發條件） |
| `mcp_ids` | JSON 陣列，關聯的 MCP 工具 ID 清單 |
| `param_mappings` | JSON 陣列，事件屬性 → MCP 輸入欄位映射 |
| `diagnostic_prompt` | AI 診斷邏輯提示詞（判斷異常的條件描述） |
| `human_recommendation` | 工程師手寫的建議行動（不由 AI 生成） |

**`param_mappings` 格式：**
```json
[
  { "event_field": "tool_id", "mcp_param": "target_equipment" },
  { "event_field": "lot_id",  "mcp_param": "lot_id" }
]
```

---

## 4. API 端點完整清單

### 4.1 認證

| Method | Path | 說明 |
|--------|------|------|
| POST | `/api/v1/auth/login` | 登入，返回 JWT token |
| POST | `/api/v1/auth/refresh` | 刷新 token |

### 4.2 診斷

| Method | Path | 說明 |
|--------|------|------|
| POST | `/api/v1/diagnose/` | 文字問題 → SSE 串流（Agent Loop） |
| POST | `/api/v1/diagnose/event-driven` | 事件驅動診斷（同步返回） |
| POST | `/api/v1/diagnose/event-driven-stream` | 事件驅動診斷（SSE，逐技能串流）|

### 4.3 Builder（LLM 設計助手）

| Method | Path | 說明 | LLM 使用 |
|--------|------|------|---------|
| POST | `/api/v1/builder/auto-map` | Event 屬性 → MCP 參數語意映射 | ✓ claude-opus-4-6 |
| POST | `/api/v1/builder/validate-logic` | 驗證診斷 Prompt 的欄位合法性 | ✓ claude-opus-4-6 |
| POST | `/api/v1/builder/suggest-logic` | 根據 Event Schema 生成 PE 邏輯建議 | ✓ claude-opus-4-6 |

### 4.4 資料管理（CRUD）

| 資源 | Prefix | 說明 |
|------|--------|------|
| Data Subjects | `/api/v1/data-subjects` | 資料主題 CRUD |
| MCP Definitions | `/api/v1/mcp-definitions` | MCP 工具 CRUD |
| Skill Definitions | `/api/v1/skill-definitions` | Skill CRUD |
| Event Types | `/api/v1/event-types` | 事件類型 CRUD |
| System Parameters | `/api/v1/system-parameters` | LLM Prompt 等系統參數 |
| Users | `/api/v1/users` | 使用者管理 |

### 4.5 Mock Data

| Method | Path | 說明 |
|--------|------|------|
| GET | `/api/v1/mock/apc` | APC 補償參數 Mock 數據 |
| GET | `/api/v1/mock/recipe` | Recipe 參數 Mock 數據 |
| GET | `/api/v1/mock/ec` | Equipment Constants Mock 數據 |
| GET | `/api/v1/mock/spc` | SPC 管制圖 Mock 數據（100筆） |
| GET | `/api/v1/mock/apc_tuning` | APC etchTime 調整值（100筆） |

---

## 5. LLM 使用全覽

系統在以下 **5 個場景**使用 `claude-opus-4-6`：

| # | 場景 | Endpoint/Service | System Prompt Key | 用途 |
|---|------|-----------------|-------------------|------|
| 1 | **MCP 腳本生成** | `MCPBuilderService.generate_script()` | `PROMPT_MCP_GENERATE` | 從自然語言生成 Python 處理腳本 |
| 2 | **MCP Try Run 沙箱** | `SandboxService.execute_script()` | `PROMPT_MCP_TRY_RUN` | 安全執行並驗證腳本輸出 |
| 3 | **Skill 診斷推論** | `EventPipelineService._run_skill()` | `PROMPT_SKILL_DIAGNOSIS` | 根據 MCP 資料判斷 NORMAL/ABNORMAL |
| 4 | **Auto Map** | `BuilderService.auto_map()` | 內嵌 prompt | Event 欄位 → MCP 參數語意映射 |
| 5 | **Validate Logic** | `BuilderService.validate_logic()` | 內嵌 prompt | 驗證診斷 Prompt 的欄位合法性 |
| 6 | **Suggest Logic** | `BuilderService.suggest_logic()` | 內嵌 prompt | 根據 Event Schema 生成 PE 排障建議 |

---

## 6. 事件驅動診斷流程

### 6.1 完整執行鏈

```
用戶點擊「⚡ 模擬 SPC OOC 觸發」
           │
           ▼
前端：POST /api/v1/diagnose/event-driven-stream
      Body: { event_type, event_id, params: { tool_id, lot_id, ... } }
      Headers: Authorization: Bearer <JWT>
           │
           ▼ SSE 串流開始
EventPipelineService.stream()
  │
  ├─ yield { type: "start", skill_count: N }
  │
  ├─ for each Skill:
  │   ├─ yield { type: "skill_start", skill_name, index }
  │   │
  │   ├─ 1. 查找 EventType → 取得綁定的 Skill 清單
  │   ├─ 2. 讀取 Skill.mcp_ids → 載入 MCP Definition
  │   ├─ 3. 讀取 MCP.data_subject_id → 載入 DataSubject
  │   ├─ 4. 套用 param_mappings：event_params → MCP 輸入
  │   ├─ 5. HTTP GET DataSubject.api_config.endpoint_url（取 raw_data）
  │   ├─ 6. execute_script(mcp.processing_script, raw_data)（沙箱執行）
  │   ├─ 7. LLM診斷：MCPBuilderService.try_diagnosis(diagnostic_prompt, mcp_output)
  │   │      → 返回 { status, conclusion, evidence, summary }
  │   │
  │   └─ yield { type: "skill_done", ...result.to_dict() }
  │
  └─ yield { type: "done" }
```

### 6.2 SSE 事件格式

```json
// start
{ "type": "start", "event": { "event_type": "SPC_OOC_Etch_CD", "event_id": "EVT-xxx", "params": {...} }, "skill_count": 3 }

// skill_start
{ "type": "skill_start", "index": 0, "skill_name": "APC 飽和度檢查", "mcp_name": "" }

// skill_done
{
  "type": "skill_done", "index": 0,
  "skill_id": 1, "skill_name": "APC 飽和度檢查", "mcp_name": "mcp_check_apc_params",
  "status": "NORMAL",
  "conclusion": "APC RF Power 未見飽和現象",
  "evidence": ["etchTime 均值 12.3s（正常範圍 10-15s）"],
  "summary": "APC 控制狀態正常，無需介入",
  "human_recommendation": "持續監控，下次 Lot 跟進",
  "mcp_output": { "dataset": [...], "ui_render": { "type": "table", "chart_data": null } }
}

// done
{ "type": "done" }
```

---

## 7. 前端架構

### 7.1 檔案結構

```
static/
├── index.html      — SPA 骨架（Tailwind CDN + Plotly CDN）
├── style.css       — 自訂 CSS（pipeline blocks、event card、skill tabs...）
├── app.js          — 主邏輯（SSE 串流、Tab 管理、報告渲染）
└── builder.js      — MCP/Skill Builder 頁面邏輯
```

### 7.2 診斷工作站佈局（30/70）

```
┌──────────────┬────────────────────────────────────┐
│  Sidebar     │  Header                            │
│  (bg-blue-   ├────────────────────────────────────┤
│   900)       │  [Chat 30%]  │  [Report 70%]       │
│  ⚡ 診斷中心  │              │  ┌────────────────┐  │
│  🔧 技能庫   │  紅色事件卡   │  │  Summary Bar   │  │
│  ⚙️ 設定     │              │  ├───┬───┬────────┤  │
│              │  ⏳ 進度訊息  │  │T1 │T2 │ T3 ... │  │
│              │              │  ├────────────────┤  │
│              │  ✅ 完成     │  │  Report Card   │  │
└──────────────┴──────────────┴──┴────────────────┘
```

### 7.3 SSE 前端實作（Fetch API）

```javascript
// 使用 fetch + ReadableStream（非 EventSource，支援 Authorization header）
const resp = await fetch('/api/v1/diagnose/event-driven-stream', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${token}`
  },
  body: JSON.stringify(payload)
});
const reader = resp.body.getReader();
// 逐行解析 data: {...}\n\n
```

### 7.4 主要 UI 元件

| 元件 | 描述 |
|------|------|
| 事件通知卡（紅色） | `bg-red-100 border-red-200 border-l-4 border-red-500` |
| Summary Bar（藍色） | `bg-blue-50 border-b border-blue-200`，全技能完成後顯示 |
| 技能 Tab（深藍主題） | `.skill-tab-btn`，active: `border-b-2 border-blue-900` |
| 報告卡片 | `.pipeline-report-block`，含狀態徽章 + 結論 + MCP 資料表 |
| Sidebar | `bg-blue-900`（深海軍藍） |

---

## 8. Builder Copilot 功能

### 8.1 MCP Builder 流程

```
Step 1: 選擇 Data Subject
        │
Step 2: 輸入處理意圖（自然語言）
        │ POST /api/v1/mcp-definitions/  →  LLM 生成腳本
        │
Step 3: Try Run（沙箱執行）
        │ 結果以資料表格顯示
        │
Step 4: 儲存 MCP Definition
```

### 8.2 Skill Builder 流程

```
Step A: 選擇事件類型
        → POST /api/v1/builder/suggest-logic  [LLM: 生成排障邏輯建議]
        │
Step B: 選擇 MCP 工具 + 設定映射
        → POST /api/v1/builder/auto-map  [LLM: 語意自動映射]
        │
Step C: 撰寫診斷 Prompt + 驗證
        → POST /api/v1/builder/validate-logic  [LLM: 語意防呆]
        │
Step D: 設定 Human Recommendation（工程師手寫建議行動）
        │
Step E: 儲存 Skill Definition
```

### 8.3 LLM Auto-Map 輸出格式

```json
{
  "mappings": [
    {
      "event_field": "tool_id",
      "tool_param": "target_equipment",
      "confidence": "HIGH",
      "reasoning": "兩者皆代表蝕刻機台識別代碼"
    }
  ],
  "unmapped_tool_params": ["optional_param"],
  "summary": "成功映射 4/5 個必填參數"
}
```

---

## 9. 系統參數（SystemParameter）

| Key | 用途 |
|-----|------|
| `PROMPT_MCP_GENERATE` | MCP 設計時 LLM 生成 Prompt |
| `PROMPT_MCP_TRY_RUN` | MCP Try Run 沙箱安全規範 Prompt |
| `PROMPT_SKILL_DIAGNOSIS` | Skill 診斷推論 System Prompt |

全部透過 `/api/v1/system-parameters` API 可修改，無需重啟服務。

---

## 10. 身份驗證與安全

- JWT Bearer Token（`Authorization: Bearer <token>`）
- 有效期：24 小時
- 儲存位置：瀏覽器 `localStorage`（鍵名 `glassbox_token`）
- 預設帳號：`gill / gill`，`admin / admin`
- SSE 端點使用 Fetch API（非 EventSource）以支援 Authorization header

---

## 11. 部署與啟動

```bash
cd fastapi_backend_service
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
# → 開啟 http://localhost:8000
```

**自動初始化（Startup Seeding）：**
1. 建立 DB 表格（`init_db()`）
2. 建立預設使用者（gill / admin）
3. 建立 5 個內建 DataSubject
4. 建立 1 個內建 EventType（SPC_OOC_Etch_CD）
5. 建立 3 個 SystemParameter（LLM Prompts）

---

## 12. 測試覆蓋

- 框架：pytest + pytest-asyncio（`asyncio_mode = auto`）
- DB：in-memory SQLite + `app.dependency_overrides[get_db]`
- LLM：測試中 Mock（避免 API 費用）
- 覆蓋率目標：≥ 80%
- 執行：`pytest --cov=app --cov-report=term-missing`
