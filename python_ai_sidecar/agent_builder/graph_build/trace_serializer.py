"""Serialize exec_trace + plan into a compact human/LLM-readable form.

Used by reflect_op_node and reflect_plan_node to feed the LLM real data
shape at each pipeline step — not just symptoms. The format is optimized
for LLM consumption (uniform shape, predictable keys) AND for humans
debugging the trace (legible without JSON parsing).

The spec target:

  NODE TRACE:
    n1 [block_process_history params={tool_id:"EQP-01", limit:1, nested:true}]
       → rows=1, cols=[eventTime, toolID, spc_charts(list[3])]
       sample: {eventTime:"2026-05-13T10:00", spc_charts:[3 items]}

    n2 [block_unnest params={column:"spc_charts"}]
       ← from n1.data
       → rows=3, cols=[eventTime, name, value, is_ooc, ucl, lcl]

    n3 [block_filter params={column:"is_ooc", operator:"==", value:true}]
       ← from n2.data
       → rows=1   ⚠ COLLAPSE: 3 → 1

This module just builds that string; it does NOT decide what counts as a
collapse — that's the inspector / reflect prompt's job.
"""
from __future__ import annotations

import json
from typing import Any, Optional


# Cap to keep prompt budget bounded — 12 nodes × ~250 chars = ~3000 chars
_MAX_NODES = 12
_MAX_PARAM_VALUE_LEN = 60


def build_node_trace(
    plan: list[dict[str, Any]],
    exec_trace: dict[str, dict[str, Any]],
    final_pipeline: Optional[dict[str, Any]] = None,
) -> str:
    """Render a NODE TRACE block.

    Pulls the per-logical-node snapshot from `exec_trace` and merges with
    the plan's add_node ops to get the (block_id, params) for each node.
    If `final_pipeline` is provided, edges are also rendered so the LLM
    sees the data flow direction.
    """
    # 1. Build {logical_id → {block_id, params}} from plan add_node ops
    nodes: dict[str, dict[str, Any]] = {}
    for op in plan:
        if op.get("type") != "add_node":
            continue
        lid = op.get("node_id")
        if not lid:
            continue
        nodes[lid] = {
            "block_id": op.get("block_id") or "?",
            "params": dict(op.get("params") or {}),
        }
    # 2. Layer in set_param ops (they override / add to params)
    for op in plan:
        if op.get("type") != "set_param":
            continue
        lid = op.get("node_id")
        kv = op.get("params") or {}
        k, v = kv.get("key"), kv.get("value")
        if lid and k is not None and lid in nodes:
            nodes[lid]["params"][k] = v

    # 3. Build {logical_id → list[upstream logical_id]} from connect ops
    upstreams: dict[str, list[str]] = {lid: [] for lid in nodes}
    for op in plan:
        if op.get("type") != "connect":
            continue
        src, dst = op.get("src_id"), op.get("dst_id")
        if src and dst and dst in upstreams:
            upstreams[dst].append(src)

    # 4. Format
    lines: list[str] = []
    rendered = 0
    for lid in nodes:
        if rendered >= _MAX_NODES:
            lines.append(f"  … {len(nodes) - rendered} more nodes elided")
            break
        info = nodes[lid]
        snap = exec_trace.get(lid)
        params_str = _format_params(info["params"])
        lines.append(f"  {lid} [{info['block_id']} params={params_str}]")
        for up in upstreams.get(lid, []):
            lines.append(f"     ← from {up}")
        if snap is not None:
            lines.append(_format_snapshot(snap))
        else:
            lines.append("     (no execution snapshot — not yet previewed)")
        rendered += 1

    if not lines:
        return "NODE TRACE: (empty plan)"
    return "NODE TRACE:\n" + "\n".join(lines)


def _format_params(params: dict[str, Any]) -> str:
    """Compact JSON-ish single line, truncating long string values."""
    parts: list[str] = []
    for k, v in params.items():
        s = _short(v)
        parts.append(f"{k}={s}")
    return "{" + ", ".join(parts) + "}"


def _short(v: Any) -> str:
    if isinstance(v, str):
        if len(v) > _MAX_PARAM_VALUE_LEN:
            return json.dumps(v[: _MAX_PARAM_VALUE_LEN - 1] + "…", ensure_ascii=False)
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, (list, dict)):
        try:
            s = json.dumps(v, ensure_ascii=False, default=str)
        except Exception:  # noqa: BLE001
            s = str(v)
        if len(s) > _MAX_PARAM_VALUE_LEN:
            return s[: _MAX_PARAM_VALUE_LEN - 1] + "…"
        return s
    return repr(v)


def _format_snapshot(snap: dict[str, Any]) -> str:
    """One-or-two line summary: rows, cols (compact), error if any, sample."""
    if snap.get("error"):
        return f"     ✗ preview error: {snap['error']}"
    rows = snap.get("rows")
    cols = snap.get("cols") or []
    sample = snap.get("sample")
    cols_str = _format_cols(cols, sample)
    lines = [f"     → rows={rows}, cols=[{cols_str}]"]
    if sample:
        # Sample is already truncated by call_tool_node; render as compact JSON
        try:
            s = json.dumps(sample, ensure_ascii=False, default=str)
        except Exception:  # noqa: BLE001
            s = str(sample)
        if len(s) > 200:
            s = s[:200] + "…"
        lines.append(f"     sample: {s}")
    return "\n".join(lines)


def _format_cols(cols: list[str], sample: Optional[dict[str, Any]]) -> str:
    """If sample has list/dict values, annotate the type in the col list.
    cols=[eventTime, spc_charts(list[3])]  ← list length signals shape.
    """
    annotated: list[str] = []
    for c in cols[:12]:
        if sample and c in sample:
            v = sample[c]
            if isinstance(v, list):
                annotated.append(f"{c}(list[{len(v)}])")
            elif isinstance(v, dict):
                annotated.append(f"{c}(obj)")
            else:
                annotated.append(c)
        else:
            annotated.append(c)
    if len(cols) > 12:
        annotated.append(f"…+{len(cols) - 12}")
    return ", ".join(annotated)
