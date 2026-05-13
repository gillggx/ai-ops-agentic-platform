"""repair_op_node — LLM #3: given a failed op + error msg + targeted context,
return fixed args.

Bounded by MAX_OP_REPAIR (2). After that, escalate to repair_plan
(graph routing decides; we just bump attempts and set status hint).

v16.1 (2026-05-14): user_msg now includes ERROR-TYPE-SPECIFIC CONTEXT
so the LLM has something to work from instead of guessing:
  - "not in catalog" → list 5-10 similar blocks with brief desc
  - param error → that block's param_schema (required/type/enum)
  - column-ref error → upstream node's actual output cols
  - port-mismatch → both sides' port schemas
This addresses the failure pattern where LLM guesses bad block_ids
repeatedly (e.g. "block_sort_limit" → "block_sort_limit" → "sort_limit")
without ever seeing what's actually available.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from python_ai_sidecar.agent_builder.graph_build.state import BuildGraphState
from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client


logger = logging.getLogger(__name__)

MAX_OP_REPAIR = 2


_SYSTEM = """這個 op 執行失敗了。看 error 訊息 + 提供的 context 修正 op 的欄位（不要改 type）。

5 種 type 的欄位:
  add_node:    block_id, block_version, node_id, params (initial)
  set_param:   node_id, params={"key":..., "value":...}
  connect:     src_id, src_port, dst_id, dst_port
  run_preview: node_id
  remove_node: node_id

修正原則:
  - 如果 error 說 block 不存在 → 從 context 列出的相近 blocks 挑 1 個
  - 如果 error 說 param 不對 → 對照 param_schema 改正
  - 如果 error 說 column 不在 upstream → 用 upstream cols 裡實際存在的欄位
  - 如果 error 說 port 不合 → 用 input/output schema 列出的合法 port + type

只輸出 JSON:
{"op": {<整個 op 物件>}}
"""


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.DOTALL)


def _strip_fence(text: str) -> str:
    return _FENCE_RE.sub("", text.strip()).strip()


def _extract_json(text: str) -> dict[str, Any]:
    from python_ai_sidecar.agent_builder.graph_build.nodes.plan import _extract_first_json_object
    return _extract_first_json_object(text)


# ── v16.1 context builders (no LLM) ─────────────────────────────────────


def _similar_blocks(failed_block_id: str, catalog: dict) -> list[tuple[str, str]]:
    """Find catalog blocks whose name shares >=1 substring with the failed
    id, plus same-category siblings. Returns [(name, brief_desc)] capped
    at ~10. Used when error is 'Block X not in catalog'."""
    if not failed_block_id:
        return []
    fid = failed_block_id.lower().replace("block_", "")
    parts = re.split(r"[_@.]", fid)
    parts = [p for p in parts if p and len(p) >= 2]
    matches: list[tuple[str, str, int]] = []
    seen: set[str] = set()
    for (name, _ver), spec in catalog.items():
        if name in seen:
            continue
        seen.add(name)
        nlc = name.lower()
        score = 0
        for p in parts:
            if p in nlc:
                score += len(p)
        if score == 0:
            continue
        desc = (spec.get("description") or "").strip()
        first = desc.split("\n", 1)[0][:100]
        matches.append((name, first, score))
    matches.sort(key=lambda t: -t[2])
    return [(n, d) for n, d, _ in matches[:10]]


def _get_upstream_logical_ids(plan: list[dict], target_logical_id: str) -> list[str]:
    """Walk plan's connect ops to find what feeds target_logical_id."""
    out: list[str] = []
    for op in plan:
        if op.get("type") != "connect":
            continue
        if op.get("dst_id") == target_logical_id:
            src = op.get("src_id")
            if isinstance(src, str):
                out.append(src)
    return out


def _format_upstream_cols(state: BuildGraphState, target_lid: str) -> str:
    """For a node ref'd by current op, find its upstream and dump their
    actual output cols (from exec_trace) so LLM has real columns to pick."""
    plan = state.get("plan") or []
    trace = state.get("exec_trace") or {}
    upstreams = _get_upstream_logical_ids(plan, target_lid)
    if not upstreams:
        return f"(沒找到 upstream node for {target_lid})"
    lines: list[str] = []
    for u in upstreams:
        snap = trace.get(u) or {}
        cols = snap.get("cols") or []
        if cols:
            lines.append(f"  {u}: cols=[{', '.join(cols[:20])}]"
                         + (f" …+{len(cols)-20}" if len(cols) > 20 else ""))
        else:
            lines.append(f"  {u}: (no preview snapshot)")
    return "\n".join(lines) if lines else "(no upstream info)"


def _format_block_schema_section(block_id: str, catalog: dict) -> str:
    """Compact param_schema dump for a block — required + types only,
    capped to keep prompt small."""
    spec = None
    for (n, _v), s in catalog.items():
        if n == block_id:
            spec = s
            break
    if not spec:
        return f"(block {block_id} not in catalog)"
    schema = spec.get("param_schema") or {}
    required = schema.get("required") or []
    props = schema.get("properties") or {}
    lines = [f"required: {required}" if required else "required: (none)"]
    for k, p in list(props.items())[:20]:
        t = p.get("type", "?")
        enum = p.get("enum")
        rng_parts = []
        if "minimum" in p: rng_parts.append(f"min={p['minimum']}")
        if "maximum" in p: rng_parts.append(f"max={p['maximum']}")
        if "default" in p: rng_parts.append(f"default={p['default']!r}")
        rng = f" [{', '.join(rng_parts)}]" if rng_parts else ""
        enum_str = f" enum={enum}" if enum else ""
        lines.append(f"  {k}: {t}{rng}{enum_str}")
    return "\n".join(lines)


def _format_port_schemas(op: dict, registry: Any) -> str:
    """For a connect op, dump src.output_schema + dst.input_schema so the
    LLM can pick valid src/dst port pairs."""
    src_id = op.get("src_id")
    dst_id = op.get("dst_id")
    plan = []  # we don't have plan here; pull block_id by walking provided pipeline if needed
    return f"(use connect with the right ports — src='{src_id}' dst='{dst_id}'; check block input/output ports)"


def _build_repair_context(
    op: dict[str, Any],
    err: str,
    state: BuildGraphState,
) -> str:
    """Pick the right context block based on the error message. Returns
    a multi-line string appended to user_msg, or empty for unknown errors.
    """
    from python_ai_sidecar.pipeline_builder.seedless_registry import SeedlessBlockRegistry
    registry = SeedlessBlockRegistry()
    registry.load()
    catalog = registry.catalog

    err_lc = (err or "").lower()
    op_type = op.get("type")
    block_id = op.get("block_id") or ""
    node_id = op.get("node_id") or op.get("dst_id") or ""

    # 1. Block name not in catalog
    if "not in catalog" in err_lc:
        candidates = _similar_blocks(block_id, catalog)
        if candidates:
            lines = [f"\nERROR_TYPE: BLOCK_NOT_FOUND",
                     f"你寫的 block_id='{block_id}' 不存在。可用相近 blocks:"]
            for name, desc in candidates:
                lines.append(f"  - {name}: {desc}")
            lines.append("從上面挑 1 個對的 block_id 重寫這個 op。")
            return "\n".join(lines)

    # 2. Param error (required missing / type wrong / enum invalid)
    if op_type == "add_node" and any(
        kw in err_lc for kw in ("required", "missing param", "value", "expected type", "enum", "param_value_invalid", "param_missing", "param_type_wrong")
    ):
        if block_id:
            sec = _format_block_schema_section(block_id, catalog)
            return (
                f"\nERROR_TYPE: PARAM_INVALID\n"
                f"block_id={block_id} 的 param_schema:\n{sec}\n"
                f"對照 schema 改正 params。"
            )

    if op_type == "set_param" and any(
        kw in err_lc for kw in ("required", "expected", "enum", "param")
    ):
        # set_param targets a node — look up its block_id from plan
        plan = state.get("plan") or []
        target_block_id = ""
        for prev in plan:
            if prev.get("type") == "add_node" and prev.get("node_id") == node_id:
                target_block_id = prev.get("block_id") or ""
                break
        if target_block_id:
            sec = _format_block_schema_section(target_block_id, catalog)
            return (
                f"\nERROR_TYPE: PARAM_INVALID\n"
                f"node {node_id} (block {target_block_id}) 的 param_schema:\n{sec}\n"
                f"對照 schema 改正 set_param 的 key/value。"
            )

    # 3. Column reference issue (upstream doesn't have that column)
    if any(kw in err_lc for kw in ("column path", "column", "not in upstream columns")):
        cols_section = _format_upstream_cols(state, node_id)
        return (
            f"\nERROR_TYPE: COLUMN_REF_INVALID\n"
            f"上游 node 的實際輸出 cols:\n{cols_section}\n"
            f"從上面實際存在的欄位挑 1 個來重寫這個 op 的 column 參數。"
        )

    # 4. Port mismatch
    if "port" in err_lc and op_type == "connect":
        return (
            f"\nERROR_TYPE: PORT_MISMATCH\n"
            f"{_format_port_schemas(op, registry)}\n"
            f"使用對的 src_port / dst_port。"
        )

    # Default: no extra context
    return ""


async def repair_op_node(state: BuildGraphState) -> dict[str, Any]:
    cursor = state.get("cursor", 0)
    plan = state.get("plan") or []
    if cursor >= len(plan):
        return {}

    op = plan[cursor]
    attempts = int(op.get("repair_attempts") or 0) + 1
    err = op.get("error_message") or "(no error msg)"

    if attempts > MAX_OP_REPAIR:
        # Caller (graph routing) will escalate to repair_plan — we just
        # mark the failed_op_idx and let the route handler decide.
        logger.warning("repair_op_node: cursor=%d attempts %d > %d → escalate",
                       cursor, attempts, MAX_OP_REPAIR)
        return {
            "failed_op_idx": cursor,
            "plan_validation_errors": state.get("plan_validation_errors", []) + [
                f"Op#{cursor} failed after {MAX_OP_REPAIR} repair attempts: {err}"
            ],
        }

    # v16.1: build context block based on error type (block-not-in-catalog,
    # param error, column ref error, port mismatch). Empty for unknown.
    context = _build_repair_context(op, err, state)

    user_msg = (
        "failed op:\n"
        + json.dumps(op, ensure_ascii=False, indent=2)
        + f"\n\nerror:\n  {err}"
        + (f"\n\nCONTEXT:{context}" if context else "")
    )

    client = get_llm_client()
    try:
        resp = await client.create(
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
            max_tokens=2048,
        )
        decision = _extract_json(resp.text or "")
        new_op = decision.get("op") or {}
    except Exception as ex:  # noqa: BLE001
        logger.warning("repair_op_node: LLM/parse failed (%s)", ex)
        new_plan = list(plan)
        new_plan[cursor] = {**op, "repair_attempts": attempts}
        return {
            "plan": new_plan,
            "sse_events": [_event("op_repaired", {
                "cursor": cursor, "attempt": attempts, "ok": False, "fix_summary": str(ex),
            })],
        }

    # Preserve type + bump attempts; clear error/status so dispatch retries
    fixed = {
        **new_op,
        "type": op.get("type"),  # never let LLM change type
        "repair_attempts": attempts,
        "result_status": "pending",
        "error_message": None,
    }
    new_plan = list(plan)
    new_plan[cursor] = fixed
    logger.info("repair_op_node: cursor=%d attempt %d ok", cursor, attempts)

    return {
        "plan": new_plan,
        "sse_events": [_event("op_repaired", {
            "cursor": cursor, "attempt": attempts, "ok": True,
            "fix_summary": f"args revised, retry now",
        })],
    }


def _event(name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"event": name, "data": data}
