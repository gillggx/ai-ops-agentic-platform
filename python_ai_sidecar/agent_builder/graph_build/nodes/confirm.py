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

    logger.info(
        "confirm_gate_node: pausing for user confirm (session=%s, %d ops)",
        state.get("session_id"), len(plan),
    )

    # The interrupt payload is what the runner sees in the resulting
    # __interrupt__ marker — used to emit confirm_pending SSE.
    user_response = interrupt({
        "session_id": state.get("session_id"),
        "plan_summary": plan_summary,
        "plan_ops": [_op_summary(op) for op in plan],
        "n_ops": len(plan),
    })

    # When resumed, user_response is whatever was passed to Command(resume=...)
    confirmed = bool(user_response.get("confirmed")) if isinstance(user_response, dict) else bool(user_response)
    logger.info("confirm_gate_node: resumed with confirmed=%s", confirmed)

    return {
        "user_confirmed": confirmed,
        "sse_events": [_event("confirm_received", {"confirmed": confirmed})],
    }


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
