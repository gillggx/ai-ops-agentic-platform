# Logging Schema

All AIOps services emit logs as single-line JSON on stdout. ELK / Loki / Promtail
can ingest these directly without per-service parsing rules.

## Top-level fields

| Field | Type | Required | Example | Notes |
|---|---|---|---|---|
| `timestamp` | string | yes | `2026-05-25T10:00:00.123Z` | ISO-8601 UTC, ms precision |
| `level` | string | yes | `INFO` | `DEBUG` / `INFO` / `WARN` / `ERROR` |
| `service` | string | yes | `python_ai_sidecar` | One of: `python_ai_sidecar` / `ontology_simulator` / `aiops-java-api` / `aiops-java-scheduler` |
| `trace_id` | string | yes | `550e8400-e29b-41d4-a716-446655440000` | UUID4; `-` if outside a request scope |
| `logger` | string | yes | `agent_orchestrator_v2.orchestrator` | Python logger name / Java class FQN |
| `message` | string | yes | `session.save complete` | Human-readable. Sensitive values pre-redacted |
| `context` | object | no | `{"session_id": 123, "duration_ms": 45}` | Optional structured fields |
| `exc_info` | string | no | `Traceback (most recent call last):\n  ...` | Only on exceptions |

## Trace ID propagation

Header: `X-Trace-ID`.

```
Client / nginx ──► aiops-java-api ──► python_ai_sidecar ──► ontology_simulator
                          │                  │
                          └─► java-scheduler ┘
```

Rules:
1. Every inbound HTTP request — if `X-Trace-ID` is missing, the receiving service
   generates a new UUID4 and sets it in MDC / ContextVar for the duration of the request.
2. The same `X-Trace-ID` is echoed in the response header.
3. Every outbound HTTP request from a service must forward its current `X-Trace-ID`.
4. Background tasks (NATS subscribers, schedulers, embedding backfill) generate a
   task-scoped id (`task_<uuid>`) so their logs still cluster.

## Sensitive field redaction

These keys (case-insensitive substring match) get their values replaced with `***`
before reaching the log sink:

- `token`
- `api_key` / `api-key` / `apikey`
- `password`
- `secret`

Applies to both `message` regex-rewrite (for `key=value` / `"key":"value"` patterns)
and `context` dict keys. Nested objects in `context` are NOT recursively redacted —
keep secrets out of nested structures, not as a fix for leakage.

## Log levels (production)

- `ERROR` — exception or external dependency failure
- `WARN` — degraded path / retry / fail-open guard
- `INFO` — request handled, scheduled job ran, business event
- `DEBUG` — silenced in prod (`LOG_LEVEL=INFO`)

Override via `LOG_LEVEL` env var on each service.

## Out of scope (deferred)

- File-based output / logrotate — K8s kubelet handles log rotation; bare-metal dev
  can pipe stdout through `logger` or `multilog` if needed.
- ELK / Fluent Bit / Promtail manifests — depends on the chosen K8s target env.
- OpenTelemetry spans / distributed tracing — `trace_id` here is correlation only.
- Frontend (Next.js) structured logging — not currently covered.
