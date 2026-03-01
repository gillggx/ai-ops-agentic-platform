# Glass Box AI 診斷引擎 — Product Spec V10

> Version: 10.0 | Date: 2026-03-02 | Status: Production

---

## 1. 產品定位

Glass Box AI 診斷引擎是為**半導體製程工程師**（Process Engineer, PE）設計的
**事件驅動式 AI 診斷平台**。當生產線發生 SPC OOC（Out-of-Control）警報或設備異常時，
系統自動調度一組預設的「診斷技能（Skill）」，每個技能透過 MCP（Machine Context Provider）
工具查詢真實數據，再由 LLM 進行推論，最終以可追溯的結構化報告呈現診斷結論。

V10 在 V8 基礎上新增：
- **V9**：Copilot 智能對話助手（Slot Filling + Slash Command 直呼工具）
- **V9.1**：右側多頁籤工作區（Multi-Tab Workspace）
- **V10**：Mobile-First 響應式佈局 + 手勢滑動切換

### 1.1 核心價值主張

| 痛點 | Glass Box 解法 |
|------|--------------|
| 資料散落多個系統（APC/MES/SPC/EC） | MCP 統一查詢介面，一個事件觸發自動取資料 |
| 資深工程師經驗難以傳承 | Skill 系統將 SOP 封裝為可複用的 AI 診斷單元 |
| 診斷等待時間長（需人工集資料） | SSE 漸進串流，每個技能完成立即推播結果 |
| AI 結論無數據依據，不可信 | 每張報告卡片內嵌 MCP 實際查詢資料表格 |
| 非工程師難以建立 AI 工具 | No-Code MCP Builder + LLM Auto-Map |
| 臨時想查單一數據需要走完整診斷流程 | Copilot 自然語言直呼 MCP/Skill（V9 新增）|
| 多個查詢結果互相覆蓋，無法比對 | Multi-Tab 工作區，每次查詢獨立頁籤（V9.1 新增）|
| 手機端操作困難，工程師無法隨時隨地診斷 | Mobile-First 響應式 + 滑動手勢（V10 新增）|

---

## 2. 技術架構

### 2.1 整體架構

```
┌─────────────────────────────────────────────────────────────────────┐
│                     瀏覽器 (SPA)                                     │
│                                                                     │
│  Desktop (>768px):                                                  │
│  ┌──────────────┐  ┌─────────────────────────────────────────────┐  │
│  │  Chat 區（30%）│  │   Multi-Tab Workspace（70%）                │  │
│  │  事件通知卡    │  │  [🚨 EVT-001] [🔍 APC查詢] [×]           │  │
│  │  Copilot 對話 │  │  ┌──────────────────────────────────────┐  │  │
│  └──────────────┘  │  │  診斷報告卡 / MCP 圖表 / Skill 結果  │  │  │
│                    │  └──────────────────────────────────────┘  │  │
│                    └─────────────────────────────────────────────┘  │
│                                                                     │
│  Mobile (≤768px):                                                   │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │  [💬 對話] ─────────────── [📊 報告]  (toggle bar)            │ │
│  │  ← 滑動切換 / 新 Tab 自動跳轉 →                                │ │
│  └────────────────────────────────────────────────────────────────┘ │
└────────────────────────┬────────────────────────────────────────────┘
                         │ SSE fetch + JWT Bearer
┌────────────────────────▼────────────────────────────────────────────┐
│              FastAPI Backend (uvicorn)                               │
│  /api/v1/diagnose/event-driven-stream  (SSE，逐技能串流)             │
│  /api/v1/diagnose/copilot-chat         (SSE，Copilot 意圖解析)      │
│  /api/v1/builder/auto-map              (LLM)                        │
│  /api/v1/builder/validate-logic        (LLM)                        │
│  /api/v1/builder/suggest-logic         (LLM)                        │
│  /api/v1/mcp-definitions/*             (CRUD)                       │
│  /api/v1/skill-definitions/*           (CRUD)                       │
│  /api/v1/data-subjects/*               (CRUD)                       │
│  /api/v1/event-types/*                 (CRUD)                       │
└────────────────────────┬────────────────────────────────────────────┘
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
| Mobile | CSS Transform + Native Touch Events（無需 react-swipeable） |

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

### 3.1 四層元件金字塔（不變）

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

屬性欄位（11 個，V10 新增 `SPC_CHART`）：

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
| `SPC_CHART` | string | ✓ | **[V9.1 新增]** SPC 圖表名稱，對應 DataSubject chart_name 查詢參數（e.g., CD）|

### 3.3 Data Subject（資料主題）— 不變

**已內建 5 個：**

| 名稱 | API Endpoint | 說明 |
|------|-------------|------|
| `APC_Data` | `/api/v1/mock/apc` | APC 控制器補償參數 |
| `Recipe_Data` | `/api/v1/mock/recipe` | Recipe 參數 + 修改時間 |
| `EC_Data` | `/api/v1/mock/ec` | 機台 Equipment Constants |
| `SPC_Chart_Data` | `/api/v1/mock/spc` | SPC 管制圖數據（100筆，只支援 `chart_name` 過濾）|
| `APC_tuning_value` | `/api/v1/mock/apc_tuning` | APC etchTime 調整值 |

### 3.4–3.5 MCP Definition / Skill Definition — 不變（見 V8 Spec §3.4–3.5）

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
| POST | `/api/v1/diagnose/copilot-chat` | **[V9 新增]** Copilot 自然語言意圖解析 + MCP/Skill 直呼（SSE）|

### 4.3 Builder（LLM 設計助手）— 不變

| Method | Path | 說明 | LLM 使用 |
|--------|------|------|---------|
| POST | `/api/v1/builder/auto-map` | Event 屬性 → MCP 參數語意映射 | ✓ claude-opus-4-6 |
| POST | `/api/v1/builder/validate-logic` | 驗證診斷 Prompt 的欄位合法性 | ✓ claude-opus-4-6 |
| POST | `/api/v1/builder/suggest-logic` | 根據 Event Schema 生成 PE 邏輯建議 | ✓ claude-opus-4-6 |

### 4.4 資料管理（CRUD）— 不變（見 V8 §4.4）

### 4.5 Mock Data — 不變（見 V8 §4.5）

---

## 5. LLM 使用全覽（V9 新增第 7 個）

| # | 場景 | Endpoint/Service | 用途 |
|---|------|-----------------|------|
| 1 | **MCP 腳本生成** | `MCPBuilderService.generate_script()` | 從自然語言生成 Python 處理腳本 |
| 2 | **MCP Try Run 沙箱** | `SandboxService.execute_script()` | 安全執行並驗證腳本輸出 |
| 3 | **Skill 診斷推論** | `EventPipelineService._run_skill()` | 根據 MCP 資料判斷 NORMAL/ABNORMAL |
| 4 | **Auto Map** | `BuilderService.auto_map()` | Event 欄位 → MCP 參數語意映射 |
| 5 | **Validate Logic** | `BuilderService.validate_logic()` | 驗證診斷 Prompt 的欄位合法性 |
| 6 | **Suggest Logic** | `BuilderService.suggest_logic()` | 根據 Event Schema 生成 PE 排障建議 |
| 7 | **Copilot Slot Filling** | `CopilotService.stream_chat()` | **[V9 新增]** 意圖識別、參數追問、工具執行 |

---

## 6. 事件驅動診斷流程 — 不變（見 V8 Spec §6）

---

## 7. V9 新功能：Copilot 智能對話助手

### 7.1 Copilot Slot Filling Engine

用戶在左側 Chat 框輸入自然語言，系統使用 LLM 進行**意圖解析與參數追問**（Slot Filling）。

**Copilot 的 System Prompt 要求 LLM 以純 JSON 回覆：**

```json
{
  "intent": "execute_mcp | execute_skill | general_chat",
  "tool_id": <int 或 null>,
  "tool_type": "mcp | skill | null",
  "extracted_params": { "參數名": "參數值" },
  "missing_params": ["缺少的參數名"],
  "is_ready": false,
  "reply_message": "給使用者的話（追問缺少參數 或 播報執行進度）",
  "tab_title": "若 is_ready=true，生成簡短頁籤標題（e.g., '🔍 APC: L12345@3200'）"
}
```

**執行流程：**
```
用戶輸入自然語言
      │
      ▼
CopilotService.stream_chat()
  ├─ LLM JSON 解析（意圖 + 參數）
  ├─ is_ready = false → reply_message 追問缺少參數
  └─ is_ready = true  → 執行工具
        ├─ intent = execute_mcp   → _execute_mcp()  → SSE mcp_result
        └─ intent = execute_skill → _execute_skill() → SSE skill_result
              │
              ▼
        右側工作區自動建立新 Tab（tab_title 由 LLM 提供）
```

### 7.2 Slash Command 快捷選單

在對話框輸入 `/` 觸發快捷選單：
- 顯示所有可用的 MCP 工具 和 Skill 技能
- 選擇後，工具名稱以 Tag 顯示在輸入框上方
- 後續輸入的內容自動作為該工具的參數

**SSE 事件格式（copilot-chat endpoint）：**

```
data: {"type": "thinking",   "message": "🔍 正在解析意圖..."}
data: {"type": "question",   "message": "請提供 operation_number（例如：3200）"}
data: {"type": "mcp_result", "mcp_id": 1, "mcp_name": "...", "mcp_output": {...}, "tab_title": "🔍 APC: L12345"}
data: {"type": "skill_result","skill_id": 2, "skill_name": "...", "result": {...}, "tab_title": "⚠️ APC飽和度"}
data: {"type": "error",       "message": "..."}
data: {"type": "done"}
```

---

## 8. V9.1 新功能：Multi-Tab 工作區

### 8.1 設計原則

廢除右側 70% 報告區「單一畫面到底」的靜態設計，全面升級為**多頁籤工作區**。

### 8.2 頁籤類型

| 頁籤類型 | 觸發時機 | 標題格式 | 行為 |
|---------|---------|---------|------|
| 事件診斷籤 | 點擊「⚡ 模擬觸發」 | `🚨 {EventID}` | 重觸發時取代舊籤（tabId=`evt-current`）|
| MCP 查詢籤 | Copilot `is_ready=true` + `execute_mcp` | LLM 生成 `tab_title` | 每次呼叫建立新籤 |
| Skill 診斷籤 | Copilot `is_ready=true` + `execute_skill` | LLM 生成 `tab_title` | 每次呼叫建立新籤 |

### 8.3 頁籤管理規則

- 每個 Tab 右側有 `[×]` 關閉按鈕
- 關閉後自動切換到最後一個剩餘 Tab；全部關閉後顯示空白提示
- 標題截斷（max-width: 140px / 180px on mobile），滑鼠 hover 顯示 title 完整內容

### 8.4 前端實作

```javascript
// 三個核心函數
_createWorkspaceTab(tabId, title, contentHtml) → { btn, panel }
_activateWorkspaceTab(tabId)
_closeWorkspaceTab(tabId)

// 狀態
let _workspaceTabs = {};  // { tabId: { btn, panel } }
let _activeTabId   = null;
```

---

## 9. V10 新功能：Mobile-First 響應式佈局

### 9.1 布局策略

| 裝置 | 條件 | 佈局 |
|------|------|------|
| Desktop | 寬度 > 768px | 維持 30%/70% 雙欄並排，Sidebar 可見 |
| Mobile | 寬度 ≤ 768px | 全螢幕單視圖，Chat 與 Workspace 交替顯示 |

### 9.2 Mobile UI 元件

- **頂部切換列（Toggle Bar）**：「💬 對話 ｜ 📊 報告」按鈕，顯示當前視圖
- **Sidebar**：手機版隱藏（節省橫向空間）
- **面板切換**：CSS `transform: translateX()` 動畫，過渡時間 280ms

### 9.3 手勢操作

| 手勢 | 觸發條件 | 結果 |
|------|---------|------|
| 向左滑（Swipe Left） | 在 Chat 視圖滑動 | 切換到 Workspace |
| 向右滑（Swipe Right） | 在 Workspace 視圖滑動 | 切換到 Chat |

- **最小水平位移：** 50px
- **防誤觸：** 水平位移 ÷ 垂直位移 ≥ 1.5（避免垂直滾動被識別為滑動）
- 使用原生 Touch Events（無需第三方庫）

### 9.4 自動切換（Auto-switch）

當 AI 在背景執行 MCP/Skill 並生成新 Tab 時，Mobile 版**自動切換至 Workspace**，讓使用者立即看到結果。

```javascript
// 在 _createWorkspaceTab() 中
if (_isMobile()) _switchMobileView('workspace');
```

### 9.5 其他 Mobile 最佳化

| 項目 | 處理方式 |
|------|---------|
| 資料表格 | `overflow-x: auto` + `min-width: 480px`，支援橫向滑動 |
| Plotly 圖表 | `max-width: 100%`，自適應容器寬度 |
| 輸入框 | `font-size: 16px`，防止 iOS 自動放大 |
| Drawer（抽屜）| Mobile 端寬度 100vw |
| 視窗旋轉 | `window.resize` 事件重新計算布局 |

---

## 10. 前端架構（V10）

### 10.1 檔案結構（不變）

```
static/
├── index.html      — SPA 骨架（Tailwind CDN + Plotly CDN）
├── style.css       — 自訂 CSS（含 Phase 10 Mobile 響應式）
├── app.js          — 主邏輯（SSE、Tab 管理、Copilot、Mobile 切換）
└── builder.js      — MCP/Skill Builder 頁面邏輯
```

### 10.2 診斷工作站佈局

**Desktop（>768px）：**
```
┌──────┬──────────────────────────────────────────────────┐
│ SB   │  Header                                          │
│      ├──────────────┬───────────────────────────────────┤
│  ⚡  │  Chat (30%)  │  Multi-Tab Workspace (70%)        │
│  🔧  │              │  [🚨 EVT] [🔍 APC] [×]  ···      │
│  ⚙️  │  Copilot     │  ┌─────────────────────────────┐  │
│      │  對話框      │  │  報告卡 / MCP 圖表 / 診斷結果│  │
└──────┴──────────────┴──┴─────────────────────────────┘─┘
```

**Mobile（≤768px）：**
```
┌────────────────────────────────────┐
│  Header (compact)                  │
├────────────────────────────────────┤
│  [💬 對話] ──── [📊 報告]          │  ← Toggle Bar
├────────────────────────────────────┤
│                                    │
│  [Chat 視圖]  ←─滑動─→  [Workspace]│
│                                    │
├────────────────────────────────────┤
│  輸入框  [/] [送出]                │
└────────────────────────────────────┘
```

### 10.3 主要 JS 函數一覽（新增 V9–V10）

| 函數 | 新增版本 | 用途 |
|------|---------|------|
| `_sendCopilotMessage()` | V9 | 送出 Copilot 訊息，接收 SSE |
| `_renderCopilotMcpPanel()` | V9.1 | 建立 MCP 查詢 Tab |
| `_renderCopilotSkillPanel()` | V9.1 | 建立 Skill 診斷 Tab |
| `_createWorkspaceTab()` | V9.1 | 建立工作區頁籤 |
| `_activateWorkspaceTab()` | V9.1 | 激活指定頁籤 |
| `_closeWorkspaceTab()` | V9.1 | 關閉頁籤 |
| `_isMobile()` | V10 | 判斷是否為手機模式（≤768px）|
| `_switchMobileView(view)` | V10 | 切換 chat/workspace 視圖 |
| `_initMobileLayout()` | V10 | 初始化/重算 Mobile 布局 |
| `_initSwipeGesture()` | V10 | 掛載 touchstart/touchend 手勢監聽 |

---

## 11. 系統參數（SystemParameter）— 不變

| Key | 用途 |
|-----|------|
| `PROMPT_MCP_GENERATE` | MCP 設計時 LLM 生成 Prompt |
| `PROMPT_MCP_TRY_RUN` | MCP Try Run 沙箱安全規範 Prompt |
| `PROMPT_SKILL_DIAGNOSIS` | Skill 診斷推論 System Prompt |

全部透過 `/api/v1/system-parameters` API 可修改，無需重啟服務。

---

## 12. 身份驗證與安全 — 不變（見 V8 §10）

---

## 13. 部署與啟動

```bash
cd fastapi_backend_service
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
# → 開啟 http://localhost:8000（Desktop）
# → 或用手機掃 QR / 連同一 WiFi：http://<server-ip>:8000
```

**自動初始化（Startup Seeding）：**
1. 建立 DB 表格（`init_db()`）
2. 建立預設使用者（gill / admin）
3. 建立 5 個內建 DataSubject
4. 建立 1 個內建 EventType（SPC_OOC_Etch_CD，含 11 個屬性）
5. 建立 3 個 SystemParameter（LLM Prompts）

---

## 14. 版本更新歷史

| 版本 | 日期 | 主要新增 |
|------|------|---------|
| V8 | 2026-03-01 | 基礎平台（診斷 + Builder + SSE）|
| V9 | 2026-03-01 | Copilot Slot Filling + Slash Command 直呼 MCP/Skill |
| V9.1 | 2026-03-01 | Multi-Tab Workspace（右側多頁籤工作區）|
| V10 | 2026-03-02 | Mobile-First 響應式佈局 + 手勢滑動切換 |

---

## 15. 測試覆蓋

- 框架：pytest + pytest-asyncio（`asyncio_mode = auto`）
- DB：in-memory SQLite + `app.dependency_overrides[get_db]`
- LLM：測試中 Mock（避免 API 費用）
- 覆蓋率目標：≥ 80%
