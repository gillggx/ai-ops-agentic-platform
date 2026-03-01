# Product Specification — Glass Box AI 診斷引擎 v7

> **版本**：7.0　｜　**狀態**：已實作完成　｜　**日期**：2026-02-28

---

## 目錄

1. [產品願景](#1-產品願景)
2. [技術架構總覽](#2-技術架構總覽)
3. [Phase 1–5 回顧](#3-phase-15-回顧)
4. [Phase 6：蝕刻製程 AI Skill 建構系統](#4-phase-6蝕刻製程-ai-skill-建構系統)
5. [Phase 7.5：UX 強化與診斷介面完善](#5-phase-75ux-強化與診斷介面完善)
6. [前端技術規格](#6-前端技術規格)
7. [頁面與路由規格](#7-頁面與路由規格)
8. [API 規格（後端）](#8-api-規格後端)
9. [SSE 事件協定](#9-sse-事件協定)
10. [Skill 系統規格](#10-skill-系統規格)
11. [Skill Builder Copilot 規格](#11-skill-builder-copilot-規格)
12. [資料流與狀態管理](#12-資料流與狀態管理)
13. [安全性規格](#13-安全性規格)
14. [測試規格](#14-測試規格)
15. [部署規格](#15-部署規格)
16. [已知限制與未來規劃](#16-已知限制與未來規劃)

---

## 1. 產品願景

### 1.1 核心理念

**Glass Box（玻璃盒）AI 診斷引擎 v7** 是一個針對半導體蝕刻製程（Etch Process）量身打造的 AI 智慧診斷平台，並配備了業界首創的 **AI Skill Builder Copilot**，讓製程工程師（PE）可以在無需撰寫程式碼的情況下，透過自然語言與 AI 協作，快速創建新的診斷 Skill。

v7 在 v5（React SPA 管理控制台）的基礎上，完成了兩大里程碑：

- **Phase 6**：全面替換通用 IT 診斷工具，改為蝕刻製程專用 MCP 工具；引入 AI Skill Builder Copilot 後端 API 與前端介面。
- **Phase 7.5**：全面優化 UI 體驗，包含診斷工作站的 SSE 串流對接、Quick Test 按鈕、Tab 自動切換、以及所有抽屜視窗的寬度調整。

### 1.2 設計原則

| 原則 | 描述 |
|------|------|
| **透明性 (Glass Box)** | AI 的每個決策步驟（工具呼叫、事件分類、報告）即時對使用者可見 |
| **領域專業 (Domain-Expert)** | 所有 Skill 針對蝕刻製程設計：SPC OOC、CD 量測、APC 補償、配方偏移 |
| **唯讀安全 (Read-Only)** | 所有診斷操作嚴格執行唯讀，不自動修復或修改製程參數 |
| **強制分流 (Triage-First)** | `mcp_event_triage` 永遠是 Agent 的第一個工具呼叫 |
| **無程式碼創建 (No-Code Build)** | PE 可透過 AI Copilot 三步驟建立新 Skill，無需撰寫程式碼 |
| **可擴充 (Extensible)** | 新增診斷 Skill 只需新增 Python 類別並在 registry 中登錄 |

### 1.3 目標用戶

| 角色 | 使用場景 |
|------|---------|
| 製程工程師（PE） | SPC OOC 告警診斷、CD 量測異常排查、APC 補償問題分析 |
| 蝕刻機台工程師 | 配方偏移確認、設備常數驗證、保養後漂移評估 |
| 製造 IT / MES 系統人員 | Skill 管理與維護、事件分診規則調整 |
| 管理者 | 系統設定、模型選擇、API 金鑰管理 |

---

## 2. 技術架構總覽

### 2.1 整體技術棧

| 層級 | 技術選型 | 版本 |
|------|---------|------|
| **後端框架** | FastAPI | 0.109.0 |
| **ASGI 伺服器** | Uvicorn | 0.27.0 |
| **ORM** | SQLAlchemy（非同步 AsyncSession） | 2.0.25 |
| **資料驗證** | Pydantic v2 | 2.6.0 |
| **AI SDK** | Anthropic Python SDK | ≥0.40 |
| **AI 模型** | Claude Opus 4.6 | claude-opus-4-6 |
| **認證** | JWT（python-jose + passlib bcrypt） | — |
| **開發資料庫** | SQLite（aiosqlite） | — |
| **正式資料庫** | PostgreSQL（asyncpg） | — |
| **前端框架** | React 19.2 + Vite 7.3.1 | — |
| **CSS 框架** | Tailwind CSS v3.4.19 | — |
| **前端路由** | React Router DOM v7 | — |
| **Markdown 渲染** | react-markdown + remark-gfm | — |
| **建置工具** | Vite（開發 proxy + HMR） | — |

### 2.2 系統架構圖

```
┌──────────────────────────────────────────────────────────────┐
│                    Browser (React SPA)                        │
│  ┌──────────┐  ┌──────────────────┐  ┌────────────────────┐  │
│  │LoginPage │  │  DiagnosisPage   │  │   SkillsPage       │  │
│  │ /login   │  │   /diagnosis     │  │    /skills         │  │
│  │          │  │  ┌────┐ ┌─────┐  │  │  ┌──────────────┐ │  │
│  └────┬─────┘  │  │Left│ │Chat │  │  │  │SkillBuilder  │ │  │
│       │        │  │Panel│ │Panel│  │  │  │  Copilot     │ │  │
│       │        │  └────┘ └─────┘  │  │  └──────────────┘ │  │
│       │        └──────────────────┘  └────────────────────┘  │
└───────┼──────────────────┬───────────────────┬───────────────┘
        │ JWT              │ POST+SSE           │ POST /builder/
        ▼                  ▼                   ▼
┌──────────────────────────────────────────────────────────────┐
│                 FastAPI Backend (:8000)                        │
│  POST /api/v1/auth/login         →  JWT 發行                  │
│  POST /api/v1/diagnose/          →  StreamingResponse(SSE)    │
│  POST /api/v1/builder/suggest-logic  →  AI Skill PE建議      │
│  POST /api/v1/builder/auto-map       →  工具欄位自動映射      │
│  POST /api/v1/builder/validate-logic →  診斷邏輯驗證         │
│  GET  /api/v1/health             →  健康檢查                  │
└──────────────────────┬───────────────────────────────────────┘
                       │ Anthropic API (claude-opus-4-6)
                       ▼
              ┌──────────────────┐
              │   Claude Opus    │
              │     4.6          │
              │  (Tool-Use)      │
              └────────┬─────────┘
                       │ tool_use blocks
                       ▼
          ┌─────────────────────────────┐
          │        SKILL_REGISTRY       │
          │  mcp_event_triage           │  ← 蝕刻事件分診（6 規則）
          │  mcp_check_recipe_offset    │  ← 配方偏移檢查
          │  mcp_check_equipment_const  │  ← 設備硬體常數驗證
          │  mcp_check_apc_params       │  ← APC 補償參數檢查
          │  ask_user_recent_changes    │  ← 詢問最近變更
          └─────────────────────────────┘
```

---

## 3. Phase 1–5 回顧

| Phase | 功能 | 技術亮點 |
|-------|------|---------|
| **Phase 1** | 基礎 FastAPI 服務，用戶 CRUD，JWT 認證 | SQLAlchemy AsyncSession，StandardResponse |
| **Phase 2** | AI 診斷代理核心，批次 API | Anthropic 工具呼叫迴圈（最多 10 回合） |
| **Phase 3** | MCP Event Triage 分流，Skill 系統 | `BaseMCPSkill`，`SKILL_REGISTRY`，`mcp_event_triage` |
| **Phase 3.5** | SSE 串流整合，即時事件推送 | `StreamingResponse`，SSE 協定，非同步生成器 |
| **Phase 4** | Glass Box 靜態前端 | 純 HTML/CSS/JS，EventSource，玻璃盒視覺化 |
| **Phase 5** | React SPA 管理控制台 | Vite + React 18 + Tailwind CSS，useSSE 狀態機 |

---

## 4. Phase 6：蝕刻製程 AI Skill 建構系統

### 4.1 升級目標

| 升級點 | Phase 5 | Phase 6 |
|--------|---------|---------|
| 診斷領域 | 通用 IT（CPU、記憶體、磁碟） | 蝕刻製程（CD SPC OOC、配方偏移、APC） |
| MCP 工具組 | mcp_mock_cpu_check、mcp_rag_knowledge_search | mcp_check_recipe_offset、mcp_check_equipment_constants、mcp_check_apc_params |
| Skill 建立方式 | 手動撰寫 Python 程式碼 | AI Copilot 三步驟無程式碼建立 |
| Builder API | 無 | `/api/v1/builder/` 三個端點 |
| Builder UI | 無 | SkillBuilderDrawer（60vw 寬，三區塊） |
| mockData | 通用 IT Skills | 蝕刻製程 Skills（5 個，含 triage 規則） |

### 4.2 蝕刻製程 MCP 工具組

#### mcp_check_recipe_offset

| 欄位 | 說明 |
|------|------|
| **功能** | 讀取機台配方目前設定值與黃金配方（Golden Recipe）之差異，檢測是否有人為修改 |
| **輸入** | `tool_id`（機台 ID）、`recipe_name`（配方名稱）、`parameter_list`（參數清單，optional） |
| **輸出** | 各參數目前值 vs. 黃金值、偏差量、偏差百分比、最後修改者、修改時間 |
| **urgency 觸發** | 配方偏差 > 5% 時回傳 `is_out_of_spec: true` |

#### mcp_check_equipment_constants

| 欄位 | 說明 |
|------|------|
| **功能** | 驗證蝕刻機台硬體常數（電極間距、高頻功率校正係數等）是否在規格範圍內 |
| **輸入** | `tool_id`、`pm_id`（Process Module ID）、`constant_category`（類別：RF/GAS/MECH） |
| **輸出** | 各常數目前值、規格上下限、最後校正日期、校正人員 |
| **urgency 觸發** | 距上次 PM 超過 90 天且常數飄移 > 2σ 時回傳警告 |

#### mcp_check_apc_params

| 欄位 | 說明 |
|------|------|
| **功能** | 查詢 Advanced Process Control（APC）補償參數，評估是否已飽和或異常 |
| **輸入** | `tool_id`、`lot_id`（批號）、`apc_model_name`（APC 模型名稱） |
| **輸出** | 目前補償量、補償上下限、飽和度百分比、觸發條件、歷史趨勢（最近 5 筆） |
| **urgency 觸發** | APC 補償量超過限制的 80% 視為「接近飽和」 |

### 4.3 AI Skill Builder Copilot 後端 API

#### POST `/api/v1/builder/suggest-logic`

**功能**：根據事件 Schema 和上下文，AI 生成 PE（製程工程師）建議的診斷邏輯步驟。

**請求體**
```json
{
  "event_schema": {
    "event_type": "SPC_OOC_Etch_CD",
    "attributes": { ... }
  },
  "context": "選填的補充說明"
}
```

**回應（200 OK）**
```json
{
  "status": "success",
  "data": {
    "suggestions": [
      {
        "step": 1,
        "action": "確認 CD 偏移方向與幅度",
        "rationale": "SPC OOC 通常由配方偏移或設備常數飄移引起",
        "apply_prompt": "當 CD 偏移超過 3σ 時，優先確認機台配方是否被人為修改…"
      }
    ]
  }
}
```

#### POST `/api/v1/builder/auto-map`

**功能**：自動將事件 Schema 欄位映射到所選 MCP 工具的輸入參數。

**請求體**
```json
{
  "event_schema": { ... },
  "tool_input_schema": {
    "tool_name": "mcp_check_recipe_offset",
    "input_schema": { ... }
  }
}
```

**回應（200 OK）**
```json
{
  "status": "success",
  "data": {
    "mappings": [
      {
        "tool_field": "tool_id",
        "event_field": "tool_id",
        "confidence": 0.95,
        "note": "直接映射，欄位名稱完全匹配"
      }
    ]
  }
}
```

#### POST `/api/v1/builder/validate-logic`

**功能**：驗證使用者撰寫的診斷邏輯 Prompt 是否合理、完整、無安全疑慮。

**請求體**
```json
{
  "user_prompt": "當 CD 偏移超過 2σ 時…",
  "tool_output_schema": { ... }
}
```

**回應（200 OK）**
```json
{
  "status": "success",
  "data": {
    "is_valid": true,
    "score": 87,
    "issues": [],
    "suggestions": ["建議增加 APC 飽和度的判斷條件"]
  }
}
```

### 4.4 Skill Builder Copilot UI（SkillBuilderDrawer）

**觸發方式**：點擊 `/skills` 頁面右上角「+ 新增技能」按鈕。

**外觀**：60vw 寬的右側滑出抽屜，深色漸變標題（indigo → purple），三個步驟區塊（A / B / C）。

#### 區塊 A：事件類型選擇 + AI PE 建議

| 元素 | 說明 |
|------|------|
| 事件下拉選單 | 目前支援：`SPC_OOC_Etch_CD`（含 7 個屬性欄位） |
| AI 建議載入動畫 | 骨架（Skeleton）動畫，呼叫 `/suggest-logic` 期間顯示 |
| 建議卡片 | 每個步驟顯示 action、rationale，附「套用」按鈕 |
| 套用行為 | 點擊「套用」將建議文字預填到區塊 C 的 Textarea |

#### 區塊 B：MCP 工具選擇 + 欄位映射

| 元素 | 說明 |
|------|------|
| 工具多選核取框 | 3 個蝕刻工具（mcp_check_recipe_offset、mcp_check_equipment_constants、mcp_check_apc_params） |
| 勾選動作 | 自動呼叫 `/auto-map`，顯示事件欄位 → 工具欄位的映射視覺化 |
| 映射表格 | 每列顯示：工具欄位 → 事件欄位 → 信心度 badge（高/中/低） |
| 取消勾選 | 移除對應映射表格 |

#### 區塊 C：診斷邏輯 + 驗證

| 元素 | 說明 |
|------|------|
| Textarea | 輸入或貼上診斷邏輯 Prompt（支援套用 A 區塊建議） |
| 驗證按鈕 | 呼叫 `/validate-logic`，合併所有選定工具的 outputSchema |
| 驗證結果 | 分數（0–100）、問題清單、改進建議 |
| Toast 通知 | 驗證成功顯示綠色通知；API 錯誤顯示紅色通知 |

---

## 5. Phase 7.5：UX 強化與診斷介面完善

### 5.1 升級目標

| 改動點 | 改動前 | 改動後 |
|--------|--------|--------|
| 所有右側抽屜寬度 | `w-[480px]`（固定 480px） | `w-[60vw]`（60% 視窗寬） |
| 診斷對話框快速測試 | 無 | ⚡ 快速觸發按鈕 |
| 診斷 SSE 對接 | 前端未正確對接 SSE 狀態 | 完整 Tab 自動切換狀態機 |
| 快速建議訊息 | 通用 IT 問題 | 蝕刻製程問題 |
| 工具呼叫圖示 | 通用 | 蝕刻製程工具專用圖示 |

### 5.2 Drawer 寬度改動

影響檔案：

| 檔案 | 舊值 | 新值 |
|------|------|------|
| `frontend/src/components/ui/Drawer.jsx` | `w-[480px]` | `w-[60vw]` |
| `frontend/src/components/SkillBuilderDrawer.jsx` | `w-[720px]` | `w-[60vw]` |

### 5.3 診斷工作站強化

#### Quick Test 按鈕

```
⚡ 模擬觸發：TETCH01 PM2 發生 SPC OOC
```

- 位置：Chat 面板訊息列表與輸入框之間
- 樣式：amber 色系（`bg-amber-50 border-amber-300 text-amber-800`）
- 觸發內容：`TETCH01 PM2 發生 SPC OOC，CD 量測值連續 3 點超出 3-sigma 管制界限，請進行蝕刻製程排障診斷。`
- 行為：`isStreaming` 時禁用

#### Tab 自動切換狀態機

| SSE 事件 | 自動切換 Tab | 觸發條件 |
|---------|------------|---------|
| `tool_call` | 切換至「工具呼叫」 | `toolCalls.length > 0` |
| `tool_result` (mcp_event_triage) | 切換至「事件分類」 | `eventObject !== null` |
| `report` | 切換至「診斷報告」 | `report` 非空字串 |

實作：三個獨立 `useEffect`，確保切換順序正確（工具 → 事件 → 報告）。

#### 蝕刻工具圖示映射

| 工具名稱 | 圖示 | 顏色 |
|---------|------|------|
| `mcp_event_triage` | Zap | rose |
| `mcp_check_recipe_offset` | Database | indigo |
| `mcp_check_equipment_constants` | Cpu | purple |
| `mcp_check_apc_params` | Zap | amber |
| `ask_user_recent_changes` | HelpCircle | teal |

#### 快速建議訊息（蝕刻領域）

```
1. TETCH01 PM2 發生 SPC OOC，CD 超出 3-sigma，請診斷
2. 機台 EAP01 配方 ETCH_POLY_V2 參數偏移，懷疑人為修改
3. Lot 03B 線寬異常，APC 補償可能已飽和
4. 機台保養後 CD 漂移，需確認 PM 品質與硬體常數
```

---

## 6. 前端技術規格

### 6.1 目錄結構

```
frontend/
├── index.html
├── vite.config.js           ← Proxy /api → :8000
├── tailwind.config.js
├── postcss.config.js
├── package.json
└── src/
    ├── main.jsx              ← BrowserRouter
    ├── App.jsx               ← Routes + PrivateRoute
    ├── index.css             ← Tailwind + 自訂元件類別
    ├── hooks/
    │   ├── useAuth.js        ← JWT localStorage 管理
    │   └── useSSE.js         ← SSE 串流 + 狀態機
    ├── services/
    │   └── builderApi.js     ← Builder Copilot API (3 端點)  【v6 新增】
    ├── components/
    │   ├── Layout.jsx        ← Sidebar + Header + Outlet
    │   ├── Sidebar.jsx       ← 深色導覽列，NavLink active states
    │   ├── Header.jsx        ← 頁面標題 + 使用者資訊 + 登出
    │   ├── SkillBuilderDrawer.jsx  ← AI Copilot 三步驟抽屜  【v6 新增】
    │   └── ui/
    │       ├── Drawer.jsx    ← 右側滑出抽屜（60vw）  【v7.5 改寬】
    │       └── JsonViewer.jsx ← 遞迴 JSON 樹狀展示
    ├── pages/
    │   ├── LoginPage.jsx
    │   ├── DiagnosisPage.jsx  ← 完整 SSE 對接 + Quick Test  【v7.5 重構】
    │   ├── SkillsPage.jsx     ← 新增技能按鈕 + Builder  【v6 更新】
    │   └── SettingsPage.jsx
    └── data/
        └── mockData.js        ← 蝕刻製程 Skills + URGENCY_CONFIG  【v6 更新】
```

### 6.2 Vite 代理設定

```js
// vite.config.js
server: {
  proxy: {
    '/api': {
      target: 'http://localhost:8000',
      changeOrigin: true,
    },
  },
}
```

### 6.3 配色系統

| 用途 | Tailwind Class | 說明 |
|------|---------------|------|
| 側邊欄背景 | `slate-900` | 深色導覽列 |
| 主背景 | `slate-50` | 淺灰頁面底色 |
| 卡片背景 | `white` + `shadow-sm` | 白色卡片 |
| 主色調 | `indigo-600` | 按鈕、active link |
| AI Copilot 漸變 | `indigo-600 → purple-600` | SkillBuilderDrawer 標題 |
| 成功狀態 | `emerald-500` | 低/中緊急度 |
| 警告狀態 | `amber-500` | 中緊急度、Quick Test 按鈕 |
| 危急狀態 | `rose-500` | critical |

### 6.4 builderApi.js 服務層

```js
const API_BASE = '/api/v1/builder'
const TOKEN_KEY = 'glassbox_token'

function getHeaders() {
  const token = localStorage.getItem(TOKEN_KEY)
  return {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${token}`,
  }
}

async function request(path, body) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: getHeaders(),
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export function suggestLogic(eventSchema, context = '')
export function autoMap(eventSchema, toolInputSchema)
export function validateLogic(userPrompt, toolOutputSchema)
```

### 6.5 useSSE Hook 狀態機

| 狀態欄位 | 類型 | 說明 |
|---------|------|------|
| `isStreaming` | boolean | 是否正在接收 SSE |
| `eventObject` | object \| null | mcp_event_triage 回傳的事件物件 |
| `toolCalls` | array | 所有工具呼叫記錄（含輸入/輸出） |
| `report` | string | 最終 Markdown 診斷報告 |
| `chatMessages` | array | 聊天紀錄（role: user \| agent） |
| `error` | string \| null | 錯誤訊息 |
| `setChatMessages` | function | 外部重置對話 |

---

## 7. 頁面與路由規格

### 7.1 路由表

| 路徑 | 元件 | 保護 | 說明 |
|------|------|------|------|
| `/login` | `LoginPage` | 公開 | 登入表單 |
| `/` | 重導向至 `/diagnosis` | PrivateRoute | — |
| `/diagnosis` | `DiagnosisPage` | PrivateRoute | 主診斷工作站 |
| `/skills` | `SkillsPage` | PrivateRoute | Skill 管理 + Builder |
| `/settings` | `SettingsPage` | PrivateRoute | 系統設定 |

### 7.2 診斷頁規格（DiagnosisPage）—— v7.5 更新

**左面板（65%）—— 三 Tab**

| Tab | 內容 | 自動切換觸發 |
|-----|------|------------|
| 診斷報告（FileText） | `.prose-report` Markdown 渲染 + 游標動畫 | `report` 非空時 |
| 事件分類（Zap） | EventObjectCard：event_type、urgency badge、建議工具鏈、分析提示 | `eventObject` 非空時 |
| 工具呼叫（Cpu）+ 數量徽章 | ToolCallCard 列表：工具名稱、圖示、執行狀態、JSON 輸入/輸出 | `toolCalls.length > 0` 時 |

**右面板（35%）—— Chat 區**

- 聊天訊息列表（user: indigo 背景；agent: white 背景 shadow）
- 空狀態：4 個蝕刻領域快速建議按鈕
- **⚡ Quick Test 按鈕**（amber 樣式，位於訊息列表下方）
- Textarea（Enter 發送，Shift+Enter 換行）
- 「發送」或「停止」按鈕（串流中切換，圖示對應）
- `isStreaming` 期間顯示「Agent 執行中...」脈衝點

### 7.3 技能頁規格（SkillsPage）—— v6 更新

**Tab 組**
- 事件分診庫（Event Triage）：`mcp_event_triage`（含 6 條蝕刻分診規則）
- 診斷工具庫（Diagnostic Actions）：`mcp_check_recipe_offset`、`mcp_check_equipment_constants`、`mcp_check_apc_params`、`ask_user_recent_changes`

**新增功能**
- 右上角「+ 新增技能」按鈕 → 開啟 SkillBuilderDrawer
- 每個 Skill 列顯示呼叫次數（invocations）和平均延遲（avgMs）
- 點擊 Skill 列 → 開啟 Drawer 詳情（Schema、分診規則等）

---

## 8. API 規格（後端）

### 8.1 認證 API

#### POST `/api/v1/auth/login`

**請求**
```json
{ "username": "string", "password": "string" }
```

**回應（200 OK）**
```json
{
  "status": "success",
  "message": "Login successful",
  "data": { "access_token": "eyJhbGci...", "token_type": "bearer" },
  "error_code": null
}
```

### 8.2 診斷 API

#### POST `/api/v1/diagnose/`

**請求頭**：`Authorization: Bearer <access_token>`

**請求體**
```json
{ "issue_description": "string（5–2000 字元）" }
```

**回應**：`Content-Type: text/event-stream`（SSE 串流，詳見第 9 節）

### 8.3 Skill Builder API（v6 新增）

所有端點均需 `Authorization: Bearer <access_token>`。

| 端點 | 功能 |
|------|------|
| `POST /api/v1/builder/suggest-logic` | AI 生成診斷邏輯建議 |
| `POST /api/v1/builder/auto-map` | 自動映射事件欄位到工具參數 |
| `POST /api/v1/builder/validate-logic` | 驗證診斷邏輯 Prompt |

### 8.4 StandardResponse 格式

```json
{
  "status": "success | error",
  "message": "說明訊息",
  "data": { ... },
  "error_code": null | "NOT_FOUND | UNAUTHORIZED | ..."
}
```

---

## 9. SSE 事件協定

### 9.1 事件格式（RFC 8895）

```
event: <event_type>\n
data: <json_payload>\n
\n
```

### 9.2 事件序列

```
session_start → tool_call* → tool_result* → (重複) → report → done
```

若發生例外則插入 `error`；`done` 無論如何都會是最後一個事件。

### 9.3 事件規格

| 事件名稱 | Payload 欄位 | 說明 |
|---------|------------|------|
| `session_start` | `{ "issue": string }` | 診斷開始 |
| `tool_call` | `{ "tool_name": string, "tool_input": object }` | Agent 呼叫工具前 |
| `tool_result` | `{ "tool_name": string, "tool_result": object, "is_error": bool }` | 工具執行後 |
| `report` | `{ "content": string, "total_turns": int, "tools_invoked": list }` | 最終 Markdown 報告 |
| `error` | `{ "message": string }` | 例外錯誤 |
| `done` | `{ "status": "complete" }` | 串流結束（finally 保證觸發） |

### 9.4 `mcp_event_triage` tool_result 結構（蝕刻版）

```json
{
  "event_id": "EVT-A1B2C3D4",
  "event_type": "SPC_OOC_Etch_CD",
  "attributes": {
    "symptom": "TETCH01 PM2 CD 量測值連續 3 點超出 3-sigma 管制界限",
    "urgency": "high"
  },
  "recommended_skills": [
    "mcp_check_recipe_offset",
    "mcp_check_equipment_constants",
    "mcp_check_apc_params"
  ]
}
```

---

## 10. Skill 系統規格

### 10.1 Skill 基礎類別（BaseMCPSkill）

```python
class BaseMCPSkill(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @property
    @abstractmethod
    def input_schema(self) -> dict: ...

    async def execute(self, **kwargs) -> dict: ...

    def to_anthropic_tool(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }
```

### 10.2 已實作的 Skills（v7 蝕刻製程版）

| Skill 名稱 | 類別 | 分類 | 說明 |
|-----------|------|------|------|
| `mcp_event_triage` | EventTriageSkill | 分診庫 | 蝕刻症狀分類，回傳 Event Object，強制第一呼叫 |
| `mcp_check_recipe_offset` | CheckRecipeOffsetSkill | 診斷工具 | 配方偏移檢查（黃金配方比對） |
| `mcp_check_equipment_constants` | CheckEquipmentConstantsSkill | 診斷工具 | 設備硬體常數驗證 |
| `mcp_check_apc_params` | CheckApcParamsSkill | 診斷工具 | APC 補償參數評估 |
| `ask_user_recent_changes` | AskUserRecentChangesSkill | 診斷工具 | 詢問最近製程或設備變更 |

### 10.3 Event Triage 蝕刻分類規則

| 關鍵詞 | event_type | urgency | recommended_skills |
|--------|-----------|---------|-------------------|
| SPC, OOC, 管制界限, sigma, CD | `SPC_OOC_Etch_CD` | high | mcp_check_recipe_offset, mcp_check_equipment_constants, mcp_check_apc_params |
| 配方, recipe, 偏移, 參數修改 | `Recipe_Parameter_Drift` | high | mcp_check_recipe_offset, ask_user_recent_changes |
| APC, 補償, 飽和, 線寬補正 | `APC_Compensation_Saturated` | medium | mcp_check_apc_params, ask_user_recent_changes |
| 設備常數, 硬體, PM, 保養後 | `Equipment_Constant_Drift` | medium | mcp_check_equipment_constants, ask_user_recent_changes |
| 線寬, CD 漂移, critical dimension | `CD_Drift` | high | mcp_check_recipe_offset, mcp_check_apc_params, mcp_check_equipment_constants |
| 機台, 產能, 良率, 良品率 | `Yield_Excursion` | critical | ask_user_recent_changes, mcp_check_recipe_offset, mcp_check_apc_params |
| （其他） | `Unknown_Etch_Symptom` | low | ask_user_recent_changes |

---

## 11. Skill Builder Copilot 規格

### 11.1 事件 Schema 目錄（v7）

| event_type | 屬性數 | 說明 |
|-----------|--------|------|
| `SPC_OOC_Etch_CD` | 7 | tool_id、pm_id、chart_type、violation_rule、violation_count、lot_id、wafer_id |

### 11.2 MCP 工具 Schema 目錄

| 工具名稱 | 必填輸入欄位 | 輸出欄位數 |
|---------|------------|----------|
| `mcp_check_recipe_offset` | tool_id, recipe_name | 6+ |
| `mcp_check_equipment_constants` | tool_id, pm_id | 4+ |
| `mcp_check_apc_params` | tool_id, lot_id | 5+ |

### 11.3 信心度 Badge 顏色規則

| 信心度範圍 | Badge 文字 | Tailwind Class |
|-----------|-----------|---------------|
| ≥ 0.9 | 高 | `badge-emerald` |
| 0.7–0.9 | 中 | `badge-amber` |
| < 0.7 | 低 | `badge-rose` |

### 11.4 Skeleton 載入動畫 CSS

```css
@keyframes skeleton-wave {
  0% { background-position: 200% center; }
  100% { background-position: -200% center; }
}
.skeleton {
  background: linear-gradient(90deg, #f1f5f9 25%, #e2e8f0 50%, #f1f5f9 75%);
  background-size: 200% auto;
  animation: skeleton-wave 1.5s linear infinite;
  border-radius: 6px;
}
```

---

## 12. 資料流與狀態管理

### 12.1 診斷工作站資料流（v7.5）

```
[用戶輸入 / 快速建議 / ⚡ Quick Test]
    → useSSE.sendMessage(text)
    → POST /api/v1/diagnose/  { issue_description: text }
    → ReadableStream 逐行讀取（TextDecoder）
    → 解析 SSE 行（event: xxx + data: {json}）
    ┌──────────────────────────────────────────────────────────┐
    │ event: session_start → setChatMessages (🔄 診斷開始…)   │
    │ event: tool_call     → setToolCalls (append placeholder) │
    │                        setActiveTab('tools')  ← 自動切換 │
    │                        setChatMessages (🔧 呼叫工具)    │
    │ event: tool_result   → setToolCalls (patch result)       │
    │   └─ if mcp_event_triage → setEventObject                │
    │                             setActiveTab('event') ← 自動  │
    │ event: report        → setReport                         │
    │                        setActiveTab('report') ← 自動切換 │
    │                        setChatMessages (✅ 診斷完成)     │
    │ event: error         → setError + setChatMessages (❌)   │
    └──────────────────────────────────────────────────────────┘
    → finally: setIsStreaming(false)
```

### 12.2 Skill Builder 資料流

```
[用戶選擇事件類型]
    → SkillBuilderDrawer.handleEventChange()
    → suggestLogic(eventSchema) → POST /api/v1/builder/suggest-logic
    → setSuggestions([...]) → 顯示建議卡片

[用戶勾選 MCP 工具]
    → handleToolToggle(toolName, checked=true)
    → autoMap(eventSchema, toolInputSchema) → POST /api/v1/builder/auto-map
    → setMappings(prev => [...prev, ...newMappings])
    → 顯示映射表格

[用戶點擊「套用」建議]
    → setDiagnosticLogic(suggestion.apply_prompt)
    → 預填 Textarea

[用戶點擊「驗證」]
    → combineOutputSchemas(selectedTools)
    → validateLogic(userPrompt, combined) → POST /api/v1/builder/validate-logic
    → setValidation({score, issues, suggestions})
    → 顯示驗證結果
```

---

## 13. 安全性規格

| 安全點 | 實作方式 |
|--------|---------|
| **認證** | JWT（HS256），`SECRET_KEY` 環境變數，預設 1 天有效期 |
| **密碼儲存** | bcrypt hash（passlib CryptContext） |
| **API 保護** | `/api/v1/diagnose/` 和 `/api/v1/builder/*` 均要求 Bearer Token |
| **唯讀原則** | 所有診斷 Skill 嚴格唯讀，System Prompt 中明確禁止修改製程參數 |
| **CORS** | 可透過 Settings 頁面設定允許來源 |
| **前端安全** | Token 存 localStorage，適合 SPA 場景 |
| **輸入驗證** | `issue_description` 5–2000 字元；Builder API 輸入由 Pydantic 驗證 |

---

## 14. 測試規格

### 14.1 後端測試（Pytest）

| 測試類型 | 數量 | 工具 |
|---------|------|------|
| 單元測試 | 83+ | pytest, httpx AsyncClient |
| 覆蓋率 | >90% | pytest-cov |
| 非同步測試 | 全部 | pytest-asyncio（asyncio_mode=auto） |
| 資料庫 | in-memory SQLite | app.dependency_overrides |

執行：
```bash
cd fastapi_backend_service
pytest --cov=app --cov-report=term-missing
```

### 14.2 前端 E2E 冒煙測試（v7）

| 測試步驟 | 預期結果 |
|---------|---------|
| 訪問 `/login`，輸入 `gill/g1i1l2l3` | 重導向至 `/diagnosis` |
| 點擊「⚡ 模擬觸發：TETCH01 PM2 發生 SPC OOC」 | 開始 SSE 串流，自動切換至「工具呼叫」Tab |
| 等待 `mcp_event_triage` 完成 | 自動切換至「事件分類」Tab，顯示 SPC_OOC_Etch_CD |
| 等待最終報告 | 自動切換至「診斷報告」Tab，顯示 Markdown 報告 |
| 進入 `/skills`，點擊「+ 新增技能」 | SkillBuilderDrawer 從右側滑出（60vw 寬） |
| 選擇事件「SPC_OOC_Etch_CD」 | Skeleton 動畫後顯示 AI 建議步驟 |
| 勾選「mcp_check_recipe_offset」 | 顯示欄位映射表格（tool_id、recipe_name 等） |
| 點擊「套用」建議 | 診斷邏輯 Textarea 被預填 |
| 點擊「驗證邏輯」 | 顯示驗證分數和改進建議 |

---

## 15. 部署規格

### 15.1 開發環境

```bash
# 後端（終端 1）
cd fastapi_backend_service
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# 前端（終端 2）
cd fastapi_backend_service/frontend
npm install
npm run dev  # 啟動於 localhost:5173
```

> ⚠️ **注意**：必須在 `fastapi_backend_service/` 目錄內執行 `uvicorn`，否則 Python 可能載入 site-packages 中的同名模組。

### 15.2 環境變數（後端）

| 變數名稱 | 預設值 | 說明 |
|---------|--------|------|
| `ANTHROPIC_API_KEY` | 必填 | Anthropic API 金鑰 |
| `SECRET_KEY` | 隨機生成 | JWT 簽名金鑰 |
| `DATABASE_URL` | SQLite dev.db | 資料庫連線字串 |
| `API_V1_PREFIX` | `/api/v1` | API 路由前綴 |
| `ALGORITHM` | `HS256` | JWT 演算法 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `1440` | Token 有效期（分鐘） |

### 15.3 正式環境部署

**後端（Docker）**
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**前端（靜態部署）**
```bash
cd frontend && npm run build  # 輸出至 dist/
```

**Nginx 反向代理**
```nginx
location /api/ { proxy_pass http://backend:8000; }
location / { root /var/www/frontend/dist; try_files $uri $uri/ /index.html; }
```

---

## 16. 已知限制與未來規劃

### 16.1 已知限制

| 限制 | 說明 |
|------|------|
| **蝕刻 Skill 為 Mock** | `mcp_check_recipe_offset` 等工具使用模擬資料，非對接真實 MES/APC 系統 |
| **Builder 未持久化** | SkillBuilderDrawer 建立的 Skill 目前不會寫入後端資料庫 |
| **Settings 未持久化** | `/settings` 頁面為 Mock，修改不會寫入後端 |
| **單事件類型** | Builder Copilot 目前僅支援 `SPC_OOC_Etch_CD` 一種事件類型 |
| **無 Streaming 報告** | 最終報告為完整字串一次送出，非逐 token 串流 |
| **無多用戶隔離** | 所有使用者共享同一 Skill Registry 和 System Prompt |

### 16.2 未來規劃（Phase 8+）

| 功能 | 說明 |
|------|------|
| **MES 真實對接** | mcp_check_recipe_offset 對接真實 MES API |
| **Skill 持久化** | Builder 建立的 Skill 存入 PostgreSQL，動態載入 |
| **更多事件類型** | 新增 APC、設備常數、良率異常等事件 Schema |
| **診斷歷史** | 儲存並查詢過往診斷報告 |
| **Streaming 最終報告** | 逐 token 串流 report 內容 |
| **告警 WebSocket** | 接收 SPC 系統主動推送的 OOC 告警 |
| **多租戶** | 用戶隔離的 Skill 設定和診斷歷史 |

---

*文件版本：v7.0 — 2026-02-28*
