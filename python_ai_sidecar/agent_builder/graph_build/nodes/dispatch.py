"""dispatch_op_node — pure routing: peek at plan[cursor].type, emit
op_dispatched SSE, hand off to call_tool_node.

The graph itself routes from call_tool_node back here when cursor < len(plan).
"""
from __future__ import annotations

import logging
from typing import Any

from python_ai_sidecar.agent_builder.graph_build.state import BuildGraphState


logger = logging.getLogger(__name__)


async def dispatch_op_node(state: BuildGraphState) -> dict[str, Any]:
    cursor = state.get("cursor", 0)
    plan = state.get("plan") or []
    if cursor >= len(plan):
        # Shouldn't happen — routing should have gone to finalize.
        return {"sse_events": [_event("op_dispatched", {"cursor": cursor, "skipped": True})]}

    op = plan[cursor]
    logger.info("dispatch_op_node: cursor=%d, type=%s", cursor, op.get("type"))
    return {
        "sse_events": [_event("op_dispatched", {"cursor": cursor, "op": op})],
    }


def _event(name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"event": name, "data": data}
