# Phase 4 — Test Report

- **Date**: 2026-04-21
- **Branch**: `feat/java-api-rewrite`
- **Tester**: Claude (self-verified)
- **Rounds**: 4a (Python sidecar skeleton) + 4b (Java proxy) + 4c (live E2E)

## Scope

SPEC §3 Phase 4 — Python AI sidecar extracted, Java proxies AI/Executor traffic to it through an authenticated internal surface.

Phase 4 does **not** migrate business logic yet — it builds the contract and the wire. Phase 5+ will swap the `/internal/*` mock responders for real LangGraph / pipeline_executor imports.

## What Shipped

### 4a — Python sidecar (`python_ai_sidecar/`)

```
python_ai_sidecar/
├── __init__.py
├── config.py                 # SERVICE_TOKEN + ALLOWED_CALLERS env-driven
├── auth.py                   # X-Service-Token guard + CallerContext (X-User-Id/Roles)
├── main.py                   # FastAPI entry, mount 4 routers, access-log middleware
├── routers/
│   ├── health.py             # GET  /internal/health
│   ├── agent.py              # POST /internal/agent/chat  (SSE)
│   │                         # POST /internal/agent/build (SSE)
│   ├── pipeline.py           # POST /internal/pipeline/execute
│   │                         # POST /internal/pipeline/validate
│   └── sandbox.py            # POST /internal/sandbox/run
├── tests/test_sidecar.py
├── requirements.txt
└── README.md
```

6 routes, all gated by `X-Service-Token`. SSE routes use `sse-starlette`. JSON routes return Pydantic-validated dicts. All responders are **mock** — they echo caller identity + input shape — but the wire protocol is final.

### 4b — Java proxy (`com.aiops.api.api.agent` + `com.aiops.api.sidecar`)

```
sidecar/
  PythonSidecarClient.java   # WebClient wrapper, injects X-User-Id/Roles headers
  PythonSidecarConfig.java   # WebClient bean (Phase 0, enhanced)

api/agent/
  AgentProxyController.java  # @PreAuthorize(ADMIN_OR_PE) class-level
    - POST /api/v1/agent/chat             (SSE via SseEmitter)
    - POST /api/v1/agent/build            (SSE via SseEmitter)
    - POST /api/v1/agent/pipeline/execute (JSON, .block())
    - POST /api/v1/agent/pipeline/validate
    - POST /api/v1/agent/sandbox/run
    - GET  /api/v1/agent/sidecar/health
```

**Design key**: JSON endpoints call `.block()` on the reactor `Mono`, SSE endpoints bridge the reactor `Flux<ServerSentEvent>` into Spring MVC's `SseEmitter`. This avoids a fatal interaction between reactive return types and the stateless JWT filter under Spring Security 6.

## QA Checklist

### 4a — Python sidecar (pytest)

| # | Test | Result |
|---|---|---|
| P1 | `test_health_ok` — valid token, caller context parsed | ✅ |
| P2 | `test_health_rejects_wrong_token` — 401 on bad token | ✅ |
| P3 | `test_pipeline_execute_mock` — echo structure | ✅ |
| P4 | `test_pipeline_validate_mock` — node_count | ✅ |
| P5 | `test_sandbox_run_mock` — input_keys | ✅ |
| P6 | `test_agent_sse_streams_both_chat_and_build` — both SSE contracts | ✅ |
| | **6/6 pass** | ✅ |

### 4b — Java compile + regression

| # | Check | Result |
|---|---|---|
| J1 | `./gradlew compileJava` clean | ✅ |
| J2 | All 29 prior Java tests still pass | ✅ |

### 4c — Live E2E smoke (Python :8050 + Java :8002)

Scripted at `/tmp/phase4_e2e.sh` — boot both, curl through Java.

| # | Step | Expected | Actual | Result |
|---|---|---|---|---|
| E1 | admin login | 200 + JWT | 211-char token | ✅ |
| E2 | admin creates PE user eve | 200 | id=59 | ✅ |
| E3 | admin `GET /agent/sidecar/health` | 200, sidecar echoes `caller_user_id=58` | ✓ | ✅ |
| E4 | PE `POST /agent/pipeline/execute` | 200, `caller_user_id=59`, echo of body | `status=mock_success, pipeline_id=42, inputs_count=1` | ✅ |
| E5 | PE `/pipeline/validate` with 3 nodes | `node_count=3` | 3 | ✅ |
| E6 | PE `/sandbox/run` with inputs | `input_keys=['x','y']` | ✓ | ✅ |
| E7 | PE SSE `/agent/chat` | open → 3× message → done, `caller_user_id=59` | full stream received | ✅ |
| E8 | PE SSE `/agent/build` | pb_glass_start → chat → op → done | full stream received | ✅ |
| E9 | on-duty user hits `/agent/chat` | 403 | 403 | ✅ |

## Observations

1. **Reactive + Spring MVC servlet stack has sharp edges**. The first cut returned `Mono<ApiResponse<Map>>`. Async dispatch ate the JWT context → everything 401'd. Fixed by `.block()` for JSON and `SseEmitter` for streams. The alternative is to move to WebFlux entirely, which is a bigger change.

2. **sse-starlette + Python 3.14 + pytest TestClient** binds asyncio primitives at module-import time and fights fresh test loops. Workaround: merge the two SSE unit tests into one shared-TestClient test. Not a prod-time issue.

3. **WireMock-style unit test for the Java proxy** was abandoned in favour of a live subprocess E2E. `@MockBean PythonSidecarClient` + `@SpringBootTest(RANDOM_PORT)` fights with the JWT filter on async dispatch in the same way the reactive return did. The live E2E is a stronger signal anyway — it proves the real wire.

## Artifacts

- Python sidecar test report: `pytest python_ai_sidecar/tests/` → 6/6 pass
- Java test suite: `./gradlew test` → 29/29 pass (unchanged)
- E2E smoke script: `/tmp/phase4_e2e.sh` — 9/9 pass
- Java bootRun log: `/tmp/aiops-java.log`
- Python sidecar log: `/tmp/py-sidecar.log`

## Known Follow-ups (Phase 5+)

| Item | Phase |
|---|---|
| Wire real `agent_orchestrator_v2` into `/internal/agent/chat` | 5 |
| Wire real `agent_builder` (Pipeline Builder Glass Box) into `/internal/agent/build` | 5 |
| Wire `pipeline_executor.py` into `/internal/pipeline/execute` + `/validate` | 5 |
| Wire `sandbox_service` into `/internal/sandbox/run` | 5 |
| Move `event_poller_service` + `nats_subscriber_service` into sidecar | 5 |
| Replace `.block()` with non-blocking MVC path OR migrate `AgentProxyController` package to WebFlux | Optional |
| Dedicated `AgentProxyIntegrationTest` using Testcontainers Python | 5 |

## Verdict

**Phase 4 PASSED** — Python sidecar skeleton runs, service-token auth works, Java proxy forwards JSON + SSE to it 1:1, caller identity propagates end-to-end, and role gating blocks unauthorised users. Ready for Phase 5 to swap mocks for real AI/Executor implementations.
