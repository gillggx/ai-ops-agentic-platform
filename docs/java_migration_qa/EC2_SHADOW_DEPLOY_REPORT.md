# EC2 Shadow Deploy Report

- **Date**: 2026-04-21
- **Host**: EC2 43.213.71.239 (Ubuntu 24.04, Linux 6.14, x86_64)
- **Branch**: `main` @ commit `14b8d7a` (merged `feat/java-api-rewrite`)
- **Mode**: Shadow — Java on :8002, old Python untouched on :8001, Frontend still points at :8001

## Services (all `systemctl is-active`)

| Port | Unit | State |
|---:|---|---|
| 8000 | aiops-app | active |
| 8001 | fastapi-backend (old) | active |
| 8002 | aiops-java-api | **active (NEW)** |
| 8012 | ontology-simulator | active |
| 8050 | aiops-python-sidecar | **active (NEW)** |

## What Ran

1. ✅ `git pull` main on EC2 — now has all 12 Java migration commits
2. ✅ JDK 21 (Temurin) installed via adoptium apt repo
3. ✅ `/opt/aiops/venv_sidecar` venv created
4. ✅ `/var/log/aiops` created
5. ✅ `/opt/aiops/java-backend/.env` composed with real DB creds + 64-char JWT secret + matching sidecar/internal tokens
6. ✅ `/opt/aiops/python_ai_sidecar/.env` composed with matching tokens
7. ✅ `deploy/java-update.sh` — built 70 MB aiops-api.jar, installed systemd units, started both services
8. ✅ `audit_logs` table created manually (Phase 6 follow-up — Python schema baseline never had it)

## Live Smoke — Reverse-Auth Round Trip Against Production DB

| # | Step | Expected | Actual | Result |
|---|---|---|---|---|
| 1 | Java health `/actuator/health` | 200 UP | `{"status":"UP","groups":["liveness","readiness"]}` | ✅ |
| 2 | admin login | 200 + JWT | 209-char token | ✅ |
| 3 | list skills via Java | real prod count | **29 skills** (matches Python) | ✅ |
| 4 | list pipelines via Java | real prod count | **30 pipelines** (matches Python) | ✅ |
| 5 | sidecar health through Java proxy | `service=python_ai_sidecar` | ✓ | ✅ |
| 6 | chat SSE `/api/v1/agent/chat` end-to-end | open→context→recall→message×8→memory→checkpoint→done | all 7 event types emitted, real prod `mcp_count: 9, skill_count: 29` in context, memory saved `id=349`, session persisted with `sessionId: shadow-smoke` | ✅ |
| 7 | event-types CRUD POST + audit log | row in `audit_logs` | 2 rows (200 + 409 conflict) | ✅ |
| 8 | Old Python still serving | `:8001` 200 | unchanged | ✅ |

## Config Applied on EC2 (for shadow mode)

`/opt/aiops/java-backend/.env` additions beyond template:

```
AIOPS_PROFILE=local                      # OIDC disabled, BCrypt admin seeded
SPRING_JPA_HIBERNATE_DDL_AUTO=none       # Java does not touch Python's schema
SPRING_FLYWAY_ENABLED=false              # no migration; Python owns structure
```

These are **shadow-mode only**. Phase 7 will reconcile Java entity types
(user_id Long vs INT etc.), then flip to Flyway-managed schema.

## Known Issues Flagged

1. **httpx missing from `python_ai_sidecar/requirements.txt`** — caught during
   first sidecar start on EC2, installed manually, now pinned in
   `requirements.txt` and will be part of the next update.
2. **`audit_logs.username` stays NULL on `/auth/login`** — login is permit-all
   so SecurityContextHolder has no principal at audit time. Cosmetic;
   method/endpoint/status still logged. Fix: promote login auditing to a
   manual write inside `AuthController` (Phase 7).
3. **Python schema uses INTEGER FK, Java entities use BIGINT** — shadow-mode
   avoids validation so no runtime impact, but we shouldn't flip `validate`
   on until types reconciled.

## Not Done (Explicit Phase 7)

- Frontend `FASTAPI_BASE_URL` is still `http://localhost:8001` — cutover to
  `:8002` deferred until real LLM + full-parity pipeline executor land.
- Old `fastapi-backend.service` stays running.

## Rollback

```bash
ssh -i ~/Desktop/ai-ops-key.pem ubuntu@43.213.71.239
bash /opt/aiops/deploy/java-rollback.sh
```

This stops Java + sidecar, verifies old Python is still up. Frontend impact:
zero (it's still pointed at :8001).

## Next Steps

- **Monitor** `sudo journalctl -u aiops-java-api -f` for 24h for any latent issues
- **Phase 7**: real LLM provider wiring in `agent_orchestrator/llm.py`, full
  `pipeline_executor.py` port in `executor/`, Mongo tail in
  `background/event_poller.py`, NATS loop in `background/nats_subscriber.py`
- **Phase 8**: cutover — flip `FASTAPI_BASE_URL` → `:8002`, restart `aiops-app`,
  watch for 30min, stop old `fastapi-backend`
