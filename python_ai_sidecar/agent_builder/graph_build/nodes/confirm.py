"""confirm_gate_node — emit confirm_pending SSE then interrupt the graph.

LangGraph's `interrupt()` pauses the graph and persists state via the
configured checkpointer. The runner returns control to the SSE handler,
which yields confirm_pending and ends the stream. Resume happens when
the frontend POSTs /agent/build/{session_id}/confirm; the runner calls
graph.invoke(Command(resume=confirmed), ...) to continue from here.

Only triggered when state.is_from_scratch is True. INCREMENTAL skips
straight to dispatch (graph routing decides this, not us).
"""
from __future__ import annotations

import logging
from typing import Any

from langgraph.types import interrupt

from python_ai_sidecar.agent_builder.graph_build.state import BuildGraphState


logger = logging.getLogger(__name__)


async def confirm_gate_node(state: BuildGraphState) -> dict[str, Any]:
    plan_summary = state.get("summary") or "(no summary)"
    plan = state.get("plan") or []
    structured_outputs = state.get("expected_outputs_structured") or []
    numbered_steps = _numbered_steps(plan)

    logger.info(
        "confirm_gate_node: pausing for user confirm (session=%s, %d ops, %d structured outputs)",
        state.get("session_id"), len(plan), len(structured_outputs),
    )

    # The interrupt payload is what the runner sees in the resulting
    # __interrupt__ marker — used to emit confirm_pending SSE.
    # v15 G2: add numbered_steps + expected_outputs_structured so the
    # frontend can render the upgraded review card with "改 step N" path.
    user_response = interrupt({
        "session_id": state.get("session_id"),
        "plan_summary": plan_summary,
        "expected_outputs": state.get("expected_outputs") or [],
        "expected_outputs_structured": structured_outputs,
        "plan_ops": [_op_summary(op) for op in plan],
        "numbered_steps": numbered_steps,
        "n_ops": len(plan),
        # echo clarifications so frontend can show "agent answered: X"
        "clarifications_applied": state.get("clarifications") or {},
    })

    # When resumed, user_response shape:
    #   confirm yes:    {"confirmed": True}
    #   confirm no:     {"confirmed": False}
    #   modify request: {"modify": True, "step_idx": int|None, "request": str}
    is_modify = (
        isinstance(user_response, dict)
        and bool(user_response.get("modify"))
    )
    if is_modify:
        step_idx = user_response.get("step_idx")
        req_text = str(user_response.get("request") or "").strip()
        modify_requests = list(state.get("modify_requests") or [])
        modify_requests.append({
            "step_idx": step_idx,
            "request": req_text,
            "at_cycle": state.get("modify_cycles", 0),
        })
        cycles = state.get("modify_cycles", 0) + 1
        logger.info(
            "confirm_gate_node: resumed with MODIFY (step_idx=%s, cycle=%d)",
            step_idx, cycles,
        )
        # user_confirmed=None signals "replan, not approve, not reject"
        # — graph route reads modify_requests / modify_cycles to decide.
        return {
            "user_confirmed": None,
            "modify_requests": modify_requests,
            "modify_cycles": cycles,
            "sse_events": [_event("modify_requested", {
                "step_idx": step_idx, "request": req_text[:200], "cycle": cycles,
            })],
        }

    confirmed = bool(user_response.get("confirmed")) if isinstance(user_response, dict) else bool(user_response)
    logger.info("confirm_gate_node: resumed with confirmed=%s", confirmed)

    return {
        "user_confirmed": confirmed,
        "sse_events": [_event("confirm_received", {"confirmed": confirmed})],
    }


def _numbered_steps(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """v15 G2: derive human-readable numbered steps from plan ops.

    Walks add_node + set_param ops in plan order, producing one step per
    add_node with the configured params merged in. Skips connect/preview
    (rendered as edges, not standalone steps).
    """
    # First pass: collect node ops with their params
    nodes: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for op in plan:
        t = op.get("type")
        if t == "add_node":
            lid = op.get("node_id") or f"n{len(order) + 1}"
            nodes[lid] = {
                "logical_id": lid,
                "block_id": op.get("block_id"),
                "params": dict(op.get("params") or {}),
            }
            order.append(lid)
        elif t == "set_param":
            lid = op.get("node_id")
            kv = op.get("params") or {}
            k, v = kv.get("key"), kv.get("value")
            if lid in nodes and k is not None:
                nodes[lid]["params"][k] = v
    # Render
    out: list[dict[str, Any]] = []
    for i, lid in enumerate(order, 1):
        n = nodes[lid]
        params = n["params"]
        # Compact param string
        param_parts: list[str] = []
        for k, v in list(params.items())[:6]:
            sv = repr(v) if not isinstance(v, str) else v
            if len(sv) > 30:
                sv = sv[:30] + "…"
            param_parts.append(f"{k}={sv}")
        params_str = ", ".join(param_parts) if param_parts else ""
        out.append({
            "step_idx": i,
            "logical_id": lid,
            "block_id": n["block_id"],
            "params_summary": params_str,
            "description": f"{n['block_id']}({params_str})" if params_str else n["block_id"] or "?",
        })
    return out


def _op_summary(op_dict: dict[str, Any]) -> str:
    """Compact one-line summary for confirm card."""
    t = op_dict.get("type", "?")
    if t == "add_node":
        return f"add {op_dict.get('block_id')} (as {op_dict.get('node_id', '?')})"
    if t == "connect":
        return f"connect {op_dict.get('src_id')}.{op_dict.get('src_port')} → {op_dict.get('dst_id')}.{op_dict.get('dst_port')}"
    if t == "set_param":
        p = op_dict.get("params") or {}
        return f"{op_dict.get('node_id')}.{p.get('key', '?')} = {p.get('value', '?')!r}"
    if t == "run_preview":
        return f"preview {op_dict.get('node_id')}"
    if t == "remove_node":
        return f"remove {op_dict.get('node_id')}"
    return t


def _event(name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"event": name, "data": data}
