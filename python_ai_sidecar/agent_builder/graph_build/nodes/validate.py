"""validate_plan_node — pure code: check Op schema, block existence,
param schema match, port compatibility, DAG legality.

If any error is found, errors list is populated; graph routes to
repair_plan_node. If clean, falls through to confirm_gate.

Uses logical ids — real ids are not assigned yet.
"""
from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from python_ai_sidecar.agent_builder.graph_build.ops import Op, OpType
from python_ai_sidecar.agent_builder.graph_build.state import BuildGraphState
from python_ai_sidecar.pipeline_builder.seedless_registry import SeedlessBlockRegistry


logger = logging.getLogger(__name__)


async def validate_plan_node(state: BuildGraphState) -> dict[str, Any]:
    plan_raw = state.get("plan") or []
    if not plan_raw:
        return {
            "plan_validation_errors": ["plan is empty"],
            "sse_events": [_event("plan_validating", {"errors": ["plan is empty"]})],
        }

    registry = SeedlessBlockRegistry()
    registry.load()
    # All validation findings are HARD by default. plan_node now exposes
    # enum + type hints in the block catalog (see _format_catalog), so the
    # LLM can pick the right enum on the first try; if it still gets it
    # wrong, repair_plan has the same hints to fix it. Letting param-value
    # mismatches through as soft warnings broke the runtime auto-run after
    # build.
    errors: list[str] = []
    warnings: list[str] = []  # reserved for future advisory-only checks

    # Defensive normalization first — Haiku regularly stuffs the version into
    # block_id (e.g. "block_xbar_r@1.0.0") AND populates block_version, so
    # lookups become "block_xbar_r@1.0.0@1.0.0" and miss the catalog. Strip
    # the @version suffix in-place on the raw plan so call_tool_node sees the
    # cleaned id too. We do this before pydantic parse so any error message
    # already shows the cleaned form.
    cleaned_plan = [_strip_block_id_version(op) for op in plan_raw]
    plan_was_cleaned = any(c is not o for c, o in zip(cleaned_plan, plan_raw))
    plan_raw = cleaned_plan

    # Pass 1 — Op pydantic schema
    parsed: list[Op] = []
    for idx, raw in enumerate(plan_raw):
        try:
            parsed.append(Op.model_validate(raw))
        except ValidationError as ve:
            errors.append(f"Op#{idx}: schema invalid — {ve.errors()[0].get('msg', str(ve))}")
            parsed.append(None)  # type: ignore[arg-type]

    # Pass 2 — semantic checks (only on rows that parsed)
    declared_ids: set[str] = set()
    id_to_block: dict[str, tuple[str, str]] = {}  # logical_id → (block_name, version)

    for idx, op in enumerate(parsed):
        if op is None:
            continue

        if op.type == OpType.ADD_NODE:
            spec = registry.get_spec(op.block_id, op.block_version or "1.0.0")
            if spec is None:
                errors.append(
                    f"Op#{idx}: block '{op.block_id}@{op.block_version}' not in registry"
                )
                continue
            logical_id = op.node_id or f"n{len(declared_ids) + 1}"
            if logical_id in declared_ids:
                errors.append(f"Op#{idx}: logical id '{logical_id}' duplicated")
            declared_ids.add(logical_id)
            id_to_block[logical_id] = (op.block_id, op.block_version or "1.0.0")
            # Validate initial params against schema. Param KEY mismatch is a
            # hard error (LLM hallucinated a non-existent param). Param VALUE
            # mismatch (enum/type) is a soft warning — repair_plan often can't
            # fix domain mapping issues, so we let the plan proceed.
            schema_props = ((spec.get("param_schema") or {}).get("properties") or {})
            for k, v in (op.params or {}).items():
                if k not in schema_props:
                    errors.append(
                        f"Op#{idx}: add_node({op.block_id}) initial param '{k}' "
                        f"not in schema. Allowed: {list(schema_props.keys())}"
                    )
                    continue
                msg = _check_param_value(schema_props[k], k, v)
                if msg:
                    errors.append(f"Op#{idx}: add_node({op.block_id}) {msg}")

        elif op.type == OpType.SET_PARAM:
            if op.node_id not in id_to_block:
                errors.append(f"Op#{idx}: set_param targets unknown node '{op.node_id}'")
                continue
            block_name, block_version = id_to_block[op.node_id]
            spec = registry.get_spec(block_name, block_version) or {}
            schema_props = ((spec.get("param_schema") or {}).get("properties") or {})
            params = op.params or {}
            key = params.get("key")
            if key not in schema_props:
                errors.append(
                    f"Op#{idx}: set_param key '{key}' not in {block_name} schema. "
                    f"Allowed: {list(schema_props.keys())}"
                )
            else:
                msg = _check_param_value(schema_props[key], key, params.get("value"))
                if msg:
                    errors.append(f"Op#{idx}: set_param {msg}")

        elif op.type == OpType.CONNECT:
            if op.src_id not in id_to_block:
                errors.append(f"Op#{idx}: connect src '{op.src_id}' not declared")
            if op.dst_id not in id_to_block:
                errors.append(f"Op#{idx}: connect dst '{op.dst_id}' not declared")
            if op.src_id in id_to_block and op.dst_id in id_to_block:
                src_spec = registry.get_spec(*id_to_block[op.src_id]) or {}
                dst_spec = registry.get_spec(*id_to_block[op.dst_id]) or {}
                src_ports = {p.get("port"): p.get("type") for p in (src_spec.get("output_schema") or [])}
                dst_ports = {p.get("port"): p.get("type") for p in (dst_spec.get("input_schema") or [])}
                if op.src_port not in src_ports:
                    errors.append(
                        f"Op#{idx}: src '{op.src_id}' has no output port '{op.src_port}' "
                        f"(have: {list(src_ports.keys())})"
                    )
                if op.dst_port not in dst_ports:
                    errors.append(
                        f"Op#{idx}: dst '{op.dst_id}' has no input port '{op.dst_port}' "
                        f"(have: {list(dst_ports.keys())})"
                    )
                if (op.src_port in src_ports and op.dst_port in dst_ports
                        and src_ports[op.src_port] != dst_ports[op.dst_port]):
                    errors.append(
                        f"Op#{idx}: port type mismatch "
                        f"{op.src_port}({src_ports[op.src_port]}) → "
                        f"{op.dst_port}({dst_ports[op.dst_port]})"
                    )

        elif op.type in (OpType.RUN_PREVIEW, OpType.REMOVE_NODE):
            if op.node_id not in id_to_block:
                errors.append(f"Op#{idx}: {op.type.value} targets unknown node '{op.node_id}'")

    logger.info("validate_plan_node: %d hard errors, %d soft warnings, plan_cleaned=%s",
                len(errors), len(warnings), plan_was_cleaned)

    update: dict[str, Any] = {
        "plan_validation_errors": errors,
        "sse_events": [_event(
            "plan_validating",
            {"errors": errors, "warnings": warnings, "ok": len(errors) == 0},
        )],
    }
    if plan_was_cleaned:
        update["plan"] = plan_raw  # propagate cleaned block_ids to call_tool_node
    return update


def _check_param_value(prop_schema: dict[str, Any], key: str, value: Any) -> str | None:
    """Mirror PipelineValidator C6_PARAM_SCHEMA logic for one param value.

    Catches enum / type mismatches at plan time so repair_plan can fix them
    instead of the build silently producing a pipeline that fails the final
    validator (and confuses the user with status=failed despite ok ops).

    Returns an error message string, or None if the value passes.
    """
    if value is None:
        return None  # nullability is not enforced at this layer
    expected_type = prop_schema.get("type")
    if expected_type == "string" and not isinstance(value, str):
        return f"param '{key}' expected string, got {type(value).__name__} {value!r}"
    if expected_type == "integer" and not isinstance(value, int):
        return f"param '{key}' expected integer, got {type(value).__name__} {value!r}"
    if expected_type == "number" and not isinstance(value, (int, float)):
        return f"param '{key}' expected number, got {type(value).__name__} {value!r}"
    if expected_type == "boolean" and not isinstance(value, bool):
        return f"param '{key}' expected boolean, got {type(value).__name__} {value!r}"
    enum = prop_schema.get("enum")
    if enum is not None and value not in enum:
        return f"param '{key}' value {value!r} not in allowed enum {enum}"
    # Numeric range guard — only meaningful after the type check passes.
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        mn = prop_schema.get("minimum")
        mx = prop_schema.get("maximum")
        if mn is not None and value < mn:
            return f"param '{key}' value {value} < minimum {mn}"
        if mx is not None and value > mx:
            return f"param '{key}' value {value} > maximum {mx}"
    return None


def _strip_block_id_version(op_raw: dict[str, Any]) -> dict[str, Any]:
    """Strip a trailing '@<digit>...' suffix from add_node.block_id.

    Haiku regularly produces block_id='block_xbar_r@1.0.0' AND populates
    block_version='1.0.0' separately, so registry lookup becomes
    ('block_xbar_r@1.0.0', '1.0.0') and misses every catalog entry. This
    normalizes block_id to 'block_xbar_r' so downstream lookup succeeds
    without burning a repair_plan attempt on a pure formatting issue.
    """
    if not isinstance(op_raw, dict):
        return op_raw
    if op_raw.get("type") != "add_node":
        return op_raw
    bid = op_raw.get("block_id")
    if not isinstance(bid, str) or "@" not in bid:
        return op_raw
    head, _, tail = bid.rpartition("@")
    if head and tail and tail[:1].isdigit():
        cleaned = dict(op_raw)
        cleaned["block_id"] = head
        # Honor the suffix as version if block_version is missing.
        if not cleaned.get("block_version"):
            cleaned["block_version"] = tail
        return cleaned
    return op_raw


def _event(name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"event": name, "data": data}
