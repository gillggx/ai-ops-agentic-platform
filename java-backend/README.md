# aiops-api (Java Spring Boot)

> AIOps Platform 後端 API 的 Java 重寫版。
> **狀態：Phase 0（Skeleton）** — 詳見 [`docs/SPEC_java_migration_v1.md`](../docs/SPEC_java_migration_v1.md)

---

## Stack

- Java 21 (toolchain)
- Spring Boot 3.5.0
- Spring Data JPA + Hibernate + Envers (audit)
- Flyway（接管現有 Python schema，baseline v0）
- Spring Security 6 + OAuth2 Resource Server（Phase 2）
- WebFlux WebClient（呼叫 Python AI Sidecar）
- PostgreSQL + pgvector

## Runtime Layout

```
Frontend (Next.js :8000)
   │
   ▼
Java API (this app, :8001 prod / :8002 dev)
   │
   ├─► Postgres (共用 schema, Flyway managed)
   └─► Python AI Sidecar (:8050)  —— via X-Service-Token
            ├─ LangGraph Agent
            ├─ Pipeline Executor (pandas/scipy)
            ├─ Event Poller
            └─ NATS Subscriber
```

## Local Dev

前置：JDK 21 + 本機 Postgres（port 5432）。

```bash
# 1. 確保 Postgres 有 aiops/aiops/aiops user/pass/db
createdb aiops

# 2. 啟動
cd java-backend
./gradlew bootRun

# 3. 確認
curl http://localhost:8002/api/v1/health
curl http://localhost:8002/actuator/health
```

### Profiles

- `local`（default）— BCrypt local auth, CORS 開到 `localhost:8000/3000`
- `prod` — OIDC (Azure AD) auth, CORS 需指定 env var

Switch：`AIOPS_PROFILE=prod ./gradlew bootRun`

## Env Vars

| Var | Default | 用途 |
|---|---|---|
| `AIOPS_JAVA_PORT` | 8002 | HTTP port |
| `AIOPS_PROFILE` | local | Spring profile |
| `DB_URL` | `jdbc:postgresql://localhost:5432/aiops` | Postgres JDBC URL |
| `DB_USER` / `DB_PASSWORD` | `aiops` / `aiops` | DB 帳密 |
| `AUTH_MODE` | `local` | `local` 或 `oidc` |
| `JWT_SECRET` | dev-secret | 本地 JWT 簽章 key |
| `OIDC_ISSUER` | Azure AD common | OIDC issuer URL |
| `OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET` | — | Azure AD app 註冊資訊 |
| `PYTHON_SIDECAR_URL` | `http://localhost:8050` | Python sidecar base URL |
| `PYTHON_SIDECAR_TOKEN` | dev-service-token | 內部服務 token |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:8000` | CORS allow-list |

## Phase 0 Status

- [x] Gradle 8 + Spring Boot 3.5 skeleton
- [x] `application.yml` + `application-local.yml` + `application-prod.yml`
- [x] Flyway V0 baseline
- [x] Phase-0 SecurityConfig（permit-all，待 Phase 2 換 JWT）
- [x] Global error envelope + exception handler
- [x] `/api/v1/health` endpoint
- [x] WebClient bean for Python sidecar
- [ ] JDK 21 + Postgres connectivity 本機 smoke test（需 reviewer 驗證）

## Next (Phase 1)

31 個 JPA Entity + Repository layer（對照 `fastapi_backend_service/app/models/`）。
