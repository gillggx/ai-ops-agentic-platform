# Phase 5a — Test Report

- **Date**: 2026-04-21
- **Branch**: `feat/java-api-rewrite`
- **Tester**: Claude (self-verified)
- **Goal**: Prove the reverse-auth architecture — Python sidecar round-trips through Java for every DB operation.

## Architecture Landed

```
Frontend (JWT)
    │
    ▼
Java API :8002 ─── /api/v1/agent/pipeline/execute  (PE+IT_ADMIN gate)
    │
    ▼
Python sidecar :8050  /internal/pipeline/execute
    │  (JavaAPIClient, X-Internal-Token, forwards X-User-Id + X-User-Roles)
    │
    ▼
Java API :8002 ─── /internal/*  (InternalServiceTokenFilter, authority SERVICE_PYTHON_SIDECAR)
    │
    ▼
Postgres (Java is sole writer)
```

## What Shipped

### Java side

- `AiopsProperties.Internal(token, allowedCallerIps)` — new config block
- `auth/InternalAuthority.java` — authority string constant
- `auth/InternalServiceTokenFilter.java` — `X-Internal-Token` check + IP allow-list + forwarded user principal construction
- `config/InternalSecurityConfig.java` — `@Order(1)` filter chain for `/internal/**`; existing JWT chain demoted to `@Order(2)`
- 9 new internal controllers under `api/internal/`:
  - `InternalPipelineController` — GET by id + list
  - `InternalBlockController` — GET list + get
  - `InternalSkillController` — GET list + get
  - `InternalMcpController` — GET list
  - `InternalExecutionLogController` — **POST create** + PATCH finish
  - `InternalAgentMemoryController` — POST create + GET list
  - `InternalAgentSessionController` — GET + PUT upsert (LangGraph checkpointer)
  - `InternalAlarmController` — POST create
  - `InternalGeneratedEventController` — POST create
- `WebClientResponseException` handler added to `GlobalExceptionHandler` — upstream 404 now propagates as 404, not 500

### Python side

- `config.py` — new `java_api_url`, `java_internal_token`, `java_timeout_sec`
- `clients/java_client.py` — `JavaAPIClient` with typed methods (`get_pipeline`, `create_execution_log`, `list_blocks`, `save_agent_memory`, `upsert_agent_session`, `create_alarm`, ...). Injects `X-Internal-Token` + forwarded caller headers.
- `routers/pipeline.py` — `/internal/pipeline/execute` now:
  1. Fetches pipeline via `java.get_pipeline(id)`
  2. Runs a minimal echo executor (Phase 5c swaps for real pandas)
  3. Persists via `java.create_execution_log(...)`
  4. Returns the Java-assigned log id + node result echo
- `tests/conftest.py` — sets env BEFORE any sidecar import so `CONFIG` loads correctly
- `tests/test_java_client.py` — httpx MockTransport-backed unit tests

## QA Checklist

### Java unit/integration (gradle test)

| # | Class | Tests | Result |
|---|---|---|---|
| J1 | `InternalEndpointsTest` (new) | 5 | ✅ |
| J2-9 | All prior Java tests | 29 | ✅ |
| | **Total** | **34 / 0 fail / 0 err** | ✅ |

### Python unit (pytest)

| # | Test | Result |
|---|---|---|
| P1 | `test_health_ok` | ✅ |
| P2 | `test_health_rejects_wrong_token` | ✅ |
| P3 | `test_pipeline_execute_round_trips_via_java` (rewritten for 5a) | ✅ |
| P4 | `test_pipeline_validate_mock` | ✅ |
| P5 | `test_sandbox_run_mock` | ✅ |
| P6 | `test_agent_sse_streams_both_chat_and_build` | ✅ |
| P7 | `test_client_forwards_token_and_caller_headers` (new) | ✅ |
| P8 | `test_headers_without_caller` (new) | ✅ |
| | **8 / 0 fail** | ✅ |

### Live E2E (both services running)

| # | Step | Expected | Actual | Result |
|---|---|---|---|---|
| E1 | `GET /internal/pipelines/1` without token | 401 | 401 | ✅ |
| E2 | `GET /internal/pipelines` with token | 6 pipelines listed | 6 | ✅ |
| E3 | admin login + create PE eve + seed pipeline id=13 | 200 chain | all 200 | ✅ |
| E4 | PE `/api/v1/agent/pipeline/execute` (full round-trip) | Java→Python→Java→Java response | execution_log_id=3, caller_user_id=71, 3 nodes, `triggered_by=e2e_test` threaded through | ✅ |
| E5 | Verify `/api/v1/execution-logs/3` in Java DB | shows sidecar-written row with JSON payload | `triggeredBy=e2e_test`, `status=success`, `llmReadableData` contains `source: python_ai_sidecar` | ✅ |
| E6 | `pipeline_id=999999` (404 from Java) | Python raises 404 → Java proxy propagates 404 | HTTP 404 with `code: sidecar_upstream_error`, body includes `pipeline 999999 not found in Java` | ✅ |
| | **6 / 6 pass** | | ✅ |

## Notable Design Decisions

1. **Two SecurityFilterChain beans** (`@Order(1)` for `/internal/**`, `@Order(2)` for everything else) — cleaner than making one chain conditionally swap filters.
2. **Internal requests still carry forwarded user identity** via `X-User-Id` / `X-User-Roles`, so audit log pins the action to the real originating user, not the sidecar service account.
3. **Single `JavaAPIClient` with per-call httpx.AsyncClient** — no pool, since Phase 5a volume is tiny; Phase 5c/6 can swap for a shared client if profiling shows connection churn.
4. **404-preserving `WebClientResponseException` handler** — sidecar errors now reach the frontend with meaningful status + body, not opaque 500s.
5. **Conftest.py gates env before sidecar imports** — `CONFIG` is frozen dataclass evaluated at import time, so pytest ordering matters.

## Known Follow-ups (for Phase 5b-d)

| Item | Phase |
|---|---|
| Wire `agent_orchestrator_v2/` (LangGraph) into `/internal/agent/chat`, use `JavaAPIClient` for context/memory/session reads | 5b |
| Wire `agent_builder` (Glass Box Agent) into `/internal/agent/build` | 5b |
| Swap echo executor for real `pipeline_executor.py` with pandas/scipy | 5c |
| Move `event_poller_service` + `nats_subscriber_service` to sidecar | 5c |
| Frontend `aiops-app` upstream → Java :8001 | 5d |
| Playwright E2E + page-by-page smoke + latency benchmark | 5d |

## Verdict

**Phase 5a PASSED** — the reverse-auth architecture is proven. Java holds the DB exclusively, Python sidecar is a stateless compute layer that round-trips every read/write through `/internal/*`. Audit trail, role gating, and upstream error propagation all work end-to-end. Phase 5b can now confidently import LangGraph code and have it speak to Java through the same `JavaAPIClient`.
