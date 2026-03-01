# Product Specification — Glass Box AI 診斷引擎

> **版本**：3.5　｜　**狀態**：已實作完成　｜　**日期**：2026-02-28

---

## 目錄

1. [產品願景](#1-產品願景)
2. [技術架構](#2-技術架構)
3. [Phase 1：基礎 FastAPI 服務](#3-phase-1基礎-fastapi-服務)
4. [Phase 2：AI 診斷代理核心](#4-phase-2ai-診斷代理核心)
5. [Phase 3：MCP Event Triage 分流機制](#5-phase-3mcp-event-triage-分流機制)
6. [Phase 3.5：SSE 串流整合](#6-phase-35sse-串流整合)
7. [Phase 4：Glass Box 前端介面](#7-phase-4glass-box-前端介面)
8. [資料模型](#8-資料模型)
9. [API 規格](#9-api-規格)
10. [Skill 系統規格](#10-skill-系統規格)
11. [SSE 事件規格](#11-sse-事件規格)
12. [安全性規格](#12-安全性規格)
13. [測試規格](#13-測試規格)
14. [部署規格](#14-部署規格)
15. [已知限制與未來規劃](#15-已知限制與未來規劃)

---

## 1. 產品願景

### 1.1 核心理念

**Glass Box（玻璃盒）AI 診斷引擎**是一個領域無關的智慧型問題診斷平台。相對於傳統 AI 系統的「黑盒」操作，本系統讓 AI 代理的每一個推理步驟、工具呼叫與資料來源都即時透明地呈現在使用者面前。

### 1.2 設計原則

| 原則 | 描述 |
|------|------|
| **透明性 (Glass Box)** | AI 的每個決策步驟即時對使用者可見 |
| **領域無關 (Domain-Agnostic)** | 路由決策完全委託 LLM，無硬編碼業務邏輯 |
| **唯讀安全 (Read-Only)** | 所有診斷操作嚴格執行唯讀，不自動修復 |
| **強制分流 (Triage-First)** | `mcp_event_triage` 永遠是 Agent 的第一步 |
| **可擴充 (Extensible MCP)** | 新增診斷能力只需兩步驟（新增 Skill + 註冊） |

### 1.3 目標用戶

- SRE / DevOps 工程師：處理系統告警的第一線排障
- IT 運維人員：非技術背景，需要 AI 輔助診斷
- 開發者：學習 MCP 工具模式和 Agentic AI 架構

---

## 2. 技術架構

### 2.1 技術棧

| 層級 | 技術選型 | 版本 |
|------|---------|------|
| Web 框架 | FastAPI | 0.109.0 |
| ASGI 伺服器 | Uvicorn | 0.27.0 |
| ORM | SQLAlchemy (非同步) | 2.0.25 |
| 資料驗證 | Pydantic v2 | 2.6.0 |
| 資料庫（開發） | SQLite + aiosqlite | 0.19.0 |
| 資料庫（正式） | PostgreSQL + asyncpg | 0.29.0 |
| 身份驗證 | python-jose (JWT) | 3.3.0 |
| 密碼雜湊 | passlib (bcrypt) | 1.7.4 |
| AI 模型客戶端 | anthropic SDK | ≥0.40.0 |
| LLM 模型 | Claude claude-opus-4-6 | — |
| 資料庫遷移 | Alembic | 1.13.1 |
| HTTP 客戶端（測試） | httpx | 0.26.0 |
| 前端框架 | Vanilla JS (無框架) | — |
| 前端 CSS | Tailwind CSS CDN | Play CDN |
| Markdown 渲染 | marked.js CDN | — |

### 2.2 系統架構圖

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Client Layer                                  │
│  Browser (http://localhost:8000/)                                    │
│  ┌────────────────────────┐  ┌───────────────────────────────────┐  │
│  │  Glass Box SPA          │  │  API Consumers (curl / Swagger)   │  │
│  │  (index.html / app.js)  │  │                                   │  │
│  └───────────┬────────────┘  └───────────────┬───────────────────┘  │
└──────────────┼────────────────────────────────┼─────────────────────┘
               │ SSE (text/event-stream)         │ JSON REST
               │ POST /api/v1/diagnose/          │ /api/v1/*
┌──────────────▼─────────────────────────────────▼─────────────────────┐
│                     FastAPI Application Layer                          │
│                                                                        │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌─────────────┐ │
│  │  auth_router │ │ users_router │ │ items_router │ │ diag_router │ │
│  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘ └──────┬──────┘ │
│         │                │                │                 │         │
│  ┌──────▼───────────────────────────────────────────────────▼──────┐ │
│  │                    Service Layer                                  │ │
│  │  AuthService  UserService  ItemService   DiagnosticService       │ │
│  └──────┬───────────────┬─────────────────────────┬────────────────┘ │
│         │               │                         │                   │
│  ┌──────▼───────────────▼──────┐  ┌──────────────▼─────────────────┐ │
│  │   Repository Layer           │  │   SKILL_REGISTRY               │ │
│  │   (UserRepo / ItemRepo)      │  │   (MCP Tool Dispatch)          │ │
│  └──────┬───────────────────────┘  └──────────────┬─────────────────┘ │
│         │                                         │                    │
│  ┌──────▼──────────────────┐  ┌──────────────────▼───────────────┐   │
│  │  SQLite / PostgreSQL     │  │  Anthropic Claude claude-opus-4-6   │   │
│  │  (AsyncSession)          │  │  (messages.create / streaming)   │   │
│  └─────────────────────────┘  └──────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────┘
```

### 2.3 請求處理流程

```
HTTP Request
    │
    ▼
RequestLoggingMiddleware (生成 X-Request-ID)
    │
    ▼
CORSMiddleware
    │
    ▼
Router (auth / users / items / diagnostic)
    │
    ▼
Service Layer (業務邏輯)
    │
    ├── [診斷請求] → DiagnosticService.stream()
    │                      │
    │                      ▼ Agent Loop
    │                  Anthropic API (Turn N)
    │                      │
    │                      ▼ tool_use blocks
    │                  SKILL_REGISTRY.dispatch()
    │                      │
    │                      ▼
    │                  Skill.execute()
    │                      │
    │                      ▼ SSE yield
    │              text/event-stream 回應
    │
    └── [其他請求] → Repository → Database
                         │
                         ▼
                   JSON StandardResponse
```

---

## 3. Phase 1：基礎 FastAPI 服務

### 3.1 交付項目

- [x] FastAPI 應用程式框架
- [x] SQLAlchemy 2.0 非同步 ORM
- [x] Pydantic v2 資料驗證
- [x] JWT 身份驗證（登入 / Token 驗證 / 當前使用者）
- [x] 使用者 CRUD API（含分頁、所有權驗證）
- [x] 物品 CRUD API（含所有權驗證）
- [x] 統一回應格式 (`StandardResponse`)
- [x] 全域例外處理（AppException / HTTP 422 / HTTP 5xx）
- [x] 結構化日誌（X-Request-ID 追蹤）
- [x] CORS 中介層
- [x] 健康檢查端點 (`GET /health`)
- [x] Alembic 資料庫遷移支援
- [x] 35 個單元測試（7 + 13 + 15）

### 3.2 統一回應格式

```json
{
  "status": "success | error",
  "message": "操作說明",
  "data": { "...": "..." },
  "error_code": null
}
```

```json
{
  "status": "error",
  "message": "錯誤說明",
  "data": null,
  "error_code": "NOT_FOUND | UNAUTHORIZED | ..."
}
```

### 3.3 JWT 認證流程

```
POST /api/v1/auth/login
  body: username + password (form-urlencoded)
  ↓
AuthService.authenticate_user()
  → 查 DB 找使用者
  → bcrypt 驗證密碼
  ↓
成功: 生成 JWT (HS256, 30分鐘效期)
  → data.access_token = "eyJ..."
失敗: HTTP 401 UNAUTHORIZED
```

---

## 4. Phase 2：AI 診斷代理核心

### 4.1 交付項目

- [x] `BaseMCPSkill` 抽象基礎類別
- [x] Skill 系統（`SKILL_REGISTRY`）
- [x] `DiagnosticService.run()` — 批次 Agent Loop
- [x] 初始 Skills：`MockCpuCheckSkill`、`MockRagKnowledgeSearchSkill`、`AskUserRecentChangesSkill`
- [x] `POST /api/v1/diagnose/` HTTP 端點
- [x] `DiagnoseRequest` / `DiagnoseResponse` Schema
- [x] 28 個診斷代理測試

### 4.2 Agent Loop 狀態機

```
初始狀態: messages = [{role: user, content: issue_description}]

迴圈（最多 max_turns=10 次）:
  ┌─ Turn N ────────────────────────────────────────────────────┐
  │  呼叫 anthropic.messages.create(tools=SKILL_REGISTRY)        │
  │                                                              │
  │  if stop_reason == "end_turn":                               │
  │      擷取 TextBlock → diagnosis_report                       │
  │      break                                                   │
  │                                                              │
  │  if stop_reason == "tool_use":                               │
  │      for each tool_use block:                                │
  │          skill = SKILL_REGISTRY[block.name]                  │
  │          result = await skill.execute(**block.input)         │
  │          append tool_result to messages                      │
  │      continue                                                │
  └─────────────────────────────────────────────────────────────┘

if max_turns_reached:
    強制請求 LLM 輸出最終報告
```

### 4.3 `_serialize_content()` — SDK 相容性修正

`anthropic >= 0.40` 回傳 Pydantic v2 Model 物件（含 SDK 內部欄位如 `citations`, `caller`），直接傳回 `messages.create()` 會造成 `pydantic-core` 崩潰。`_serialize_content()` 負責將 SDK 物件轉換為純 dict：

```python
def _serialize_content(blocks: list) -> list[dict]:
    result = []
    for block in blocks:
        t = getattr(block, "type", None)
        if t == "text":
            result.append({"type": "text", "text": block.text})
        elif t == "tool_use":
            result.append({
                "type": "tool_use",
                "id": block.id,
                "name": block.name,
                "input": dict(block.input),
            })
    return result
```

---

## 5. Phase 3：MCP Event Triage 分流機制

### 5.1 交付項目

- [x] `EventTriageSkill` (`mcp_event_triage`) — 強制第一呼叫工具
- [x] 6 種事件類型分類規則（關鍵字比對，First-Match）
- [x] 結構化 Event Object 輸出
- [x] System Prompt 強制分流約束
- [x] Phase 3 整合測試

### 5.2 事件分類規則

| 優先級 | 觸發關鍵字 | 事件類型 | 緊急程度 | 推薦工具 |
|--------|-----------|---------|---------|---------|
| 1 | 慢, slow, cpu, 效能, lag, 高負載 | `Performance_Degradation` | HIGH | cpu_check, rag |
| 2 | 記憶體, memory, oom, heap, leak | `Memory_Leak` | HIGH | rag, ask_user |
| 3 | 延遲, latency, timeout, 回應時間 | `High_Latency` | MEDIUM | cpu_check, rag |
| 4 | 磁碟, disk, 空間不足, no space | `Disk_Full` | HIGH | rag, ask_user |
| 5 | 掛了, down, crash, 503, 無法存取 | `Service_Down` | CRITICAL | rag, ask_user |
| 6 | 部署, deploy, rollback, 版本 | `Deployment_Issue` | MEDIUM | ask_user, rag |
| 7 | （未匹配） | `Unknown_Symptom` | LOW | rag |

### 5.3 Event Object 結構

```json
{
  "event_id": "EVT-A1B2C3D4",
  "event_type": "Performance_Degradation",
  "attributes": {
    "symptom": "系統很慢，CPU 使用率很高",
    "urgency": "high"
  },
  "recommended_skills": [
    "mcp_mock_cpu_check",
    "mcp_rag_knowledge_search"
  ]
}
```

### 5.4 System Prompt 強制分流

```
**執行鐵律（必須嚴格遵守，違者視為錯誤）：**
1. 收到使用者問題後，**第一步且唯一的第一步**必須呼叫 `mcp_event_triage`，
   並以使用者的完整原始症狀作為 `user_symptom` 參數。
2. 取得 Event Object 後，依照其中 `recommended_skills` 清單，依序呼叫後續工具。
3. **在取得 mcp_event_triage 的回傳結果之前，絕對禁止呼叫任何其他工具。**
```

---

## 6. Phase 3.5：SSE 串流整合

### 6.1 交付項目

- [x] `DiagnosticService.stream()` — 非同步產生器（AsyncGenerator）
- [x] `GET /api/v1/diagnose/` → `StreamingResponse(media_type="text/event-stream")`
- [x] SSE 格式輔助函式 `_sse(event_type, data)`
- [x] 6 種 SSE 事件類型（session_start / tool_call / tool_result / report / error / done）
- [x] `done` 事件在 `finally` 區塊中確保永遠發送
- [x] SSE 整合測試

### 6.2 串流設計要點

- 使用 FastAPI `StreamingResponse` 搭配 `AsyncGenerator`
- 每個 SSE 字串以 `\n\n` 結尾（RFC 8895 規範）
- 客戶端必須使用 `Fetch API + ReadableStream`（不能用 `EventSource`，因後者不支援 `Authorization` Header）
- `error` 事件在例外逃逸時發送，`done` 事件在 `finally` 保證發送

---

## 7. Phase 4：Glass Box 前端介面

### 7.1 交付項目

- [x] 純靜態 SPA（`static/index.html` + `static/style.css` + `static/app.js`）
- [x] FastAPI `StaticFiles` 掛載於 `/`（API 路由優先）
- [x] 登入畫面（帳密登入 + JWT 直接輸入）
- [x] 左側動態工具頁籤系統（tab navigation）
- [x] 右側即時 SSE 對話流
- [x] `mcp_event_triage` 結構化 Event Object 卡片渲染
- [x] Markdown 診斷報告渲染（marked.js）
- [x] 載入中旋轉動畫（Spinner）+ 進度條（Loading Bar）

### 7.2 前端技術細節

#### SSE 實作（Fetch API + ReadableStream）

```javascript
const response = await fetch('/api/v1/diagnose/', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({ issue_description: text })
});

const reader = response.body.getReader();
const decoder = new TextDecoder();
let buffer = '';

while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  buffer += decoder.decode(value, { stream: true });
  // 以 \n\n 分割 SSE 事件
  const parts = buffer.split('\n\n');
  buffer = parts.pop();  // 保留不完整的最後一段
  for (const part of parts) {
    const parsed = _parseSSEChunk(part);
    if (parsed) _handleSSEEvent(parsed);
  }
}
```

#### 動態頁籤管理

```javascript
// tool_call 事件 → 新增頁籤（Spinner 狀態）
function _createToolTab(toolName) {
  const tab = document.createElement('button');
  tab.innerHTML = `<span class="tab-spinner"></span> ${toolName}`;
  tab.dataset.tool = toolName;
  tabBar.appendChild(tab);
}

// tool_result 事件 → 更新頁籤（完成狀態）
function _renderToolResult(toolName, result, isError) {
  const tab = document.querySelector(`[data-tool="${toolName}"]`);
  tab.innerHTML = isError ? `❌ ${toolName}` : `✓ ${toolName}`;
}
```

### 7.3 介面版面規格

```
100% viewport width
├── Header (固定高度): Logo + 使用者名稱 + 登出
└── Main Content (剩餘高度)
    ├── Left Panel (70%): 診斷工作區
    │   ├── Tab Bar (固定高度): 動態頁籤
    │   └── Tab Content (剩餘高度, overflow-y: auto)
    │       └── 工具資料卡片 / Markdown 報告
    └── Right Panel (30%): 即時對話
        ├── Chat History (剩餘高度, overflow-y: auto)
        └── Input Area (固定高度): TextArea + 送出按鈕
```

### 7.4 靜態檔案掛載

```python
# main.py — 必須在所有 API router 之後掛載
_STATIC_DIR = Path(__file__).parent / "static"
if _STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="frontend")
```

---

## 8. 資料模型

### 8.1 User Model

```python
class User(Base):
    __tablename__ = "users"
    id: int (PK, autoincrement)
    username: str (unique, not null)
    email: str (unique, not null)
    hashed_password: str (not null)
    is_active: bool (default=True)
    created_at: datetime (default=now)
    updated_at: datetime (auto-update)
```

### 8.2 Item Model

```python
class Item(Base):
    __tablename__ = "items"
    id: int (PK, autoincrement)
    title: str (not null)
    description: str | None
    owner_id: int (FK → users.id, CASCADE DELETE)
    created_at: datetime (default=now)
    updated_at: datetime (auto-update)
```

### 8.3 DiagnoseRequest / DiagnoseResponse Schema

```python
class DiagnoseRequest(BaseModel):
    issue_description: str = Field(
        min_length=1,
        max_length=2000,
        description="自由文字的問題描述"
    )

class ToolCallRecord(BaseModel):
    tool_name: str
    tool_input: dict
    tool_result: dict

class DiagnoseResponse(BaseModel):
    issue_description: str
    tools_invoked: list[ToolCallRecord]
    diagnosis_report: str
    total_turns: int
```

---

## 9. API 規格

### 9.1 端點一覽

| 方法 | 路徑 | 認證 | 功能 |
|------|------|------|------|
| GET | `/health` | 無 | 服務健康檢查 |
| GET | `/` | 無 | Glass Box 前端 SPA |
| POST | `/api/v1/auth/login` | 無 | 登入，取得 JWT |
| GET | `/api/v1/auth/me` | JWT | 查詢當前使用者 |
| GET | `/api/v1/users/` | 無 | 使用者列表（分頁） |
| POST | `/api/v1/users/` | 無 | 建立使用者 |
| GET | `/api/v1/users/{id}` | 無 | 查詢指定使用者 |
| PUT | `/api/v1/users/{id}` | JWT（本人） | 更新使用者 |
| DELETE | `/api/v1/users/{id}` | JWT（本人） | 刪除使用者 |
| GET | `/api/v1/items/` | 無 | Items 列表（分頁） |
| GET | `/api/v1/items/me` | JWT | 自己的 Items |
| POST | `/api/v1/items/` | JWT | 建立 Item |
| GET | `/api/v1/items/{id}` | 無 | 查詢指定 Item |
| PUT | `/api/v1/items/{id}` | JWT（擁有者） | 更新 Item |
| DELETE | `/api/v1/items/{id}` | JWT（擁有者） | 刪除 Item |
| POST | `/api/v1/diagnose/` | JWT | 執行 AI 診斷（SSE 串流） |

### 9.2 診斷端點規格

**POST /api/v1/diagnose/**

```
Request:
  Headers:
    Authorization: Bearer <JWT>
    Content-Type: application/json
  Body:
    {"issue_description": "問題描述字串"}

Response:
  Status: 200 OK
  Content-Type: text/event-stream
  Cache-Control: no-cache
  Body: SSE 串流（見 §11）
```

### 9.3 分頁參數

所有列表端點支援：

| 參數 | 類型 | 預設 | 說明 |
|------|------|------|------|
| `skip` | int | 0 | 跳過筆數 |
| `limit` | int | 100 | 每頁最大筆數 |

---

## 10. Skill 系統規格

### 10.1 BaseMCPSkill 介面

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

    @abstractmethod
    async def execute(self, **kwargs: Any) -> dict: ...

    def to_anthropic_tool(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema
        }

    def to_mcp_schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema  # camelCase
        }
```

### 10.2 已實作 Skills

#### mcp_event_triage（強制第一呼叫）

```
輸入: {"user_symptom": str}
輸出: {
  "event_id": "EVT-XXXXXXXX",
  "event_type": str,
  "attributes": {"symptom": str, "urgency": "critical|high|medium|low"},
  "recommended_skills": [str, ...]
}
```

#### mcp_mock_cpu_check

```
輸入: {"service_name": str}
輸出: {
  "service_name": str,
  "cpu_usage_percent": float,
  "cpu_cores": int,
  "load_average_1m": float,
  "load_average_5m": float,
  "load_average_15m": float,
  "status": "normal|moderate|high_load|critical",
  "note": str
}
```

#### mcp_rag_knowledge_search

```
輸入: {"query": str, "top_k": int = 3}
輸出: {
  "query": str,
  "results_found": int,
  "documents": [
    {"doc_id": str, "title": str, "content": str, "relevance_score": float}
  ]
}
```

#### ask_user_recent_changes

```
輸入: {"question": str, "context": str = ""}
輸出: {
  "question": str,
  "simulated_answer": str,
  "timestamp": str,
  "source": "simulated_human_operator"
}
```

### 10.3 新增 Skill 流程

```bash
# Step 1: 建立 Skill 類別
cat > app/skills/my_skill.py << 'EOF'
from app.skills.base import BaseMCPSkill
class MySkill(BaseMCPSkill):
    @property
    def name(self): return "my_skill_name"
    @property
    def description(self): return "何時應呼叫此工具"
    @property
    def input_schema(self): return {"type": "object", "properties": {...}}
    async def execute(self, **kwargs): return {"result": "..."}
EOF

# Step 2: 在 SKILL_REGISTRY 中註冊
# app/skills/__init__.py
# _ALL_SKILLS.append(MySkill())
```

---

## 11. SSE 事件規格

### 11.1 格式規範（RFC 8895）

```
event: <event_type>\n
data: <JSON string>\n
\n
```

### 11.2 事件定義

#### session_start
```json
{"issue": "問題描述字串"}
```
觸發時機：每次診斷請求開始時，發送一次。

#### tool_call
```json
{"tool_name": "mcp_event_triage", "tool_input": {"user_symptom": "..."}}
```
觸發時機：AI 決定呼叫工具之前。

#### tool_result
```json
{
  "tool_name": "mcp_event_triage",
  "tool_result": {"event_id": "EVT-...", ...},
  "is_error": false
}
```
觸發時機：工具執行完成後（成功或失敗均發送）。

#### report
```json
{
  "content": "## 問題摘要\n...",
  "total_turns": 4,
  "tools_invoked": [
    {"tool_name": "mcp_event_triage", "tool_input": {...}, "tool_result": {...}}
  ]
}
```
觸發時機：AI 完成最終診斷報告時。

#### error
```json
{"message": "例外訊息"}
```
觸發時機：未處理的例外逃逸 Agent Loop 時。

#### done
```json
{"status": "complete"}
```
觸發時機：診斷結束，**永遠在 `finally` 發送**，即使發生錯誤。

### 11.3 事件序列保證

1. `session_start` 永遠是第一個事件
2. `done` 永遠是最後一個事件
3. 每個 `tool_call` 之後一定有對應的 `tool_result`
4. `report` 在 `done` 之前
5. 若發生錯誤，`error` 在 `done` 之前

---

## 12. 安全性規格

### 12.1 認證機制

- JWT（HS256）
- Token 效期：30 分鐘（可設定）
- 儲存：前端 `localStorage`
- 傳輸：HTTP Header `Authorization: Bearer <token>`

### 12.2 授權控制

| 操作 | 授權規則 |
|------|---------|
| 更新使用者 | 只有本人 (`current_user.id == user_id`) |
| 刪除使用者 | 只有本人 |
| 更新 Item | 只有擁有者 (`item.owner_id == current_user.id`) |
| 刪除 Item | 只有擁有者 |
| 診斷 API | 任何已登入使用者 |

### 12.3 安全約束

- AI 代理嚴格限制：不得對任何系統執行寫入操作或重啟服務
- 所有診斷結論僅供人類參考，不能自動修復
- API Key 透過環境變數注入，不寫入程式碼
- 密碼使用 bcrypt 雜湊儲存

### 12.4 輸入驗證

| 欄位 | 規則 |
|------|------|
| `issue_description` | `min_length=1`, `max_length=2000` |
| `username` | 唯一性約束 |
| `email` | Email 格式驗證 + 唯一性 |
| `password` | 伺服器端 bcrypt 雜湊 |

---

## 13. 測試規格

### 13.1 測試策略

- 所有測試使用函式作用域獨立 in-memory SQLite
- Anthropic API 使用 `unittest.mock` 完整 mock
- 測試之間完全隔離（無共享狀態）
- 非同步測試：`pytest-asyncio`，`asyncio_mode = auto`

### 13.2 測試覆蓋

| 測試檔案 | 測試數 | 涵蓋範圍 |
|---------|--------|---------|
| `test_auth.py` | 7 | JWT 登入、Token 驗證 |
| `test_users.py` | 13 | 使用者 CRUD、權限 |
| `test_items.py` | 15 | Item CRUD、所有權 |
| `test_diagnostic_flow.py` | 28 | Skill 合約、Agent Loop、HTTP 端點 |
| `test_combined_flow.py` | 20 | 端到端整合、SSE 事件序列 |
| **合計** | **83** | |

### 13.3 Mock 設計

```python
# 標準三輪 Mock
mock_responses = [
    # Turn 1: LLM 要求呼叫 mcp_event_triage
    MagicMock(
        stop_reason="tool_use",
        content=[ToolUseBlock(id="tu1", name="mcp_event_triage", input={...})]
    ),
    # Turn 2: LLM 要求呼叫 mcp_mock_cpu_check
    MagicMock(
        stop_reason="tool_use",
        content=[ToolUseBlock(id="tu2", name="mcp_mock_cpu_check", input={...})]
    ),
    # Turn 3: LLM 輸出最終報告
    MagicMock(
        stop_reason="end_turn",
        content=[TextBlock(type="text", text="## 問題摘要\n...")]
    ),
]
```

---

## 14. 部署規格

### 14.1 開發環境

```bash
cd fastapi_backend_service
pip install -r requirements.txt

# 設定環境變數
cp .env.example .env
# 編輯 .env 填入 ANTHROPIC_API_KEY

# 啟動
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 14.2 正式環境（建議）

```bash
# 使用 Gunicorn + Uvicorn workers
gunicorn main:app \
  -w 4 \
  -k uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --timeout 120

# 環境變數（正式環境請使用系統環境變數，勿使用 .env）
export DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db
export ANTHROPIC_API_KEY=sk-ant-...
export SECRET_KEY=$(openssl rand -hex 32)
export ALLOWED_ORIGINS=https://yourdomain.com
```

### 14.3 Docker（參考）

```dockerfile
FROM python:3.10-slim
WORKDIR /app
COPY fastapi_backend_service/ .
RUN pip install -r requirements.txt
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 14.4 環境變數清單

| 變數名 | 必填 | 預設值 | 說明 |
|--------|------|--------|------|
| `APP_NAME` | 否 | FastAPI Backend Service | 服務名稱 |
| `APP_VERSION` | 否 | 1.0.0 | 版本號 |
| `DEBUG` | 否 | False | 開發模式 |
| `API_V1_PREFIX` | 否 | /api/v1 | API 路由前綴 |
| `DATABASE_URL` | 否 | sqlite+aiosqlite:///./dev.db | 資料庫連線字串 |
| `SECRET_KEY` | **是** | — | JWT 簽署金鑰 |
| `ALGORITHM` | 否 | HS256 | JWT 演算法 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 否 | 30 | Token 效期（分鐘） |
| `ANTHROPIC_API_KEY` | **是** | — | Claude API 金鑰 |
| `ALLOWED_ORIGINS` | 否 | * | CORS 允許的 Origin |
| `LOG_LEVEL` | 否 | INFO | 日誌等級 |

---

## 15. 已知限制與未來規劃

### 15.1 當前版本限制（v3.5）

| 限制 | 說明 |
|------|------|
| Skill 為模擬資料 | 所有 Skill 回傳 Mock 資料，非真實系統指標 |
| 無對話歷史持久化 | 每次診斷獨立，不保存 Session |
| 單一 LLM 後端 | 固定使用 Claude claude-opus-4-6，不支援切換 |
| 無速率限制 | 未實作 API Rate Limiting |
| 無多租戶隔離 | 所有使用者共享 Skill 配置 |
| 無診斷記錄 | 診斷結果未持久化到資料庫 |

### 15.2 未來規劃（v4.x+）

| 功能 | 說明 |
|------|------|
| 真實 Metrics 整合 | 接入 Prometheus / Datadog API |
| 診斷歷史記錄 | 持久化診斷結果，支援搜尋回溯 |
| 多 LLM 支援 | 支援 Gemini、GPT-4 等後端 |
| Skill Marketplace | 動態載入第三方 Skill 插件 |
| 多語言報告 | 支援 EN / JP 等診斷報告語言 |
| Real-time Metrics | WebSocket 即時監控儀表板 |
| Role-Based Access | 管理員 / 操作員 / 觀察者角色 |
| Webhook 通知 | 診斷完成後觸發 Slack / PagerDuty |

---

## 附錄：版本歷史

| 版本 | 日期 | 主要變更 |
|------|------|---------|
| 1.0 | 2026-02-28 | Phase 1：基礎 FastAPI 服務（Auth + CRUD + 35 tests） |
| 2.0 | 2026-02-28 | Phase 2：AI 診斷代理核心（Agent Loop + Skills + 28 tests） |
| 3.0 | 2026-02-28 | Phase 3：MCP Event Triage 分流（EventTriageSkill + 強制分流） |
| 3.5 | 2026-02-28 | Phase 3.5 + Phase 4：SSE 串流整合 + Glass Box 前端（83 tests） |

---

*Glass Box AI 診斷引擎 — Product Spec v3.5*
*Powered by Anthropic Claude claude-opus-4-6 · Built with FastAPI · Streamed via SSE*
