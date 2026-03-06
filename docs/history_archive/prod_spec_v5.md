# Product Specification — Glass Box AI 診斷引擎 v5

> **版本**：5.0　｜　**狀態**：已實作完成　｜　**日期**：2026-02-28

---

## 目錄

1. [產品願景](#1-產品願景)
2. [技術架構總覽](#2-技術架構總覽)
3. [Phase 1–4 回顧](#3-phase-14-回顧)
4. [Phase 5：企業級管理控制台](#4-phase-5企業級管理控制台)
5. [前端技術規格](#5-前端技術規格)
6. [頁面與路由規格](#6-頁面與路由規格)
7. [API 規格（後端）](#7-api-規格後端)
8. [SSE 事件協定](#8-sse-事件協定)
9. [Skill 系統規格](#9-skill-系統規格)
10. [資料流與狀態管理](#10-資料流與狀態管理)
11. [安全性規格](#11-安全性規格)
12. [測試規格](#12-測試規格)
13. [部署規格](#13-部署規格)
14. [已知限制與未來規劃](#14-已知限制與未來規劃)

---

## 1. 產品願景

### 1.1 核心理念

**Glass Box（玻璃盒）AI 診斷引擎 v5** 是一個具備企業級管理介面的智慧型問題診斷平台。v5 在 v3.5（FastAPI 後端 + SSE 串流）與 v4（靜態 HTML 玻璃盒介面）的基礎上，全面升級為基於 React SPA 的現代化管理控制台。

系統核心理念不變：AI 代理的每一個推理步驟、工具呼叫與決策路由，都即時透明地呈現在使用者面前——這正是「玻璃盒」的精髓。

### 1.2 設計原則

| 原則 | 描述 |
|------|------|
| **透明性 (Glass Box)** | AI 的每個決策步驟（工具呼叫、事件分類、報告）即時對使用者可見 |
| **領域無關 (Domain-Agnostic)** | 路由決策完全委託 LLM，無硬編碼業務邏輯 |
| **唯讀安全 (Read-Only)** | 所有診斷操作嚴格執行唯讀，不自動修復 |
| **強制分流 (Triage-First)** | `mcp_event_triage` 永遠是 Agent 的第一個工具呼叫 |
| **企業級 UX** | SaaS 管理後台佈局、暗色 Sidebar、專業配色系統 |
| **可擴充 (Extensible)** | 新增診斷 Skill 只需新增 Python 類別並在 registry 中登錄 |

### 1.3 目標用戶

| 角色 | 使用場景 |
|------|---------|
| SRE / DevOps 工程師 | 系統告警第一線診斷、效能問題排查 |
| IT 運維人員 | 非技術背景，AI 輔助診斷自然語言輸入 |
| 開發者 / 架構師 | 了解 MCP 工具模式與 Agentic AI 架構 |
| Admin | 管理 System Prompt、模型選擇、API 金鑰 |

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
| **前端框架** | React 18 + Vite | — |
| **CSS 框架** | Tailwind CSS v3 | — |
| **前端路由** | React Router DOM v6 | — |
| **建置工具** | Vite（開發 proxy + HMR） | — |

### 2.2 系統架構圖

```
┌─────────────────────────────────────────────────────┐
│                  Browser (React SPA)                 │
│  ┌──────────┐  ┌──────────┐  ┌───────────────────┐  │
│  │LoginPage │  │Diagnosis │  │Skills / Settings  │  │
│  │ /login   │  │  /diag   │  │  /skills /settings│  │
│  └────┬─────┘  └────┬─────┘  └────────┬──────────┘  │
└───────┼──────────────┼────────────────┼─────────────┘
        │ JWT          │ POST+SSE        │ Mock
        ▼              ▼                ▼
┌─────────────────────────────────────────────────────┐
│               FastAPI Backend (:8000)                │
│  POST /api/v1/auth/login  →  JWT 發行               │
│  POST /api/v1/diagnose/   →  StreamingResponse(SSE) │
│  GET  /api/v1/health      →  健康檢查               │
│  GET  /api/v1/skills      →  Skill 清單（預留）     │
└────────────────────────┬────────────────────────────┘
                         │ Anthropic API
                         ▼
                 ┌───────────────┐
                 │  Claude       │
                 │  Opus 4.6     │
                 │ (Tool-Use)    │
                 └──────┬────────┘
                        │ tool_use blocks
                        ▼
               ┌────────────────────┐
               │   SKILL_REGISTRY   │
               │  mcp_event_triage  │
               │  mcp_mock_cpu_check│
               │  mcp_rag_knowledge │
               │  ask_user_recent.. │
               └────────────────────┘
```

---

## 3. Phase 1–4 回顧

| Phase | 功能 | 技術亮點 |
|-------|------|---------|
| **Phase 1** | 基礎 FastAPI 服務，用戶 CRUD，JWT 認證 | SQLAlchemy AsyncSession，StandardResponse |
| **Phase 2** | AI 診斷代理核心，批次 API | Anthropic 工具呼叫迴圈（最多 10 回合） |
| **Phase 3** | MCP Event Triage 分流，Skill 系統 | `BaseMCPSkill`，`SKILL_REGISTRY`，`mcp_event_triage` |
| **Phase 3.5** | SSE 串流整合，即時事件推送 | `StreamingResponse`，SSE 協定，非同步生成器 |
| **Phase 4** | Glass Box 靜態前端 | 純 HTML/CSS/JS，EventSource，玻璃盒視覺化 |

---

## 4. Phase 5：企業級管理控制台

### 4.1 升級目標

| 升級點 | Phase 4 | Phase 5 |
|--------|---------|---------|
| 前端框架 | 純 HTML/CSS/JS 靜態頁面 | Vite + React 18 SPA |
| CSS 方案 | 手寫 CSS / Bootstrap 風格 | Tailwind CSS v3 |
| 路由 | 單頁無路由 | React Router DOM（/login, /diagnosis, /skills, /settings） |
| 佈局 | 無固定 Layout | SaaS 管理後台：深色 Sidebar + Header |
| 狀態管理 | 原生 JS 全局變數 | React hooks（useAuth, useSSE） |
| SSE 接收 | EventSource API | Fetch + ReadableStream + TextDecoder |
| 工具呼叫展示 | 簡易列表 | 三 Tab 面板（報告 / 事件分類 / 工具呼叫） |
| Skill 管理 | 無 | /skills 頁面，兩類 Skill 分類，Right Drawer 詳情 |
| 系統設定 | 無 | /settings 頁面，表單式管理 |

### 4.2 核心模組

#### 模組 A：診斷工作站（`/diagnosis`）

**主功能**
- 左側面板（65%）：三個 Tab 頁籤
  - **診斷報告**：Markdown 渲染的最終報告（`.prose-report` 樣式）
  - **事件分類**：事件物件卡片，顯示 event_id、event_type、urgency badge、recommended_skills
  - **工具呼叫**：每次 tool call 的手風琴卡片，含輸入/輸出 JSON
- 右側面板（35%）：Chat 對話區
  - 使用者與 Agent 氣泡樣式區分
  - 3 個快速建議按鈕
  - Textarea + 發送按鈕
  - 串流進行時顯示「Agent 執行中...」禁用輸入

**SSE 整合**
- 使用 Fetch API（非 EventSource）實現 SSE 接收
- `POST /api/v1/diagnose/`，Bearer Token 授權
- 即時解析 `event: xxx` + `data: {json}` 格式

#### 模組 B：技能與事件庫（`/skills`）

**主功能**
- 兩個頁籤：
  - **事件分診庫**：顯示 `mcp_event_triage` 等分流技能
  - **診斷工具庫**：顯示 `mcp_mock_cpu_check`、`mcp_rag_knowledge_search` 等診斷工具
- 每個 Skill 以卡片形式呈現，顯示名稱、描述
- 點擊卡片展開右側抽屜（Right Drawer）
- 抽屜內：技能描述、Input Schema（JsonViewer 遞迴展示）

#### 模組 C：系統與環境變數（`/settings`）

**主功能**
- 全局提示詞（Global System Prompt）：大型 Textarea
- 模型選擇（Model Routing）：下拉選單（Claude Opus 4.6 / Sonnet 4.6 / Haiku 4.5）
- API 金鑰管理：密碼遮蔽輸入框
- CORS 來源設定：文字輸入框
- 日誌等級（Log Level）：下拉選單
- 儲存按鈕：顯示成功提示

---

## 5. 前端技術規格

### 5.1 目錄結構

```
frontend/
├── index.html
├── vite.config.js          ← Proxy /api → :8000
├── tailwind.config.js
├── postcss.config.js
├── package.json
└── src/
    ├── main.jsx             ← BrowserRouter
    ├── App.jsx              ← Routes + PrivateRoute
    ├── App.css
    ├── index.css            ← Tailwind + 自訂元件類別
    ├── hooks/
    │   ├── useAuth.js       ← JWT localStorage 管理
    │   └── useSSE.js        ← SSE 串流 + 狀態機
    ├── components/
    │   ├── Layout.jsx       ← Sidebar + Header + Outlet
    │   ├── Sidebar.jsx      ← 深色導覽列，NavLink active states
    │   ├── Header.jsx       ← 頁面標題 + 使用者資訊 + 登出
    │   └── ui/
    │       ├── Drawer.jsx   ← 右側滑出抽屜，Escape 關閉
    │       └── JsonViewer.jsx ← 遞迴 JSON 樹狀展示
    ├── pages/
    │   ├── LoginPage.jsx
    │   ├── DiagnosisPage.jsx
    │   ├── SkillsPage.jsx
    │   └── SettingsPage.jsx
    └── data/
        └── mockData.js      ← MOCK_SKILLS, MOCK_SETTINGS
```

### 5.2 Vite 代理設定

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

### 5.3 配色系統

| 用途 | Tailwind Class | 說明 |
|------|---------------|------|
| 側邊欄背景 | `slate-900` | 深色導覽列 |
| 主背景 | `slate-50` | 淺灰頁面底色 |
| 卡片背景 | `white` + `shadow-sm` | 白色卡片 |
| 主色調 | `indigo-600` | 按鈕、active link |
| 成功狀態 | `emerald-500` | 低/中緊急度 |
| 警告狀態 | `amber-500` | 中緊急度 |
| 危急狀態 | `rose-500` | critical |
| 字體 | Inter（Google Fonts） | 高可讀性 |

### 5.4 自訂 CSS 元件類別（`@layer components`）

| 類別 | 用途 |
|------|------|
| `.sidebar-link` | Sidebar 導覽連結（含 hover / active） |
| `.btn-primary` | 主要動作按鈕（indigo） |
| `.btn-secondary` | 次要動作按鈕（gray） |
| `.card` | 基礎白色卡片 |
| `.badge` | 小標籤基礎樣式 |
| `.badge-indigo/emerald/amber/rose/slate/purple` | 各色 badge |
| `.input-field` | 標準輸入框樣式 |
| `.prose-report` | Markdown 報告渲染（h1–h3, p, ul, table, blockquote, code, pre） |
| `.typing-cursor` | 打字機游標動畫 |

### 5.5 useAuth Hook

```js
const TOKEN_KEY = 'glassbox_token'

export function useAuth() {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY))
  const login = useCallback((newToken) => {
    localStorage.setItem(TOKEN_KEY, newToken)
    setToken(newToken)
  }, [])
  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY)
    setToken(null)
  }, [])
  return { token, login, logout }
}
```

### 5.6 useSSE Hook 狀態機

| 狀態欄位 | 類型 | 說明 |
|---------|------|------|
| `isStreaming` | boolean | 是否正在接收 SSE |
| `eventObject` | object \| null | mcp_event_triage 回傳的事件物件 |
| `toolCalls` | array | 所有工具呼叫記錄（含輸入/輸出） |
| `report` | string | 最終 Markdown 診斷報告 |
| `chatMessages` | array | 聊天紀錄（role: user \| agent） |
| `error` | string \| null | 錯誤訊息 |

---

## 6. 頁面與路由規格

### 6.1 路由表

| 路徑 | 元件 | 保護 | 說明 |
|------|------|------|------|
| `/login` | `LoginPage` | 公開 | 登入表單 |
| `/` | 重導向至 `/diagnosis` | PrivateRoute | — |
| `/diagnosis` | `DiagnosisPage` | PrivateRoute | 主診斷工作站 |
| `/skills` | `SkillsPage` | PrivateRoute | Skill 管理 |
| `/settings` | `SettingsPage` | PrivateRoute | 系統設定 |

### 6.2 PrivateRoute 邏輯

```jsx
function PrivateRoute({ children }) {
  const { token } = useAuth()
  return token ? children : <Navigate to="/login" replace />
}
```

未登入時自動重導向至 `/login`；登入後由 `Layout` 包裹，提供 Sidebar + Header。

### 6.3 登入頁規格

- 用戶名稱（text input）+ 密碼（password input）+ 登入按鈕
- 送出：`POST /api/v1/auth/login`，Content-Type: `application/json`
- 請求體：`{ "username": "...", "password": "..." }`
- 回應讀取：`response.data.data.access_token`（StandardResponse 包裝）
- 成功後導向 `/diagnosis`
- 失敗顯示錯誤訊息

### 6.4 診斷頁規格（DiagnosisPage）

**左面板（65%）—— 三 Tab**

| Tab | 內容 | 顯示條件 |
|-----|------|---------|
| 診斷報告 | `.prose-report` Markdown 渲染 | `report` 非空 |
| 事件分類 | EventObjectCard（event_type, urgency badge, skills list） | `eventObject` 非空 |
| 工具呼叫 | ToolCallCard 列表（名稱 + JSON 輸入/輸出） | `toolCalls.length > 0` |

空狀態顯示說明文字引導用戶開始診斷。

**右面板（35%）—— Chat 區**

- 聊天訊息列表（user: indigo 背景；agent: white 背景）
- 3 個快速建議按鈕（`onClick` 直接呼叫 `sendMessage(s)`）
- Textarea（Enter 發送，Shift+Enter 換行）
- 「發送」或「停止」按鈕（串流中切換）
- `isStreaming` 期間顯示「Agent 執行中...」spinner

---

## 7. API 規格（後端）

### 7.1 認證 API

#### POST `/api/v1/auth/login`

**請求**
```json
{
  "username": "string",
  "password": "string"
}
```

**回應（200 OK）**
```json
{
  "status": "success",
  "message": "Login successful",
  "data": {
    "access_token": "eyJhbGci...",
    "token_type": "bearer"
  },
  "error_code": null
}
```

### 7.2 診斷 API

#### POST `/api/v1/diagnose/`

**請求頭**
```
Content-Type: application/json
Authorization: Bearer <access_token>
```

**請求體**
```json
{
  "issue_description": "string（5–2000 字元）"
}
```

**回應**：`Content-Type: text/event-stream`（SSE 串流，詳見第 8 節）

### 7.3 健康檢查

#### GET `/api/v1/health`

```json
{
  "status": "healthy",
  "database": "connected",
  "version": "1.0.0"
}
```

### 7.4 StandardResponse 格式

所有非串流 API 回應統一包裝：

```json
{
  "status": "success | error",
  "message": "說明訊息",
  "data": { ... },
  "error_code": null | "NOT_FOUND | UNAUTHORIZED | ..."
}
```

---

## 8. SSE 事件協定

### 8.1 事件格式（RFC 8895）

```
event: <event_type>\n
data: <json_payload>\n
\n
```

### 8.2 事件序列

```
session_start → tool_call* → tool_result* → (重複) → report → done
```

若發生例外則插入 `error`；`done` 無論如何都會是最後一個事件。

### 8.3 事件規格

| 事件名稱 | Payload 欄位 | 說明 |
|---------|------------|------|
| `session_start` | `{ "issue": string }` | 診斷開始 |
| `tool_call` | `{ "tool_name": string, "tool_input": object }` | Agent 呼叫工具前 |
| `tool_result` | `{ "tool_name": string, "tool_result": object, "is_error": bool }` | 工具執行後 |
| `report` | `{ "content": string, "total_turns": int, "tools_invoked": list }` | 最終 Markdown 報告 |
| `error` | `{ "message": string }` | 例外錯誤 |
| `done` | `{ "status": "complete" }` | 串流結束（finally 保證觸發） |

### 8.4 `mcp_event_triage` tool_result 結構

```json
{
  "event_id": "EVT-A1B2C3D4",
  "event_type": "Performance_Degradation",
  "attributes": {
    "symptom": "系統 API 很慢",
    "urgency": "high"
  },
  "recommended_skills": ["mcp_mock_cpu_check", "mcp_rag_knowledge_search"]
}
```

**urgency 值**：`critical` | `high` | `medium` | `low`

---

## 9. Skill 系統規格

### 9.1 Skill 基礎類別（BaseMCPSkill）

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

### 9.2 已實作的 Skills

| Skill 名稱 | 類別 | 分類 | 說明 |
|-----------|------|------|------|
| `mcp_event_triage` | EventTriageSkill | 分診庫 | 症狀分類，回傳 Event Object，強制第一呼叫 |
| `mcp_mock_cpu_check` | MockCpuCheckSkill | 診斷工具 | 模擬 CPU 使用率檢測 |
| `mcp_rag_knowledge_search` | RagKnowledgeSearchSkill | 診斷工具 | 模擬 RAG 知識庫搜索 |
| `ask_user_recent_changes` | AskUserRecentChangesSkill | 診斷工具 | 詢問用戶最近的系統變更 |

### 9.3 Event Triage 分類規則

| 關鍵詞 | event_type | urgency | recommended_skills |
|--------|-----------|---------|-------------------|
| 慢, slow, CPU, 效能, lag | `Performance_Degradation` | high | mcp_mock_cpu_check, mcp_rag_knowledge_search |
| 記憶體, memory, OOM, heap, leak | `Memory_Leak` | high | mcp_rag_knowledge_search, ask_user_recent_changes |
| 延遲, latency, timeout, 超時 | `High_Latency` | medium | mcp_mock_cpu_check, mcp_rag_knowledge_search |
| 磁碟, disk, 空間不足, inode | `Disk_Full` | high | mcp_rag_knowledge_search, ask_user_recent_changes |
| 掛了, down, crash, 503, 500 | `Service_Down` | critical | mcp_rag_knowledge_search, ask_user_recent_changes |
| 部署, deploy, 上線, release | `Deployment_Issue` | medium | ask_user_recent_changes, mcp_rag_knowledge_search |
| （其他） | `Unknown_Symptom` | low | mcp_rag_knowledge_search |

---

## 10. 資料流與狀態管理

### 10.1 診斷工作站資料流

```
[用戶輸入 or 快速建議]
    → useSSE.sendMessage(text)
    → POST /api/v1/diagnose/  {issue_description: text}
    → ReadableStream 逐行讀取
    → 解析 SSE 行
    ┌───────────────────────────────────────────────────┐
    │ event: session_start → setChatMessages (系統訊息) │
    │ event: tool_call     → setToolCalls (append)     │
    │ event: tool_result   → setToolCalls (patch last) │
    │   └─ if mcp_event_triage → setEventObject        │
    │ event: report        → setReport + setChatMessages│
    │ event: error         → setError + setChatMessages │
    │ event: done          → (忽略)                    │
    └───────────────────────────────────────────────────┘
    → finally: setIsStreaming(false)
```

### 10.2 工具呼叫配對邏輯

每個 `tool_call` 事件先 append 一筆 `{ name, input, result: null }` placeholder。
對應的 `tool_result` 事件到來時，倒序查找相同 name 且 `result === null` 的項目並 patch。

### 10.3 JWT 認證流

```
localStorage (glassbox_token)
    ↓
useAuth() → { token, login, logout }
    ↓
PrivateRoute: !token → Navigate to /login
    ↓
API 請求: Authorization: Bearer <token>
    ↓
後端 verify_token() → 回傳 User 物件
```

---

## 11. 安全性規格

| 安全點 | 實作方式 |
|--------|---------|
| **認證** | JWT（HS256），`SECRET_KEY` 環境變數，預設 1 天有效期 |
| **密碼儲存** | bcrypt hash（passlib CryptContext） |
| **API 保護** | `/api/v1/diagnose/` 要求 Bearer Token，FastAPI `Depends(get_current_user)` |
| **唯讀原則** | 所有診斷 Skill 嚴格唯讀，System Prompt 中明確禁止寫入操作 |
| **CORS** | 可透過 Settings 頁面設定允許來源（預設 localhost） |
| **前端安全** | Token 存 localStorage（非 httpOnly cookie），適合 SPA 場景 |
| **輸入驗證** | `issue_description` 5–2000 字元限制（Pydantic Field） |

---

## 12. 測試規格

### 12.1 後端測試（Pytest）

| 測試類型 | 數量 | 工具 |
|---------|------|------|
| 單元測試 | 83 | pytest, httpx AsyncClient |
| 覆蓋率 | >90% | pytest-cov |
| 非同步測試 | 全部 | pytest-asyncio（asyncio_mode=auto） |
| 資料庫 | in-memory SQLite | app.dependency_overrides |

執行：
```bash
cd fastapi_backend_service
pytest --cov=app --cov-report=term-missing
```

### 12.2 前端 E2E 冒煙測試（Playwright）

| 測試步驟 | 預期結果 |
|---------|---------|
| 訪問 `/login` | 顯示登入表單 |
| 輸入 `gill/g1i1l2l3` 並送出 | 重導向至 `/diagnosis` |
| 點選快速建議按鈕 | 開始 SSE 串流，顯示「Agent 執行中」 |
| 等待 `✅ 診斷完成` | 最終報告出現（`.prose-report`） |
| 切換「事件分類」Tab | EventObjectCard 顯示 |
| 切換「工具呼叫」Tab | ToolCallCard 列表顯示 |
| 點選「技能與事件庫」Sidebar | 進入 `/skills` 頁面 |
| 點選 `mcp_event_triage` 卡片 | 右側抽屜展開，顯示 Input Schema |
| 點選「診斷工具庫」Tab | 顯示診斷工具列表 |
| 點選「系統與環境變數」Sidebar | 進入 `/settings` 頁面 |

---

## 13. 部署規格

### 13.1 開發環境

```bash
# 後端（終端 1）
cd fastapi_backend_service
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# 前端（終端 2）
cd fastapi_backend_service/frontend
npm install
npm run dev  # 啟動於 localhost:5173 或 5174
```

### 13.2 環境變數（後端）

| 變數名稱 | 預設值 | 說明 |
|---------|--------|------|
| `ANTHROPIC_API_KEY` | 必填 | Anthropic API 金鑰 |
| `SECRET_KEY` | 隨機生成 | JWT 簽名金鑰 |
| `DATABASE_URL` | SQLite dev.db | 資料庫連線字串 |
| `API_V1_PREFIX` | `/api/v1` | API 路由前綴 |
| `ALGORITHM` | `HS256` | JWT 演算法 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `1440` | Token 有效期（分鐘） |

### 13.3 正式環境部署

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
cd frontend
npm run build  # 輸出至 dist/
# 可由 Nginx、Cloudflare Pages、Vercel 等服務托管
```

**Nginx 反向代理**
```nginx
location /api/ {
    proxy_pass http://backend:8000;
}
location / {
    root /var/www/frontend/dist;
    try_files $uri $uri/ /index.html;
}
```

---

## 14. 已知限制與未來規劃

### 14.1 已知限制

| 限制 | 說明 |
|------|------|
| **Skill 為 Mock** | `mcp_mock_cpu_check`、`mcp_rag_knowledge_search` 使用模擬資料，非實際系統資料 |
| **Settings 未持久化** | `/settings` 頁面為 Mock，修改不會寫入後端 |
| **Skills API 未實作** | `/skills` 頁面使用前端 mockData，非來自後端 API |
| **無多用戶隔離** | 所有使用者共享同一 Skill Registry 和 System Prompt |
| **Token 在 localStorage** | 比 httpOnly cookie 更易受 XSS 攻擊（SPA 典型取捨） |
| **無 WebSocket 推送** | 診斷結果僅可由用戶主動觸發，非被動接收告警 |

### 14.2 未來規劃（Phase 6+）

| 功能 | 說明 |
|------|------|
| **真實 Skill 對接** | 對接真實 CPU/Memory/Disk 監控 API |
| **Settings 持久化** | Settings API + 資料庫儲存 |
| **Skill 動態載入** | 從 `/api/v1/skills` 動態取得 Skill 清單 |
| **告警 WebSocket** | 接收主動推送的系統告警 |
| **多租戶** | 用戶隔離的 Skill 設定和診斷歷史 |
| **診斷歷史** | 儲存並查詢過往診斷報告 |
| **MCP Server** | 將 Skill 系統包裝為標準 MCP Server |
| **Streaming 報告** | 逐 token 串流最終報告（目前為完整報告一次送出） |

---

*文件版本：v5.0 — 2026-02-28*
