"""canvas_reset_node — deterministic graph step that wipes the canvas
(nodes + edges) when ``state.is_from_scratch`` is True, BEFORE any plan
op executes.

Why this is a graph node, not a prompt rule:
  Per CLAUDE.md「流程由 graph 決定，LLM 只做 reasoning」. The decision
  「from-scratch rebuild = blank canvas」is a hard runtime invariant —
  if we rely on the LLM to either (a) emit remove_node ops first or
  (b) understand「incremental」when it really wants to rebuild, we get
  the leftover-orphan-node bug user reported (multiple build attempts
  in a row leave disconnected leftovers from earlier plans).

What it preserves:
  - ``inputs[]`` (declare_input results — pipeline-level params)
  - ``metadata`` + ``name``
  - ``version``

What it clears:
  - ``nodes[]`` and ``edges[]``

Idempotent + cheap — runs once per build, only when is_from_scratch.
"""
from __future__ import annotations

import logging
from typing import Any

from python_ai_sidecar.agent_builder.graph_build.state import BuildGraphState


logger = logging.getLogger(__name__)


async def canvas_reset_node(state: BuildGraphState) -> dict[str, Any]:
    base = state.get("base_pipeline") or {}
    nodes = base.get("nodes") or []
    edges = base.get("edges") or []
    if not nodes and not edges:
        # Already empty — no-op (still emits SSE so frontend can log it).
        logger.info("canvas_reset_node: canvas already empty (from_scratch noop)")
        return {
            "sse_events": [_event("canvas_reset", {"cleared_nodes": 0, "cleared_edges": 0})],
        }

    cleared_pipeline = {
        **base,
        "nodes": [],
        "edges": [],
    }
    logger.info(
        "canvas_reset_node: cleared %d node(s) + %d edge(s) for from-scratch build",
        len(nodes), len(edges),
    )
    return {
        # Both base_pipeline and final_pipeline must agree — call_tool_node
        # reads final_pipeline if set, falling back to base_pipeline.
        "base_pipeline": cleared_pipeline,
        "final_pipeline": cleared_pipeline,
        # Reset cursor + logical id map for safety (should already be 0 / {}
        # at this point in the graph, but defensive).
        "logical_to_real": {},
        "sse_events": [_event("canvas_reset", {
            "cleared_nodes": len(nodes),
            "cleared_edges": len(edges),
        })],
    }


def _event(name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"event": name, "data": data}
