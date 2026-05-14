# SPEC — Hybrid Java + Python 後端架構

> **狀態：** Draft（僅作規劃，尚未核准開工）
> **建立日期：** 2026-04-18
> **適用範圍：** `fastapi_backend_service` 的部分 Java 化移植
> **前置評估：** 見對話紀錄「後端 Python → Java 移植可行性評估」，本 Spec 承接方案 B（Hybrid）

---

## 1. Context & Objective

### 1.1 背景
現行後端 `fastapi_backend_service` 為純 Python（FastAPI + SQLAlchemy async），共 222 檔 / ~43,547 行。全部改寫為 Java 成本過高（18–21 人月），且會削弱 LLM Code Generation 的核心競爭力（pandas / exec / LangGraph 的 Python 依賴）。

### 1.2 目標
將**無狀態、CRUD 導向、效能敏感**的部分以 Java（Spring Boot）實作，作為前端的主要 API Gateway；**Agent / Sandbox / 資料科學工具**等高度依賴 Python 生態的部分，封裝成獨立 Python sidecar service（gRPC / HTTP）。

### 1.3 非目標（Out of Scope）
- ❌ 不在本 Spec 內重寫 Agent Orchestrator（永久保留 Python）
- ❌ 不更動 `ontology_simulator`（已是獨立服務）
- ❌ 不處理前端（`aiops-app`）改動
- ❌ 不處理 DB schema 遷移（沿用同一份 PostgreSQL）

### 1.4 預期收益
| 項目 | 現況 | 預期 |
|---|---|---|
| CRUD API p99 延遲 | ~80ms | ~25ms（JVM JIT + connection pool 優化） |
| 單機 QPS（CRUD 類） | ~400 | ~1,500（無 GIL 限制） |
| Java 團隊可接手維運 | ❌ | ✅（Router + Repository 層） |
| Agent 核心迭代速度 | 不變 | 不變（保留 Python） |

---

## 2. Architecture & Design

### 2.1 服務拆分圖

```
┌─────────────────────────────────────────────────────────────┐
│                  aiops-app (Next.js Frontend)               │
│                    /api/* proxy routes                      │
└──────────────────────┬──────────────────────────────────────┘
                       │ HTTP
                       ▼
┌─────────────────────────────────────────────────────────────┐
│        ★ aiops-java-gateway (Spring Boot 3 + WebFlux)        │
│        Port: 8001 (取代現行 fastapi-backend)                │
│                                                             │
│   ✅ 承擔職責：                                              │
│   - 所有 Router (40+) — CRUD、Auth、User、Alarm、Skill 管理   │
│   - Repository (15) — PostgreSQL CRUD (R2DBC)                │
│   - Pydantic Schema (21) → Java DTO + Bean Validation        │
│   - JWT / Session 認證                                       │
│   - Rate limiting、Metrics、Health check                     │
│   - Event Poller / APScheduler 等定時任務                    │
│   - NATS subscriber（若啟用）                                │
└──────────┬──────────────────────────────────────┬───────────┘
           │                                      │
           │ gRPC / HTTP                          │ 直連 DB
           │ (internal only, localhost)           │
           ▼                                      ▼
┌─────────────────────────────┐      ┌─────────────────────────┐
│  ★ aiops-agent-python       │      │   PostgreSQL + pgvector │
│    (FastAPI, Port 8002)     │      │     (共用同一實例)       │
│                             │      └─────────────────────────┘
│  ✅ 承擔職責：                │
│  - agent_orchestrator_v2    │      ┌─────────────────────────┐
│  - mcp_builder_service      │ ───▶ │  ontology_simulator     │
│  - mcp_definition_service   │      │  (Port 8012, 不變)      │
│  - sandbox_service (exec)   │      └─────────────────────────┘
│  - skill_executor_service   │
│  - generic_tools (pandas)   │      ┌─────────────────────────┐
│  - analysis_library         │ ───▶ │  Anthropic / OpenAI API │
│  - copilot_service          │      └─────────────────────────┘
│  - data_profile / distill   │
│  - LangGraph StateGraph     │
│  - mem0ai 記憶              │
└─────────────────────────────┘
```

### 2.2 切分原則（判定矩陣）

| 判準 | 留在 Python | 搬到 Java |
|---|---|---|
| 呼叫 LLM API 做決策 | ✅ | ❌ |
| 用到 pandas / numpy / scipy | ✅ | ❌ |
| 呼叫 `exec()` / dynamic import | ✅ | ❌ |
| 依賴 LangGraph / mem0ai | ✅ | ❌ |
| 純 PostgreSQL CRUD | ❌ | ✅ |
| 用戶認證 / JWT / Session | ❌ | ✅ |
| Event bus 訂閱 / 轉發 | ❌ | ✅ |
| 排程 / Cron | ❌ | ✅ |

### 2.3 模組切分清單（逐檔對照）

**搬到 Java（Spring Boot）：**
```
app/routers/
  ├─ auth.py             → AuthController.java
  ├─ user.py             → UserController.java
  ├─ alarm.py            → AlarmController.java
  ├─ event_mapping.py    → EventMappingController.java
  ├─ event_type.py       → EventTypeController.java
  ├─ data_subject.py     → DataSubjectController.java
  ├─ diagnostic_rule.py  → DiagnosticRuleController.java (CRUD only)
  ├─ skill_definition.py → SkillDefinitionController.java (CRUD only)
  ├─ mcp_definition.py   → MCPDefinitionController.java (CRUD only)
  └─ ... (約 30 個純 CRUD router)

app/repositories/*        → src/main/java/.../repository/ (R2DBC)
app/models/*              → src/main/java/.../entity/
app/schemas/*             → src/main/java/.../dto/
app/services/
  ├─ auth_service.py        → AuthService.java
  ├─ user_service.py        → UserService.java
  ├─ alarm_service.py       → AlarmService.java
  ├─ event_poller_service.py→ EventPollerService.java (Spring @Scheduled)
  ├─ cron_scheduler_service → CronSchedulerService.java (Quartz)
  └─ nats_subscriber_service→ NatsSubscriber.java
```

**保留在 Python（新 service `aiops-agent-python`）：**
```
app/services/agent_orchestrator_v2/    ← 全部
app/services/mcp_builder_service.py    ← 全部
app/services/mcp_definition_service.py ← 執行邏輯部分（CRUD 移 Java）
app/services/sandbox_service.py        ← 全部
app/services/skill_executor_service.py ← 全部
app/services/copilot_service.py        ← 全部
app/services/analysis_library.py       ← 全部
app/services/data_distillation_service.py
app/services/data_profile_service.py
app/services/experience_memory_service.py
app/services/context_builder_service.py
app/services/agent_memory_service.py
app/generic_tools/                     ← 全部（pandas/matplotlib）
```

### 2.4 跨服務通訊協定

**選定方案：HTTP + JSON（gRPC 為後期優化）**

理由：
- gRPC 需定義 `.proto`，維護成本高
- 初期走 HTTP，內部網路 latency < 2ms 可接受
- 所有 payload 以 `aiops-contract` 作為 single source of truth（擴充 Java 綁定）

**Java → Python 的呼叫點（預估約 8–10 個端點）：**
```
POST /internal/agent/run              # 執行 Agent 推理
POST /internal/agent/stream           # Streaming 模式（SSE）
POST /internal/mcp/build              # 產生 MCP
POST /internal/mcp/execute            # 執行 MCP
POST /internal/skill/execute          # 執行 Skill
POST /internal/copilot/chat           # Copilot 對話
POST /internal/analysis/profile       # 資料 profile
POST /internal/analysis/distill       # 資料 distillation
GET  /internal/agent/status/{task_id} # 任務狀態
```

**Python → Java 的呼叫點：**
- Python service 不直接呼叫 Java，而是**共用同一個 PostgreSQL**（只讀 + 寫 agent 結果表）
- 若有事件要通知，走 NATS 或 DB trigger

### 2.5 共用合約（aiops-contract 擴充）

現行：`TypeScript + Python`
新增：`Java`

```
aiops-contract/
├─ ts/         # 既有
├─ python/     # 既有
└─ java/       # 新增 — 用 Maven 發佈至 internal repo
    └─ AIOpsReportContract.java (Jackson + @Validated)
```

生成方式：**手動維護** + 用 JSON Schema 驗證三端一致性（`aiops-contract/schema.json` 為 source of truth）。

### 2.6 資料庫策略

**決策：共用同一個 PostgreSQL 實例、同一 schema。**

| 表群 | Java 寫 | Python 寫 | 備註 |
|---|---|---|---|
| `users`, `sessions`, `alarms`, `event_*`, `data_subjects` | ✅ | - | Java 獨佔 |
| `mcp_definitions`, `skill_definitions`, `diagnostic_rules`（metadata） | ✅ (CRUD) | ✅ (執行結果回寫) | 雙寫，要加樂觀鎖或 version 欄 |
| `agent_runs`, `agent_checkpoints`, `agent_memory`, `conversation_history` | - | ✅ | Python 獨佔 |
| `experience_memory`, `pgvector` 表 | - | ✅ | Python 獨佔（pgvector-java 不成熟） |

**衝突風險：** `mcp_definitions` / `skill_definitions` 雙寫 → 加 `updated_at` + `version` 欄位，Java 更新時檢查 version，避免覆蓋 Python runtime 回寫的 `last_execution_status`。

### 2.7 部署拓撲

```
systemd services:
├─ aiops-app.service           (Node.js, :3000)         ← 不變
├─ aiops-java-gateway.service  (Java 21 + Spring, :8001) ★ 新增
├─ aiops-agent-python.service  (Python + FastAPI, :8002) ★ 新增（原 :8001 降級）
└─ ontology-simulator.service  (Python, :8012)           ← 不變
```

**Deploy 流程調整：** `deploy/update.sh` 需同時處理兩個後端服務的版本同步。

---

## 3. Step-by-Step Execution Plan

### Phase 0 — PoC 驗證（2 週，1 人）
- [ ] 建立 Spring Boot 3 + WebFlux + R2DBC 骨架
- [ ] 實作 1 個 CRUD endpoint（例：`GET /users`）連接現有 PostgreSQL
- [ ] 驗證 pgvector 表能正常讀（即使不寫）
- [ ] 實作 Java → Python 呼叫範例（呼叫一個假的 `/internal/agent/run`）
- [ ] 驗證 `aiops-contract` 三端型別一致性
- **Go/No-Go 判準：** PoC 延遲 < 30ms、無 connection pool 問題

### Phase 1 — 骨架 + 認證層（3 週，1–2 人）
- [ ] Spring Security + JWT 整合
- [ ] Session 管理（Redis 或 DB）
- [ ] 全域 Exception Handler + Error Response
- [ ] Logging + Metrics（Micrometer + Prometheus）
- [ ] Health check + Readiness probe
- [ ] Dockerfile + systemd unit file
- [ ] 搬移 `auth.py`, `user.py` router

### Phase 2 — 核心 CRUD Router 搬移（6 週，2 人）
- [ ] Batch 1：User / Auth / Alarm / Session（2 週）
- [ ] Batch 2：Event Mapping / Event Type / Data Subject（2 週）
- [ ] Batch 3：Skill / MCP / Diagnostic Rule 的 CRUD 部分（2 週）
- 每 batch 結束執行回歸測試（前端手動 + 17 個 test cases）

### Phase 3 — Python sidecar 改造（3 週，1 人）
- [ ] 抽出 Agent 相關 service 到新 FastAPI app（`aiops-agent-python`）
- [ ] 定義 `/internal/*` 路由（不對外曝光）
- [ ] 移除舊 Python backend 的 CRUD router（避免雙入口）
- [ ] 調整 `main.py` 只啟動 Agent-related lifespan tasks

### Phase 4 — 排程與事件（2 週，1 人）
- [ ] Event Poller 遷移到 Java（`@Scheduled`）
- [ ] Cron scheduler 遷移到 Java（Quartz 或 Spring Scheduling）
- [ ] NATS subscriber 遷移（若啟用）

### Phase 5 — 整合測試 + 切流（2 週，2 人）
- [ ] 前端所有 `/api/*` proxy 指向新 Java gateway
- [ ] 壓力測試 + 效能比對
- [ ] Canary 切流（10% → 50% → 100%）
- [ ] 正式下線舊 Python backend 的 CRUD 部分

### 總工時估算
- **約 18 週 / 4.5 個月曆時間（2 人團隊）**
- **約 7–8 人月工作量**
- 比起全量改寫（18+ 人月）節省 **60%** 成本

---

## 4. Edge Cases & Risks

### 4.1 技術風險

| # | 風險 | 機率 | 影響 | 緩解策略 |
|---|---|---|---|---|
| R1 | R2DBC + pgvector 相容性問題 | 中 | 中 | Phase 0 PoC 驗證；必要時改用 JDBC + Virtual Threads |
| R2 | Java ↔ Python 雙寫 race condition | 中 | 高 | 加 `version` 欄位 + 樂觀鎖；critical 表由單邊獨佔 |
| R3 | `aiops-contract` 三端不同步 | 高 | 中 | 以 JSON Schema 為 SSOT + CI 驗證 |
| R4 | Java 服務重啟導致 session 失效 | 中 | 低 | Session 存 Redis 或 DB（非 in-memory） |
| R5 | Python 服務 OOM（pandas 吃記憶體）拖垮 Java | 低 | 高 | 資源隔離（systemd cgroup）+ circuit breaker |
| R6 | 兩套後端 log 難追蹤 | 高 | 中 | 統一 correlation ID（X-Trace-Id）貫穿兩端 |

### 4.2 組織風險

| # | 風險 | 緩解策略 |
|---|---|---|
| O1 | 團隊同時要維護 Java + Python 兩套技能 | 明確分工：Java team 負責 gateway、Python team 負責 agent |
| O2 | 切分界線長期可能被破壞（Java 偷偷呼叫 LLM） | 在 CLAUDE.md 和 code review 明確禁止 |
| O3 | 新功能開發時爭論「該放哪邊」 | 以 §2.2 判定矩陣作為 tie-breaker |

### 4.3 邊界情境

- **Agent streaming 回應：** Java gateway 必須 proxy SSE stream，不能 buffer 整包回應。使用 WebFlux `Flux<ServerSentEvent>`。
- **檔案上傳：** 大檔案（資料集）直接上傳到 Python service，Java 只回傳 presigned URL 或 redirect。
- **Long-running agent task：** 改走非同步模式（202 Accepted + task_id）。Java gateway 提交任務後立即回 client，client 輪詢或訂閱 SSE。
- **DB migration：** 初期仍由 Python 端 Alembic 管理；Java 端只做 schema 讀取，不擁有 migration。

### 4.4 Rollback 計畫
每個 Phase 都可獨立 rollback：
- Phase 2–4 都是**新增**新路由，舊 Python backend 保留運作
- Phase 5 的切流可用 nginx / 前端 feature flag 控制比例
- 只要不刪舊程式碼，隨時可切回 Python

---

## 5. 成功指標（KPI）

上線 30 天內必須達到：
- [ ] CRUD API p99 延遲 ≤ 30ms（現況 ~80ms）
- [ ] Gateway 單機 QPS ≥ 1,000
- [ ] Java 服務 uptime ≥ 99.9%
- [ ] 所有 17 個 V2 test cases 全數通過
- [ ] Agent 核心功能 zero regression

---

## 6. 開放議題（尚待決策）

- [ ] **Q1**：Java 框架 — Spring Boot WebFlux vs Quarkus？（影響：團隊學習曲線 vs 啟動速度）
- [ ] **Q2**：通訊協定 — 初期 HTTP 是否可接受？還是直接上 gRPC？
- [ ] **Q3**：Session 儲存 — Redis vs PostgreSQL？（目前無 Redis 實例）
- [ ] **Q4**：是否同時導入 API Gateway（Spring Cloud Gateway / Kong）做統一入口？
- [ ] **Q5**：`aiops-contract` 的 Java binding 如何發佈（Maven repo vs git submodule）？

---

## 7. 附錄：檔案搬移檢查清單（Phase 2 細節展開用）

> 待 Phase 2 啟動前，由負責工程師展開為逐檔 checklist。

---

**備註：** 本 Spec 僅作規劃草案，待實際啟動前需重新 review 以下項目：
1. 現行 Python backend 的狀態是否仍與本 Spec 假設一致（檔案數、模組結構）
2. Java 生態的 R2DBC / pgvector-java 成熟度是否改善
3. 是否有新增的 service 需重新分類
