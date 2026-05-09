"""call_tool_node — calls the existing BuilderToolset methods directly.

Reuses tools.py implementations (add_node / set_param / connect / preview /
remove_node) so we get all the placeholder/port-type/schema validation
logic for free.

Logical → real id mapping: when add_node returns a real id, we record it
in state.logical_to_real and substitute on subsequent ops.
"""
from __future__ import annotations

import logging
from typing import Any

from python_ai_sidecar.agent_builder.graph_build.state import BuildGraphState
from python_ai_sidecar.agent_builder.session import AgentBuilderSession
from python_ai_sidecar.agent_builder.tools import BuilderToolset, ToolError
from python_ai_sidecar.pipeline_builder.pipeline_schema import PipelineJSON
from python_ai_sidecar.pipeline_builder.seedless_registry import SeedlessBlockRegistry


logger = logging.getLogger(__name__)


async def call_tool_node(state: BuildGraphState) -> dict[str, Any]:
    cursor = state.get("cursor", 0)
    plan = state.get("plan") or []
    op = plan[cursor]
    logical_to_real = dict(state.get("logical_to_real", {}))
    base_pipeline_dict = state.get("base_pipeline") or None
    final_pipeline = state.get("final_pipeline") or base_pipeline_dict

    # Reconstruct a transient session over the current pipeline so we can
    # call the existing BuilderToolset. Each call rehydrates from state —
    # graph_build doesn't keep an AgentBuilderSession across ticks.
    pipeline = (
        PipelineJSON.model_validate(final_pipeline) if final_pipeline
        else PipelineJSON(version="1.0", name="New Pipeline (Agent v2)",
                          metadata={"created_by": "agent_v2"}, nodes=[], edges=[])
    )
    transient = AgentBuilderSession.new(
        user_prompt=state.get("instruction", ""),
        base_pipeline=pipeline,
    )
    registry = SeedlessBlockRegistry()
    registry.load()
    toolset = BuilderToolset(transient, registry)

    op_type = op.get("type")
    args = _build_tool_args(op_type, op, logical_to_real)
    if isinstance(args, str):
        # logical-id resolution failed → mark op error
        return _error_update(cursor, plan, op, args)

    tool_name = _OP_TO_TOOL.get(op_type)
    if tool_name is None:
        return _error_update(cursor, plan, op, f"unknown op type '{op_type}'")

    try:
        result = await toolset.dispatch(tool_name, args)
    except ToolError as e:
        logger.info("call_tool_node: cursor=%d %s failed: %s", cursor, tool_name, e.message)
        return _error_update(cursor, plan, op, e.message, hint=e.hint)
    except Exception as e:  # noqa: BLE001
        logger.warning("call_tool_node: cursor=%d %s threw: %s", cursor, tool_name, e)
        return _error_update(cursor, plan, op, f"{type(e).__name__}: {e}")

    # Success — capture real id for add_node + advance cursor
    if op_type == "add_node":
        real_id = result.get("node_id")
        logical_id = op.get("node_id") or f"n{len(logical_to_real) + 1}"
        if real_id:
            logical_to_real[logical_id] = real_id

    # Persist updated pipeline in state
    new_pipeline_dict = transient.pipeline_json.model_dump(by_alias=True)

    op_updated = {**op, "result_status": "ok", "result_node_id": result.get("node_id")}
    new_plan = list(plan)
    new_plan[cursor] = op_updated

    logger.info("call_tool_node: cursor=%d %s ok", cursor, tool_name)
    return {
        "plan": new_plan,
        "cursor": cursor + 1,
        "logical_to_real": logical_to_real,
        "final_pipeline": new_pipeline_dict,
        "sse_events": [_event("op_completed", {
            "cursor": cursor, "op": op_updated, "result": result,
        })],
    }


_OP_TO_TOOL = {
    "add_node": "add_node",
    "connect": "connect",
    "set_param": "set_param",
    "run_preview": "preview",
    "remove_node": "remove_node",
}


def _resolve(logical_to_real: dict[str, str], lid: str | None) -> str | None:
    """Translate logical id → real id; pass through if not registered yet."""
    if lid is None:
        return None
    return logical_to_real.get(lid, lid)


def _build_tool_args(op_type: str, op: dict[str, Any], logical_to_real: dict[str, str]) -> dict[str, Any] | str:
    """Build the kwargs dict for BuilderToolset.<tool>. Returns error string if
    a referenced logical id has no real-id binding yet."""
    if op_type == "add_node":
        return {
            "block_name": op.get("block_id"),
            "block_version": op.get("block_version") or "1.0.0",
            "params": op.get("params") or {},
        }
    if op_type == "set_param":
        nid = _resolve(logical_to_real, op.get("node_id"))
        params = op.get("params") or {}
        return {
            "node_id": nid,
            "key": params.get("key"),
            "value": params.get("value"),
        }
    if op_type == "connect":
        src = _resolve(logical_to_real, op.get("src_id"))
        dst = _resolve(logical_to_real, op.get("dst_id"))
        if src is None or dst is None:
            return f"connect: cannot resolve logical ids src={op.get('src_id')} dst={op.get('dst_id')}"
        return {
            "from_node": src,
            "from_port": op.get("src_port"),
            "to_node": dst,
            "to_port": op.get("dst_port"),
        }
    if op_type == "run_preview":
        return {"node_id": _resolve(logical_to_real, op.get("node_id"))}
    if op_type == "remove_node":
        return {"node_id": _resolve(logical_to_real, op.get("node_id"))}
    return f"unsupported op type {op_type}"


def _error_update(cursor: int, plan: list, op: dict, msg: str, hint: str | None = None) -> dict[str, Any]:
    op_updated = {
        **op,
        "result_status": "error",
        "error_message": msg if not hint else f"{msg} | hint: {hint}",
    }
    new_plan = list(plan)
    new_plan[cursor] = op_updated
    return {
        "plan": new_plan,
        "sse_events": [_event("op_error", {"cursor": cursor, "op": op_updated})],
    }


def _event(name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"event": name, "data": data}
