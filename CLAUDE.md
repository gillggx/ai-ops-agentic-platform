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

Skill 的 `description` 欄位必須清楚說明：
- 這個 Skill 做什麼（用途 + 使用場景）
- 預期的 input（哪些參數、型別）
- 輸出什麼（chart type / table / scalar）
- 判斷邏輯（e.g. 「最近 5 次 process 中 >= 2 次 OOC 則觸發」）
- ⚠️ 與相似 Skill 的區別（e.g. 「這是 APC 參數，不是 Recipe 參數」）

**理由：** Agent 選 Skill 時只看 `name` + `description`。如果 description 模糊，Agent 會選錯 Skill。

### 4. Block Description 也是如此（Pipeline Builder）

Pipeline Builder block 的 `description` / `param_schema` / `examples` 欄位是 **唯一**的 block 文件來源：

- Glass Box agent 建 pipeline 時讀它（既有）
- **Builder Mode Block Advisor**（2026-05-02 新增）回答 user「這個 block 怎麼用 / A vs B / 我該用哪個」也讀它
- BlockDocsDrawer 給 user 看的也是它

如果三邊不一致 = description 過時 = LLM 跟 user 都拿到錯的資訊。改 block 行為 → 一定要同時改 description / param_schema / examples。

---

## Agent Behaviour Principles

### 流程（flow）由 graph 決定，LLM 只做 reasoning

**Hard rule**: 任何「下一步該做什麼 / 該呼叫哪個 tool」的決策**禁止**塞進 LLM system prompt。改寫成 graph node + deterministic dispatch。

**理由**：
- LLM 自由意志會違抗 prompt 規則（已多次證實）
- prompt 寫的 flow 不可單測；graph node 是 pure function 可單測
- 出錯時 graph 知道是哪個 node fail，prompt-flow 只能猜「LLM 又走偏了」

**正確示範**：
- Chat orchestrator 的 `intent_classifier` node → 5 buckets → graph 路由到 llm_call vs synthesis
- Chat orchestrator 的 `intent_completeness` gate → deterministic check → 路由到 clarify vs llm_call
- Builder Glass Box 的 `classify_advisor_intent` → 5 buckets (BUILD/EXPLAIN/COMPARE/RECOMMEND/AMBIGUOUS) → graph 路由到 build vs advisor

**錯誤示範**：
```python
# ❌ 把 flow 塞進 prompt
system_prompt = """
若 user 問 block 用法 → 呼叫 explain_block tool
若 user 想對比 → 呼叫 compare_blocks tool
若 user 想建構 → 直接 add_node
"""
```
LLM 看心情選哪個，且 prompt 改一個字行為就漂移。

**正確做法**：classifier node 先決定 bucket，每 bucket 對應**固定**的後續 node 序列。LLM 在每個 node 內只做思考型工作（分類 / 抽參 / 寫答），不決定下一步。

### 各 surface 的 agent stack 對照

| Surface | Endpoint | Orchestrator | 路由方式 |
|---|---|---|---|
| Chat panel (operations) | `/internal/agent/chat` | `agent_orchestrator_v2` (LangGraph) | `intent_classifier` + `intent_completeness` graph nodes |
| Builder Glass Box (build instruction) | `/internal/agent/build` | `agent_builder.stream_agent_build` (Anthropic loop) | tool-use loop, tools 在 prompt 列出 |
| Builder Block Advisor (Q&A) | `/internal/agent/build` (same endpoint) | `agent_builder.advisor.stream_block_advisor` | `classify_advisor_intent` graph dispatch |

`/internal/agent/build` 入口先跑 `classify_advisor_intent`：BUILD → 既有 Glass Box；非 BUILD → advisor graph。

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

- `deploy/update.sh`：frontend + simulator（會自動 systemctl restart aiops-app + ontology-simulator）
- `deploy/java-update.sh`：Java + sidecar（rebuild jar + venv，restart aiops-java-api + aiops-python-sidecar）
- systemd services：aiops-app (8000), aiops-java-api (8002), aiops-python-sidecar (8050), ontology-simulator (8012)
- ⚠️ `update.sh` 不會重啟 sidecar 跟 Java — 改動 sidecar 或 Java 後要跑 `java-update.sh`
- Frontend 用 `output: "standalone"` 模式

### Database

- PostgreSQL + pgvector（backend）
- MongoDB（simulator）
- Schema changes 用 Alembic migration（但目前用 create_all + seed）
- System MCPs 每次啟動自動 sync（canonical list in main.py）

---

## Architecture Boundaries

```
aiops-app :8000 (Frontend, Next.js standalone)
  → 只做 UI 渲染 + /api/ proxy
  → 不直接呼叫 simulator / sidecar / Java

java-backend :8002 (Spring Boot, sole DB owner)
  → 所有 PostgreSQL 讀寫、auth (JWT)、business CRUD
  → /api/v1/* (user-facing, JWT) + /internal/* (service-to-service, X-Internal-Token)
  → Pipeline registry, skill registry, alarms, role audit

python_ai_sidecar :8050 (LangGraph + Pipeline Executor)
  → Agent 全部住這裡 (chat orchestrator_v2, Glass Box builder, Block Advisor)
  → 27 BUILTIN_EXECUTORS + 18 chart blocks 在 sidecar in-process 跑
  → 透過 JavaAPIClient 與 Java 對話；NEVER 直接連 PostgreSQL

ontology_simulator :8012 (Data Source)
  → 純資料服務，不知道 Agent 的存在
  → API 介面與 production ontology 完全相同

aiops-contract (Shared Types)
  → Agent ↔ Frontend 的共用型別（AIOpsReportContract）
  → 雙語言：TypeScript + Python
```

**Phase 8-A-1d cutover (2026-04-25)**：fastapi_backend_service (:8001) decommissioned，所有路徑走 Java + sidecar。`fastapi_backend_service/` 目錄還在 repo 但 runtime 不啟動。
