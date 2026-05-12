"""validate_plan_node — pure code: check Op schema, block existence,
param schema match, port compatibility, DAG legality, op order,
and column-ref correctness against the logical pipeline.

If any error is found, errors list is populated; graph routes to
repair_plan_node. If clean, falls through to confirm_gate.

Uses logical ids — real ids are not assigned yet.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import ValidationError

from python_ai_sidecar.agent_builder.graph_build.ops import Op, OpType
from python_ai_sidecar.agent_builder.graph_build.state import BuildGraphState
from python_ai_sidecar.agent_builder.tools import (
    COLUMN_REF_KEYS,
    _columns_for_block_port,
)
from python_ai_sidecar.pipeline_builder.pipeline_schema import (
    EdgeEndpoint,
    NodePosition,
    PipelineEdge,
    PipelineJSON,
    PipelineNode,
)
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

    # Pass 3 — op-order + column-ref pre-check (Fix 2 + Fix 3 of Phase 10-C).
    # Walks plan in order, builds a transient PipelineJSON as it goes; at each
    # set_param with a column-ref key, requires the target node to already have
    # an inbound edge AND verifies the chosen column exists in upstream output.
    if not errors:  # don't bother if pass 2 already failed — repair_plan first
        order_errors = _check_op_order_and_column_refs(plan_raw, parsed, registry, state)
        errors.extend(order_errors)

    # Pass 4.5 — Phase 11 v13. Block-specific deep validators for params
    # whose schema is too free-form for pass-2 (free-form `object` types).
    # Per CLAUDE.md「flow 由 graph 決定」this lives here as a deterministic
    # validator, NOT as prompt rules — repair_plan picks it up and re-prompts.
    if not errors:
        deep_errors = await _check_freeform_object_params(parsed)
        errors.extend(deep_errors)

    # Pass 4 — Phase 11 skill-step terminal check.
    # When the caller is creating a Skill step's pipeline, the plan must end
    # with an add_node for block_step_check. SkillRunner reads that node's
    # output to decide pass/fail; without it the step has no verdict.
    #
    # 2026-05-12: these checks now fire UNCONDITIONALLY in skill_step_mode
    # (not gated behind `if not errors`). Previously the severity enum
    # violation from add_node(block_alert) won the first repair shot,
    # masking the architectural problem and letting repair keep block_alert
    # around. Now the LLM sees "remove block_alert" alongside whatever
    # other errors there are, so repair removes alert in one shot.
    if state.get("skill_step_mode"):
        terminal_ok = False
        for op in reversed(parsed):
            if op is None:
                continue
            if op.type == OpType.ADD_NODE:
                terminal_ok = (op.block_id == "block_step_check")
                break
        if not terminal_ok:
            errors.append(
                "skill_step_mode: pipeline must end with add_node block_step_check "
                "(needed for SkillRunner to read pass/fail). Add a final step_check "
                "node operating on the upstream filter/aggregate result."
            )

        # LLM kept wiring step_check → alert (with hallucinated 'triggered'
        # port) when user instruction said "觸發告警". In skill architecture
        # SkillRunner handles alerts; pipeline only reports pass/fail via
        # step_check. Multiple plan_unfixable failures on skill 54 traced
        # to this exact pattern.
        has_alert = any(
            op is not None and op.type == OpType.ADD_NODE and op.block_id == "block_alert"
            for op in parsed
        )
        if has_alert:
            errors.append(
                "skill_step_mode: pipeline must NOT contain block_alert — "
                "Skill 架構下 SkillRunner 從 block_step_check.check.pass 讀結果"
                "後自動發 alarm，pipeline 本身不該再寫 block_alert。"
                "移除所有 add_node(block_alert) 操作；終端只留 block_step_check。"
            )

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


def _check_op_order_and_column_refs(
    plan_raw: list[dict[str, Any]],
    parsed: list[Op],
    registry: SeedlessBlockRegistry,
    state: BuildGraphState,
) -> list[str]:
    """Phase 10-C Fix 2 + Fix 3.

    Walks the plan in order, maintaining a transient PipelineJSON. At each
    set_param touching a COLUMN_REF_KEYS param:
      - require target node has at least one inbound data edge (Fix 2)
      - require value to be a column in upstream's expected output (Fix 3)

    Reuses tools.py `_columns_for_block_port` so the logic matches what the
    existing v1 BuilderToolset.set_param does at write time — the only
    difference is we run it BEFORE call_tool so the LLM sees the error in
    plan-time and repair_plan can fix it.
    """
    errors: list[str] = []

    # Seed transient pipeline from base_pipeline (incremental builds).
    base = state.get("base_pipeline")
    if base:
        try:
            transient = PipelineJSON.model_validate(base)
        except Exception:  # noqa: BLE001
            transient = _empty_pipeline()
    else:
        transient = _empty_pipeline()

    # Track logical→real id mapping for incremental builds where base nodes
    # have real ids; new add_node ops use logical ids n1..nN. They coexist.
    next_logical_idx = 1
    logical_id_set: set[str] = {n.id for n in transient.nodes}

    # Class registry — we need to look up BlockRegistry-shaped catalog for
    # _columns_for_block_port. SeedlessBlockRegistry has the same .catalog
    # and .get_spec interface so it works as a drop-in.
    for idx, (raw, op) in enumerate(zip(plan_raw, parsed)):
        if op is None:
            continue

        if op.type == OpType.ADD_NODE:
            logical_id = op.node_id
            if not logical_id:
                logical_id = f"n{next_logical_idx}"
                next_logical_idx += 1
            logical_id_set.add(logical_id)
            transient.nodes.append(PipelineNode(
                id=logical_id,
                block_id=op.block_id,
                block_version=op.block_version or "1.0.0",
                position=NodePosition(x=0, y=0),
                params=dict(op.params or {}),
            ))

        elif op.type == OpType.CONNECT:
            if op.src_id in logical_id_set and op.dst_id in logical_id_set:
                edge_id = f"e{len(transient.edges) + 1}"
                transient.edges.append(PipelineEdge(
                    id=edge_id,
                    **{"from": EdgeEndpoint(node=op.src_id, port=op.src_port or "data")},
                    to=EdgeEndpoint(node=op.dst_id, port=op.dst_port or "data"),
                ))

        elif op.type == OpType.SET_PARAM:
            if not op.node_id or op.node_id not in logical_id_set:
                continue  # already flagged in pass 2
            params = op.params or {}
            key = params.get("key")
            value = params.get("value")
            if key not in COLUMN_REF_KEYS:
                # Apply param to transient (so downstream column derivations
                # see updates like agg_column on groupby_agg).
                _apply_set_param(transient, op.node_id, key, value)
                continue

            # Fix 2 — column-ref needs an inbound edge first.
            target_node = next((n for n in transient.nodes if n.id == op.node_id), None)
            inbound = [
                e for e in transient.edges if e.to.node == op.node_id
            ]
            if target_node is None:
                continue  # shouldn't happen
            if not inbound:
                errors.append(
                    f"Op#{idx}: set_param '{key}' on node '{op.node_id}' BEFORE any "
                    f"connect — column-ref params must come AFTER connecting upstream"
                )
                continue

            # Fix 3 — value must be in upstream's expected output columns.
            try:
                upstream_cols = _resolve_upstream_cols(transient, op.node_id, registry)
            except Exception as ex:  # noqa: BLE001
                logger.warning("col-ref pre-check unavailable for %s: %s", op.node_id, ex)
                _apply_set_param(transient, op.node_id, key, value)
                continue
            if upstream_cols is None:
                # fail-open: can't compute (multi-port edge case etc.)
                _apply_set_param(transient, op.node_id, key, value)
                continue

            # value can be string column name OR list of strings.
            bad = []
            if isinstance(value, list):
                bad = [v for v in value if isinstance(v, str) and v not in upstream_cols]
            elif isinstance(value, str):
                # tolerate $placeholder refs (resolved at runtime)
                if value and not value.startswith("$") and value not in upstream_cols:
                    bad = [value]
            if bad:
                preview = upstream_cols[:8]
                more = "" if len(upstream_cols) <= 8 else f"…+{len(upstream_cols)-8}"
                errors.append(
                    f"Op#{idx}: set_param '{key}'={bad!r} on node '{op.node_id}' — "
                    f"value not in upstream columns. Available: {preview}{more}"
                )
                continue

            _apply_set_param(transient, op.node_id, key, value)

    # Phase 11 v14 — FINAL-PASS column-ref recheck. Walks every node in
    # the now-built transient pipeline and verifies that every COLUMN_REF
    # param resolves to a column that actually exists in the current
    # upstream output. Catches the case where the LLM put a column-ref
    # directly in `add_node params={...}` (Pass 3 only walks set_param ops),
    # or where a connect was rewired AFTER the original set_param.
    #
    # User-reported bug: step_check.column='ooc_count' with step_check
    # wired to spc_long_form (no ooc_count) — got past validate, fired
    # at runtime.
    final_errors = _final_column_ref_check(transient, registry)
    errors.extend(final_errors)

    return errors


# Phase 11 v14: blocks where a key normally in COLUMN_REF_KEYS is actually
# the OUTPUT column name (not a ref to upstream). For these, skip the
# upstream-existence check on that key.
#   block_compute.column        : new column to add (output)
#   block_groupby_agg.agg_column : new aggregated column name (output)
#                                  but `group_by` IS an upstream ref
_OUTPUT_COLUMN_KEYS_BY_BLOCK: dict[str, set[str]] = {
    "block_compute": {"column"},
    "block_groupby_agg": {"agg_column"},
}


def _final_column_ref_check(
    pipeline: PipelineJSON,
    registry: SeedlessBlockRegistry,
) -> list[str]:
    """Re-check every column-ref param against the final transient pipeline
    state. Catches refs left behind in add_node's initial params (Pass 3
    only checks set_param ops) and refs invalidated by later rewiring."""
    errors: list[str] = []
    for node in pipeline.nodes:
        if not node.params:
            continue
        skip_keys = _OUTPUT_COLUMN_KEYS_BY_BLOCK.get(node.block_id, set())
        for key, value in node.params.items():
            if key not in COLUMN_REF_KEYS:
                continue
            if key in skip_keys:
                continue  # this param NAMES an output column, not an upstream ref
            try:
                upstream_cols = _resolve_upstream_cols(pipeline, node.id, registry)
            except Exception:  # noqa: BLE001
                continue  # fail-open
            if upstream_cols is None:
                continue  # fail-open (multi-port etc.)
            bad: list[str] = []
            if isinstance(value, list):
                bad = [v for v in value if isinstance(v, str) and v not in upstream_cols]
            elif isinstance(value, str):
                if value and not value.startswith("$") and value not in upstream_cols:
                    bad = [value]
            if not bad:
                continue
            preview = upstream_cols[:8]
            more = "" if len(upstream_cols) <= 8 else f"…+{len(upstream_cols)-8}"
            # Comma-string hint: LLM regularly writes "a,b,c" instead of ["a","b","c"]
            # for list-accepting params (group_by, columns). Without this hint the
            # repair_plan loop never figures out the right form (see plan_unfixable
            # case from skill 48 build at 2026-05-12 04:39 UTC).
            comma_split_hint = ""
            if (
                len(bad) == 1
                and isinstance(bad[0], str)
                and "," in bad[0]
                and all(c.strip() in upstream_cols for c in bad[0].split(",") if c.strip())
            ):
                parts = [c.strip() for c in bad[0].split(",") if c.strip()]
                comma_split_hint = (
                    f" (it looks like a comma-separated string — for multi-column "
                    f"params use a list: {key}={parts!r})"
                )
            # Producer hint — find a node in the pipeline whose declared
            # output_columns_hint contains the missing column. Lets the LLM
            # rewire instead of guessing.
            hint = _find_producer_hint(pipeline, registry, bad) if not comma_split_hint else ""
            errors.append(
                f"node '{node.id}' ({node.block_id}): {key}={bad!r} not in upstream "
                f"columns. Available: {preview}{more}.{comma_split_hint}{hint}"
            )
    return errors


def _find_producer_hint(
    pipeline: PipelineJSON,
    registry: SeedlessBlockRegistry,
    missing_cols: list[str],
) -> str:
    """Scan the transient pipeline for nodes whose output COULD contain any
    of the missing column names. Returns a short hint string for repair_plan
    or empty string if no candidate found.

    Looks at:
      1. block's output_columns_hint (static cols declared in seed.py)
      2. block_compute / block_groupby_agg : `column` / `agg_column` param
         is the dynamically-added column name
    """
    candidates: list[tuple[str, str]] = []  # (node_id, why)
    for node in pipeline.nodes:
        spec = registry.get_spec(node.block_id, node.block_version) or {}
        # 1. static hint
        for hint_col in (spec.get("output_columns_hint") or []):
            name = hint_col.get("name") if isinstance(hint_col, dict) else hint_col
            if name in missing_cols:
                candidates.append((node.id, f"{node.block_id} declares '{name}'"))
                break
        # 2. dynamic add (compute / groupby_agg name a new column via params)
        params = node.params or {}
        added_col = None
        if node.block_id == "block_compute":
            added_col = params.get("column")
        elif node.block_id == "block_groupby_agg":
            added_col = params.get("agg_column") or params.get("column")
        if added_col and added_col in missing_cols:
            candidates.append((node.id, f"{node.block_id} adds '{added_col}' via params"))

    if not candidates:
        return " (no node in this plan produces this column — add a block_compute or block_groupby_agg upstream)"
    nodes_list = ", ".join(f"{nid} ({why})" for nid, why in candidates[:3])
    return f" — try connecting from: {nodes_list}"


def _empty_pipeline() -> PipelineJSON:
    return PipelineJSON(
        version="1.0",
        name="(transient)",
        metadata={},
        inputs=[],
        nodes=[],
        edges=[],
    )


def _apply_set_param(pipeline: PipelineJSON, node_id: str, key: str, value: Any) -> None:
    node = next((n for n in pipeline.nodes if n.id == node_id), None)
    if node is None or not key:
        return
    node.params = {**(node.params or {}), key: value}


def _resolve_upstream_cols(
    pipeline: PipelineJSON,
    node_id: str,
    registry: SeedlessBlockRegistry,
) -> list[str] | None:
    """Find first inbound edge → ask tools._columns_for_block_port for that
    upstream node's output schema on the matching port."""
    for edge in pipeline.edges:
        if edge.to.node != node_id:
            continue
        upstream = next((n for n in pipeline.nodes if n.id == edge.from_.node), None)
        if upstream is None:
            continue
        return _columns_for_block_port(
            pipeline, upstream, registry, edge.from_.port,
        )
    return None


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


# ── Phase 11 v13 — block-specific deep validators ──────────────────────
#
# Pass 4.5 looks at every (add_node | set_param) for blocks whose param
# schema is a free-form object (block_compute.expression, block_mcp_call.args).
# Pass 2's generic `_check_param_value` only checks `type=='object'` — it
# can't tell whether the dict is structurally legal. These validators
# implement the structural rules in code (CLAUDE.md flow-in-graph rule),
# so repair_plan can pick up the error and re-prompt the LLM with the
# FIX suggestion in the error message.
#
# All structural rules come from the BLOCK / MCP DB description — not
# hardcoded here. We just walk the shape declared upstream.


def _accumulate_node_params(parsed: list[Op]) -> dict[str, dict[str, Any]]:
    """Replay add_node + set_param ops to compute the final params each
    logical node id will have. Returns {logical_id: {block_id, params}}."""
    state: dict[str, dict[str, Any]] = {}
    for op in parsed:
        if op is None:
            continue
        if op.type == OpType.ADD_NODE and op.node_id:
            state[op.node_id] = {
                "block_id": op.block_id,
                "params": dict(op.params or {}),
            }
        elif op.type == OpType.SET_PARAM and op.node_id and op.node_id in state:
            params = op.params or {}
            key = params.get("key")
            value = params.get("value")
            if key is not None:
                state[op.node_id]["params"][key] = value
    return state


def _walk_compute_expression(node: Any, path: str) -> list[str]:
    """Recursively check that ``node`` matches the expression grammar:
       literal | {column: str} | {op: str, operands: list}.
    Grammar source = python_ai_sidecar.pipeline_builder.blocks.compute._eval."""
    errors: list[str] = []
    if node is None or isinstance(node, (bool, int, float, str)):
        return errors  # literal — OK
    if isinstance(node, list):
        return errors  # list literal — OK (e.g. for `in` op)
    if not isinstance(node, dict):
        errors.append(
            f"{path}: must be literal | {{column: ...}} | {{op: ..., operands: [...]}}; "
            f"got {type(node).__name__}"
        )
        return errors
    if "column" in node:
        col = node["column"]
        if not isinstance(col, str) or not col:
            errors.append(f"{path}.column: must be a non-empty string; got {col!r}")
        return errors
    if "op" in node:
        operands = node.get("operands")
        if not isinstance(operands, list):
            errors.append(
                f"{path}: op '{node['op']}' missing 'operands' list "
                f"(got keys={sorted(node.keys())[:5]})"
            )
            return errors
        for i, child in enumerate(operands):
            errors.extend(_walk_compute_expression(child, f"{path}.operands[{i}]"))
        return errors
    errors.append(
        f"{path}: dict node must have 'column' or 'op' key "
        f"(got keys={sorted(node.keys())[:5]} — see block_compute description for grammar)"
    )
    return errors


def _check_sort_columns(cols: Any, path: str) -> list[str]:
    """Validate block_sort.columns shape: must be list of {column, order?}.
    Source of truth = python_ai_sidecar.pipeline_builder.blocks.sort:
    InvalidSortSpec raised when entry is not dict or missing 'column'."""
    errors: list[str] = []
    if not isinstance(cols, list):
        errors.append(
            f"{path}: must be a list of {{column, order}}, got {type(cols).__name__}. "
            f"Example: [{{'column':'ooc_count','order':'desc'}}]"
        )
        return errors
    if not cols:
        errors.append(f"{path}: empty list — at least one {{column, order}} required")
        return errors
    for i, entry in enumerate(cols):
        if not isinstance(entry, dict):
            errors.append(
                f"{path}[{i}]: must be {{column, order}} dict, got "
                f"{type(entry).__name__}({entry!r}). Example: "
                f"{{'column':'ooc_count','order':'desc'}}"
            )
            continue
        if "column" not in entry or not isinstance(entry["column"], str) or not entry["column"]:
            errors.append(
                f"{path}[{i}]: missing 'column' key (got keys={sorted(entry.keys())[:5]})"
            )
        order = entry.get("order")
        if order is not None and order not in ("asc", "desc"):
            errors.append(
                f"{path}[{i}]: order='{order}' invalid (must be 'asc' or 'desc')"
            )
    return errors


async def _check_mcp_call_args(node_id: str, args: Any) -> list[str]:
    """Check block_mcp_call.args against the MCP's DB-declared input_schema.

    Required fields (input_schema entries with required=true) MUST be
    present in args. We DO NOT hardcode any MCP-name-specific rules —
    the source of truth is mcp_definitions.input_schema in the Java DB.
    """
    errors: list[str] = []
    if not isinstance(args, dict):
        errors.append(
            f"node '{node_id}' (mcp_call): args must be an object/dict, "
            f"got {type(args).__name__}"
        )
        return errors
    # mcp_name is a sibling param (not inside args). Caller passes us only
    # args. The mcp_name lookup is done by caller.
    return errors


async def _check_freeform_object_params(parsed: list[Op]) -> list[str]:
    """Pass 4.5 entry: replay ops, find blocks with free-form object params,
    walk shape against grammar, query MCP DB schema for mcp_call args.

    Returns a list of error strings already prefixed with op-style locator;
    repair_plan_node will feed them back to the LLM verbatim.
    """
    from python_ai_sidecar.clients.java_client import JavaAPIClient
    from python_ai_sidecar.config import CONFIG

    errors: list[str] = []
    accumulated = _accumulate_node_params(parsed)

    # Collect mcp_name → set of nodes referencing it so we batch fetch
    # mcp_definitions (one HTTP per unique MCP).
    mcp_refs: dict[str, list[tuple[str, dict]]] = {}

    for node_id, info in accumulated.items():
        block_id = info.get("block_id")
        params = info.get("params") or {}

        if block_id == "block_compute":
            expr = params.get("expression")
            if expr is not None:
                expr_errors = _walk_compute_expression(expr, f"node '{node_id}'.expression")
                errors.extend(expr_errors)

        elif block_id == "block_sort":
            cols = params.get("columns")
            if cols is not None:
                sort_errors = _check_sort_columns(cols, f"node '{node_id}'.columns")
                errors.extend(sort_errors)

        elif block_id == "block_mcp_call":
            mcp_name = params.get("mcp_name")
            args = params.get("args", {})
            shape_errors = await _check_mcp_call_args(node_id, args)
            errors.extend(shape_errors)
            if isinstance(mcp_name, str) and mcp_name:
                mcp_refs.setdefault(mcp_name, []).append((node_id, params))

    # Resolve MCP definitions once (per unique mcp_name) and check args
    # against declared required fields.
    if mcp_refs:
        try:
            client = JavaAPIClient(
                base_url=CONFIG.java_api_url,
                token=CONFIG.java_internal_token,
                timeout_sec=CONFIG.java_timeout_sec,
            )
            for mcp_name, refs in mcp_refs.items():
                try:
                    mcp_def = await client.get_mcp_by_name(mcp_name)
                except Exception as ex:  # noqa: BLE001
                    logger.warning("validate: failed to fetch MCP '%s' schema: %s", mcp_name, ex)
                    continue
                if not mcp_def:
                    errors.append(
                        f"mcp_call: unknown mcp_name '{mcp_name}' "
                        f"(not registered in mcp_definitions)"
                    )
                    continue
                input_schema = mcp_def.get("input_schema") or mcp_def.get("inputSchema") or []
                # input_schema may be either a JSON-Schema-ish {properties:...}
                # OR a list of {name,type,required,description} entries
                # (mcp_definitions stores list-of-entries — see the MCP we
                # already inspected). Handle both.
                required_names: list[str] = []
                if isinstance(input_schema, list):
                    required_names = [
                        e.get("name") for e in input_schema
                        if isinstance(e, dict) and e.get("required") is True and e.get("name")
                    ]
                elif isinstance(input_schema, dict):
                    required_names = list(input_schema.get("required") or [])

                # MCP-level "at least one of" semantics aren't in JSON-Schema
                # by default. We rely on description's「Required params」
                # section if present (DB description is the source of truth
                # per CLAUDE.md). Pattern: "至少帶 X / Y / Z" line.
                desc = (mcp_def.get("description") or "")
                at_least_one_of = _parse_at_least_one_of(desc)

                for node_id, params in refs:
                    args = params.get("args") or {}
                    if not isinstance(args, dict):
                        continue
                    # Hard required (required=true)
                    missing_req = [n for n in required_names if n not in args]
                    if missing_req:
                        errors.append(
                            f"node '{node_id}' (mcp_call '{mcp_name}'): "
                            f"missing required args {missing_req}. "
                            f"See mcp_definitions.{mcp_name}.input_schema."
                        )
                    # At-least-one-of
                    if at_least_one_of and not any(k in args for k in at_least_one_of):
                        errors.append(
                            f"node '{node_id}' (mcp_call '{mcp_name}'): "
                            f"args must include at least ONE of {at_least_one_of}. "
                            f"This MCP returns 400 if all are missing — see its description."
                        )
        except Exception as ex:  # noqa: BLE001
            logger.warning("validate: MCP resolution batch failed: %s", ex)

    return errors


_AT_LEAST_RE = re.compile(
    r"至少帶?\s*([A-Za-z_][A-Za-z0-9_]*(?:\s*[/、]\s*[A-Za-z_][A-Za-z0-9_]*)+)",
)


def _parse_at_least_one_of(description: str) -> list[str]:
    """Find「至少帶 toolID / lotID / step」-style lines in MCP description.
    Returns the listed param names. Empty list if pattern not found.
    """
    if not description:
        return []
    m = _AT_LEAST_RE.search(description)
    if not m:
        return []
    raw = m.group(1)
    parts = [p.strip() for p in re.split(r"[/、]", raw)]
    return [p for p in parts if p]
