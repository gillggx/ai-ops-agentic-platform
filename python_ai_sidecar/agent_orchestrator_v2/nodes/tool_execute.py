"""tool_execute node — runs tools via the existing ToolDispatcher.

Handles:
  - Preflight validation (MISSING_MCP_NAME, MISSING_PARAMS, etc.)
  - Tool execution via dispatcher.execute()
  - Programmatic data distillation
  - Render card building (for SSE tool_done events)
  - Chart rendered notification (sets chart_already_rendered flag)
  - Result trimming for LLM context (large results truncated)
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List
from langchain_core.runnables import RunnableConfig

from langchain_core.messages import ToolMessage

logger = logging.getLogger(__name__)


async def _execute_build_pipeline(
    db: Any,
    tool_input: Dict[str, Any],
    event_emit: Any = None,
) -> Dict[str, Any]:
    """Phase 5: run an LLM-built pb_pipeline via Pipeline Builder's executor.

    Returns the same contract as /api/v1/pipeline-builder/execute so the chat
    render card can display result_summary (triggered / evidence / charts /
    data_views) — identical to what the /admin/pipeline-builder "Run Full"
    button produces.

    Phase 5-UX-5: `event_emit` is a sync callback taking dict events emitted
    by the executor (pb_run_start / pb_node_start / pb_node_done / pb_run_done).
    Used to stream per-node progress into the chat SSE channel so the canvas
    can animate node-by-node.
    """
    from python_ai_sidecar.pipeline_builder.pipeline_schema import PipelineJSON
    from python_ai_sidecar.pipeline_builder.block_registry import BlockRegistry
    from python_ai_sidecar.pipeline_builder.executor import PipelineExecutor
    from python_ai_sidecar.pipeline_builder.validator import PipelineValidator

    raw_pipeline = tool_input.get("pipeline_json") or {}
    inputs_map = tool_input.get("inputs") or {}

    try:
        pipeline_json = PipelineJSON.model_validate(raw_pipeline)
    except Exception as e:  # noqa: BLE001
        return {
            "status": "validation_error",
            "error_message": f"pipeline_json failed schema parse: {e}",
        }

    # Phase 5-UX-5: emit the DAG structure before we validate/run so the
    # frontend can render grey-pending nodes immediately.
    if event_emit is not None:
        try:
            event_emit({
                "type": "pb_structure",
                "pipeline_json": raw_pipeline,
            })
        except Exception:  # noqa: BLE001
            pass

    # Load registry (reuse session's DB)
    registry = BlockRegistry()
    try:
        await registry.load_from_db(db)
    except Exception as e:  # noqa: BLE001
        return {"status": "failed", "error_message": f"BlockRegistry load failed: {e}"}

    # Validate first — return structured errors so LLM can retry
    validator = PipelineValidator(registry.catalog)
    errors = validator.validate(pipeline_json)
    if errors:
        return {
            "status": "validation_error",
            "errors": errors,
            "error_message": (
                f"Pipeline validation failed ({len(errors)} error(s)). "
                "Fix the nodes/edges and call build_pipeline again."
            ),
        }

    # Execute — ad-hoc (pipeline_id=None, no telemetry bump)
    executor = PipelineExecutor(registry)
    try:
        result = await executor.execute(
            pipeline_json,
            inputs=inputs_map or None,
            on_event=event_emit,  # Phase 5-UX-5: stream per-node events
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("build_pipeline executor crash")
        return {"status": "failed", "error_message": f"Executor crashed: {type(e).__name__}: {e}"}

    # Shape result to match dispatcher's expected envelope
    return {
        "status": result.get("status", "failed"),
        "run_id": result.get("run_id"),
        "node_results": result.get("node_results") or {},
        "error_message": result.get("error_message"),
        "result_summary": result.get("result_summary"),
        # Compact summary for LLM context (avoid dumping full evidence table)
        "llm_readable_data": _summarize_for_llm(result),
    }


async def _execute_build_pipeline_live(
    db: Any,
    tool_input: Dict[str, Any],
    event_emit: Any = None,
    chat_session_id: Any = None,
    chat_user_id: Any = None,
) -> Dict[str, Any]:
    """Phase 5-UX-6: Glass Box pipeline build.

    Spawns an agent_builder sub-session and relays its SSE events
    (chat / operation / error / done) as pb_glass_* events through the
    chat's SSE channel. The frontend mounts/updates a canvas overlay in
    real-time while this tool runs.

    Context continuity: if the chat session already has a canvas snapshot
    (agent_sessions.last_pipeline_json), hydrate the sub-agent with it so
    follow-up turns ("加一張常態分佈圖") see the existing nodes instead of
    starting from scratch. Explicit `base_pipeline_id` (DB pipeline) wins
    over session snapshot.

    Returns to the chat LLM a compact summary once the sub-agent finishes.
    """
    from python_ai_sidecar.agent_builder.orchestrator import stream_agent_build
    from python_ai_sidecar.agent_builder.session import AgentBuilderSession
    from python_ai_sidecar.agent_builder.registry import get_session_registry
    from python_ai_sidecar.pipeline_builder.block_registry import BlockRegistry
    from python_ai_sidecar.pipeline_builder.pipeline_schema import PipelineJSON

    goal = (tool_input.get("goal") or "").strip()
    notes = (tool_input.get("notes") or "").strip()
    base_pipeline_id = tool_input.get("base_pipeline_id")
    if not goal:
        return {"status": "validation_error", "error_message": "goal is required"}
    prompt = goal if not notes else f"{goal}\n\n補充 context:\n{notes}"

    # Load block registry (shared with main PipelineExecutor)
    block_registry = BlockRegistry()
    try:
        await block_registry.load_from_db(db)
    except Exception as e:  # noqa: BLE001
        return {"status": "failed", "error_message": f"BlockRegistry load failed: {e}"}

    # Resolve base pipeline — priority: explicit base_pipeline_id > chat session snapshot
    # Phase 8-A-1d: pipeline + session lookups go through Java /internal/*
    # instead of opening a local DB session. The sidecar config carries the
    # service token; per-request CallerContext is unavailable here so we
    # build an unauthenticated-from-user-perspective client (Java audit will
    # see actor=service).
    from python_ai_sidecar.clients.java_client import JavaAPIClient
    from python_ai_sidecar.config import CONFIG
    java = JavaAPIClient(
        CONFIG.java_api_url,
        CONFIG.java_internal_token,
        timeout_sec=CONFIG.java_timeout_sec,
    )

    base_pipeline: Any = None
    base_source = "none"
    if base_pipeline_id is not None:
        try:
            import json as _json
            row = await java.get_pipeline(int(base_pipeline_id))
            pipeline_json = (row or {}).get("pipelineJson") or (row or {}).get("pipeline_json")
            if pipeline_json:
                base_pipeline = PipelineJSON.model_validate(_json.loads(pipeline_json))
                base_source = f"pipeline#{base_pipeline_id}"
        except Exception as e:  # noqa: BLE001
            logger.warning("base_pipeline load failed (ignored): %s", e)

    # Phase E3 follow-up: tool_execute_node injects the orchestrator's
    # state.pipeline_snapshot here when builder-mode and no explicit
    # base_pipeline_id. This is the user's CURRENT canvas (with declared
    # inputs / nodes) — takes priority over the agent_session snapshot
    # below because canvas state is fresher.
    if base_pipeline is None:
        canvas_snap = tool_input.get("_state_pipeline_snapshot")
        if canvas_snap and (canvas_snap.get("nodes") or canvas_snap.get("inputs")):
            try:
                base_pipeline = PipelineJSON.model_validate(canvas_snap)
                base_source = "canvas_snapshot"
            except Exception as e:  # noqa: BLE001
                logger.warning("canvas_snapshot validate failed (ignored): %s", e)

    # Phase 5-UX-6 fix: if no explicit base, carry forward the chat session's
    # last canvas snapshot so follow-up requests see what the previous build
    # produced (context continuity).
    if base_pipeline is None and chat_session_id and chat_user_id:
        try:
            import json as _json
            sess = await java.get_agent_session(str(chat_session_id))
            last_json = (sess or {}).get("lastPipelineJson") or (sess or {}).get("last_pipeline_json")
            if last_json and (sess.get("userId") == chat_user_id or sess.get("user_id") == chat_user_id):
                snap = _json.loads(last_json)
                if snap.get("nodes"):
                    base_pipeline = PipelineJSON.model_validate(snap)
                    base_source = "session_snapshot"
        except Exception as e:  # noqa: BLE001
            logger.warning("session snapshot hydration failed (ignored): %s", e)
    logger.info("build_pipeline_live base=%s, goal=%r", base_source, goal[:80])

    # Create & register session
    session = AgentBuilderSession.new(
        user_prompt=prompt,
        base_pipeline=base_pipeline,
        base_pipeline_id=base_pipeline_id,
    )
    registry = get_session_registry()
    registry.start_cleanup()
    await registry.register(session)

    # Signal frontend to open canvas overlay
    if event_emit is not None:
        try:
            event_emit({
                "type": "pb_glass_start",
                "session_id": session.session_id,
                "goal": goal,
            })
        except Exception:  # noqa: BLE001
            pass

    # Relay events
    op_count = 0
    last_status: str = "running"
    try:
        async for evt in stream_agent_build(session, block_registry):
            evt_type = evt.type  # chat | operation | error | done | suggestion_card
            payload: Dict[str, Any] = {"session_id": session.session_id}
            if evt_type == "chat":
                payload["type"] = "pb_glass_chat"
                payload["content"] = (evt.data or {}).get("content", "")
            elif evt_type == "operation":
                op_count += 1
                payload["type"] = "pb_glass_op"
                payload["op"] = (evt.data or {}).get("op")
                payload["args"] = (evt.data or {}).get("args") or {}
                payload["result"] = (evt.data or {}).get("result") or {}
            elif evt_type == "error":
                payload["type"] = "pb_glass_error"
                payload["message"] = (evt.data or {}).get("message", "")
                payload["hint"] = (evt.data or {}).get("hint")
                payload["op"] = (evt.data or {}).get("op")
            elif evt_type == "done":
                payload["type"] = "pb_glass_done"
                payload["status"] = (evt.data or {}).get("status", "finished")
                payload["pipeline_json"] = (evt.data or {}).get("pipeline_json")
                payload["summary"] = (evt.data or {}).get("summary")
                last_status = payload["status"]
            elif evt_type == "plan":
                # v1.4 — forward Glass Box's checklist to outer chat stream as-is
                payload["type"] = "plan"
                payload["items"] = (evt.data or {}).get("items") or []
            elif evt_type == "plan_update":
                payload["type"] = "plan_update"
                payload["id"] = (evt.data or {}).get("id")
                payload["status"] = (evt.data or {}).get("status")
                payload["note"] = (evt.data or {}).get("note")
            elif evt_type == "continuation_request":
                # SPEC_glassbox_continuation: forward Glass Box's pause card
                # through the chat stream so AIAgentPanel can render it.
                payload["type"] = "continuation_request"
                d = evt.data or {}
                payload["session_id"] = d.get("session_id")
                payload["turns_used"] = d.get("turns_used")
                payload["ops_count"] = d.get("ops_count")
                payload["completed"] = d.get("completed") or []
                payload["remaining"] = d.get("remaining") or []
                payload["estimate"] = d.get("estimate")
                payload["options"] = d.get("options") or []
            elif evt_type == "glass_usage":
                # Phase 2-A: surface Glass Box per-LLM-call token cost
                # (input + output + cache_creation + cache_read) to the chat UI.
                payload["type"] = "glass_usage"
                d = evt.data or {}
                for k in ("turn", "input_tokens", "output_tokens",
                          "cache_creation_input_tokens", "cache_read_input_tokens"):
                    payload[k] = d.get(k, 0)
            elif evt_type == "glass_progress":
                # SPEC_glassbox_continuation §B/A: live turn counter + 70% warning.
                payload["type"] = "glass_progress"
                d = evt.data or {}
                for k in ("turn_used", "turn_budget", "absolute_max", "percent", "warning"):
                    payload[k] = d.get(k)
            else:
                continue  # skip suggestion_card + other unknown types
            if event_emit is not None:
                try:
                    event_emit(payload)
                except Exception:  # noqa: BLE001
                    pass
    except Exception as e:  # noqa: BLE001
        logger.exception("build_pipeline_live sub-agent crashed")
        return {"status": "failed", "error_message": f"Sub-agent crashed: {type(e).__name__}: {e}"}

    final_pipeline = session.pipeline_json.model_dump(by_alias=True)
    return {
        "status": last_status,
        "pipeline_json": final_pipeline,
        "summary": session.summary or f"已建立 pipeline（{len(final_pipeline.get('nodes') or [])} nodes, {op_count} operations）",
        "node_count": len(final_pipeline.get("nodes") or []),
        "edge_count": len(final_pipeline.get("edges") or []),
        "run_status": last_status,
        "llm_readable_data": {
            "goal": goal,
            "final_status": last_status,
            "nodes_built": len(final_pipeline.get("nodes") or []),
            "operations_taken": op_count,
            "summary_for_user": session.summary,
        },
    }


async def _execute_propose_pipeline_patch(
    db: Any,
    tool_input: Dict[str, Any],
) -> Dict[str, Any]:
    """Phase 5-UX-5 Copilot: validate patches + return a proposal envelope.

    Does NOT mutate anything — frontend renders the proposal card and the user
    clicks 'Apply' to actually touch the canvas.

    Validates:
      - patches non-empty
      - each op is one of the allowed verbs
      - block_id (for insert_*) exists in the registry
    Returns:
      {status, patches, reason, errors?} — frontend surfaces to user.
    """
    from python_ai_sidecar.pipeline_builder.block_registry import BlockRegistry

    raw_patches = tool_input.get("patches") or []
    reason = tool_input.get("reason") or ""
    if not isinstance(raw_patches, list) or not raw_patches:
        return {"status": "validation_error", "error_message": "patches must be a non-empty list"}

    registry = BlockRegistry()
    try:
        await registry.load_from_db(db)
    except Exception as e:  # noqa: BLE001
        return {"status": "failed", "error_message": f"BlockRegistry load failed: {e}"}

    allowed_ops = {"insert_after", "insert_before", "update_params", "delete_node", "connect_edge"}
    errors: list[dict[str, Any]] = []
    for i, p in enumerate(raw_patches):
        if not isinstance(p, dict):
            errors.append({"index": i, "message": "patch must be an object"})
            continue
        op = p.get("op")
        if op not in allowed_ops:
            errors.append({"index": i, "message": f"invalid op '{op}'"})
            continue
        if op in ("insert_after", "insert_before"):
            block_id = p.get("block_id")
            block_version = p.get("block_version") or "1.0.0"
            if not block_id:
                errors.append({"index": i, "message": f"{op} requires block_id"})
                continue
            if registry.get_spec(block_id, block_version) is None:
                errors.append({"index": i, "message": f"block_id '{block_id}@{block_version}' not found"})

    if errors:
        return {
            "status": "validation_error",
            "errors": errors,
            "error_message": f"{len(errors)} patch(es) failed validation",
        }

    # Proposal is valid structurally; return for frontend rendering.
    return {
        "status": "success",
        "reason": reason,
        "patches": raw_patches,
        "llm_readable_data": {
            "proposal_submitted": True,
            "patch_count": len(raw_patches),
            "ops": [p.get("op") for p in raw_patches],
            "awaiting_user_approval": True,
            # Hint to LLM: don't repeat the proposal next turn, wait for user response.
        },
    }


def _summarize_for_llm(result: Dict[str, Any]) -> Dict[str, Any]:
    """Condensed result for LLM — skip raw rows, keep key facts."""
    summary = result.get("result_summary") or {}
    charts = summary.get("charts") or [] if isinstance(summary, dict) else []
    data_views = summary.get("data_views") or [] if isinstance(summary, dict) else []
    return {
        "triggered": bool(summary.get("triggered")) if isinstance(summary, dict) else False,
        "evidence_rows": summary.get("evidence_rows", 0) if isinstance(summary, dict) else 0,
        "evidence_node_id": summary.get("evidence_node_id") if isinstance(summary, dict) else None,
        "chart_count": len(charts),
        "chart_titles": [c.get("title") for c in charts][:5],
        "data_view_count": len(data_views),
        "data_view_titles": [v.get("title") for v in data_views][:5],
        "node_status_counts": {
            s: sum(1 for nr in (result.get("node_results") or {}).values() if nr.get("status") == s)
            for s in ("success", "failed", "skipped")
        },
    }


async def tool_execute_node(state: Dict[str, Any], config: RunnableConfig) -> Dict[str, Any]:
    """Execute all tool_calls from the last AIMessage.

    Returns tool result messages + updated state (tools_used, render_cards, flags).
    """
    db = config["configurable"]["db"]
    base_url = config["configurable"]["base_url"]
    auth_token = config["configurable"]["auth_token"]
    user_id = config["configurable"]["user_id"]
    # Phase 5-UX-5: optional SSE event sink — agent_chat_router injects a sync
    # callback here so tool-level lifecycle events (pb_structure / pb_node_*)
    # can stream out to the chat UI for progressive canvas animation.
    event_emit = config["configurable"].get("pb_event_emit")

    # Import here to avoid circular imports at module level
    from python_ai_sidecar.agent_orchestrator_v2.helpers import (
        _preflight_validate,
        _is_spc_result,
        _result_summary,
    )
    from python_ai_sidecar.agent_orchestrator_v2.render_card import _build_render_card
    from python_ai_sidecar.agent_helpers_native.data_distillation_service import DataDistillationService
    from python_ai_sidecar.agent_helpers.tool_dispatcher import ToolDispatcher

    # Get the last AI message's tool_calls
    messages = state["messages"]
    last_msg = messages[-1] if messages else None
    if not last_msg or not hasattr(last_msg, "tool_calls") or not last_msg.tool_calls:
        return {}

    # Phase 8-A-1d: ToolDispatcher accepts a Java client so its mcp_id /
    # save_memory / search_memory paths can route through Java when no
    # local AsyncSession is supplied (chat native mode).
    from python_ai_sidecar.clients.java_client import JavaAPIClient
    from python_ai_sidecar.config import CONFIG
    java = JavaAPIClient(
        CONFIG.java_api_url, CONFIG.java_internal_token,
        timeout_sec=CONFIG.java_timeout_sec,
    )
    dispatcher = ToolDispatcher(
        db=db,
        base_url=base_url,
        auth_token=auth_token,
        user_id=user_id,
        java=java,
    )
    distill_svc = DataDistillationService()

    tool_messages: List[ToolMessage] = []
    new_tools_used: List[Dict[str, Any]] = []
    new_render_cards: List[Dict[str, Any]] = []
    chart_rendered = state.get("chart_already_rendered", False)
    last_spc = state.get("last_spc_result")
    force_synth = False
    # v1.4 Plan Panel — accumulated across tool calls in this node invocation.
    # Carries forward whatever was already in state.plan_items so updates
    # apply to existing items.
    plan_items: List[Dict[str, Any]] = list(state.get("plan_items") or [])

    for tc in last_msg.tool_calls:
        tool_name = tc["name"]
        tool_input = tc.get("args", {})
        tc_id = tc.get("id", "")

        # Preflight validation
        preflight_err = await _preflight_validate(
            db, tool_name, tool_input,
            caller_roles=config["configurable"].get("caller_roles") or (),
        )
        if preflight_err:
            result = preflight_err
        elif tool_name == "build_pipeline_live":
            # Phase 5-UX-6: Glass Box pipeline build — spawns agent_builder
            # sub-agent, streams per-operation events to chat SSE.
            # Pass chat session context so the sub-agent carries canvas snapshot
            # across follow-up turns.
            # Phase E3 follow-up: also forward the canvas snapshot from
            # builder-mode requests via a synthetic _state_pipeline_snapshot
            # entry on tool_input, picked up by _execute_build_pipeline_live
            # when no explicit base_pipeline_id is supplied.
            snap = state.get("pipeline_snapshot")
            if snap and not tool_input.get("base_pipeline_id"):
                tool_input = {**tool_input, "_state_pipeline_snapshot": snap}
            result = await _execute_build_pipeline_live(
                db,
                tool_input,
                event_emit=event_emit,
                chat_session_id=state.get("session_id"),
                chat_user_id=user_id,
            )
        else:
            # Inject flat_data into execute_analysis so sandbox can read it directly
            if tool_name == "execute_analysis" and state.get("flat_data"):
                tool_input = {**tool_input, "_flat_data": state["flat_data"]}
            result = await dispatcher.execute(tool_name, tool_input)

        # ── v1.4 Plan Panel — emit plan / plan_update SSE events ─────
        if (tool_name == "update_plan" and isinstance(result, dict)
                and result.get("_plan_action")):
            action = result["_plan_action"]
            if action == "create":
                items = result.get("items") or []
                plan_items = [dict(it) for it in items]
                if event_emit is not None:
                    try:
                        event_emit({"type": "plan", "items": plan_items})
                    except Exception:  # noqa: BLE001
                        pass
            elif action == "update":
                pid = result.get("id")
                new_status = result.get("status_value")
                note = result.get("note")

                # Phase E3 follow-up — Builder-mode anti-pattern guard.
                # In builder mode the agent must not mark a plan item "done"
                # with a note that says it's waiting for the user. The user
                # is on a canvas with declared inputs — the right move is
                # to reuse the $name and call build_pipeline_live, not park
                # waiting for clarification. Mutate the tool result into an
                # error so the LLM sees "you can't do that, try again" and
                # the graph routes back through llm_call instead of going
                # to synthesis with a half-finished plan.
                anti_pattern = (
                    state.get("mode") == "builder"
                    and new_status == "done"
                    and isinstance(note, str)
                    and any(kw in note for kw in (
                        "等待使用者", "需要使用者", "等待用戶", "需要用戶",
                        "請使用者提供", "請用戶提供", "等候使用者",
                    ))
                )
                if anti_pattern:
                    # Mutate result into an error so the LLM sees "you can't
                    # do that, try again" — graph routes back through
                    # llm_call. Do NOT mutate plan_items or emit plan_update
                    # so the UI doesn't flash a misleading 'done' state.
                    result.clear()
                    result.update({
                        "status": "error",
                        "code": "BUILDER_WAITS_USER_FORBIDDEN",
                        "message": (
                            "Builder mode forbids marking a plan item 'done' "
                            "while waiting on the user. The canvas already "
                            "has declared inputs (see the user opening's "
                            "'當前 canvas 已宣告的 inputs' section) — REUSE "
                            "those $names and call build_pipeline_live to "
                            "build the pipeline structure now. Do NOT stop. "
                            "Re-call update_plan with status='in_progress' "
                            "(NOT 'done', and NO 'waiting for user' note) and "
                            "immediately invoke build_pipeline_live."
                        ),
                    })
                    logger.warning(
                        "tool_execute: blocked builder-mode 'waiting for user' "
                        "anti-pattern on plan item id=%s note=%r",
                        pid, note,
                    )

                if not anti_pattern:
                    for it in plan_items:
                        if it.get("id") == pid:
                            if new_status:
                                it["status"] = new_status
                            if note is not None:
                                it["note"] = note
                            break
                    if event_emit is not None:
                        try:
                            event_emit({
                                "type": "plan_update",
                                "id": pid,
                                "status": new_status,
                                "note": note,
                            })
                        except Exception:  # noqa: BLE001
                            pass

        # ── v1.4 Auto-Run — chain execute after build_pipeline_live success ─
        if (tool_name == "build_pipeline_live"
                and isinstance(result, dict)
                and result.get("status") in {"finished", "success"}
                and result.get("pipeline_json")):
            pipeline_json = result["pipeline_json"]
            node_count = len((pipeline_json.get("nodes") or []) if isinstance(pipeline_json, dict) else [])
            if event_emit is not None:
                try:
                    event_emit({
                        "type": "pb_run_start",
                        "node_count": node_count,
                    })
                except Exception:  # noqa: BLE001
                    pass
            try:
                from python_ai_sidecar.executor.real_executor import (
                    execute_native, all_blocks_native,
                )
                if all_blocks_native(pipeline_json):
                    run_result = await execute_native(
                        pipeline_json, inputs={}, run_id=None,
                    )
                    run_status = run_result.get("status") or "error"
                    if run_status == "success":
                        # Attach run result to the build result so synthesis
                        # can summarise; also surface via SSE for AnalysisPanel.
                        result["auto_run"] = {
                            "status": "success",
                            "node_results": run_result.get("node_results") or {},
                            "result_summary": run_result.get("result_summary"),
                            "duration_ms": run_result.get("duration_ms"),
                        }
                        if event_emit is not None:
                            try:
                                event_emit({
                                    "type": "pb_run_done",
                                    "status": "success",
                                    "node_results": run_result.get("node_results") or {},
                                    "result_summary": run_result.get("result_summary"),
                                    "duration_ms": run_result.get("duration_ms"),
                                })
                            except Exception:  # noqa: BLE001
                                pass
                    else:
                        err = run_result.get("error_message") or "execution failed"
                        result["auto_run"] = {"status": "error", "error_message": err}
                        if event_emit is not None:
                            try:
                                event_emit({
                                    "type": "pb_run_error",
                                    "error_message": err,
                                })
                            except Exception:  # noqa: BLE001
                                pass
                else:
                    # Hybrid pipeline (non-native blocks) — skip auto-run
                    # for now; user can hit Run Full manually.
                    result["auto_run"] = {"status": "skipped", "reason": "non-native blocks"}
            except Exception as exc:  # noqa: BLE001
                logger.warning("auto-run after build_pipeline_live failed: %s", exc)
                result["auto_run"] = {"status": "error", "error_message": str(exc)[:300]}
                if event_emit is not None:
                    try:
                        event_emit({
                            "type": "pb_run_error",
                            "error_message": str(exc)[:300],
                        })
                    except Exception:  # noqa: BLE001
                        pass

        # Track SPC results for auto-contract fallback
        if (tool_name == "execute_mcp" and isinstance(result, dict)
                and _is_spc_result(result)):
            last_spc = (result.get("mcp_name", tool_name), result)

        # Distillation for execute_mcp results
        if tool_name == "execute_mcp" and isinstance(result, dict) and result.get("status") == "success":
            result = await distill_svc.distill_mcp_result(result)

            # Inject data overview so LLM knows the full picture even when raw data is truncated.
            # get_process_info returns {total, events:[...]} wrapped in dataset list.
            od = result.get("output_data") or {}
            ds = od.get("dataset") or od.get("_raw_dataset") or []
            if isinstance(ds, list) and len(ds) == 1 and isinstance(ds[0], dict):
                inner = ds[0]
                events = inner.get("events")
                if isinstance(events, list) and len(events) > 5:
                    ooc_n = sum(1 for e in events if isinstance(e, dict) and e.get("spc_status") == "OOC")
                    ooc_steps: dict = {}
                    for e in events:
                        if isinstance(e, dict) and e.get("spc_status") == "OOC":
                            s = e.get("step", "?")
                            ooc_steps[s] = ooc_steps.get(s, 0) + 1
                    step_summary = ", ".join(f"{s}:{n}" for s, n in sorted(ooc_steps.items(), key=lambda x: -x[1])[:5])
                    overview = (
                        f"\n═══ DATA OVERVIEW ═══\n"
                        f"total_events: {len(events)}, ooc_count: {ooc_n}, ooc_rate: {ooc_n/len(events)*100:.1f}%\n"
                        f"ooc_by_step: {step_summary or 'none'}\n"
                        f"═════════════════════\n"
                    )
                    # Prepend to llm_readable_data
                    lrd = result.get("llm_readable_data")
                    if isinstance(lrd, str):
                        result["llm_readable_data"] = overview + lrd
                    elif isinstance(lrd, dict):
                        result["llm_readable_data"] = {**lrd, "_data_overview": overview}
                    else:
                        result["_data_overview"] = overview

        # Phase 5-UX-6: build_pipeline_live persists final canvas snapshot to
        # agent_sessions so /chat/[id] can restore on page reload. No render
        # card — the overlay already showed everything live.
        # Phase 8-A-1d: native chat path (db=None) routes via Java upsert.
        if tool_name == "build_pipeline_live" and isinstance(result, dict) and result.get("status") in {"finished", "success"}:
            sid = state.get("session_id")
            pipeline_json = result.get("pipeline_json")
            if sid and pipeline_json:
                try:
                    if db is None:
                        # Anonymous caller — skip persist (Java requires userId).
                        if not user_id or user_id <= 0:
                            pass
                        else:
                            # Java upsert — minimal payload preserves prior fields.
                            await java.upsert_agent_session(str(sid), {
                                "userId": user_id,
                                "lastPipelineJson": json.dumps(pipeline_json, ensure_ascii=False),
                            })
                    else:
                        from python_ai_sidecar.agent_helpers._model_stubs import AgentSessionModel
                        from sqlalchemy import select as _select
                        _sess_row = (await db.execute(
                            _select(AgentSessionModel).where(
                                AgentSessionModel.session_id == sid,
                                AgentSessionModel.user_id == user_id,
                            )
                        )).scalar_one_or_none()
                        if _sess_row is not None:
                            _sess_row.last_pipeline_json = json.dumps(pipeline_json, ensure_ascii=False)
                            await db.flush()
                except Exception as e:  # noqa: BLE001
                    logger.warning("session pipeline snapshot writeback failed: %s", e)

        # PR-C: invoke_published_skill also returns a pb pipeline summary
        if tool_name == "invoke_published_skill" and isinstance(result, dict) and result.get("status") == "success":
            card = {
                "type": "pb_pipeline_published",
                "slug": result.get("slug"),
                "skill_name": result.get("skill_name"),
                "charts": result.get("charts") or [],
                "triggered": result.get("triggered"),
                "evidence_rows": result.get("evidence_rows"),
                "run_id": result.get("run_id"),
            }
            new_render_cards.append(card)

        # Handle query_data: stash flat_data in state + build render_card with ui_config
        elif tool_name == "query_data" and isinstance(result, dict) and result.get("_flat_data"):
            _flat_data = result.get("_flat_data")
            _flat_meta = result.get("_flat_metadata")
            _viz_hint = result.get("_visualization_hint")
            # Build UI config from viz_hint
            _ui_config = None
            if _viz_hint and isinstance(_viz_hint, dict):
                _ui_config = {
                    "ui_component": "ChartExplorer",
                    "initial_view": _viz_hint,
                    "available_datasets": _flat_meta.get("available_datasets", []) if _flat_meta else [],
                }
            # Build render card for SSE
            # Build query info for frontend display
            _query_params = tool_input.get("params", {})
            _total = _flat_meta.get("total_events", 0) if _flat_meta else 0
            _ooc = _flat_meta.get("ooc_count", 0) if _flat_meta else 0
            _ooc_rate = _flat_meta.get("ooc_rate", 0) if _flat_meta else 0
            card = {
                "type": "query_data",
                "mcp_name": result.get("mcp_name", ""),
                "flat_data": _flat_data,
                "flat_metadata": _flat_meta,
                "ui_config": _ui_config,
                "query_info": {
                    "mcp": result.get("mcp_name", ""),
                    "params": _query_params,
                    "result_summary": f"{_total} events, {_ooc} OOC ({_ooc_rate}%)",
                },
            }
            new_render_cards.append(card)
        # Handle execute_skill returning pipeline result (Pipeline Skill)
        elif (tool_name == "execute_skill" and isinstance(result, dict)
              and result.get("is_pipeline_skill")):
            card = {
                "type": "pipeline",
                "pipeline_cards": result.get("pipeline_cards", []),
                "flat_data": result.get("flat_data"),
                "flat_metadata": result.get("flat_metadata"),
                "ui_config": result.get("ui_config"),
            }
            new_render_cards.append(card)
        else:
            # Build render card (for SSE events)
            render_card = _build_render_card(tool_name, tool_input, result)
            if render_card:
                new_render_cards.append(render_card)

        # Check if chart was rendered (via _notify_chart_rendered side effect)
        if isinstance(result, dict) and result.get("_chart_rendered"):
            chart_rendered = True

        # Track successful tool uses (for memory lifecycle)
        if isinstance(result, dict) and result.get("status") == "success":
            try:
                result_text = json.dumps(result, ensure_ascii=False, default=str)[:20000]
            except Exception:
                result_text = str(result)[:20000]
            new_tools_used.append({
                "tool": tool_name,
                "mcp_name": tool_input.get("mcp_name", ""),
                "params": {k: v for k, v in tool_input.items()
                           if k not in ("mcp_id", "mcp_name", "python_code", "params")},
                "result_text": result_text,
            })

        # Force synthesis on unrecoverable MCP/skill errors
        if isinstance(result, dict) and result.get("status") == "error":
            if tool_name in ("execute_mcp", "execute_skill"):
                if result.get("code") != "MISSING_PARAMS":
                    force_synth = True

        # Convert result to ToolMessage (trimmed for LLM context)
        result_content = _trim_result_for_llm(result)
        tool_messages.append(ToolMessage(
            content=result_content,
            tool_call_id=tc_id,
            name=tool_name,
        ))

    # Collect flat_data/ui_config from pipeline or query_data results
    _state_flat_data = None
    _state_flat_meta = None
    _state_ui_config = None
    for card in new_render_cards:
        if card.get("type") in ("query_data", "pipeline"):
            _state_flat_data = card.get("flat_data")
            _state_flat_meta = card.get("flat_metadata")
            _state_ui_config = card.get("ui_config")

    result_state: Dict[str, Any] = {
        "messages": tool_messages,
        "tools_used": new_tools_used,
        "render_cards": new_render_cards,
        "chart_already_rendered": chart_rendered,
        "last_spc_result": last_spc,
        "force_synthesis": force_synth or state.get("force_synthesis", False),
        # v1.4 Plan Panel — propagate the running plan so subsequent nodes
        # (synthesis, memory_lifecycle) can read final state.
        "plan_items": plan_items,
    }
    if _state_flat_data:
        result_state["flat_data"] = _state_flat_data
        result_state["flat_metadata"] = _state_flat_meta
    if _state_ui_config:
        result_state["ui_config"] = _state_ui_config

    return result_state


def _trim_result_for_llm(result: Any, max_chars: int = 4000) -> str:
    """Trim tool result for LLM context — keep llm_readable_data, drop heavy payloads."""
    if not isinstance(result, dict):
        return str(result)[:max_chars]

    # Prefer llm_readable_data (designed for LLM consumption)
    lrd = result.get("llm_readable_data")
    if lrd:
        if isinstance(lrd, str):
            return lrd[:max_chars]
        try:
            return json.dumps(lrd, ensure_ascii=False, default=str)[:max_chars]
        except Exception:
            pass

    # Fallback: strip heavy keys, serialize the rest
    trimmed = dict(result)
    for key in ("output_data", "ui_render_payload", "_raw_dataset", "dataset", "_data_profile"):
        trimmed.pop(key, None)
    try:
        text = json.dumps(trimmed, ensure_ascii=False, default=str)
        return text[:max_chars]
    except Exception:
        return str(result)[:max_chars]


# ── Chart DSL → Vega-Lite converter (Python port of ChartIntentRenderer) ──

_SERIES_COLORS = ["#4299e1", "#38a169", "#d69e2e", "#9f7aea", "#ed8936", "#e53e3e"]
_RULE_COLORS = {"danger": "#e53e3e", "warning": "#dd6b20", "center": "#718096"}


def _chart_intent_to_vega_lite(intent: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a _chart DSL dict to a Vega-Lite spec.

    Python equivalent of the frontend ChartIntentRenderer.intentToVegaLite().
    Used by execute_analysis to embed charts in contract.visualization.
    """
    chart_type = intent.get("type", "line")
    title = intent.get("title", "")
    data = intent.get("data", [])
    x = intent.get("x", "index")
    y = intent.get("y", ["value"])
    rules = intent.get("rules", [])
    highlight = intent.get("highlight")
    x_label = intent.get("x_label", x)
    y_label = intent.get("y_label", y[0] if y else "value")

    layers: List[Dict[str, Any]] = []

    # Main data series
    for i, y_field in enumerate(y):
        color = _SERIES_COLORS[i % len(_SERIES_COLORS)]

        if chart_type == "line":
            layers.append({
                "mark": {"type": "line", "color": color, "strokeWidth": 1.5},
                "encoding": {
                    "x": {"field": x, "type": "ordinal", "title": x_label,
                          "axis": {"labelAngle": -60, "labelFontSize": 7}},
                    "y": {"field": y_field, "type": "quantitative", "title": y_label,
                          "scale": {"zero": False}},
                },
            })
            # Point overlay
            point_encoding: Dict[str, Any] = {
                "x": {"field": x, "type": "ordinal"},
                "y": {"field": y_field, "type": "quantitative"},
            }
            if highlight:
                point_encoding["color"] = {
                    "condition": {
                        "test": f"datum.{highlight['field']} === {json.dumps(highlight['eq'])}",
                        "value": "#e53e3e",
                    },
                    "value": color,
                }
            else:
                point_encoding["color"] = {"value": color}
            layers.append({
                "mark": {"type": "point", "size": 50, "filled": True},
                "encoding": point_encoding,
            })
        elif chart_type == "bar":
            layers.append({
                "mark": {"type": "bar", "color": color},
                "encoding": {
                    "x": {"field": x, "type": "nominal", "title": x_label,
                          "axis": {"labelAngle": -45, "labelFontSize": 8}},
                    "y": {"field": y_field, "type": "quantitative", "title": y_label,
                          "scale": {"zero": False}},
                },
            })
        else:  # scatter
            layers.append({
                "mark": {"type": "point", "size": 60, "filled": True, "color": color},
                "encoding": {
                    "x": {"field": x, "type": "ordinal", "title": x_label},
                    "y": {"field": y_field, "type": "quantitative", "title": y_label,
                          "scale": {"zero": False}},
                },
            })

    # Rule lines (UCL, LCL, CL)
    for rule in rules:
        rule_color = _RULE_COLORS.get(rule.get("style", "danger"), "#e53e3e")
        dash = [3, 3] if rule.get("style") == "center" else [6, 4]
        layers.append({
            "mark": {"type": "rule", "color": rule_color, "strokeDash": dash, "strokeWidth": 1.5},
            "encoding": {"y": {"datum": rule["value"]}},
        })
        layers.append({
            "mark": {"type": "text", "align": "right", "dx": -2, "fontSize": 9,
                     "color": rule_color, "fontWeight": "bold"},
            "encoding": {
                "y": {"datum": rule["value"]},
                "text": {"value": f"{rule.get('label', '')}={rule['value']}"},
                "x": {"value": 0},
            },
        })

    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "width": "container",
        "height": 280,
        "title": {"text": title, "fontSize": 13, "anchor": "start"},
        "data": {"values": data},
        "layer": layers,
    }
