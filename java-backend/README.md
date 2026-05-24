# aiops-api (Java Spring Boot)

> AIOps Platform 後端 API · sole owner of PostgreSQL · `:8002` in prod
>
> **Status (2026-05-24)**: production. Phase 8 cutover (2026-04-25) deprecated the
> Python `fastapi_backend_service` and made this the canonical backend.
> Latest OOP refactor merged from PR #5 — see
> [docs/history/PROJECT_HANDOFF.md §3](../docs/history/PROJECT_HANDOFF.md#3-phases-since-phase-8-chronological).

---

## Stack

- Java **Temurin 17** (NOT 21 — DevOps standard 2026-05-14)
- Spring Boot 3.5.14
- Maven (multi-module: parent + `java-backend` + `java-scheduler`)
- Spring Data JPA + Hibernate + Envers (audit)
- Flyway — `V*.sql` migrations live in `src/main/resources/db/migration/`
  ⚠️ **Flyway is disabled in prod** — new `V**.sql` files must be applied via
  manual `psql -f` on EC2. See memory `feedback_flyway_disabled_in_prod`.
- Spring Security 6 + JWT (`local`) or OAuth2 Resource Server (`prod`, OIDC)
- WebFlux WebClient (sidecar HTTP)
- PostgreSQL 17 + pgvector

## Runtime Layout

```
Frontend (Next.js :8000)
   │
   ▼
Java API (this app, :8002)
   │
   ├─► Postgres (sole owner; Hibernate + native SQL for pgvector)
   ├─► Python AI Sidecar (:8050)   — via X-Service-Token
   └─► java-scheduler (:8003)      — sibling module (cron + event dispatch)
```

## Package Layout (post-Phase-12 refactor)

`com.aiops.api.api.{domain}` houses the HTTP + service layer per domain.
Each package has a `package-info.java` describing the controller↔service↔repo
boundary. Key packages:

| Package | Controllers / Services |
|---|---|
| `api.skill` | SkillDocumentController + 5 services: SkillDocumentService / SkillRunnerService / SkillStepExecutor / SkillAlarmEmitter / SkillMaterializeService |
| `api.pipeline` | PipelineController + PipelineService · PipelineBuilderController + PipelineBuilderService · PipelineDocGenerator · PublishedSkillController · PipelineDtos |
| `api.fleet` | FleetController + 3-split services + façade: FleetService / FleetRosterService / FleetEquipmentDetailService / FleetSimulatorClient |
| `api.agent` | AgentProxyController (SSE proxy for chat / build) + AgentFeedbackController + AgentToolController |
| `api.agentknowledge` | AgentKnowledgeController + AgentKnowledgeService (4 sections: Directives / Lexicon / Knowledge / Examples) |
| `api.internal` | Sidecar-only endpoints (RAG search, embedding lifecycle) — `@PreAuthorize(InternalAuthority.REQUIRE_SIDECAR)` |
| `api.alarm`, `api.patrol`, `api.auth`, `api.admin`, `api.health`, … | Other domain controllers |
| `common` | Cross-cutting: `ApiResponse` envelope, `ApiException`, `SseEmitterBridge`, `RequestBodyAccess`, `JsonUtils` |
| `domain.{X}` | JPA entities + repositories (sole DB-access layer) |
| `auth`, `audit`, `scheduler`, `sidecar`, `config` | Infrastructure |

## Local Dev

前置：JDK 17 + 本機 Postgres (port 5432)。

```bash
# 1. Postgres user/db: aiops/aiops/aiops
createdb aiops

# 2. Run
cd java-backend
mvn spring-boot:run

# 3. Smoke
curl http://localhost:8002/actuator/health
```

### Profiles

- `local` (default) — BCrypt local auth, CORS open to `localhost:8000/3000`
- `prod` — OIDC (Azure AD) auth, CORS configured via env

Switch via `AIOPS_PROFILE=prod mvn spring-boot:run`.

### Test

```bash
mvn test                                          # all tests
mvn -Dtest=SkillAlarmEmitterTest test             # single class
mvn -Dtest=JsonUtilsTest,SkillDocumentServiceTest test   # comma-list
```

Current coverage: 6 active test files / 145 tests (Mockito unit, no Spring context).
See `src/test/java/com/aiops/api/`.

## Env Vars

| Var | Default | 用途 |
|---|---|---|
| `AIOPS_JAVA_PORT` | 8002 | HTTP port |
| `AIOPS_PROFILE` | local | Spring profile |
| `DB_URL` | `jdbc:postgresql://localhost:5432/aiops` | Postgres JDBC URL |
| `DB_USER` / `DB_PASSWORD` | `aiops` / `aiops` | DB credentials |
| `AUTH_MODE` | `local` | `local` or `oidc` |
| `JWT_SECRET` | dev-secret | Local JWT signing key |
| `OIDC_ISSUER` | Azure AD common | OIDC issuer URL |
| `OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET` | — | Azure AD app registration |
| `PYTHON_SIDECAR_URL` | `http://localhost:8050` | Sidecar base URL |
| `PYTHON_SIDECAR_TOKEN` | dev-service-token | Sidecar → Java internal token (sidecar-to-java direction) |
| `JAVA_INTERNAL_TOKEN` | dev-internal-token | Service token Java validates on `/internal/*` (sidecar + scheduler clients) |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:8000` | CORS allow-list |

## Wire format conventions

**All JSON properties are snake_case** (Jackson config). Don't send camelCase
keys to Java endpoints — they're silent-ignored. See memory
`feedback_jackson_snake_case_wire`.

## Deploy

`bash ../deploy/java-update.sh` from the repo root rebuilds the jar, syncs the
sidecar venv, and restarts `aiops-java-api` + `aiops-java-scheduler` +
`aiops-python-sidecar` systemd units. Frontend untouched — use
`../deploy/update.sh` for that.
