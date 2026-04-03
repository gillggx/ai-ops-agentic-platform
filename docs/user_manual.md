# FastAPI Backend Service — 使用者手冊

> 版本：1.2.0　｜　最後更新：2026-03-07

---

## 目錄

1. [前置作業](#1-前置作業)
2. [專案目錄結構](#2-專案目錄結構)
3. [環境設定](#3-環境設定)
4. [啟動服務](#4-啟動服務)
5. [核心 API 操作](#5-核心-api-操作)
6. [MCP Skill 開發指南](#6-mcp-skill-開發指南)
7. [AI 診斷代理操作](#7-ai-診斷代理操作)
8. [執行測試](#8-執行測試)
9. [資料庫遷移 (Alembic)](#9-資料庫遷移-alembic)
10. [常見問題排除](#10-常見問題排除)
11. [Glass Box 前端介面操作](#11-glass-box-前端介面操作)

---

## 1. 前置作業

### 1.1 系統需求

| 項目 | 最低版本 | 備註 |
|------|----------|------|
| Python | 3.10+ | 使用 `match/case`、`X \| Y` 型別語法 |
| pip / conda | 最新版 | 用於安裝套件 |
| SQLite | 內建於 Python | 開發環境預設資料庫 |
| PostgreSQL | 14+ | 正式環境選用 |

### 1.2 安裝 Python 依賴

```bash
# 進入專案工作目錄
cd fastapi_backend_service

# （建議）建立虛擬環境
python -m venv .venv
source .venv/bin/activate          # macOS / Linux
# .venv\Scripts\activate           # Windows

# 安裝所有依賴
pip install -r requirements.txt
```

> **conda 使用者**
> ```bash
> conda create -n fastapi_service python=3.10
> conda activate fastapi_service
> pip install -r requirements.txt
> ```

### 1.3 取得 Anthropic API Key

診斷代理功能需要呼叫 Claude API。

1. 前往 [https://console.anthropic.com](https://console.anthropic.com) 登入或註冊。
2. 點選左側 **API Keys** → **Create Key**，複製金鑰。
3. 將金鑰寫入 `.env` 檔案（見下一節）。

---

## 2. 專案目錄結構

```
fastapi_backend_service/
├── main.py                          # 應用程式入口
├── requirements.txt                 # Python 依賴
├── pytest.ini                       # 測試設定
├── alembic.ini                      # 資料庫遷移設定
├── .env                             # 環境變數（需自行建立，勿提交 git）
│
├── alembic/                         # 資料庫遷移腳本
│   ├── env.py
│   └── versions/
│
├── app/
│   ├── config.py                    # 應用程式設定 (pydantic-settings)
│   ├── database.py                  # SQLAlchemy 非同步引擎 / session
│   ├── dependencies.py              # FastAPI Depends 工廠函式
│   ├── middleware.py                # Request Logging Middleware
│   │
│   ├── core/
│   │   ├── exceptions.py            # AppException + 錯誤碼常數
│   │   ├── logging.py               # AppLogger (結構化日誌)
│   │   └── response.py              # StandardResponse / HealthResponse
│   │
│   ├── models/                      # SQLAlchemy ORM 模型
│   │   ├── user.py
│   │   └── item.py
│   │
│   ├── schemas/                     # Pydantic 資料驗證模型
│   │   ├── common.py
│   │   ├── user.py
│   │   ├── item.py
│   │   └── diagnostic.py            # 診斷代理的 Request / Response
│   │
│   ├── repositories/                # 資料庫存取層 (CRUD)
│   │   ├── user_repository.py
│   │   └── item_repository.py
│   │
│   ├── services/                    # 業務邏輯層
│   │   ├── auth_service.py
│   │   ├── user_service.py
│   │   ├── item_service.py
│   │   └── diagnostic_service.py    # Agent Loop 主邏輯
│   │
│   ├── routers/                     # FastAPI 路由層
│   │   ├── auth.py
│   │   ├── users.py
│   │   ├── items.py
│   │   └── diagnostic.py            # POST /api/v1/diagnose
│   │
│   └── skills/                      # MCP Tool / Skill 定義
│       ├── base.py                  # BaseMCPSkill 抽象基礎類別
│       ├── cpu_check.py             # mcp_mock_cpu_check
│       ├── ask_user.py              # ask_user_recent_changes
│       ├── rag_search.py            # mcp_rag_knowledge_search
│       └── __init__.py              # SKILL_REGISTRY 聚合所有 skill
│
└── tests/
    ├── conftest.py                  # pytest fixtures（測試用 DB / client）
    ├── test_auth.py
    ├── test_users.py
    ├── test_items.py
    └── test_diagnostic_flow.py      # 診斷代理測試（含 mock Anthropic）
```

---

## 3. 環境設定

在專案根目錄 (`fastapi_backend_service/`) 建立 `.env` 檔案：

```bash
# 複製範本（或手動建立）
cp .env.example .env       # 若專案提供範本
```

`.env` 內容範例：

```dotenv
# ── 應用程式 ──────────────────────────────────────────────
APP_NAME=FastAPI Backend Service
APP_VERSION=1.0.0
DEBUG=false
API_V1_PREFIX=/api/v1

# ── 安全性 ────────────────────────────────────────────────
# 請使用 openssl rand -hex 32 產生強度足夠的金鑰
SECRET_KEY=your-secret-key-change-this-in-production
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# ── 資料庫 ────────────────────────────────────────────────
# 開發環境（SQLite，無需額外安裝）
DATABASE_URL=sqlite+aiosqlite:///./dev.db

# 正式環境（PostgreSQL）
# DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/dbname

# ── AI 診斷代理 ───────────────────────────────────────────
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxx

# ── CORS ──────────────────────────────────────────────────
# 正式環境請指定允許的 Origin
ALLOWED_ORIGINS=*

# ── 日誌 ──────────────────────────────────────────────────
LOG_LEVEL=INFO
```

> **安全提醒**
> - `.env` 包含機密資訊，**絕對不要提交到版本控制**。
> - 確保 `.gitignore` 已包含 `.env`。
> - 正式環境請以系統環境變數或 Secret Manager 注入，而非 `.env` 檔案。

---

## 4. 啟動服務

### 4.1 開發模式（熱重載）

```bash
cd fastapi_backend_service
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

啟動成功後，終端機會顯示：

```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

### 4.2 正式模式（多 worker）

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

### 4.3 驗證服務正常運作

```bash
# 健康檢查
curl http://localhost:8000/health
```

預期回應：

```json
{
  "status": "ok",
  "version": "1.0.0",
  "database": "connected",
  "timestamp": "2026-02-28T10:00:00.000Z"
}
```

### 4.4 互動式 API 文件

服務啟動後，瀏覽器開啟以下網址：

| 文件類型 | 網址 |
|----------|------|
| Swagger UI（互動式） | http://localhost:8000/docs |
| ReDoc（閱讀版） | http://localhost:8000/redoc |

---

## 5. 核心 API 操作

所有 API 回應遵循統一格式：

```json
{
  "status": "success",
  "message": "操作說明",
  "data": { ... },
  "error_code": null
}
```

### 5.1 使用者註冊與登入

**建立帳號**

```bash
curl -X POST http://localhost:8000/api/v1/users/ \
  -H "Content-Type: application/json" \
  -d '{
    "username": "alice",
    "email": "alice@example.com",
    "password": "securepassword"
  }'
```

**登入取得 JWT Token**

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=alice&password=securepassword"
```

回應範例：

```json
{
  "status": "success",
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "token_type": "bearer"
  }
}
```

> 後續所有需要認證的請求，都要在 Header 加入：
> `Authorization: Bearer <access_token>`

**查看目前使用者資訊**

```bash
curl http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer <access_token>"
```

### 5.2 Items 管理

```bash
# 建立 Item
curl -X POST http://localhost:8000/api/v1/items/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"title": "我的第一個 Item", "description": "這是描述"}'

# 取得所有 Items（分頁）
curl "http://localhost:8000/api/v1/items/?skip=0&limit=10"

# 取得自己的 Items
curl http://localhost:8000/api/v1/items/me \
  -H "Authorization: Bearer <token>"

# 更新 Item
curl -X PUT http://localhost:8000/api/v1/items/1 \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"title": "更新後的標題"}'

# 刪除 Item
curl -X DELETE http://localhost:8000/api/v1/items/1 \
  -H "Authorization: Bearer <token>"
```

---

## 6. MCP Skill 開發指南

### 6.1 什麼是 Skill？

每個 `Skill` 代表診斷代理可以呼叫的一個工具（Tool）。它必須：

1. 繼承 `BaseMCPSkill`
2. 定義 `name`、`description`、`input_schema`（三個抽象屬性）
3. 實作 `execute()` 非同步方法

`BaseMCPSkill` 會自動提供兩種格式的 JSON Schema：

| 方法 | 用途 | Key 格式 |
|------|------|----------|
| `to_anthropic_tool()` | 傳給 `anthropic.messages.create(tools=[...])` | snake_case `input_schema` |
| `to_mcp_schema()` | 符合 MCP 標準規範 | camelCase `inputSchema` |

### 6.2 新增自訂 Skill（逐步教學）

**步驟一：在 `app/skills/` 建立新檔案**

```python
# app/skills/disk_check.py
from typing import Any
from app.skills.base import BaseMCPSkill

class MockDiskCheckSkill(BaseMCPSkill):
    """查詢指定服務的磁碟使用率。"""

    @property
    def name(self) -> str:
        return "mcp_mock_disk_check"

    @property
    def description(self) -> str:
        return (
            "查詢特定服務主機的磁碟使用率與可用空間。"
            "當使用者描述磁碟空間不足、寫入失敗等問題時，請呼叫此工具。"
        )

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "host": {
                    "type": "string",
                    "description": "主機名稱或 IP，例如 'db-server-01'",
                },
                "path": {
                    "type": "string",
                    "description": "要查詢的掛載路徑，例如 '/data'",
                    "default": "/",
                },
            },
            "required": ["host"],
        }

    async def execute(self, host: str, path: str = "/", **kwargs: Any) -> dict:
        # MVP 階段：回傳模擬資料
        return {
            "host": host,
            "path": path,
            "total_gb": 500.0,
            "used_gb": 423.5,
            "free_gb": 76.5,
            "usage_percent": 84.7,
            "status": "warning",
            "note": "Disk usage above 80% threshold.",
        }
```

**步驟二：在 `app/skills/__init__.py` 中註冊**

```python
# app/skills/__init__.py
from app.skills.disk_check import MockDiskCheckSkill   # ← 新增這行

_ALL_SKILLS: list[BaseMCPSkill] = [
    MockRagKnowledgeSearchSkill(),
    MockCpuCheckSkill(),
    MockDiskCheckSkill(),              # ← 新增這行
    AskUserRecentChangesSkill(),
]
```

完成！重新啟動服務後，診斷代理會自動看到並能使用這個新工具。**不需要修改任何路由或核心邏輯。**

### 6.3 Skill 設計原則

| 原則 | 說明 |
|------|------|
| **描述要精確** | `description` 是 LLM 判斷何時呼叫的唯一依據，務必清楚說明適用情境 |
| **參數要精簡** | 只定義真正必要的輸入，避免讓 LLM 猜測不必要的欄位 |
| **回傳要結構化** | `execute()` 回傳的 dict 會被序列化後傳回 LLM，欄位名稱應具語義 |
| **只讀原則** | MVP 階段的 Skill 絕對不執行任何寫入或副作用操作 |
| **失敗要優雅** | 若執行失敗，回傳包含 `"error"` 欄位的 dict，讓 LLM 可以調整策略 |

### 6.4 現有 Skill 一覽

| Skill Name | 類別 | 觸發情境 |
|------------|------|----------|
| `mcp_rag_knowledge_search` | Type-B 主動 | **永遠優先呼叫**，搜尋已知 SOP |
| `mcp_mock_cpu_check` | Type-B 主動 | 效能問題（慢、卡頓、高負載） |
| `ask_user_recent_changes` | Type-A 被動 | 資訊不足時，向人工操作員提問 |

---

## 7. AI 診斷代理操作

### 7.1 呼叫診斷 API

**端點：** `POST /api/v1/diagnose/`
**認證：** 需要 JWT Bearer Token

```bash
# 取得 token（如尚未登入）
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -d "username=alice&password=securepassword" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['access_token'])")

# 呼叫診斷代理
curl -X POST http://localhost:8000/api/v1/diagnose/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "issue_description": "系統變好慢，API 回應時間從 200ms 暴增到 5 秒，CPU 使用率看起來很高"
  }'
```

### 7.2 回應格式說明

```json
{
  "status": "success",
  "message": "診斷完成",
  "data": {
    "issue_description": "系統變好慢，API 回應時間從 200ms 暴增到 5 秒",
    "tools_invoked": [
      {
        "tool_name": "mcp_rag_knowledge_search",
        "tool_input": { "query": "系統慢 CPU 高使用率" },
        "tool_result": {
          "results_found": 1,
          "documents": [{ "doc_id": "sop-001", "title": "CPU 高使用率排障 SOP", ... }]
        }
      },
      {
        "tool_name": "mcp_mock_cpu_check",
        "tool_input": { "service_name": "api-server" },
        "tool_result": {
          "cpu_usage_percent": 87.3,
          "status": "high_load"
        }
      }
    ],
    "diagnosis_report": "## 問題摘要\n...\n## 建議處置\n...",
    "total_turns": 3
  },
  "error_code": null
}
```

| 欄位 | 說明 |
|------|------|
| `tools_invoked` | Agent 本次依序呼叫的工具清單，包含輸入與輸出 |
| `diagnosis_report` | LLM 產出的 Markdown 格式診斷報告 |
| `total_turns` | Agent Loop 執行的總迴圈次數（含最終總結回合） |

### 7.3 典型 Agent 執行流程

```
使用者輸入
    │
    ▼
[Turn 1] LLM 分析問題
    │── tool_use: mcp_rag_knowledge_search → 搜尋 SOP
    ▼
[Turn 2] LLM 讀取 SOP，決定下一步
    │── tool_use: mcp_mock_cpu_check → 查詢 CPU
    ▼
[Turn 3] LLM 整合所有資料
    │── stop_reason: end_turn
    ▼
Markdown 診斷報告輸出
```

### 7.4 常見診斷問題範例

```bash
# 效能問題
"系統變好慢，使用者反映 API 回應很慢"
"CPU 使用率突然飆升到 90%"

# 詢問使用者情境
"服務今天早上突然異常，不知道發生什麼事"
"最近沒有改什麼，但系統就出問題了"

# 混合問題
"資料庫查詢變慢，而且 CPU 使用率也很高，昨天剛做了部署"
```

---

## 8. 執行測試

### 8.1 執行所有測試

```bash
cd fastapi_backend_service
pytest
```

### 8.2 執行特定測試檔

```bash
# 只測試診斷代理
pytest tests/test_diagnostic_flow.py -v

# 只測試 Auth
pytest tests/test_auth.py -v
```

### 8.3 執行含覆蓋率報告

```bash
pytest --cov=app --cov-report=term-missing
```

### 8.4 測試架構說明

所有測試使用 **函式作用域的獨立 in-memory SQLite**，測試間完全隔離。

診斷代理測試中的 Anthropic API 呼叫使用 `unittest.mock` 完整 mock，**不需要真實 API Key** 也能執行。

```
tests/
├── conftest.py              → 測試資料庫、HTTP client、JWT fixtures
├── test_auth.py             → 7  個測試（登入、token 驗證）
├── test_users.py            → 13 個測試（CRUD、權限控管）
├── test_items.py            → 15 個測試（CRUD、所有權驗證）
└── test_diagnostic_flow.py  → 28 個測試（Skill 契約、Agent Loop、HTTP 端點）
                                ─────
                               63 個測試（全部通過）
```

---

## 9. 資料庫遷移 (Alembic)

### 9.1 初始化（第一次使用）

開發環境啟動時會自動呼叫 `init_db()` 建立所有資料表，無需手動執行。

正式環境請使用 Alembic：

```bash
# 套用所有待執行的 migration
alembic upgrade head
```

### 9.2 新增資料表遷移

當你修改了 ORM Model 後：

```bash
# 自動產生 migration 腳本
alembic revision --autogenerate -m "add_new_column_to_items"

# 檢查生成的腳本（路徑會顯示在輸出中）
# 確認內容正確後套用
alembic upgrade head
```

### 9.3 回滾

```bash
# 回滾一個版本
alembic downgrade -1

# 回滾到指定版本
alembic downgrade <revision_id>
```

---

## 10. 常見問題排除

### Q1：啟動時出現 `ModuleNotFoundError: No module named 'pydantic_settings'`

```bash
pip install pydantic-settings==2.1.0
```

### Q2：測試時出現 `AttributeError: module 'bcrypt' has no attribute '__about__'`

`passlib 1.7.4` 與 `bcrypt >= 4.0.0` 不相容，需固定版本：

```bash
pip install "bcrypt==3.2.2"
```

### Q3：診斷 API 回傳 `500` 且日誌顯示 `AuthenticationError`

Anthropic API Key 未設定或無效。請確認：

1. `.env` 中 `ANTHROPIC_API_KEY` 已正確填入。
2. 金鑰有足夠的 API 額度。
3. 重新啟動服務（`.env` 變更需要重啟才能生效）。

### Q4：新增 Skill 後 LLM 沒有呼叫到它

1. 確認已在 `app/skills/__init__.py` 的 `_ALL_SKILLS` 列表中加入實例。
2. 確認 `description` 的內容清楚描述了**何時應該呼叫**。
3. 重新啟動服務（Python 模組在啟動時載入）。

### Q5：`pytest` 測試出現 `UNIQUE constraint failed`

確認 `conftest.py` 中的 `engine` fixture 沒有加上 `scope="session"`，正確設定為函式作用域（預設，不填 scope）。

### Q6：如何增加 Agent Loop 的最大迴圈次數？

在 `app/routers/diagnostic.py` 中修改 `DiagnosticService` 的實例化：

```python
service = DiagnosticService(max_turns=20)  # 預設為 10
```

---

## 11. Glass Box 前端介面操作

### 11.1 開啟介面

服務啟動後，用瀏覽器開啟：

```
http://localhost:8000/
```

即可看到 Glass Box 診斷介面的登入畫面。

### 11.2 登入

**方法 A：使用帳號密碼**

1. 在「用戶名」欄位輸入帳號（預設測試帳號：`admin`）
2. 在「密碼」欄位輸入密碼
3. 點擊「登入」按鈕

**方法 B：直接貼上 JWT Token**

若已持有 Token（例如從 Swagger UI 取得），可點擊「使用 Token 登入」，直接貼入 Token 字串。

### 11.3 介面總覽

登入後進入 **診斷站（預設首頁）**，左側為深色圖示 Sidebar，可切換以下頁面：

| 圖示 | 頁面 | 說明 |
|------|------|------|
| 🔬 | **診斷站** | Copilot 對話 + 事件觸發診斷（預設首頁） |
| ⊞ | 戰情指揮中心 | 全局 KPI、排程監控、24H 執行軌跡 |
| ◫ | 巢狀建構器 | L1（任務）→ L2（Skill）→ L3（MCP）全流程設定 |
| 🗄 | Data Subjects | 資料來源管理 |
| ⚙ | MCP Builder | MCP 定義管理（全頁編輯器） |
| 📋 | Skill Builder | Skill 定義管理（全頁編輯器） |
| ⚡ | Event Types | 事件類型管理 |
| 🔔 | 自動生成警報 | 巡檢觸發的異常事件列表 |
| ≡ | 系統參數 | 系統設定 |
| ❓ | 說明助手 | AI 助手（側滑浮動面板） |

### 11.4 診斷站操作

```
┌── Sidebar ──┬──── 對話區 (30%) ────────────┬──── 報告區 (70%) ─────────────────┐
│  🔬 ← 當前  │  [對話歷史]                   │  [分析頁籤列]                      │
│  ⊞          │                               │  ┌────────────────────────────┐   │
│  ◫          │  ⚡ 模擬觸發按鈕              │  │  診斷報告 / MCP 查詢結果   │   │
│  …          │                               │  │  圖表 / 表格 / 原始資料    │   │
│             │  [輸入框]       [→ 送出]      │  └────────────────────────────┘   │
│             │  Ctrl+Enter 送出              ├────────────────────────────────────┤
│             │                               │  ▌ Agent Console (深色底部面板)   │
│             │                               │  00:01:23 → 使用者：查詢 APC...   │
│             │                               │  00:01:24 🤔 Agent 思考中…        │
│             │                               │  00:01:26 🔧 MCP 查詢完成         │
└─────────────┴───────────────────────────────┴────────────────────────────────────┘
```

**對話操作**：
1. 在輸入框描述問題，例如：`查詢 CD chart 的 SPC 趨勢`
2. 或輸入 `/` 呼叫 Slash Command Menu，直接選擇 MCP / Skill 工具
3. 按 **Ctrl+Enter** 或點擊送出按鈕

**事件觸發診斷**：點擊 ⚡ 快速觸發按鈕模擬 `TETCH01 PM2 發生 SPC OOC` 事件，系統自動執行所有綁定 Skill 並串流輸出結果。

**Agent Console**（右下角深色面板）：
- 自動在 Agent 第一個動作時展開
- 顯示時間戳 + 圖示標記的執行記錄（思考、MCP 呼叫、Skill 結果、錯誤）
- 點擊 `▲/▼` 折疊/展開；點擊 `clear` 清空記錄

### 11.5 Skill Builder 操作

**列表狀態**：顯示所有 Skill 卡片，右上角「新增 Skill」新增。

**編輯狀態**（點擊任一 Skill 卡片進入）：

```
┌── ← Skill 列表 | [Skill 名稱] ────────────────── [💾 儲存] [▶ Try Run] ──┐
├──── 左側設定 (50%) ──────────────────┬──── 右側結果 (50%) ──────────────┤
│  L2 Skill 設定（紫色邊框）           │  [📋 Terminal Logs] [📊 Report]  │
│  · Skill 名稱 / 說明                 │                                  │
│  · 異常判斷條件 (Diagnostic Prompt)  │  執行記錄 / 診斷結果              │
│  · 有問題物件 / 專家建議處置          │  + MCP 佐證圖表                  │
│                                      │                                  │
│  L3 MCP 綁定（翠綠色邊框）           │                                  │
│  · 選擇 MCP / 參數提示               │                                  │
│  · [👁 撈取與預覽樣本]               │                                  │
└──────────────────────────────────────┴──────────────────────────────────┘
```

點擊 **▶ Try Run** 執行完整模擬：撈取 MCP 資料 → 執行 MCP Script → LLM 生成診斷 → 渲染結果。

### 11.6 MCP Builder 操作

**列表狀態**：顯示所有 MCP 卡片，右上角「新增 MCP」新增。

**編輯狀態**（點擊任一 MCP 卡片進入）：

```
┌── ← MCP 列表 | [MCP 名稱] ───────────────────── [💾 儲存] [▶ Try Run] ──┐
├──── 左側設定 (50%) ──────────────────┬──── 右側結果 (50%) ──────────────┤
│  L3 MCP 設定（翠綠色邊框）           │  [📋 Terminal Logs] [📊 Report]  │
│  · MCP 名稱 / Data Subject           │                                  │
│  · 說明 / 加工意圖 (Intent)          │  執行記錄 / 圖表結果              │
│  · [👁 撈取與預覽樣本]               │                                  │
│                                      │                                  │
│  <details> 資料預覽 (Data Review)    │                                  │
│  <details> 格式預覽 (Format Review)  │                                  │
└──────────────────────────────────────┴──────────────────────────────────┘
```

點擊 **▶ Try Run** 執行：撈取 DS 樣本資料 → LLM 生成 Python Script → 沙箱執行 → 渲染圖表。

| 欄位 | 說明 |
|------|------|
| 事件 ID | 唯一識別符，格式 `EVT-XXXXXXXX` |
| 事件類型 | 分類結果（見下表） |
| 緊急程度 | `CRITICAL` / `HIGH` / `MEDIUM` / `LOW` |
| 建議工具 | AI 接下來會依序呼叫的工具 |

**事件分類對照表**

| 關鍵字觸發 | 事件類型 | 緊急程度 |
|------------|----------|----------|
| 慢、CPU、效能、高負載 | `Performance_Degradation` | HIGH |
| 記憶體、OOM、Heap | `Memory_Leak` | HIGH |
| 延遲、Timeout、回應時間 | `High_Latency` | MEDIUM |
| 磁碟、空間不足 | `Disk_Full` | HIGH |
| 掛了、503、無法存取 | `Service_Down` | CRITICAL |
| 部署、上線、Rollback | `Deployment_Issue` | MEDIUM |
| （其他） | `Unknown_Symptom` | LOW |

---

## 附錄：API 端點速查表

| 方法 | 路徑 | 認證 | 說明 |
|------|------|------|------|
| GET  | `/health` | 不需要 | 服務健康檢查 |
| GET  | `/` | 不需要 | Glass Box 前端介面 |
| POST | `/api/v1/auth/login` | 不需要 | 登入取得 JWT |
| GET  | `/api/v1/auth/me` | 需要 | 查看當前使用者 |
| GET  | `/api/v1/users/` | 不需要 | 列出所有使用者（分頁） |
| POST | `/api/v1/users/` | 不需要 | 建立新使用者 |
| GET  | `/api/v1/users/{id}` | 不需要 | 查詢指定使用者 |
| PUT  | `/api/v1/users/{id}` | 需要 | 更新使用者（限本人） |
| DELETE | `/api/v1/users/{id}` | 需要 | 刪除使用者（限本人） |
| GET  | `/api/v1/items/` | 不需要 | 列出所有 Items（分頁） |
| GET  | `/api/v1/items/me` | 需要 | 列出自己的 Items |
| POST | `/api/v1/items/` | 需要 | 建立 Item |
| GET  | `/api/v1/items/{id}` | 不需要 | 查詢指定 Item |
| PUT  | `/api/v1/items/{id}` | 需要 | 更新 Item（限擁有者） |
| DELETE | `/api/v1/items/{id}` | 需要 | 刪除 Item（限擁有者） |
| POST | `/api/v1/diagnose/` | 需要 | 執行 AI 診斷代理（SSE 串流） |
