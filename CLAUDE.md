# AIOps Platform — Development Guidelines

## Core Principles

### 0. 禁止把 case-specific rule 塞進 LLM prompt（最高優先）

**症狀**：trace 顯示某 case 失敗 → 直接在 prompt 加「禁列 mean/std/Q1」「box_plot 內建 stats」「『偵測』+ chart 不該拆 scalar」這種規則。

**問題**：
- 每個 fix 只蓋一個 case；換語言（中文 → 英文）、換 keyword（「中位數」「median」）、換組合（「偵測」→「找出」）就 bypass
- prompt 變一份不斷膨脹的 case 清單，無人維護、互相打架
- 違反 [feedback_flow_in_graph_not_prompt.md](memory)：flow control 寫 graph node，不寫 prompt

**正確做法**：trace 失敗 → 問**根因原則**是什麼，不是「再加一條 rule」。可選擇：
1. 把 case 抽象成**一句原則**寫進 prompt（例：「value_desc 用業務語意，不寫結構規格」），不列舉具體案例
2. 移到 graph node 做 deterministic 檢查 / 後處理（例 `_maybe_inject_chart_phase`）
3. 改 schema / state design（例 block.meta 加 `self_contained` flag）

**簽收檢核**：每次想在 prompt 加規則前，自問「我這條規則會不會 6 個月後又被一個新 case 變形繞過？」如果是，請改架構。

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

### 5. V54 衍生 Block / Skill（mcp_auto，2026-06-03 上線）

當 System MCP 在 admin form 勾選「連動產生 Data Block / Skill」時，Java 會原子寫入：
- `mcp_definitions.produces_block = true` / `produces_skill = true`
- `pb_blocks` row：`source='mcp_auto'`，`source_mcp_id=<mcp.id>`，
  `implementation = {"type": "mcp_proxy", "mcp_name": "<name>", "delegate_block": "block_mcp_call"}`
- `pb_pipelines` row：單 block DAG
- `pb_published_skills` row：`source='mcp_auto'`，`source_mcp_id=<mcp.id>`

執行端：sidecar 的 `BlockRegistry` 看到 `implementation.type == "mcp_proxy"` 時，
自動 bind `McpProxyBlockExecutor`（吃 block spec 裡的 `mcp_name`，內部走跟
`block_mcp_call` 一樣的 dispatch path）。

**Critical rules:**
- LLM 生成的 block / skill **永遠當草稿** — user 必須在 form 內 review + 編輯後才 commit。
- MCP description 改了之後 **不會** 自動 regenerate；UI 顯示 stale warning，user 手動觸發。
- LLM 用 `claude-haiku-4-5-20251001`（hardcoded for cost）；可由 env
  `MCP_DERIVATIVE_LLM_MODEL` override 但 production 不該。
- 生成 prompt 必須是 **principles**（不列 case rules）。修改 `mcp_derivative/generator.py:_build_system_prompt` 時 bump `PROMPT_VERSION`，audit metadata 才正確。
- Frontend lint 與 sidecar lint 兩邊都跑 — sidecar 是 source of truth（前端可繞）。
- 刪 MCP 時 FK ON DELETE SET NULL — 衍生 block / skill 不會被刪（避免誤刪 user 已調整的內容），
  UI 顯示 detached 提示。

---

## Spec 產出規範（2026-07-06）

出任何 Tech/Product Spec **必須**遵循 `.claude/skills/spec-template`（兩層式）：
第一層 feature-first 對齊稿（無技術名詞、含 before→after 情境與 user 可自驗的
驗收欄），user 對齊後才展開第二層實作細項。交付時逐條回報第一層驗收欄。

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
| Chat panel / ChatOps (operations) | `/internal/agent/chat` | **Coordinator** = `chat_agent_loop`（Anthropic tool-use loop，`CHAT_AGENT_LOOP_ENABLED=1` prod ON；舊 LangGraph classifier 為 fallback） | prompt 只有人設 + 少數硬規則（核心路由：建圖→plan_pipeline／改圖→modify／查資料→查詢工具）；其餘知識在標準 Skill |
| Builder Glass Box (build instruction) | `/internal/agent/build` | `agent_builder.stream_agent_build` (Anthropic loop) | tool-use loop, tools 在 prompt 列出 |
| Builder Block Advisor (Q&A) | `/internal/agent/build` (same endpoint) | `agent_builder.advisor.stream_block_advisor` | `classify_advisor_intent` graph dispatch |

`/internal/agent/build` 入口先跑 `classify_advisor_intent`：BUILD → 既有 Glass Box；非 BUILD → advisor graph。
Agent 套件邊界（Wave 2）：`python_ai_sidecar/agents/{coordinator,planner,builder,supervisor}` 是唯一公開 import 面，鐵律見 `agents/README.md`。

### 標準 Skill（2026-07-10 起，術語鎖定）

- **Skill = 標準 Skill**：一份具名說明書（`agent_skills` 表，`/admin/agent-skills` GUI 可編），教 Coordinator「怎麼做某類事」。
  `when_to_use` 注入系統提示目錄；全文由 `load_skill` 工具按需載入。**Domain Skill** = pipeline+automation（skills_v2），要特別講才是。
- 「怎麼做事」的知識一律放標準 Skill 或工具 description，**不放 prompt**；prompt 只留人設 + 核心路由硬規則。
- 強制閘門（寫入必過確認卡、patrol 需 verdict、resolve=ADMIN/PE）在 **code** 強制——Skill 只教，code 保底。
- Coordinator 的能力面：granted builtin（含 alarm 讀寫）+ granted external System MCP（**2026-07-10 決策：有標準 Skill 說明書的
  System MCP 可直呼**，registry external kind 可授權對內，參數文件取自 mcp_definitions）+ invoke_skill（Domain Skill 預設可用，支援 params）。
- Coordinator 的所有寫入走瀏覽器端確認卡（使用者 JWT 執行）：`alarm_action_confirm`／`skill_activate_confirm`／`skill_admin_confirm`／`automation_handoff`。
- 工具結果在 loop 層有 30K 字元硬上限（防 3.5MB 結果炸 context）。

---

## Coding Standards

### Backend (Python / FastAPI sidecar)

- 遵循 Repository → Service → Router 分層
- Async first（所有 DB 和 HTTP 操作用 async）
- Error handling：不靜默吞 exception，log + 回傳有意義的錯誤
- Event Poller 跑在 `asyncio.ensure_future`（lifespan 內），不用 APScheduler 或 thread

### Backend (Java / Spring Boot — canonical backend post-Phase-8 cutover)

After the Phase 12 OOP refactor (PR #5, 2026-05-24) the Java tier follows
**thin controller + focused service** consistently. New endpoints / services
should adopt the same pattern:

- **Controller**: HTTP only — `@PreAuthorize` + parameter binding + DTO map
  + delegate to service in 1-2 lines. No entity manipulation, no validation
  logic, no `try/catch` of business exceptions. SSE wiring stays via
  {@link com.aiops.api.common.SseEmitterBridge}.
- **Service**: `@Service` bean — owns validation, entity ops, JSON serdes,
  cross-entity transactions, sidecar calls. Throw `ApiException` for
  client-facing errors; let `@ControllerAdvice` map to HTTP status.
- **Repository**: only the service tier touches it. Controllers never
  inject repositories directly (exception: legacy aliases where the
  passthrough is genuinely 1 line and a service indirection would be
  ceremony — judge per case).

**Use the shared common helpers — never re-implement**:
- `JsonUtils.parseObject(mapper, json)` / `parseListOfObjects` /
  `safeWrite` / `asMap` — null/blank/parse-fail-fallback Jackson.
- `SseEmitterBridge.bridge(flux, tag)` — reactive `Flux<ServerSentEvent>`
  → MVC `SseEmitter`. Used by AgentProxy + Briefing + SkillDocument.
- `RequestBodyAccess.pickAlias(body, "snake_case", "camelCase")` /
  `requireAlias` — for endpoints accepting both alias families.

**Exception handling**: never `catch (Exception)` — narrow to the actual
type. Convention (per P1, 52 → 0):
- `JsonProcessingException` for `mapper.read/write`
- `DateTimeParseException` for ISO parse fallback chains
- `NumberFormatException` for `Long/Double.parseLong/parseDouble`
- `RuntimeException` for reactor `block()` / JPA `save()` / fail-open guards
  (catches unchecked but lets checked exceptions bubble — signals intent)

**Wire format**: JSON properties are **snake_case** on the wire (Jackson
config). camelCase keys are silent-ignored — call sites that send camelCase
look fine (HTTP 200) but produce nulls. See memory
`feedback_jackson_snake_case_wire`.

**Tests**: pure Mockito (no Spring context, fast). Pattern:
`SkillAlarmEmitterTest`. Run subset via
`mvn -Dtest=ClassA,ClassB test` (comma-separated, not `+`).

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
- Schema changes 用 Flyway migration (`java-backend/src/main/resources/db/migration/V*.sql`)
  ⚠️ **Flyway is disabled in prod** — new V**.sql must be applied via manual
  `psql -f` on EC2. See memory `feedback_flyway_disabled_in_prod`.
- System MCPs 每次啟動自動 sync（canonical list in main.py）

#### pgvector columns (`embedding vector(N)`)

JPA binds `String` parameters as VARCHAR; PostgreSQL refuses the implicit
varchar → vector cast. **Never write the embedding via JPA `save()` or
`entity.setEmbedding(...)`** — both fail with SQL 42804.

Use the established pattern (per fix `e03020d`):
- Entity field: `@Column(insertable=false, updatable=false, columnDefinition="vector(N)")`
  so JPA INSERT/UPDATE omits the column entirely.
- Writes: native `@Query` with `CAST(:vec AS vector)`. See
  `AgentKnowledgeRepository.updateEmbedding` + `clearEmbedding` as the
  reference shape.
- Reads: JPA SELECTs the column via field reflection — `getEmbedding()`
  still works for retrieval.

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

---

## Deployment Targets (EC2 today, K8s future)

### Stack versions (must stay consistent across pom.xml / Dockerfile / README / deploy scripts)
- Java: **Temurin 17**（不是 21，2026-05-14 修了 java-update.sh 殘留）
- Spring Boot: **3.5.14** + Maven (不是 Gradle)
- Python: **3.11**
- Node.js: **20.18**

DevOps spec source of truth: `docs/devOps_technique_guide_2.0.md`

### Port convention — env-driven, no source hardcode

**EC2 prod (current, single-host systemd)** — distinct ports per service：
- aiops-app: 8000
- aiops-java-api: 8002
- python_ai_sidecar: 8050
- ontology-simulator: 8012

**K8s (future)** — 每 service 各自 Docker image，container `EXPOSE 8080`，service port → 80，service-name 互通。

**Rule（兩 env 都適用）**：URLs/ports 從 `.env` / ConfigMap 讀，**禁止** source code hardcode `http://localhost:PORT`。可接受的 fallback pattern：
```python
url = os.environ.get("XXX_URL", "http://localhost:80NN").rstrip("/")
```
```typescript
const BASE = process.env.XXX_BASE_URL ?? "http://localhost:80NN";
```

### Run wrappers
- EC2: `deploy/aiops-*.service` (systemd units) + `deploy/update.sh` / `java-update.sh`
- K8s（待做）: 每 service 一個 `deploy/<service>-run.sh` while-true loop 包裝。等 K8s target env (GKE/EKS/自建) 確定才寫。
