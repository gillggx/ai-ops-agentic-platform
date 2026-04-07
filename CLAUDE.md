# AIOps Platform — Development Guidelines

## Core Principles

### 1. MCP / Skill 的 Description 是唯一的文件來源

**LLM prompt 禁止 hardcode MCP 的使用說明、參數範例、回傳格式。**

所有 LLM（Agent orchestrator、Skill generator、MCP builder）需要了解 MCP 或 Skill 時，必須從 DB 動態讀取：
- `mcp_definitions.description` — 用途、使用場景、回傳欄位說明
- `mcp_definitions.input_schema` — 參數定義（name, type, required, description）
- `skill_definitions.description` — Skill 用途
- `skill_definitions.input_schema` / `output_schema` — IO 定義

**理由：** 如果 MCP 的行為改了但 prompt 的 hardcode 沒跟著改，LLM 會產生錯誤的 code。單一來源（DB）才能保證一致性。

**錯誤示範：**
```python
# ❌ 在 prompt 裡 hardcode MCP 用法
prompt = """
- get_process_history params: toolID(opt), lotID(opt)
  回傳: [{eventTime, lotID, toolID, step, spc_status}]
"""
```

**正確做法：**
```python
# ✅ 從 DB 讀取
mcps = await mcp_repo.get_all_by_type("system")
catalog = format_for_llm(mcps)  # 從 name + description + input_schema 組裝
```

### 2. MCP Description 必須自帶完整文件

每個 System MCP 的 `description` 欄位必須包含：
- 用途（什麼時候用）
- 回傳欄位名稱和型別
- 關鍵欄位的語義（e.g. `spc_status: 'PASS' | 'OOC'`，不是 `status`）
- 常見誤用警告（如果有）

這不是「好 practice」，這是**強制要求** — 因為 LLM 只看得到 description，看不到 source code。

### 3. Skill Description 也是如此

Skill 的 `auto_check_description` 欄位必須清楚說明：
- 這個 Skill 檢查什麼
- 預期的 input（event_payload 帶什麼欄位）
- 判斷邏輯（e.g. 「最近 5 次 process 中 >= 2 次 OOC 則觸發」）

---

## Coding Standards

### Backend (Python / FastAPI)

- 遵循 Repository → Service → Router 分層
- Async first（所有 DB 和 HTTP 操作用 async）
- Error handling：不靜默吞 exception，log + 回傳有意義的錯誤
- Event Poller 跑在 `asyncio.ensure_future`（lifespan 內），不用 APScheduler 或 thread

### Frontend (TypeScript / Next.js)

- App Router (not Pages Router)
- API routes 只做 proxy（不放業務邏輯）
- 所有 backend 互動走 `/api/` proxy routes
- Inline styles（目前不用 CSS modules / Tailwind）

### Deploy

- `deploy/update.sh` 是唯一的 deploy 入口
- systemd services：aiops-app (8000), fastapi-backend (8001), ontology-simulator (8012)
- Frontend 用 `output: "standalone"` 模式
- Single worker for backend（background tasks 需要）

### Database

- PostgreSQL + pgvector（backend）
- MongoDB（simulator）
- Schema changes 用 Alembic migration（但目前用 create_all + seed）
- System MCPs 每次啟動自動 sync（canonical list in main.py）

---

## Architecture Boundaries

```
aiops-app (Frontend)
  → 只做 UI 渲染 + API proxy
  → 不直接呼叫 simulator

fastapi_backend_service (Backend + Agent)
  → 所有業務邏輯在這裡
  → Agent 模組未來可拆分（orchestrator_v2/, context_loader, tool_dispatcher）

ontology_simulator (Data Source)
  → 純資料服務，不知道 Agent 的存在
  → API 介面與 production ontology 完全相同

aiops-contract (Shared Types)
  → Agent ↔ Frontend 的共用型別（AIOpsReportContract）
  → 雙語言：TypeScript + Python
```
