"""layout_node — Phase 10-D Fix C.

Auto-layout the canvas at the graph level instead of relying on the frontend.
Pure Python: topological sort + LR grid placement. Mutates
state.final_pipeline.nodes[*].position so the SSE `done` event delivers a
ready-to-render canvas; frontend can stop running its dagre pass.

Algorithm (Kahn's BFS topological sort + level assignment):
  1. Compute in-degree for each node from edges.
  2. Roots (in_degree==0) → level 0.
  3. Pop one level at a time; each successor's level = max(parent levels) + 1.
  4. Within a level, lay out evenly along Y; X is level * STEP_X.
  5. Disconnected components offset on Y so they don't overlap.

Cycles fall through to a fallback diagonal layout (validator should have
rejected cycles already; this is just defense-in-depth).
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from python_ai_sidecar.agent_builder.graph_build.state import BuildGraphState
from python_ai_sidecar.pipeline_builder.pipeline_schema import PipelineJSON


logger = logging.getLogger(__name__)


# Spacing constants — match what the previous frontend dagre pass produced
# so users don't see a layout regression.
STEP_X = 220   # px between levels (LR direction)
STEP_Y = 130   # px between siblings within a level
ORIGIN_X = 40
ORIGIN_Y = 80


async def layout_node(state: BuildGraphState) -> dict[str, Any]:
    pipeline_dict = state.get("final_pipeline")
    if not pipeline_dict:
        return {}

    try:
        pipeline = PipelineJSON.model_validate(pipeline_dict)
    except Exception as ex:  # noqa: BLE001
        logger.warning("layout_node: invalid pipeline (%s) — skipped", ex)
        return {}

    if not pipeline.nodes:
        return {}

    # Build adjacency + in-degree.
    successors: dict[str, list[str]] = defaultdict(list)
    in_degree: dict[str, int] = {n.id: 0 for n in pipeline.nodes}
    for e in pipeline.edges:
        # Edges that reference unknown nodes (shouldn't happen post-validate)
        # are skipped silently to avoid blowing up layout.
        if e.from_.node not in in_degree or e.to.node not in in_degree:
            continue
        successors[e.from_.node].append(e.to.node)
        in_degree[e.to.node] += 1

    # Kahn's BFS — emit levels.
    level: dict[str, int] = {}
    frontier = [nid for nid, d in in_degree.items() if d == 0]
    for nid in frontier:
        level[nid] = 0
    cur_in_degree = dict(in_degree)
    visited = set(frontier)
    queue = list(frontier)
    while queue:
        nid = queue.pop(0)
        for succ in successors.get(nid, []):
            cur_in_degree[succ] -= 1
            # Level = max parent level + 1 (set when all parents seen).
            new_level = level.get(nid, 0) + 1
            if succ in level:
                level[succ] = max(level[succ], new_level)
            else:
                level[succ] = new_level
            if cur_in_degree[succ] == 0 and succ not in visited:
                visited.add(succ)
                queue.append(succ)

    # Cycle detection — any node not assigned a level → fallback diagonal.
    unassigned = [n.id for n in pipeline.nodes if n.id not in level]
    if unassigned:
        logger.warning("layout_node: %d nodes unreached (cycles?) — diagonal fallback",
                       len(unassigned))
        for i, nid in enumerate(unassigned):
            level[nid] = len({l for l in level.values()})  # extend last level
        # Cycles are extremely rare post-validate; this is a safety net.

    # Group by level → assign Y within each.
    by_level: dict[int, list[str]] = defaultdict(list)
    for nid, lv in level.items():
        by_level[lv].append(nid)

    new_positions: dict[str, dict[str, float]] = {}
    for lv in sorted(by_level.keys()):
        siblings = sorted(by_level[lv])  # stable order by id
        for j, nid in enumerate(siblings):
            new_positions[nid] = {
                "x": float(ORIGIN_X + lv * STEP_X),
                "y": float(ORIGIN_Y + j * STEP_Y),
            }

    # Apply.
    for n in pipeline.nodes:
        pos = new_positions.get(n.id)
        if pos is None:
            continue
        n.position.x = pos["x"]
        n.position.y = pos["y"]

    n_levels = max(by_level.keys()) + 1 if by_level else 0
    logger.info(
        "layout_node: laid out %d nodes across %d level(s)",
        len(pipeline.nodes), n_levels,
    )

    return {
        "final_pipeline": pipeline.model_dump(by_alias=True),
    }
