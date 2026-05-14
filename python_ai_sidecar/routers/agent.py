"""Agent chat + Pipeline Builder Glass Box.

Phase 8-A-1d: chat goes through AgentOrchestratorV2 (LangGraph) natively.
DB-coupled nodes were rewired to JavaAPIClient + ported pure-compute helpers
under ``agent_helpers_native/``; the sidecar no longer needs an AsyncSession.

The old fallback path (proxy → :8001) is retained behind ``FALLBACK_ENABLED=1``
purely as an emergency rollback switch — production should run with it ``0``.
Phase 8-D drops the fallback proxy outright + decommissions :8001.
"""

from __future__ import annotations

import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sse_starlette.sse import EventSourceResponse

from ..auth import CallerContext, ServiceAuth
from ..clients.java_client import JavaAPIClient
from ..config import CONFIG

log = logging.getLogger("python_ai_sidecar.agent_router")
router = APIRouter(prefix="/internal/agent", tags=["agent"])


class ChatRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    message: str = Field(..., min_length=1)
    session_id: str | None = Field(default=None, alias="sessionId")
    # Part B (SPEC_context_engineering): client-side state hint for the agent.
    # Currently carries `selected_equipment_id` from AppContext.selectedEquipment;
    # may grow with `current_page`, `last_viewed_alarm_id`, etc.
    client_context: dict | None = Field(default=None, alias="clientContext")
    # Phase E2: "chat" (default) or "builder". When "builder", the agent
    # biases toward aggressive build_pipeline_live invocation because the
    # caller is on the Pipeline Builder canvas and pipeline modification
    # is the default intent. Sent by AIAgentPanel when mounted inside
    # BuilderLayout (via E3 wiring).
    mode: str | None = Field(default=None)
    # Phase E3 follow-up: when AIAgentPanel runs in builder context, the
    # current canvas pipeline_json (with its declared inputs) flows here so
    # the orchestrator can surface "Pipeline 已宣告的 inputs" in the user
    # opening message — same context the Glass Box subsession used to get
    # via /agent/build's pipelineSnapshot param.
    pipeline_snapshot: dict | None = Field(default=None, alias="pipelineSnapshot")


class BuildRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    instruction: str = Field(..., min_length=1)
    pipeline_id: int | None = Field(default=None, alias="pipelineId")
    pipeline_snapshot: dict | None = Field(default=None, alias="pipelineSnapshot")
    # 2026-05-12: explicit flag so the skill-step terminal + anti-alert
    # validators fire when caller is building a Skill step pipeline.
    # Frontend embed=skill flow + chat orchestrator's build_pipeline_live
    # both set this true; standalone Pipeline Builder builds keep default.
    skill_step_mode: bool = Field(default=False, alias="skillStepMode")
    # 2026-05-13: sample trigger payload (production /run input). When the
    # caller is building a Skill, this should mirror what the alarm/event
    # will actually fire — so finalize's dry-run exercises the same code
    # path production will, and inspect/reflect catches mismatches.
    trigger_payload: dict | None = Field(default=None, alias="triggerPayload")


async def _chat_stream_native(req: ChatRequest, caller: CallerContext) -> AsyncGenerator[dict, None]:
    """Phase 8-A-1d: native LangGraph orchestrator.

    The orchestrator uses ``db=None`` and routes every state read/write
    through JavaAPIClient + the ported pure-compute helpers.
    """
    from ..agent_orchestrator_v2.orchestrator import AgentOrchestratorV2

    orchestrator = AgentOrchestratorV2(
        db=None,
        base_url=CONFIG.java_api_url,
        auth_token=CONFIG.java_internal_token,
        user_id=caller.user_id or 0,
        roles=caller.roles,
    )
    async for v1_event in orchestrator.run(
        req.message,
        session_id=req.session_id,
        client_context=req.client_context,
        mode=req.mode or "chat",
        pipeline_snapshot=req.pipeline_snapshot,
    ):
        # AgentOrchestratorV2 yields v1-style {type, ...} dicts; convert to SSE
        ev_type = v1_event.get("type") or "message"
        yield {"event": ev_type, "data": json.dumps(v1_event, ensure_ascii=False)}


async def _chat_stream(req: ChatRequest, caller: CallerContext) -> AsyncGenerator[dict, None]:
    """Chat entry — always native via the in-process LangGraph orchestrator.

    The :8001 fallback proxy was retired in 2026-05-02 cleanup; the native
    orchestrator (rewired to Java client in Phase 8-A-1d) covers the full
    chat surface end-to-end.
    """
    async for ev in _chat_stream_native(req, caller):
        yield ev


async def _build_stream(req: BuildRequest, caller: CallerContext) -> AsyncGenerator[dict, None]:
    """Phase 10-B: unified Glass Box build via graph_build (LangGraph).

    1. classify_advisor_intent → 6 buckets (BUILD vs Q&A advisor)
    2. BUILD → stream_graph_build (10-node graph; FROM_SCRATCH pauses on
       confirm_gate, frontend POSTs /build/confirm to resume)
    3. Q&A → stream_block_advisor (unchanged advisor sub-graph)

    The old v1 stream_agent_build (Anthropic 80-turn free tool-use loop)
    was retired in this commit. No more feature flag — graph is the only
    path.
    """
    import os
    from python_ai_sidecar.agent_builder.advisor import (
        classify_advisor_intent, stream_block_advisor,
    )
    from python_ai_sidecar.agent_builder.graph_build import stream_graph_build
    from python_ai_sidecar.clients.java_client import JavaAPIClient

    if not os.environ.get("ANTHROPIC_API_KEY"):
        yield {"event": "error", "data": json.dumps({
            "message": "ANTHROPIC_API_KEY not set on sidecar — /agent/build unavailable",
        })}
        yield {"event": "done", "data": json.dumps({"status": "failed"})}
        return

    try:
        intent, conf, reason = await classify_advisor_intent(req.instruction)
        log.info("build: intent=%s conf=%.2f reason=%r", intent, conf, reason)

        if intent != "BUILD":
            java = JavaAPIClient.for_caller(caller)
            async for stream_event in stream_block_advisor(req.instruction, intent, java=java):
                yield {
                    "event": stream_event.type,
                    "data": json.dumps(stream_event.data, default=str, ensure_ascii=False),
                }
            return

        async for stream_event in stream_graph_build(
            instruction=req.instruction,
            base_pipeline=req.pipeline_snapshot,
            user_id=caller.user_id,
            skill_step_mode=req.skill_step_mode,
            skip_confirm=False,  # Builder Mode shows the Apply/Cancel card
            trigger_payload=req.trigger_payload,
        ):
            yield {
                "event": stream_event.type,
                "data": json.dumps(stream_event.data, default=str, ensure_ascii=False),
            }
    except Exception as ex:  # noqa: BLE001
        log.exception("build failed")
        yield {"event": "error", "data": json.dumps({
            "message": f"build failed: {ex.__class__.__name__}: {str(ex)[:200]}",
        })}
        yield {"event": "done", "data": json.dumps({"status": "failed"})}


@router.post("/chat")
async def agent_chat(req: ChatRequest, caller: CallerContext = ServiceAuth) -> EventSourceResponse:
    return EventSourceResponse(_chat_stream(req, caller))


@router.post("/build")
async def agent_build(req: BuildRequest, caller: CallerContext = ServiceAuth) -> EventSourceResponse:
    return EventSourceResponse(_build_stream(req, caller))


# ── Phase 10: graph_build confirm endpoint (resume after confirm_gate) ────


class BuildConfirmRequest(BaseModel):
    """Phase 10-B: resume a paused graph_build session after confirm_pending.

    Only fires for Builder Mode FROM_SCRATCH builds. Chat Mode passes
    skip_confirm=True so confirm_gate never fires there.
    """
    model_config = ConfigDict(populate_by_name=True)

    session_id: str = Field(..., alias="sessionId")
    confirmed: bool = Field(...)


async def _build_confirm_stream(
    req: BuildConfirmRequest, caller: CallerContext,
) -> AsyncGenerator[dict, None]:
    from python_ai_sidecar.agent_builder.graph_build import resume_graph_build

    try:
        async for stream_event in resume_graph_build(
            session_id=req.session_id, confirmed=req.confirmed,
        ):
            yield {
                "event": stream_event.type,
                "data": json.dumps(stream_event.data, default=str, ensure_ascii=False),
            }
    except Exception as ex:  # noqa: BLE001
        log.exception("build/confirm failed for session=%s", req.session_id)
        yield {"event": "error", "data": json.dumps({
            "message": f"build/confirm failed: {ex.__class__.__name__}: {str(ex)[:200]}",
            "session_id": req.session_id,
        }, ensure_ascii=False)}
        yield {"event": "done", "data": json.dumps({"status": "failed"})}


@router.post("/build/confirm")
async def agent_build_confirm(
    req: BuildConfirmRequest, caller: CallerContext = ServiceAuth,
) -> EventSourceResponse:
    """Resume a graph_build session paused at confirm_gate. Only used when
    AGENT_BUILD_GRAPH=v2 — v1 doesn't have this gate."""
    return EventSourceResponse(_build_confirm_stream(req, caller))


# ── v15 G1: clarify-respond endpoint ──────────────────────────────────────


class BuildClarifyRespondRequest(BaseModel):
    """v15 — resume a paused graph from clarify_intent_node with user's
    answers to the multiple-choice questions emitted earlier. Frontend
    POSTs this when user picks options on the clarification dialog.
    """
    model_config = ConfigDict(populate_by_name=True)

    session_id: str = Field(..., alias="sessionId")
    # {question_id: chosen_value}; values can be option `value`s from the
    # original questions or free-text the user typed.
    answers: dict[str, str] = Field(default_factory=dict)


async def _build_clarify_stream(
    req: BuildClarifyRespondRequest, caller: CallerContext,
) -> AsyncGenerator[dict, None]:
    from python_ai_sidecar.agent_builder.graph_build.runner import (
        resume_graph_build_with_clarify,
    )

    try:
        async for stream_event in resume_graph_build_with_clarify(
            session_id=req.session_id, answers=req.answers,
        ):
            yield {
                "event": stream_event.type,
                "data": json.dumps(stream_event.data, default=str, ensure_ascii=False),
            }
    except Exception as ex:  # noqa: BLE001
        log.exception("build/clarify-respond failed for session=%s", req.session_id)
        yield {"event": "error", "data": json.dumps({
            "message": f"clarify-respond failed: {ex.__class__.__name__}: {str(ex)[:200]}",
            "session_id": req.session_id,
        }, ensure_ascii=False)}
        yield {"event": "done", "data": json.dumps({"status": "failed"})}


@router.post("/build/clarify-respond")
async def agent_build_clarify_respond(
    req: BuildClarifyRespondRequest, caller: CallerContext = ServiceAuth,
) -> EventSourceResponse:
    """Resume a paused graph at clarify_intent_node with user's answers."""
    return EventSourceResponse(_build_clarify_stream(req, caller))


# ── v15 G2: modify-request endpoint ──────────────────────────────────────


class BuildModifyRequestRequest(BaseModel):
    """v15 G2 — user reviewed the plan at confirm_gate and wants a change
    (e.g. "改 Step 3 變成 trend chart"). plan_node re-runs with the
    request appended to state.modify_requests. Bounded by MAX_MODIFY_CYCLES.
    """
    model_config = ConfigDict(populate_by_name=True)

    session_id: str = Field(..., alias="sessionId")
    step_idx: int | None = Field(default=None, alias="stepIdx")
    request: str = Field(..., min_length=1, max_length=2000)


async def _build_modify_stream(
    req: BuildModifyRequestRequest, caller: CallerContext,
) -> AsyncGenerator[dict, None]:
    from python_ai_sidecar.agent_builder.graph_build.runner import (
        resume_graph_build_with_modify,
    )

    try:
        async for stream_event in resume_graph_build_with_modify(
            session_id=req.session_id, step_idx=req.step_idx, request=req.request,
        ):
            yield {
                "event": stream_event.type,
                "data": json.dumps(stream_event.data, default=str, ensure_ascii=False),
            }
    except Exception as ex:  # noqa: BLE001
        log.exception("build/modify-request failed for session=%s", req.session_id)
        yield {"event": "error", "data": json.dumps({
            "message": f"modify-request failed: {ex.__class__.__name__}: {str(ex)[:200]}",
            "session_id": req.session_id,
        }, ensure_ascii=False)}
        yield {"event": "done", "data": json.dumps({"status": "failed"})}


@router.post("/build/modify-request")
async def agent_build_modify_request(
    req: BuildModifyRequestRequest, caller: CallerContext = ServiceAuth,
) -> EventSourceResponse:
    """Resume a paused graph at confirm_gate with user's modify request,
    routing back to plan_node for a re-plan."""
    return EventSourceResponse(_build_modify_stream(req, caller))


# ── Phase 11: Skill-step translation (sync) ──────────────────────────────


class SkillStepTranslateRequest(BaseModel):
    """Phase 11 — translate a Skill step's NL description into a pipeline
    ending in block_step_check. Java's POST /skill-documents/{slug}/steps
    calls this synchronously (block until done) and persists the resulting
    pipeline_json as a new pb_pipelines row.
    """
    model_config = ConfigDict(populate_by_name=True)

    text: str = Field(..., min_length=1, description="Natural language step description")
    base_pipeline: dict | None = Field(default=None, alias="basePipeline")


@router.post("/skill/translate-step")
async def skill_translate_step(
    req: SkillStepTranslateRequest, caller: CallerContext = ServiceAuth,
):
    """Sync skill-step translator — drives graph_build with skill_step_mode=True
    and skip_confirm=True, returns the final pipeline_json."""
    from python_ai_sidecar.agent_builder.graph_build import translate_skill_step
    result = await translate_skill_step(
        instruction=req.text,
        base_pipeline=req.base_pipeline,
    )
    return result


# ── Build trace viewer (read-only, for debugging build behavior) ──────
# Reads JSON traces written by BuildTracer when BUILDER_TRACE_DIR env
# is set. Lists most-recent-first; detail page renders graph steps +
# LLM calls + final pipeline. Not meant for production traffic; internal
# debugging only — same X-Service-Token guard as the rest of /internal.

import os as _os
from pathlib import Path as _Path
from fastapi.responses import HTMLResponse as _HTMLResponse, JSONResponse as _JSONResponse


def _trace_dir() -> _Path | None:
    raw = _os.getenv("BUILDER_TRACE_DIR", "").strip()
    if not raw:
        return None
    p = _Path(raw)
    return p if p.exists() else None


@router.get("/build/traces")
async def list_traces(caller: CallerContext = ServiceAuth):
    """Return list of recent build traces (newest first)."""
    d = _trace_dir()
    if not d:
        return _JSONResponse({"error": "BUILDER_TRACE_DIR not set or missing"}, status_code=503)
    files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:200]
    out = []
    for f in files:
        try:
            data = json.loads(f.read_text())
            out.append({
                "file": f.name,
                "build_id": data.get("build_id"),
                "session_id": data.get("session_id"),
                "started_at": data.get("started_at"),
                "duration_ms": data.get("duration_ms"),
                "status": data.get("status"),
                "instruction": (data.get("instruction") or "")[:140],
                "n_steps": len(data.get("graph_steps") or []),
                "n_llm": len(data.get("llm_calls") or []),
                "n_nodes": len(((data.get("final_pipeline") or {}).get("nodes")) or []),
                "n_edges": len(((data.get("final_pipeline") or {}).get("edges")) or []),
            })
        except Exception:
            continue
    return {"traces": out, "dir": str(d)}


@router.get("/build/traces/view", response_class=_HTMLResponse)
async def traces_view_inline(caller: CallerContext = ServiceAuth):
    """Single-page HTML viewer. Defined BEFORE the {filename} route so
    /view doesn't get caught by the dynamic path matcher."""
    return _HTMLResponse(_VIEWER_HTML)


@router.get("/build/traces/{filename}")
async def get_trace(filename: str, caller: CallerContext = ServiceAuth):
    d = _trace_dir()
    if not d:
        return _JSONResponse({"error": "BUILDER_TRACE_DIR not set"}, status_code=503)
    # safety: filename must end in .json + no path separators
    if "/" in filename or ".." in filename or not filename.endswith(".json"):
        return _JSONResponse({"error": "bad filename"}, status_code=400)
    f = d / filename
    if not f.exists():
        return _JSONResponse({"error": "not found"}, status_code=404)
    return json.loads(f.read_text())


_VIEWER_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Build Traces</title>
<style>
body{font-family:-apple-system,monospace;margin:0;padding:16px;background:#0d1117;color:#c9d1d9}
h1{font-size:18px;margin:0 0 12px}
table{width:100%;border-collapse:collapse;font-size:12px}
th,td{padding:6px 10px;text-align:left;border-bottom:1px solid #30363d}
tr:hover{background:#161b22;cursor:pointer}
.ok{color:#3fb950}
.fail{color:#f85149}
.partial{color:#d29922}
#detail{position:fixed;top:0;right:0;bottom:0;width:55%;background:#0d1117;border-left:1px solid #30363d;overflow:auto;padding:16px;display:none;font-size:12px}
#detail.open{display:block}
#close{position:absolute;top:8px;right:12px;cursor:pointer;font-size:20px}
.section{margin:16px 0;border:1px solid #30363d;border-radius:6px;padding:10px}
.section h3{font-size:13px;margin:0 0 8px;color:#58a6ff}
.step{padding:6px 8px;background:#161b22;margin:4px 0;border-radius:4px;border-left:3px solid #30363d}
.step.ok{border-left-color:#3fb950}
.step.fail{border-left-color:#f85149}
pre{white-space:pre-wrap;word-wrap:break-word;font-size:11px;background:#161b22;padding:8px;border-radius:4px;max-height:300px;overflow:auto}
.muted{color:#8b949e}
.token{padding:1px 6px;border-radius:3px;background:#161b22;font-size:11px}
</style></head><body>
<h1>Build Traces <span class="muted" id="dir"></span></h1>
<table><thead><tr><th>Time</th><th>Status</th><th>Dur</th><th>Steps/LLM</th><th>Nodes</th><th>Instruction</th></tr></thead><tbody id="rows"></tbody></table>
<div id="detail"><span id="close" onclick="document.getElementById('detail').classList.remove('open')">×</span><div id="content"></div></div>
<script>
const TOKEN = new URLSearchParams(window.location.search).get('token') || '';
async function api(path) {
  const r = await fetch(path, {headers: {'X-Service-Token': TOKEN}});
  return r.json();
}
function fmtTime(iso) { return iso ? iso.replace('T', ' ').slice(0, 19) : ''; }
function statusClass(s) { return s === 'finished' ? 'ok' : (s === 'plan_unfixable' || s === 'failed' ? 'fail' : 'partial'); }
async function loadList() {
  const data = await api('/internal/agent/build/traces');
  document.getElementById('dir').textContent = data.dir || '';
  const rows = document.getElementById('rows');
  rows.innerHTML = (data.traces || []).map(t => `
    <tr onclick="loadDetail('${t.file}')">
      <td>${fmtTime(t.started_at)}</td>
      <td class="${statusClass(t.status)}">${t.status || '-'}</td>
      <td>${t.duration_ms ? (t.duration_ms / 1000).toFixed(1) + 's' : '-'}</td>
      <td>${t.n_steps}/${t.n_llm}</td>
      <td>${t.n_nodes}/${t.n_edges}</td>
      <td>${t.instruction}</td>
    </tr>
  `).join('');
}
async function loadDetail(file) {
  const t = await api('/internal/agent/build/traces/' + file);
  const steps = (t.graph_steps || []).map(s => `
    <div class="step ${s.status === 'ok' ? 'ok' : (s.status === 'failed' ? 'fail' : '')}">
      <b>${s.node || '?'}</b> <span class="muted">${s.ts || ''}</span>
      ${s.duration_ms ? `<span class="muted">${s.duration_ms}ms</span>` : ''}
      <pre>${JSON.stringify(s, null, 2)}</pre>
    </div>
  `).join('');
  const llm = (t.llm_calls || []).map(c => `
    <div class="step">
      <b>${c.node || '?'}</b> ${c.attempt ? `<span class="token">attempt ${c.attempt}</span>` : ''} <span class="muted">${c.ts}</span>
      <details><summary>user_msg (${(c.user_msg || '').length} chars)</summary><pre>${(c.user_msg || '').replace(/[<>]/g, c => ({'<':'&lt;','>':'&gt;'}[c]))}</pre></details>
      <details><summary>raw_response</summary><pre>${(c.raw_response || '').replace(/[<>]/g, c => ({'<':'&lt;','>':'&gt;'}[c]))}</pre></details>
      ${c.parsed ? `<details><summary>parsed</summary><pre>${JSON.stringify(c.parsed, null, 2)}</pre></details>` : ''}
    </div>
  `).join('');
  const fp = t.final_pipeline || {};
  const nodes = (fp.nodes || []).map(n => `<div class="step"><b>${n.id}</b> [${n.block_id}] <pre>${JSON.stringify(n.params, null, 2)}</pre></div>`).join('');
  document.getElementById('content').innerHTML = `
    <h2>${t.build_id}</h2>
    <div class="muted">Status: ${t.status} · ${t.duration_ms}ms · ${t.session_id}</div>
    <div class="section"><h3>Instruction</h3><pre>${t.instruction || ''}</pre></div>
    <div class="section"><h3>Final Pipeline (${(fp.nodes || []).length} nodes)</h3>${nodes || '(empty)'}</div>
    <div class="section"><h3>Graph Steps (${(t.graph_steps || []).length})</h3>${steps}</div>
    <div class="section"><h3>LLM Calls (${(t.llm_calls || []).length})</h3>${llm}</div>
  `;
  document.getElementById('detail').classList.add('open');
}
loadList();
</script></body></html>"""


# (the /view route is registered above, before /{filename})
