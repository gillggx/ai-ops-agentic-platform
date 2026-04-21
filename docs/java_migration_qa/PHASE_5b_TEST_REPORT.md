# Phase 5b — Test Report

- **Date**: 2026-04-21
- **Branch**: `feat/java-api-rewrite`
- **Tester**: Claude (self-verified)
- **Goal**: Wire a real (scaffolded) LangGraph-style agent orchestrator in the Python sidecar, backed by `JavaAPIClient` for every state touch.

## What Shipped

### `python_ai_sidecar/agent_orchestrator/`

| Module | Role |
|---|---|
| `context_loader.py` | `load_context(java)` pulls MCPs + active skills for LLM prompt |
| `llm.py` | Stub `llm_stream(system, user)` → streams tokens. Swap file for real OpenAI/Bedrock |
| `memory.py` | `recall()` + `remember()` via `JavaAPIClient.list_agent_memories` / `save_agent_memory` |
| `session.py` | `SessionState` + `load_or_new()` + `save()` — LangGraph-style checkpointer on Java's `/internal/agent-sessions` |
| `graph.py` | `run_chat_turn()` — 6-step async graph, one SSE event per step |

### `python_ai_sidecar/routers/agent.py`

- `/internal/agent/chat` now runs the real graph (was Phase 4 mock)
- `/internal/agent/build` now fetches Java block catalog before streaming `pb_glass_*` events
- Pydantic models accept both `sessionId` (camel, from Frontend) and `session_id` via alias

## Graph Event Flow

```
POST /api/v1/agent/chat  (JWT-authenticated, PE or IT_ADMIN)
   │
   ▼  Java AgentProxyController  (SseEmitter bridge)
   │
   ▼  POST /internal/agent/chat  (X-Service-Token)
   │     ┌─────────────────────────────────┐
   │     │ sidecar agent_orchestrator.graph│
   │     └─────────────────────────────────┘
   │              │
   │              ├─► event:open       session id, caller_user_id, prior_messages
   │              ├─► event:context    mcp_count, skill_count   (via JavaAPIClient.list_mcps/skills)
   │              ├─► event:recall     memory_count            (via list_agent_memories)
   │              ├─► event:message *  streamed LLM tokens      (llm_stream)
   │              ├─► event:memory     saved_id                 (save_agent_memory)
   │              ├─► event:checkpoint persisted                (upsert_agent_session)
   │              └─► event:done       summary, turns
   │
Frontend receives the stream 1:1.
```

## QA Checklist

### Python unit (pytest)

| # | Test | Result |
|---|---|---|
| P1-2 | health endpoints | ✅ |
| P3 | `/pipeline/execute` round-trip (Phase 5a) | ✅ |
| P4 | `/pipeline/validate` | ✅ |
| P5 | `/sandbox/run` | ✅ |
| P6 | **SSE chat + build streams** (updated for 5b event shape + Java stubs) | ✅ |
| P7-8 | JavaAPIClient unit tests | ✅ |
| | **8 / 0 fail** | ✅ |

### Live E2E (both services running)

| # | Step | Expected | Actual | Result |
|---|---|---|---|---|
| E1 | Login + seed MCP/skill | 200 chain | ok | ✅ |
| E2 | SSE `/api/v1/agent/chat` via Java proxy | open → context → recall → message* → memory → checkpoint → done | all 7 event types present, 8 token frames for stub reply | ✅ |
| E3 | `agent_sessions` row persisted | `phase5b-demo` with title | 1 row, title=`"hello from phase 5b"` | ✅ |
| E4 | `agent_memories` row persisted | `task_type=chat_reply` | 1 row | ✅ |
| E5 | SSE `/api/v1/agent/build` Glass Box | pb_glass_start → chat → done | ✓ (no active blocks in fresh DB → stream explains "seed pb_blocks first") | ✅ |
| E6 | Second turn same session resumes | prior_messages > 0 on open event | `prior_messages: 6` (user+assistant×3), `memory_count: 3` recalled | ✅ |

All 6 steps green. Session persistence is real (DB-backed), context is real (live MCP/skill lookup per turn), recall is real (Java memory read).

## Design Decisions

1. **No LangGraph runtime dependency** — a hand-rolled async graph in ~80 lines. Easier to reason about, zero overhead. If the graph grows > 5 nodes we can drop in LangGraph without changing the public event contract.
2. **LLM stub as a pluggable file** — swap `llm.py` (one 30-line module) for a real OpenAI/Anthropic/Bedrock client when keys are provisioned. The graph doesn't change.
3. **Session messages kept as JSON string in `agent_sessions.messages`** — matches Python SQLAlchemy schema exactly (Text column). No dedicated `session_messages` table.
4. **Memory writes are best-effort** — a failed `save_agent_memory` emits an error event but doesn't abort the turn. Chat must keep working even when the memory DB hiccups.
5. **Context re-loaded every turn** — per CLAUDE.md, MCP/Skill descriptions are single source of truth; can't cache without risking drift.
6. **Pydantic `alias="sessionId"`** so Frontend's camelCase payload deserializes into Python snake_case fields without extra mapping code.

## Not Yet Wired (for 5c)

| Item | Status |
|---|---|
| Real `agent_builder` Glass Box LLM-driven pipeline construction | scaffolded envelope only |
| Real pandas/scipy pipeline executor in `/internal/pipeline/execute` | echo executor only |
| `event_poller` + `nats_subscriber` moved to sidecar | not started |
| Real LLM calls (OpenAI/Bedrock) | stub only |

## Verdict

**Phase 5b PASSED** — live chat SSE flows Frontend → Java proxy → Python sidecar graph → Java `/internal/*` (context, memory, session) → back. Session persistence verified across turns. Glass Box envelope confirmed with Java-backed block catalog. Ready to port real `agent_orchestrator_v2` and `agent_builder` logic into the same graph pattern in Phase 5c.
