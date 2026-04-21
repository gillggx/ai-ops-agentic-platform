# SPEC: Java Spring Boot API 重寫計畫 v1.0

> **狀態**: Draft（等待 Approval）
> **作者**: Claude (Tech Lead)
> **日期**: 2026-04-19
> **分支**: `feat/java-api-rewrite`（尚未建立）

---

## 1. Context & Objective

### 1.1 背景
目前 AIOps Platform 後端 (`fastapi_backend_service`) 為 Python FastAPI，部署在 EC2 port 8001。
隨著平台轉正 production-grade，需要：
- **Enterprise auth**: SSO / SAML / OIDC / Audit log / SOD
- **角色權限治理**: IT admin / PE (Process Engineer) / On-duty 三類 user，權限隔離
- **更成熟的型別、交易、Security 生態**: Spring Security / Spring Data JPA / Spring Cloud

### 1.2 核心目標
以 **Java 21 + Spring Boot 3.x** 重寫 **API layer（CRUD + Auth + 業務 flow）**，**完全取代** 現有 Python FastAPI。

### 1.3 Non-goals（不處理的部分）
以下 Python 元件 **保留不動**，以 Sidecar 方式呼叫：
- `agent_orchestrator_v2/`（LangGraph-based Agent）
- `agent_builder/`（Pipeline Builder Glass Box Agent）
- `pipeline_executor.py`（pandas / scipy / sklearn 執行）
- `event_poller_service.py`（MongoDB tail-based poller）
- `nats_subscriber_service.py`（NATS event subscriber）
- `sandbox_service.py`（Python sandbox for user script）

這些元件會被拆出成獨立的 **Python AI/Executor Sidecar 服務**，Java API 透過 REST 呼叫。

### 1.4 驗收標準
- 所有現有 Frontend (`aiops-app`) 功能在新 Java API 上運作不變
- 3 類 user 可透過 SSO 登入，權限正確隔離
- Audit log 覆蓋所有寫操作
- 舊 Python API（port 8001）下線，Java（port 8001）接手
- 另一個 project（同 EC2）不受影響

---

## 2. Architecture & Design

### 2.1 System Topology

```
┌──────────────────────────────────────────────────────────────┐
│                      EC2 (43.213.71.239)                     │
│                                                              │
│  ┌────────────────┐       ┌──────────────────────────┐       │
│  │  aiops-app     │       │  Java Spring Boot API    │       │
│  │  (Next.js)     │──────▶│  :8001                   │       │
│  │  :8000         │ HTTP  │  (取代舊 Python)         │       │
│  └────────────────┘       └──────┬───────────────────┘       │
│                                  │ REST + Service Token      │
│                                  ▼                           │
│                          ┌──────────────────────────┐        │
│                          │  Python AI Sidecar       │        │
│                          │  :8050 (新)              │        │
│                          │  - LangGraph Agent       │        │
│                          │  - Pipeline Executor     │        │
│                          │  - Event Poller          │        │
│                          │  - NATS Subscriber       │        │
│                          └──────┬───────────────────┘        │
│                                 │                            │
│  ┌────────────────┐             │                            │
│  │  ontology_sim  │◀────────────┘                            │
│  │  :8012         │                                          │
│  └────────────────┘                                          │
│                                                              │
│  ┌────────────────┐       ┌──────────────────────────┐       │
│  │  PostgreSQL    │◀──────│  共用 (Java + Python)    │       │
│  │  + pgvector    │       │  schema 不變             │       │
│  └────────────────┘       └──────────────────────────┘       │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  另一個 Project (不動)                                   │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

### 2.2 技術選型

| Layer | 選型 | 理由 |
|---|---|---|
| Runtime | Java 21 LTS | 現代語法（records, pattern matching, virtual threads），長支援 |
| Framework | Spring Boot 3.3.x | 業界標準，Auth / JPA / Web / Actuator 整合完整 |
| Build | Gradle 8 (Kotlin DSL) | 比 Maven 快，DSL 比 XML 可讀 |
| DB / ORM | Spring Data JPA + Hibernate | CRUD boilerplate 最少 |
| Migration | Flyway | 取代 Alembic，接管同一個 schema |
| Auth | Spring Security 6 + spring-security-oauth2-resource-server | JWT + OIDC |
| SSO | Spring Security SAML2 + OIDC | 支援 Okta / Azure AD / Keycloak |
| HTTP Client | Spring WebClient (reactive) | 呼叫 Python sidecar 用 |
| Test | JUnit 5 + Testcontainers | 整合測試用真 Postgres |
| Observability | Micrometer + Prometheus | 與 Spring Actuator 整合 |
| Audit | Hibernate Envers or spring-data-envers | 自動記錄 entity 變更 |

### 2.3 Module 切分（Gradle multi-module）

```
java-backend/
├── build.gradle.kts                     (root)
├── settings.gradle.kts
├── app/                                  (Spring Boot 啟動點)
├── core-domain/                          (JPA entities + domain services)
├── core-auth/                            (Security + SSO + RBAC)
├── core-audit/                           (Audit log + Envers config)
├── api-aiops/                            (Controllers: alarms, briefing, events...)
├── api-pipeline/                         (Controllers: pipelines, pb_published_skill...)
├── api-agent/                            (proxy to Python sidecar)
├── api-admin/                            (IT admin 專用 endpoints)
└── integration-python/                   (WebClient + DTO for Python sidecar)
```

### 2.4 DB 策略：Share Schema, No Migration

- Java 與 Python Sidecar **共用同一個 Postgres schema**
- Flyway 接管（初次啟動：`flyway baseline` 標記現狀為 v1）
- 後續 schema 變更只能在 Java 側做，Python Sidecar 被動配合
- pgvector 透過 `pgvector-java` driver 支援

### 2.5 Python AI Sidecar 契約

新增 `python_ai_sidecar/` 目錄（從現有 `fastapi_backend_service` 拆出）：

**Endpoints**（REST, authenticated by **Service Token**）:
```
POST /internal/agent/chat           → LangGraph Agent (SSE stream)
POST /internal/agent/build          → Pipeline Builder Glass Box Agent (SSE)
POST /internal/pipeline/execute     → pandas/scipy 執行 pipeline
POST /internal/pipeline/validate    → dry-run validation
POST /internal/sandbox/run          → user script sandbox
GET  /internal/health               → liveness/readiness
```

**Service Token**:
- 僅 Java Backend 可呼叫（IP allowlist + static bearer token）
- Token 來自 env var，不走 user JWT（避免 user token 洩漏到 internal）
- 用 request header `X-Service-Token: <secret>`

**Event Poller / NATS Subscriber**:
- 留在 Python Sidecar（因為既有邏輯複雜，不優先重寫）
- Poller 產生的 event 寫 Postgres，Java 從 DB 讀

### 2.6 Auth & RBAC 設計（高版）

#### 2.6.1 3 Roles

| Role | 說明 | 典型操作 |
|---|---|---|
| **IT admin** | 平台維運者 | User 管理、MCP 註冊、System parameters、Deploy、查看 audit log |
| **PE (Process Engineer)** | 製程工程師 | 建 Skill / Pipeline / Alarm rule、跑 dispatch、分析 event |
| **On-duty** | 值班工程師 | 查 alarm、ack event、跑 briefing、唯讀 |

#### 2.6.2 權限矩陣（核心 endpoint 摘要）

| Endpoint | IT admin | PE | On-duty |
|---|:---:|:---:|:---:|
| `GET /alarms`, `/events`, `/briefing` | ✅ | ✅ | ✅ |
| `POST /events/{id}/ack` | ✅ | ✅ | ✅ |
| `POST /pipelines` (create) | ✅ | ✅ | ❌ |
| `POST /pipelines/{id}/publish` | ✅ | ✅ | ❌ |
| `POST /pipelines/{id}/execute` | ✅ | ✅ | ✅ |
| `POST /mcp_definitions` | ✅ | ❌ | ❌ |
| `POST /users`, `/system_parameters` | ✅ | ❌ | ❌ |
| `GET /audit/log` | ✅ | ❌ | ❌ |

**實作**: Spring Security `@PreAuthorize("hasRole('IT_ADMIN')")` / `hasAnyRole('IT_ADMIN','PE')`。

#### 2.6.3 Auth Flow

```
1. User 瀏覽器 → aiops-app (Next.js)
2. Next.js middleware 檢查 session cookie
3. 沒 session → redirect SSO IdP (Azure AD / Okta)
4. IdP 回 OIDC id_token → Next.js 交換成 Java API 的 JWT
5. 後續 Request 帶 JWT (Authorization: Bearer) → Java API
6. Java Spring Security 驗 JWT → 抽 role → 交給 @PreAuthorize 判斷
```

**Fallback: Local Password (for demo/dev)**
- `auth_mode=local` 時，Java 走 BCrypt + local user table
- Prod 預設 `auth_mode=oidc`

#### 2.6.4 SOD (Segregation of Duties)

- 禁止同一個 user 同時擁有 IT_ADMIN + PE（建 Skill 的人不能改 System parameters）
- On-duty 不能觸發 destructive action（DELETE / UPDATE 寫入）
- 實作: `UserRoleValidator` service，`POST /users` 時檢查 role 組合

#### 2.6.5 Audit Log

- 所有 `POST/PUT/DELETE/PATCH` 自動寫 `audit_log` table
- 實作: Spring AOP `@Aspect` + Envers for entity-level diff
- 欄位: `timestamp, user_id, role, endpoint, http_method, resource_id, before_json, after_json, ip, user_agent`
- 只允許 IT_ADMIN 查閱

### 2.7 Route 對照表（摘要）

現有 41 個 Router 歸納成 11 個 Java Controller 群組：

| Python Router (群組) | Java Controller | Module |
|---|---|---|
| `auth.py`, `users.py` | `AuthController`, `UserController` | core-auth, api-admin |
| `alarms_router.py` | `AlarmController` | api-aiops |
| `briefing.py`, `analysis.py` | `BriefingController` | api-aiops |
| `event_types.py`, `system_events_router.py`, `generated_events_router.py` | `EventController` | api-aiops |
| `auto_patrols.py`, `routine_check_router.py` | `PatrolController` | api-aiops |
| `data_subjects.py`, `mock_data_router.py`, `mock_data_studio_router.py` | `DataSubjectController` | api-aiops |
| `mcp_definitions.py`, `agent_tool_router.py`, `generic_tools_router.py` | `McpController`, `ToolController` | api-aiops |
| `skill_definitions.py`, `my_skills.py`, `agentic_skill_router.py`, `script_registry_router.py` | `SkillController` | api-pipeline |
| `pipeline_builder_router.py`, `builder_router.py` | `PipelineController` | api-pipeline |
| `agent_*.py` (10 files) | `AgentProxyController` | api-agent |
| `cron_jobs_router.py`, `system_parameters.py`, `monitor_router.py`, `diagnostic*.py` | `AdminController`, `MonitorController` | api-admin |

---

## 3. Step-by-Step Execution Plan

### Phase 0: 準備（0.5 week）
- [ ] 建 branch `feat/java-api-rewrite`
- [ ] 新增 `java-backend/` 目錄（Gradle multi-module skeleton）
- [ ] Local 跑得起來：`./gradlew bootRun` 連到既有 Postgres
- [ ] 設 Flyway `baseline-on-migrate=true`，標記現狀為 v1

### Phase 1: Core Infrastructure（1 week）
- [ ] 31 個 JPA Entity（1:1 map 現有 SQLAlchemy model）
- [ ] Repository layer（Spring Data JPA）
- [ ] 共用 DTO / Error / Response envelope
- [ ] Exception handler + validation
- [ ] Audit log infrastructure（AOP + Envers）

### Phase 2: Auth & RBAC（1 week）
- [ ] User / Role / Permission JPA entity
- [ ] Local BCrypt auth + JWT issuance
- [ ] OIDC SSO 接 Keycloak（或 mock IdP）
- [ ] Spring Security config + 3 roles
- [ ] `@PreAuthorize` 套用 controllers（先套 skeleton）
- [ ] SOD validator
- [ ] Audit log endpoint（IT_ADMIN only）

### Phase 3: 核心 CRUD Controllers（1.5 week）
Priority 依 Frontend 用到的頻率：
- [ ] AlarmController + EventController（Frontend Alarm Center 必用）
- [ ] BriefingController
- [ ] PatrolController
- [ ] DataSubjectController
- [ ] McpController + ToolController
- [ ] SkillController
- [ ] PipelineController
- [ ] UserController + AdminController
- [ ] MonitorController（health, metrics proxy）

### Phase 4: Python Sidecar 拆分 + Proxy（1 week）
- [ ] 建 `python_ai_sidecar/` (port 8050)，包裝：
  - `agent_orchestrator_v2/`
  - `agent_builder/`
  - `pipeline_executor.py`
  - `event_poller_service.py`
  - `nats_subscriber_service.py`
- [ ] Service Token 機制
- [ ] Java `AgentProxyController` 用 WebClient proxy SSE
- [ ] E2E：Frontend → Java → Python Sidecar → Ontology Simulator 全通

### Phase 5: Feature Parity 驗收（0.5 week）
- [ ] Playwright E2E 跑過
- [ ] Manual smoke test：每個 Frontend page 試一次
- [ ] Performance：JVM warmup 後 latency < Python baseline

### Phase 6: Production Cutover（0.5 week）
- [ ] EC2 上建 systemd unit `aiops-java-api.service`
- [ ] Port 暫用 8002 上線驗證
- [ ] 驗證 OK → 停舊 `fastapi-backend.service`，Java 切到 8001
- [ ] 另一個 project 不動（驗證其 systemd unit 完全無影響）
- [ ] 監控 24h，rollback plan 備好（stop java / start python）

**總工期：約 6 週（單人）**

---

## 4. Deployment Plan

### 4.1 systemd Units（新）

```
/etc/systemd/system/aiops-java-api.service     (Java API :8001)
/etc/systemd/system/aiops-python-sidecar.service (Python Sidecar :8050)
/etc/systemd/system/aiops-app.service          (Next.js :8000, 不動)
/etc/systemd/system/ontology-simulator.service (:8012, 不動)
```

**下線**:
- `/etc/systemd/system/fastapi-backend.service`（現有 Python FastAPI）

### 4.2 deploy/update.sh 改造

```bash
# 新流程
1. git pull
2. cd java-backend && ./gradlew bootJar  (產出 fat jar)
3. cd python_ai_sidecar && pip install -r requirements.txt
4. cd aiops-app && npm run build
5. Flyway migrate (Java 啟動時自動)
6. systemctl restart aiops-java-api
7. systemctl restart aiops-python-sidecar
8. systemctl restart aiops-app
9. Health check 3 services
```

### 4.3 Rollback

```bash
# 一鍵回滾
systemctl stop aiops-java-api aiops-python-sidecar
systemctl start fastapi-backend
# （Frontend 不用動，API 路徑不變）
```

### 4.4 環境變數（新增）

```
# Java side
DB_URL=jdbc:postgresql://localhost:5432/aiops
DB_USER=aiops
DB_PASSWORD=***
JWT_SECRET=***
JWT_EXPIRY_MINUTES=60
OIDC_ISSUER=https://login.microsoftonline.com/<tenant>/v2.0
OIDC_CLIENT_ID=***
OIDC_CLIENT_SECRET=***
PYTHON_SIDECAR_URL=http://localhost:8050
PYTHON_SIDECAR_SERVICE_TOKEN=***
AUTH_MODE=oidc  # or local

# Python sidecar
SERVICE_TOKEN=***  # 與 Java 同一個
ALLOWED_CALLERS=127.0.0.1
```

---

## 5. Git Branch Strategy

### 5.1 Branch
```
feat/java-api-rewrite
```
- 從 `main` 分出
- 長期存在（~6 週）
- 每個 Phase 一個 PR（小步 merge 到 branch 上）
- 全部 Phase 完成 → 一次大 PR merge 回 main（或 squash）

### 5.2 Commit 規範
- `feat(java): add AlarmController`
- `feat(sidecar): extract agent orchestrator to python sidecar`
- `chore(deploy): add systemd unit for java backend`
- `test(e2e): playwright coverage for alarm flow`

### 5.3 保護措施
- 過程中 `main` 仍可接受 hotfix（cherry-pick 到 branch）
- branch 上保持 Python FastAPI 可跑（避免 Frontend dev 被擋）
- 直到 Phase 6 cutover 才切 systemd

---

## 6. Edge Cases & Risks

### 6.1 Risks

| Risk | 影響 | Mitigation |
|---|---|---|
| **JPA 跟 SQLAlchemy schema 誤差** | 資料讀錯 | Phase 1 用 Testcontainers 跑 dump → restore → Java read，對拍 |
| **pgvector Java driver 成熟度** | embedding 查詢失效 | 先 PoC，若不行退 fallback：該 endpoint proxy 到 Python |
| **SSE stream 透過 Java proxy** | Frontend chat 斷線 | WebClient with `MediaType.TEXT_EVENT_STREAM`，測試 long-running |
| **Service Token 外洩** | Python sidecar 被直接攻擊 | IP allowlist + 定期輪替 + Audit |
| **Audit log 寫入拖慢 API** | Latency 上升 | Async 寫入（`@Async` + queue） |
| **Feature parity 漏掉小 endpoint** | Frontend 某 page 壞 | Phase 3 完 checklist：41 → 41 對照表 |
| **同一 EC2 的另一 project 被影響** | 跨 project 崩壞 | Port / systemd / user / path 完全隔離，絕不動它的 service file |
| **6 週工期評估不足** | 延期 | Phase 3 砍半（保留 10 個核心 controller 先上，其他後補） |

### 6.2 Edge Cases

- **pgvector 相似度查詢**: `agent_experience_memory`、`mcp_definitions` 用到，Java 需驗證 driver
- **SQLAlchemy `JSONB` column**: Java 用 Hibernate `@JdbcTypeCode(SqlTypes.JSON)` + `@Column(columnDefinition="jsonb")`
- **Enum 對應**: Python `str Enum` → Java `@Enumerated(EnumType.STRING)`
- **Timestamp 時區**: 統一用 `OffsetDateTime`，DB 用 `TIMESTAMP WITH TIME ZONE`
- **SSE heartbeat**: Java WebClient → Python Sidecar 需設 keep-alive，Frontend 感受不能變
- **Agent 透過 Java 拿 user context**: Python sidecar 呼叫時，Java 會注入 `X-User-Id`、`X-User-Role`

### 6.3 Non-Goals 再確認
- ❌ 不重寫 LangGraph Agent（留在 Python）
- ❌ 不重寫 Pipeline Executor（pandas 生態 Java 無替代）
- ❌ 不改 DB schema（共用）
- ❌ 不動另一 project
- ❌ 不改 Frontend（API 介面 100% 相容）

---

## 7. 開發順序 Gantt（簡）

```
Week 1  [Phase 0 + Phase 1 kickoff]
Week 2  [Phase 1 finish + Phase 2]
Week 3  [Phase 3 (1/2)]
Week 4  [Phase 3 (2/2) + Phase 4 kickoff]
Week 5  [Phase 4 finish + Phase 5]
Week 6  [Phase 6 cutover + monitoring]
```

---

## 8. Success Metrics

- [ ] 41/41 Python router → Java controller 覆蓋
- [ ] 100% Frontend Playwright 測試 pass
- [ ] Auth：3 role + SSO + audit 全部可 demo
- [ ] Latency：p50 ≤ Python baseline，p99 ≤ Python baseline × 1.2
- [ ] Memory：JVM ≤ 1.5GB (vs Python ~400MB，接受此成本換型別安全)
- [ ] 舊 Python FastAPI 完全下線，另一 project 零影響
- [ ] Audit log：所有 write op 可追溯

---

## 9. Open Questions — Resolved (2026-04-21)

| # | Question | Decision |
|---|---|---|
| 1 | SSO IdP | **Azure AD (OIDC)** — `spring-security-oauth2-client` + `spring-security-oauth2-resource-server` |
| 2 | 現有 Python user table 遷移 | **重建** — 不遷移，Phase 2 由 Java 建新 schema + seed 管理員 |
| 3 | 另一 project | **Skip / 不碰** — deploy script 只動 aiops-* systemd units |
| 4 | Pipeline Executor 是否半重寫 | **Keep Python** — pandas/scipy 完全保留在 sidecar |
| 5 | Audit log retention | **90 天** — cleanup job 每日清理 `audit_log.timestamp < now() - 90d` |

---

## 10. Status Log

- 2026-04-21 SPEC v1.0 approved; branch `feat/java-api-rewrite` created; Phase 0 kicked off.
