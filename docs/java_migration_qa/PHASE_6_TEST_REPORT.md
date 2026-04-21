# Phase 6 — Deploy Artifacts + Migration Summary

- **Date**: 2026-04-21
- **Branch**: `feat/java-api-rewrite`
- **Goal**: Produce deployment artifacts so the new Java API + Python sidecar can run on EC2 in shadow mode beside the old Python FastAPI.

## Artifacts Shipped

| File | Purpose |
|---|---|
| `deploy/aiops-java-api.service` | systemd unit, port 8002, JVM 21, 1.5G heap cap |
| `deploy/aiops-python-sidecar.service` | systemd unit, port 8050, requires Java unit |
| `deploy/aiops-java-api.env.example` | env template (DB / JWT / OIDC / sidecar token) |
| `deploy/aiops-python-sidecar.env.example` | env template (service token + Java callback) |
| `deploy/java-update.sh` | build fat jar + sync sidecar venv + restart services |
| `deploy/java-rollback.sh` | stop Java stack, verify old Python is still serving |
| `deploy/README-java.md` | full runbook (install / update / cutover / rollback) |

## QA Checklist

| # | Check | Expected | Actual | Result |
|---|---|---|---|---|
| 1 | `./gradlew bootJar` | fat jar in `build/libs/aiops-api.jar` | 70 MB jar built | ✅ |
| 2 | Java tests all green | 34 / 0 fail | 34 / 0 fail | ✅ |
| 3 | Python tests all green | 14 / 0 fail | 14 / 0 fail | ✅ |
| 4 | systemd unit syntax | parses without error | `systemd-analyze verify` clean (locally, syntax check) | ✅ |
| 5 | `java-update.sh` logic review | idempotent, safe on re-run, doesn't clobber .env | ✓ | ✅ |
| 6 | `java-rollback.sh` logic review | always ensures old Python is serving post-rollback | ✓ | ✅ |
| 7 | README covers all operational flows | install, update, cutover, rollback, another-project-safety | ✓ | ✅ |

## Live Smoke (Phase 6 not yet run on EC2)

Deploy to EC2 is **not executed** in this phase. The SPEC requires explicit
user confirmation before modifying the production box. Local verification
confirms:

- Fat jar builds clean
- Java + Python sidecar start together locally and pass Phase 5a/5b/5c E2E
- systemd unit paths resolve against the expected `/opt/aiops/*` layout

## Cutover Plan

Per SPEC §2 and reinforced in `deploy/README-java.md`:

1. `bash deploy/java-update.sh` (shadow mode — no Frontend change)
2. Monitor journal for ≥30 min
3. Flip `FASTAPI_BASE_URL` in `aiops-app/.env.local` → `http://localhost:8002`
4. `systemctl restart aiops-app.service`
5. Smoke via `scripts/perf-smoke.sh`
6. If happy: `systemctl stop fastapi-backend.service`
7. If unhappy: `bash deploy/java-rollback.sh`

Step 3 **should wait until Phase 7** completes real-LLM + full-parity
pipeline executor. Phase 5-6 provide the shadow-mode + infra, not the
functional equivalence.

## Migration Summary — 12 Commits on `feat/java-api-rewrite`

| # | Phase | Commit | Deliverable |
|---|---|---|---|
| 1 | 0 | `0706102` | Spring Boot 3.5 + Gradle 8 skeleton, Flyway baseline, actuator, 3 profiles |
| 2 | 1 | `dbba3ff` | 29 JPA entities + repositories across 9 domain packages |
| 3 | 2 | `79ae354` | Auth + RBAC + Audit log (Azure AD OIDC + local JWT, 3 roles, SOD, 90d retention) |
| 4 | 3a | `7096426` | Alarm / EventType / GeneratedEvent / SystemParameter CRUD |
| 5 | 3b | `351a4e7` | Skill / Pipeline / AutoPatrol CRUD |
| 6 | 3c | `62aa44c` | DataSubject / MCP / MockDataSource / AgentTool / ExecutionLog |
| 7 | 4 | `6f2c9f8` | Python sidecar skeleton + Java AgentProxyController (JSON + SSE) |
| 8 | 5a | `b0011fb` | Java `/internal/*` chain + Python `JavaAPIClient` — **Java sole DB owner** |
| 9 | 5b | `8fc2fef` | Async orchestrator graph, LLM stub, Glass Box scaffold via Java |
| 10 | 5c | `2f849ad` | Real DAG walker (6 block types) + event poller / NATS lifecycle |
| 11 | 5d | `6578dfc` | Frontend env switch docs + perf smoke + Playwright compat matrix |
| 12 | 6 | (this) | systemd + deploy/rollback scripts + runbook |

## Test Totals Across Branch

| Layer | Tests | Failures |
|---|---|---|
| Java (gradle test) | **34** | 0 |
| Python sidecar (pytest) | **14** | 0 |
| Live E2E steps (scripted) | **~21** across all phases | 0 |

## Production Readiness Checklist

Green = ready. Yellow = needs Phase 7. Red = blocker.

| Area | Status | Notes |
|---|:---:|---|
| Java API 29 entities × CRUD | 🟢 | Covered by 12 controllers |
| Auth + RBAC | 🟢 | 3 roles, SOD, local + OIDC |
| Audit log | 🟢 | Async write, 90d retention |
| Reverse auth chain | 🟢 | Java sole DB owner verified |
| Agent chat (streamed) | 🟡 | Stub LLM — real provider is 1 file swap |
| Agent Glass Box | 🟡 | Scaffold only — real `agent_builder` not yet ported |
| Pipeline executor | 🟡 | 6 block types — real pandas blocks not yet ported |
| Event poller / NATS | 🟡 | Lifecycle wired, tail loop not yet ported |
| systemd + deploy + rollback | 🟢 | Shipped |
| Playwright compat | 🟡 | 2/5 specs expected-green, 3/5 need yellow items above |
| Another project safety | 🟢 | Deploy scripts only touch aiops-* units |

## Verdict

**Phase 6 PASSED** (as scoped). The Java API + Python sidecar are packaged,
installable, and documented. All 12 phase reports in
`docs/java_migration_qa/` form the complete paper trail.

Not shipping to EC2 in this commit — waiting for explicit user direction.
