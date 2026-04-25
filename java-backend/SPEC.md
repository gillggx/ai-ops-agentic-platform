# java-backend — Spec

**Date:** 2026-04-25
**HEAD:** 5114b9b
**Status:** Living Document（依 code 實況萃取）

---

## 1. 定位

AIOps 平台的 **新主要 backend**（Phase 8 Java cutover 後的 system of record）。
- **CRUD + 權限 + auth** — 接 Frontend `/api/v1/*`
- **Internal proxy** — 接 sidecar `/internal/*`（reverse-auth）
- **Agent SSE proxy** — 把 chat/build SSE 串流 proxy 到 python_ai_sidecar :8050
- **Audit / Envers** — JPA Hibernate Envers 自動寫 `_aud` 表
- **Flyway** — DB schema 唯一管理（fastapi_backend_service 的 alembic 已不再 own DB）

**邊界：** 不開 LLM、不算 pandas、不直接打 ontology_simulator。所有 AI / executor 工作丟給 sidecar。

## 2. 技術棧

| Category | Tech | Version |
|---|---|---|
| Lang | Java | 21 (toolchain) |
| Framework | Spring Boot | 3.5.0 |
| Build | Gradle Kotlin DSL | wrapper |
| ORM | Hibernate JPA + Envers | 6.x |
| DB | PostgreSQL (+ pgvector) | jdbc + `com.pgvector:0.1.4` |
| Migration | Flyway | core + flyway-database-postgresql |
| Security | Spring Security + OAuth2 Resource Server + auth0 java-jwt 4.4 | – |
| JSON / 型別擴充 | hibernate-types-60 (vlad) | 2.21.1 |
| HTTP client | spring-webflux WebClient | – |
| Util | Lombok（compileOnly + annotationProcessor） | – |
| Test | spring-boot-starter-test, testcontainers (postgresql) | 1.20.4 |

## 3. 模組樹

```
java-backend/src/main/java/com/aiops/api/
├── ApiApplication.java            Spring Boot entrypoint
├── api/                           ★ 45 個 @RestController（HTTP 入口）
│   ├── admin/                     UsersController + AuditController + MonitorController
│   ├── agent/                     AgentProxyController(SSE) + Session/Tool/MemoryAlias
│   ├── aiops/BriefingController   GET ?scope= SSE proxy；POST 多檔聚合
│   ├── alarm/                     Alarm CRUD + ack/resolve
│   ├── auth/                      AuthController + OidcController
│   ├── event/                     GeneratedEvent + EventType
│   ├── health/                    /api/v1/health
│   ├── internal/                  ★ 9 個 controller — 給 sidecar 反向呼叫，受 InternalServiceTokenFilter 保護
│   ├── mcp/                       McpDefinition + DataSubject + MockDataSource
│   ├── patrol/                    AutoPatrolController
│   ├── pipeline/                  PipelineController + PipelineBuilderController
│   └── skill/                     5 個 controller — Skill / Routine / Cron / Script
├── auth/                          ★ JWT + role + filter
│   ├── Role.java                  enum: IT_ADMIN / PE / ON_DUTY
│   ├── RoleCodec.java             JSON ↔ EnumSet
│   ├── Authorities.java           hasRole 字串常數
│   ├── SegregationOfDuties.java   role combo 限制
│   ├── JwtService + JwtAuthenticationFilter
│   ├── SharedSecretAuthFilter     legacy IT_ADMIN bypass token
│   ├── InternalServiceTokenFilter sidecar → Java 用
│   ├── UserAccountService         create/auth/changePwd/displayName
│   └── BootstrapSeeder            首次啟動建 admin/admin
├── config/                        ★ Spring config beans
│   ├── SecurityConfig             RoleHierarchy: IT_ADMIN > PE > ON_DUTY
│   ├── InternalSecurityConfig     /internal/* SecurityFilterChain
│   ├── JacksonConfig              SNAKE_CASE strategy
│   ├── CorsConfig + WebMvcConfig
│   ├── AiopsProperties            @ConfigurationProperties("aiops")
│   └── PropertiesConfig
├── domain/                        ★ JPA entities + repositories（domain-driven 分包）
│   ├── agent/  (5 entities) AgentDraft / AgentMemory / AgentExperienceMemory / AgentSession / AgentTool
│   ├── alarm/                AlarmEntity + AlarmRepository
│   ├── audit/                AuditLogEntity + RoleChangeLogEntity
│   ├── event/                GeneratedEvent / EventType
│   ├── mcp/                  McpDefinition / DataSubject / MockDataSource
│   ├── patrol/               AutoPatrolEntity + scheduled_at
│   ├── pipeline/             PbBlock / PbPipeline / ExecutionLog
│   ├── skill/                SkillDefinition / RoutineCheck / Cron / Script
│   ├── system/               SystemParameterEntity
│   └── user/                 UserEntity / UserPreference / Role / Item / RoleChangeLog
├── audit/                         AuditService + EnversConfig
├── common/                        ApiException + ApiResponse + RestExceptionHandler
└── sidecar/                       PythonSidecarClient + Config
```

**Source LOC：** 138 個 .java 檔，31 個 Entity，~45 個 RestController。

## 4. API Surface

### 4.1 對外 `/api/v1/*`（30 個 controller，給 Frontend / 外部）

| Path 前綴 | 用途 |
|---|---|
| `/auth` | login / oidc-upsert / `/me` 個資 / change-password |
| `/admin/users` | （IT_ADMIN）使用者 CRUD + role 變更 + role-history |
| `/admin/audit` | Audit log 查詢 |
| `/admin/monitor`, `/system/monitor` | 系統健康監控 |
| `/agent/*` | **SSE proxy → sidecar :8050** — chat / chat/stream / build / pipeline/{execute,validate} / sandbox/run / sidecar/health |
| `/agent-tools` | 使用者私人 tool 註冊 |
| `/alarms`, `/alarms/stats` | 告警 + 統計 |
| `/auto-patrols` | Auto-Patrol CRUD（有 `scheduled_at` since V1） |
| `/briefing` | Dashboard AI Summary — GET `?scope=` SSE proxy + POST 多檔聚合 |
| `/cron-jobs`, `/script-versions`, `/routine-checks` | Skill 排程 + 版本 |
| `/data-subjects`, `/mock-data-sources`, `/mcp-definitions` | MCP 註冊 + 模擬資料源 |
| `/diagnostic-rules` | DR 管理 |
| `/event-types`, `/generated-events`, `/execution-logs` | 事件 + 執行紀錄 |
| `/my-skills`, `/published-skills`, `/skill-definitions`, `/skills` | Skill 多視角 |
| `/pipelines`, `/pipeline-builder` | Pipeline CRUD + Builder（execute/validate） |
| `/system-parameters` | 系統參數 |
| `/health` | health check |

### 4.2 Internal `/internal/*`（9 個 controller，僅 sidecar 可調）

| Path | 用途 |
|---|---|
| `/internal/agent-memories` | sidecar memory_lifecycle_node 讀寫使用者長期記憶 |
| `/internal/agent-sessions` | sidecar 寫 session metadata |
| `/internal/alarms` | sidecar 寫告警（patrol 觸發） |
| `/internal/blocks` | sidecar 讀 block catalog（seedless 之外的 fallback） |
| `/internal/execution-logs` | sidecar 寫 pipeline 執行紀錄 |
| `/internal/generated-events` | sidecar 寫事件（patrol 結果） |
| `/internal/mcp-definitions` | sidecar 讀 MCP catalog |
| `/internal/pipelines` | sidecar 讀 pipeline 定義（DR/AP execution） |
| `/internal/skills` | sidecar 讀 skill catalog |

**保護機制：** [InternalServiceTokenFilter](java-backend/src/main/java/com/aiops/api/auth/InternalServiceTokenFilter.java) — 檢查 `X-Internal-Token` header（值來自 `aiops.internal.token` env），且 client IP 在 `aiops.internal.allowed-caller-ips` 名單內（默認 127.0.0.1 / ::1）。

### 4.3 Briefing SSE Proxy

`GET /api/v1/briefing?scope=...` → 把 `Accept: text/event-stream` 上來的 client 接到 sidecar，串流 Dashboard AI Summary（commit `e163c60` 加的）。

## 5. 認證 / 授權模型

### 5.1 Role 階層（[SecurityConfig.java:103-105](java-backend/src/main/java/com/aiops/api/config/SecurityConfig.java#L103-L105)）

```
ROLE_IT_ADMIN > ROLE_PE
ROLE_PE       > ROLE_ON_DUTY
```

`IT_ADMIN` 隱含擁有 `PE` + `ON_DUTY` authority — 不需要 explicit 多角色。

### 5.2 Authorities 常數（[Authorities.java](java-backend/src/main/java/com/aiops/api/auth/Authorities.java)）

```java
public static final String ADMIN = "hasRole('IT_ADMIN')";
public static final String PE    = "hasRole('PE')";
public static final String ON_DUTY = "hasRole('ON_DUTY')";
public static final String ADMIN_OR_PE = "hasAnyRole('IT_ADMIN','PE')";
public static final String ANY_ROLE    = "hasAnyRole('IT_ADMIN','PE','ON_DUTY')";
```

### 5.3 三種 auth filter

| Filter | 用途 | 觸發條件 |
|---|---|---|
| `JwtAuthenticationFilter` | 對外 `/api/v1/*` 主流 | `Authorization: Bearer <jwt>` |
| `SharedSecretAuthFilter` | Phase 2 cutover compat | `Authorization: Bearer <AIOPS_SHARED_SECRET_TOKEN>` → IT_ADMIN |
| `InternalServiceTokenFilter` | sidecar → Java | `X-Internal-Token: <JAVA_INTERNAL_TOKEN>` + IP whitelist |

### 5.4 OIDC 多 provider

`auth.mode=local|oidc` 切換。OIDC 走 `OidcController.upsertOidcUser()`：
- Frontend NextAuth 拿到 IdP token
- POST `/api/v1/auth/oidc-upsert` (X-Upsert-Secret)
- Java 找/建本地 user，回 Java JWT
- 角色 mapping 在 AIOps DB（不從 IdP claim 取）

## 6. Domain Entities（31 個）

**agent**：AgentDraft / AgentMemory（pgvector embedding 欄位） / AgentExperienceMemory / AgentSession / AgentTool

**alarm**：AlarmEntity + repo

**audit**：AuditLogEntity + RoleChangeLogEntity（user role 變更稽核）

**event**：GeneratedEventEntity + EventTypeEntity

**mcp**：McpDefinition + DataSubject + MockDataSource

**patrol**：AutoPatrolEntity（V1 加 `scheduled_at`）

**pipeline**：PbBlock / PbPipeline / ExecutionLogEntity

**skill**：SkillDefinition / RoutineCheck / CronJob / ScriptVersion

**system**：SystemParameterEntity（key/value config）

**user**：UserEntity（含 OIDC 欄位 V2 + display_name V3） / UserPreference / RoleChangeLog / Item

JPA 配置：`hibernate.ddl-auto=validate`（不會自動改 schema），`open-in-view=false`（嚴禁 lazy load 漏到 controller）。

## 7. Flyway Migrations

| Version | 檔名 | 內容 |
|---|---|---|
| V0 | `V0__baseline.sql` | 從 fastapi_backend_service alembic 接手的 baseline schema |
| V1 | `V1__auto_patrol_scheduled_at.sql` | AutoPatrol 加 `scheduled_at` |
| V2 | `V2__oidc_user_extras.sql` | users 加 `oidc_provider`, `oidc_sub`, `last_login_at` |
| V3 | `V3__user_display_name.sql` | users 加 `display_name` |

`baseline-on-migrate=true, baseline-version=0` — 既有 DB 直接從 V0 接續。

## 8. Build / Deploy

- **Local：** `./gradlew bootRun`（profile=local，連 localhost:5432 dev DB）
- **Build：** `./gradlew bootJar` → `build/libs/aiops-api.jar`
- **Prod：** systemd unit [deploy/aiops-java-api.service](deploy/aiops-java-api.service)
  ```
  /usr/bin/java -server -Xms512m -Xmx1536m \
    -XX:+HeapDumpOnOutOfMemoryError -XX:HeapDumpPath=/var/log/aiops/java-heap-dump.hprof \
    -Duser.timezone=UTC -Dfile.encoding=UTF-8 \
    -jar /opt/aiops/java-backend/build/libs/aiops-api.jar
  ```
- **deploy 入口**：`bash deploy/update.sh`（含 Java 重啟）；`deploy/java-update.sh` + `deploy/java-rollback.sh` 是 Java-only 路徑

## 9. 環境變數（[deploy/aiops-java-api.env.example](deploy/aiops-java-api.env.example)）

| Variable | Default | 說明 |
|---|---|---|
| `AIOPS_PROFILE` | `local`（prod 設 `prod`） | Spring profile |
| `AIOPS_JAVA_PORT` | `8002` | listen port |
| `DB_URL` | `jdbc:postgresql://localhost:5432/aiops` | Postgres |
| `DB_USER / DB_PASSWORD` | `aiops/aiops` | DB creds |
| `JWT_SECRET` | dev fallback；prod 必填 ≥32 字元 | JWT 簽章 |
| `JWT_EXPIRY_MINUTES` | `60` | JWT 有效期 |
| `AUTH_MODE` | `local` | `local` 或 `oidc` |
| `OIDC_ISSUER / OIDC_CLIENT_ID / SECRET` | – | Azure AD / Keycloak / Auth0 |
| `OIDC_ROLE_CLAIM` | `roles` | OIDC role claim path |
| `AIOPS_SHARED_SECRET_TOKEN` | – | legacy IT_ADMIN bypass，Phase 2 用 |
| `PYTHON_SIDECAR_URL` | `http://localhost:8050` | downstream sidecar |
| `PYTHON_SIDECAR_TOKEN` | `dev-service-token` | sidecar bearer |
| `JAVA_INTERNAL_TOKEN` | `dev-internal-token` | sidecar 反向呼叫用 |
| `JAVA_INTERNAL_ALLOWED_IPS` | `127.0.0.1,::1,...` | `/internal/*` IP whitelist |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:8000` | Frontend origins |

## 10. 已知缺口

1. **`hibernate.ddl-auto=validate`** — 任何 Entity 欄位增刪如果沒對應 Flyway migration，啟動就會炸。要求 PR 一定要附 migration
2. **Internal IP whitelist 只防代理層** — sidecar 跟 Java 同台（127.0.0.1）OK，未來分機需要重新審視
3. **`shared-secret-token` 還活著** — Phase 2 compat 用，要記得在 Phase 8-D 移除
4. **無 OpenAPI/Swagger 自動 doc** — 31 個 controller 需手動列；考慮加 springdoc-openapi
5. **沒 chaos / load test** — testcontainers 限定整合測，無壓測 baseline
6. **Audit log retention 90 天** 寫死在 `aiops.audit.retention-days`，沒見排程清理 cron

## 11. 變更指南

### 加 endpoint
1. 對外：放 `api/<domain>/`，加 `@PreAuthorize(Authorities.X)` 明確標角色
2. Internal：放 `api/internal/`，**不加** `@PreAuthorize`（filter 已驗證）
3. DTO 用 record + `@JsonProperty` 或靠 [JacksonConfig](java-backend/src/main/java/com/aiops/api/config/JacksonConfig.java) 的 SNAKE_CASE — 別在 controller 自己 mix camel/snake
4. error 用 `throw ApiException.badRequest(...)`，response wrapper 由 `RestExceptionHandler` 處理

### 改 schema
1. 加 Flyway `V{n}__<desc>.sql`（`{n}=max(existing)+1`）
2. 改對應 `Entity.java`
3. **不要**用 `ddl-auto=update` 抄捷徑

### 加 Role
1. `Role.java` enum
2. `Authorities.java` 加常數
3. `SecurityConfig.roleHierarchy()` 補階層關係
4. Frontend [aiops-app/src/components/shell/AppShell.tsx](aiops-app/src/components/shell/AppShell.tsx) 加 `userCanSeeXxx`

### Sidecar callback
- 走 [PythonSidecarClient](java-backend/src/main/java/com/aiops/api/sidecar/PythonSidecarClient.java) 統一 client
- 不要自己 `new WebClient()`
