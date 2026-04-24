# Phase 8-A · Agent Port Runbook

**Goal**: move `agent_chat` + `agent_build (Glass Box)` logic from the old
`fastapi_backend_service` (:8001) into `python_ai_sidecar` (:8050). Once
complete, the sidecar `/internal/agent/*` endpoints run natively —
`fallback/python_proxy.py` can drop chat + build.

**Prereqs**: Phase 8-B complete (Block B native executor + 27 blocks, verified
2026-04-25). Phase 8-A-2 done (one-step SSE unified 2026-04-25).

---

## Scope

| Module | LOC | Port status |
|---|---|---|
| `fastapi_backend_service/app/services/agent_builder/` | 1515 | **not started** |
| `fastapi_backend_service/app/services/agent_orchestrator_v2/` | 3179 | **not started** |
| Transitive deps (see below) | ~2000 | **not audited** |

**Transitive deps** (`app.*` imports discovered by `grep -rh "^from app\." | sort -u`):
- `app.config.get_settings` — already shim'd in `pipeline_builder/_sidecar_deps.py`
- `app.schemas.pipeline.PipelineJSON` et al — already copied to `pipeline_builder/pipeline_schema.py`
- `app.services.context_loader` — NOT COPIED — core RAG / memory loader
- `app.services.task_context_extractor` — NOT COPIED — parses user intent
- `app.services.tool_dispatcher` — NOT COPIED — tool schemas + dispatch
- `app.services.pipeline_builder.{executor, validator, block_registry}` — ALREADY in sidecar
- `app.models.{agent_session, mcp_definition, skill_definition}` — SQLAlchemy models (type hints only; can stub)

---

## Sequence

### A-1a · Copy scaffolding (est 1h)
Mirror the Block B pattern:
```bash
cp -r fastapi_backend_service/app/services/agent_builder         python_ai_sidecar/agent_builder
cp -r fastapi_backend_service/app/services/agent_orchestrator_v2 python_ai_sidecar/agent_orchestrator_v2
cp    fastapi_backend_service/app/services/context_loader.py     python_ai_sidecar/agent_orchestrator_v2/context_loader.py
cp    fastapi_backend_service/app/services/task_context_extractor.py python_ai_sidecar/agent_orchestrator_v2/task_context_extractor.py
cp    fastapi_backend_service/app/services/tool_dispatcher.py    python_ai_sidecar/agent_orchestrator_v2/tool_dispatcher.py
find python_ai_sidecar -name "__pycache__" -exec rm -rf {} +
```

### A-1b · Rewrite imports (est 1h)
```bash
# Intra-package
find python_ai_sidecar/agent_builder python_ai_sidecar/agent_orchestrator_v2 \
  -name "*.py" -exec sed -i '' \
    's|from app\.services\.agent_builder\.|from python_ai_sidecar.agent_builder.|g' {} +
find python_ai_sidecar/agent_builder python_ai_sidecar/agent_orchestrator_v2 \
  -name "*.py" -exec sed -i '' \
    's|from app\.services\.agent_orchestrator_v2\.|from python_ai_sidecar.agent_orchestrator_v2.|g' {} +

# pipeline_builder (already in sidecar)
find python_ai_sidecar/agent_builder python_ai_sidecar/agent_orchestrator_v2 \
  -name "*.py" -exec sed -i '' \
    's|from app\.services\.pipeline_builder\.|from python_ai_sidecar.pipeline_builder.|g' {} +

# Schemas
find python_ai_sidecar/agent_builder python_ai_sidecar/agent_orchestrator_v2 \
  -name "*.py" -exec sed -i '' \
    's|from app\.schemas\.pipeline import|from python_ai_sidecar.pipeline_builder.pipeline_schema import|g' {} +

# Singleton shims (config / models)
find python_ai_sidecar/agent_builder python_ai_sidecar/agent_orchestrator_v2 \
  -name "*.py" -exec sed -i '' \
    's|from app\.config import get_settings|from python_ai_sidecar.pipeline_builder._sidecar_deps import get_settings|g' {} +

# context_loader / task_context_extractor / tool_dispatcher — path renames
find python_ai_sidecar/agent_builder python_ai_sidecar/agent_orchestrator_v2 \
  -name "*.py" -exec sed -i '' \
    's|from app\.services\.context_loader|from python_ai_sidecar.agent_orchestrator_v2.context_loader|g' {} +
find python_ai_sidecar/agent_builder python_ai_sidecar/agent_orchestrator_v2 \
  -name "*.py" -exec sed -i '' \
    's|from app\.services\.task_context_extractor|from python_ai_sidecar.agent_orchestrator_v2.task_context_extractor|g' {} +
find python_ai_sidecar/agent_builder python_ai_sidecar/agent_orchestrator_v2 \
  -name "*.py" -exec sed -i '' \
    's|from app\.services\.tool_dispatcher|from python_ai_sidecar.agent_orchestrator_v2.tool_dispatcher|g' {} +
```

Then scan again — anything `app.models.*` remaining needs a stub (those are SQLAlchemy classes used for isinstance / type hints only, not DB queries). Add to `pipeline_builder/_sidecar_deps.py`:
```python
class AgentSessionModel: pass
class MCPDefinitionModel: pass
class SkillDefinitionModel: pass
```

### A-1c · Wire the agent routes to use native (est 2-3h)

In `python_ai_sidecar/routers/agent.py`:

1. Import the newly-ported modules:
```python
from python_ai_sidecar.agent_builder.orchestrator import AgentBuilderOrchestrator
from python_ai_sidecar.agent_orchestrator_v2.orchestrator import AgentOrchestratorV2
```

2. Replace `_chat_stream` fallback path with native:
```python
async def _chat_stream(req, caller):
    orch = AgentOrchestratorV2(java_client=JavaAPIClient.for_caller(caller))
    async for ev in orch.run(user_message=req.message, session_id=req.session_id):
        yield ev
```

3. Same for `_build_stream` — construct `AgentBuilderOrchestrator`.

4. **Keep fallback as safety net** — wrap in try/except, log warning, fall through to old :8001 if native raises.

### A-1d · DB-dependent context (est 2h)
`context_loader` + `task_context_extractor` currently hit DB directly for:
- `agent_session` row fetch
- Memory CRUD
- Skill / Pipeline lookup for "what can you run" context
- RAG embedding search

Sidecar already has `java_client.list_agent_memories()` etc. — rewire these helpers to use Java instead of direct DB. **This is the bulk of the port work** (2h+ per helper if done carefully).

### A-1e · LLM call + prompt caching
`llm_call_node` already uses `anthropic.Anthropic()` — works identically in sidecar. Ensure prompt caching breakpoints still fire — Claude Code skill for prompt caching guidance.

### A-1f · A-3 drop fallback
Once A-1c/d are green and smoke-tested, remove chat+build from `fallback/python_proxy.py`. `:8001` can then be decommissioned by Block D.

---

## Verification

```bash
# 1. Sidecar imports cleanly
python3 -c 'from python_ai_sidecar.agent_orchestrator_v2.orchestrator import AgentOrchestratorV2'

# 2. Unit tests (port from fastapi_backend_service/tests/agent_*)
cd python_ai_sidecar && pytest tests/test_agent_*

# 3. Smoke: POST /api/agent/build with a real prompt, verify native path
#    is taken (check log for "native" marker) + SSE events flow identically
#    to the old :8001 path.

# 4. Run existing Phase 8-B probe with agent-built pipelines — parity
#    between native-built pipeline and :8001-built pipeline (for same prompt).
```

---

## Risks

| Risk | Mitigation |
|---|---|
| Transitive dep count underestimated | Build an import graph before starting; budget +50% |
| LangGraph checkpointer was in-memory → sidecar needs one too | Copy pattern as-is; revisit when stateful restart matters |
| Memory RAG (pgvector) — sidecar doesn't own DB | Route via Java `/internal/agent-memories` which exists |
| Prompt caching regression | Run before/after token comparison per prompt fixture |
| Long tail of subtle bugs | Keep fallback active + log every native failure for 24h before A-3 |

---

## Estimated total

**A-1a** 1h  +  **A-1b** 1h  +  **A-1c** 3h  +  **A-1d** 2h  +  **A-1e** 1h  +  **A-1f** 0.5h  +  test/fix  2h
= **~10 hours focused work** (1-2 session spans).
