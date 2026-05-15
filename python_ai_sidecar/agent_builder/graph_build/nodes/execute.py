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
    # Defensive guard: reflect_op / repair_op may bail without rewinding
    # the cursor, leaving cursor past plan length. Route_after_call then
    # decides next_chunk vs finalize — we just must not crash here.
    if cursor >= len(plan):
        logger.warning(
            "call_tool_node: cursor=%d >= len(plan)=%d — no-op",
            cursor, len(plan),
        )
        return {}
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

    # ── Idempotency: re-execution after reflect_op rollback ───────────
    # reflect_op rewinds cursor and clears result_status for plan[K..N],
    # so call_tool_node runs each op again. Without dedup we'd:
    #   - add_node: create a 2nd real node for the same logical id,
    #     leaving the 1st as an orphan in the canvas
    #   - connect: stack parallel edges between the same ports
    # Detect re-execution and either remove the stale real node first
    # (add_node, since the LLM may have changed params) or skip
    # (connect, since the edge is idempotent).
    if op_type == "add_node":
        logical_id = op.get("node_id")
        prior_real_id = logical_to_real.get(logical_id) if logical_id else None
        if prior_real_id:
            try:
                await toolset.dispatch("remove_node", {"node_id": prior_real_id})
                logger.info(
                    "call_tool_node: cursor=%d re-exec %s — removed prior real %s",
                    cursor, logical_id, prior_real_id,
                )
                logical_to_real.pop(logical_id, None)
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "call_tool_node: prior remove for %s (real %s) failed: %s",
                    logical_id, prior_real_id, e,
                )
    elif op_type == "connect":
        src_real = args.get("from_node")
        src_port = args.get("from_port")
        dst_real = args.get("to_node")
        dst_port = args.get("to_port")
        existing = any(
            e.from_.node == src_real and e.from_.port == src_port
            and e.to.node == dst_real and e.to.port == dst_port
            for e in transient.pipeline_json.edges
        )
        if existing:
            logger.info(
                "call_tool_node: cursor=%d connect %s.%s→%s.%s already exists — skip",
                cursor, src_real, src_port, dst_real, dst_port,
            )
            op_updated = {**op, "result_status": "ok",
                          "result_node_id": None, "_skipped_idempotent": True}
            new_plan = list(plan)
            new_plan[cursor] = op_updated
            return {
                "plan": new_plan,
                "cursor": cursor + 1,
                "sse_events": [_event("op_completed", {
                    "cursor": cursor, "op": op_updated, "result": {"skipped": True},
                })],
            }

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

    # ── Phase F: auto-preview after add_node (source) / connect (target) ──
    # Right moment to snapshot per-node data shape: source blocks have output
    # the moment they're added; downstream blocks need ≥1 inbound edge before
    # preview is meaningful. Snapshot is non-fatal — preview failure just
    # records the error in trace, never blocks the build flow.
    exec_trace = dict(state.get("exec_trace") or {})
    preview_target = _pick_preview_target(op_type, op, result, logical_to_real, registry, transient)
    touched_logical_id: str | None = None
    if preview_target is not None:
        snapshot = await _snapshot_node(toolset, preview_target, cursor)
        if snapshot is not None:
            # exec_trace keyed by logical id (what the LLM uses), value tagged
            # with after_cursor so reflect knows when it was taken
            exec_trace[snapshot["logical_id"]] = snapshot
            touched_logical_id = snapshot["logical_id"]

    # ── v13.1 (2026-05-13): per-op trigger temporarily disabled ─────────
    # Earlier v13 fired contract_diff after every op which cascaded:
    # reflect_op patches → re-dispatched add_node ops → GUI canvas reset
    # mid-build → harness saw transient ✓ → saved partial state.
    #
    # For now we only fire on preview-raised executor errors (v8 trigger).
    # Contracts are still collected at plan time and surfaced to reflect_plan
    # via inspect_execution at finalize — see node_contracts in plan_node.
    block_id_for_issue = preview_target.get("block_id") if preview_target else None
    last_op_issue = _detect_op_issue(
        touched_logical_id, exec_trace, ops_executed=cursor + 1,
        block_id=block_id_for_issue,
    )

    logger.info("call_tool_node: cursor=%d %s ok", cursor, tool_name)
    return {
        "plan": new_plan,
        "cursor": cursor + 1,
        "logical_to_real": logical_to_real,
        "final_pipeline": new_pipeline_dict,
        "exec_trace": exec_trace,
        "last_op_issue": last_op_issue,
        "sse_events": [_event("op_completed", {
            "cursor": cursor, "op": op_updated, "result": result,
        })],
    }


# ── v8: per-op issue detector (no LLM, pure function) ────────────────────
# Triggers reflect_op routing when the just-completed op's snapshot exposes
# a data-level problem the validator can't catch ahead of time.
#
# Threshold: skip until at least MIN_OPS_BEFORE_CHECK ops have run. The
# first 1-2 source ops legitimately have no inbound data and rows=0 may be
# normal mid-state — only meaningful after the pipeline has some depth.
MIN_OPS_BEFORE_CHECK = 3


def _detect_op_issue(
    touched_logical_id: str | None,
    exec_trace: dict[str, dict],
    *,
    ops_executed: int,
    block_id: str | None,
) -> dict | None:
    """Return an ErrorEnvelope-shaped dict if the just-completed op's
    snapshot looks broken; None otherwise. Caller writes the result into
    state.last_op_issue."""
    if touched_logical_id is None:
        return None
    if ops_executed < MIN_OPS_BEFORE_CHECK:
        return None
    snap = exec_trace.get(touched_logical_id) or {}
    err = snap.get("error")
    rows = snap.get("rows")

    # Signal 1: executor / preview raised — column ref wrong, port mismatch,
    # block-internal failure, etc.
    if err:
        return {
            "code": "DATA_SHAPE_WRONG",
            "kind": "op_executor_error",
            "node_id": touched_logical_id,
            "block_id": block_id or snap.get("block_id"),
            "message": f"node '{touched_logical_id}' preview raised: {str(err)[:200]}",
            "given": {"error": str(err)[:300]},
            "expected": {"status": "success"},
            "hint": (
                "Inspect the block's required input columns + upstream "
                "output_columns. Most common: column name not in upstream "
                "data, or wrong path syntax."
            ),
        }

    # NOTE 2026-05-13: `rows == 0` mid-pipeline was originally a signal,
    # but it caused cascading reflect_op cycles in real test runs — the
    # data sometimes legitimately has zero OOC events / zero matches for
    # a filter, and the LLM keeps "fixing" what's really a data sparsity
    # condition. The cascade reset the canvas repeatedly and confused the
    # harness Save flow. Empty-data signals are still caught at finalize-
    # time by inspect_execution (which sees the WHOLE chain and can tell
    # apart "wrong filter" from "sparse data"). reflect_op now focuses on
    # the unambiguous case: the preview itself raised an error (column
    # ref wrong, type mismatch, port shape clash) — those are real bugs
    # in the op's params, not in the data.

    return None


def _pick_preview_target(
    op_type: str,
    op: dict[str, Any],
    result: dict[str, Any],
    logical_to_real: dict[str, str],
    registry: "SeedlessBlockRegistry",
    transient: "AgentBuilderSession",
) -> dict[str, Any] | None:
    """Decide which node (if any) to snapshot after this op.

    - add_node + source-category block: preview the new node (no inputs needed)
    - connect: preview the destination node (now has at least 1 inbound feed)
    - set_param on a node that already has all its incoming edges wired:
        preview that node so a wrong column name gets caught immediately
    - other ops (run_preview is explicit, remove_node, etc.): no auto-snapshot
    """
    if op_type == "add_node":
        real_id = result.get("node_id")
        logical_id = op.get("node_id") or _reverse_lookup(logical_to_real, real_id)
        block_id = op.get("block_id") or ""
        spec = next(
            (s for (n, _v), s in registry.catalog.items() if n == block_id),
            None,
        )
        if spec and (spec.get("category") == "source"):
            return {"real_id": real_id, "logical_id": logical_id, "block_id": block_id}
        return None
    if op_type == "connect":
        dst_logical = op.get("dst_id")
        dst_real = logical_to_real.get(dst_logical, dst_logical)
        # Read block_id from the live pipeline (transient.pipeline_json)
        block_id = ""
        for n in transient.pipeline_json.nodes:
            if n.id == dst_real:
                block_id = n.block_id
                break
        return {"real_id": dst_real, "logical_id": dst_logical, "block_id": block_id}
    if op_type == "set_param":
        nid_logical = op.get("node_id")
        nid_real = logical_to_real.get(nid_logical, nid_logical)
        # Only preview if the node has at least 1 inbound edge already
        has_in = any(
            e.to.node == nid_real for e in transient.pipeline_json.edges
        )
        if not has_in:
            return None
        block_id = ""
        for n in transient.pipeline_json.nodes:
            if n.id == nid_real:
                block_id = n.block_id
                break
        return {"real_id": nid_real, "logical_id": nid_logical, "block_id": block_id}
    return None


async def _snapshot_node(toolset, target: dict[str, Any], cursor: int) -> dict[str, Any] | None:
    """Run a tightly-bounded preview on `target.real_id` and return a compact
    trace snapshot. Returns None on hard failure (preview tool itself raised).

    Snapshot keeps it small for prompt budget:
      - rows: total row count (or None for non-df)
      - cols: column names only (no values, no dtypes)
      - sample: first row (dict) — gives LLM the actual shape
      - error: if preview returned an error status, capture it
    """
    real_id = target["real_id"]
    logical_id = target["logical_id"] or real_id
    block_id = target["block_id"]
    try:
        pv = await toolset.preview(node_id=real_id, sample_size=5)
    except Exception as ex:  # noqa: BLE001 — preview is best-effort
        logger.info("trace: preview %s threw: %s", real_id, ex)
        return {
            "logical_id": logical_id, "real_id": real_id, "block_id": block_id,
            "rows": None, "cols": [], "sample": None,
            "error": f"{type(ex).__name__}: {str(ex)[:200]}",
            "after_cursor": cursor,
        }

    status = pv.get("status")
    err = pv.get("error")
    preview_blob = pv.get("preview") or {}
    cols: list[str] = []
    sample: dict[str, Any] | None = None
    # preview shape from _summarize_preview (tools.py): the dataframe blob
    # uses key 'sample_rows', not 'rows_sample'. Older callers used 'rows'.
    # Check all three so nothing silently drops the sample row.
    for _port, blob in preview_blob.items():
        if not isinstance(blob, dict):
            continue
        if blob.get("type") == "dataframe":
            cols = list(blob.get("columns") or [])
            rows_sample = (
                blob.get("sample_rows")
                or blob.get("rows_sample")
                or blob.get("rows")
                or []
            )
            if rows_sample:
                sample = rows_sample[0] if isinstance(rows_sample[0], dict) else None
            break
        if blob.get("type") == "dict":
            snap = blob.get("snapshot")
            if isinstance(snap, dict):
                sample = {k: snap[k] for k in list(snap.keys())[:6]}
            break

    # v30 A3: build runtime_schema_md from preview sample for v30 prompt
    # builders (goal_plan, react_round). v27 prompt code still uses cols+sample
    # directly, so this is additive — no regression risk.
    runtime_schema_md = _build_runtime_schema_md(
        block_id=block_id,
        logical_id=logical_id,
        cols=cols,
        rows_sample=preview_blob,  # full blob so we can extract more rows
        toolset=toolset,
        total_rows=pv.get("rows"),
    )

    return {
        "logical_id": logical_id, "real_id": real_id, "block_id": block_id,
        "rows": pv.get("rows"),
        "cols": cols[:20],   # cap to keep prompt small
        "sample": _truncate_sample(sample),
        "runtime_schema_md": runtime_schema_md,  # v30
        "error": err if status != "success" else None,
        "after_cursor": cursor,
    }


def _build_runtime_schema_md(
    block_id: str,
    logical_id: str,
    cols: list[str],
    rows_sample: dict,
    toolset,
    total_rows: int | None,
) -> str:
    """v30 A3: reconstruct a small pandas DF from preview blob + run
    infer_runtime_schema(). Returns markdown string for v30 prompts.

    Best-effort — empty string on any error so v27 path stays unaffected.
    """
    try:
        import pandas as pd
        from python_ai_sidecar.pipeline_builder.schema_doc import infer_runtime_schema
    except Exception:
        return ""

    # Extract sample rows from preview blob (any dataframe port)
    sample_rows: list[dict] = []
    for _port, blob in (rows_sample or {}).items():
        if not isinstance(blob, dict):
            continue
        if blob.get("type") == "dataframe":
            sample_rows = (
                blob.get("sample_rows")
                or blob.get("rows_sample")
                or blob.get("rows")
                or []
            )
            break

    if not sample_rows or not cols:
        return ""

    try:
        df = pd.DataFrame(sample_rows)
        # Force col order to match preview blob (some samples drop cols if null)
        existing = [c for c in cols if c in df.columns]
        if existing:
            df = df[existing]
    except Exception:
        return ""

    # Look up block_spec for column_docs hints
    block_spec = None
    try:
        if toolset and hasattr(toolset, "registry"):
            block_spec = toolset.registry.get_spec(block_id, "1.0.0")
    except Exception:
        block_spec = None

    md = infer_runtime_schema(df, block_spec, node_id=logical_id)
    if md and total_rows is not None:
        # Patch first line to reflect TRUE total rows (not just sample size)
        md = md.replace(
            f"-> {len(df)} rows x",
            f"-> {total_rows} rows (sample showing {len(df)}) x",
            1,
        )
    return md


def _truncate_sample(sample: dict[str, Any] | None) -> dict[str, Any] | None:
    """Trim long string values; sample row should fit in ~500 chars total."""
    if not isinstance(sample, dict):
        return None
    out: dict[str, Any] = {}
    for k, v in list(sample.items())[:20]:
        if isinstance(v, str) and len(v) > 80:
            out[k] = v[:80] + "…"
        elif isinstance(v, list) and len(v) > 5:
            out[k] = v[:5] + ["…"]
        else:
            out[k] = v
    return out


def _reverse_lookup(logical_to_real: dict[str, str], real_id: str | None) -> str | None:
    if not real_id:
        return None
    for lid, rid in logical_to_real.items():
        if rid == real_id:
            return lid
    return real_id


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


def _strip_none(params: dict[str, Any]) -> dict[str, Any]:
    """Remove keys whose value is None. The LLM sometimes emits optional
    params as `key: null` to be explicit, but JSON Schema's `type: number`
    rejects null and our C6_PARAM_SCHEMA validator then fails the build.
    Treat null as "absent" — schema defaults / runtime defaults kick in.
    """
    return {k: v for k, v in (params or {}).items() if v is not None}


def _build_tool_args(op_type: str, op: dict[str, Any], logical_to_real: dict[str, str]) -> dict[str, Any] | str:
    """Build the kwargs dict for BuilderToolset.<tool>. Returns error string if
    a referenced logical id has no real-id binding yet."""
    if op_type == "add_node":
        return {
            "block_name": op.get("block_id"),
            "block_version": op.get("block_version") or "1.0.0",
            "params": _strip_none(op.get("params") or {}),
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
