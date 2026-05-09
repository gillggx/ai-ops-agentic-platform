"""plan_node — LLM call #1: turn instruction into a list[Op] plan.

LLM uses logical ids n1, n2, ... — call_tool_node maps to real ids at
execution time. The plan is one-shot: no mid-flight extension (E8).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from python_ai_sidecar.agent_builder.graph_build.state import BuildGraphState
from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client


logger = logging.getLogger(__name__)


_SYSTEM = """你是 pipeline planner，把使用者需求拆成一個 plan = list[Op]。

Op type 共 5 種:
  add_node     — 加 1 個 block (帶 block_id, block_version="1.0.0", params)
  set_param    — 改某 node 的某個 param (params={"key":..., "value":...})
  connect      — 接 2 個 node (src_id, src_port, dst_id, dst_port)
  run_preview  — 預覽某 node 輸出 (node_id) — 通常不必加，僅 debug
  remove_node  — 移除某 node (node_id)

規則:
  1. 用邏輯 id n1, n2, n3, ... 編號（不要編真實 id）
  2. 順序：先 add_node，緊接該 node 的 set_param，最後才 connect
  3. connect 的 src_id / dst_id 都用邏輯 id
  4. 一次出完整 plan — 後面不能再補 op
  5. block 必須來自下面的目錄；不要編造 block_id
  6. 如需 preview/debug 輸出，可在中間或末尾加 run_preview op
  7. **block_id 不要帶 @version 後綴**。block_id 跟 block_version 是兩個分開的欄位：
     ✅ 對：{"block_id":"block_xbar_r", "block_version":"1.0.0"}
     ❌ 錯：{"block_id":"block_xbar_r@1.0.0", "block_version":"1.0.0"}（會找不到 block）

Block 目錄:
{BLOCK_CATALOG}

只輸出 JSON，不要 markdown fence:
{
  "plan_summary": "<一句話描述要建什麼>",
  "plan": [
    {"type":"add_node", "block_id":"...", "block_version":"1.0.0", "node_id":"n1", "params":{...}},
    {"type":"set_param", "node_id":"n1", "params":{"key":"...", "value":...}},
    {"type":"connect", "src_id":"n1", "src_port":"out", "dst_id":"n2", "dst_port":"in"},
    ...
  ]
}
"""


def _format_catalog(catalog: dict[tuple[str, str], dict[str, Any]]) -> str:
    """Single source of truth for block info — DB description (CLAUDE.md §1).

    Each line: name@version  in=[...]  out=[...]  params={key:enum-or-type, ...}
    Param enum/type info is critical — without it the LLM passes user phrases
    like 'spc_xbar_chart_value' to enum params expecting 'SPC'/'APC'/etc.
    """
    lines = []
    for (name, version), spec in sorted(catalog.items()):
        desc = (spec.get("description") or "").strip().split("\n", 1)[0]
        if len(desc) > 120:
            desc = desc[:120].rsplit(" ", 1)[0] + "…"
        in_ports = [p.get("port") for p in (spec.get("input_schema") or [])]
        out_ports = [p.get("port") for p in (spec.get("output_schema") or [])]
        param_props = ((spec.get("param_schema") or {}).get("properties") or {})
        param_hints = []
        for k, v in param_props.items():
            if not isinstance(v, dict):
                continue
            enum = v.get("enum")
            if enum is not None:
                # Cap to 6 enum values + ellipsis to keep prompt size sane.
                preview = enum[:6]
                more = "" if len(enum) <= 6 else f"…+{len(enum)-6}"
                param_hints.append(f"{k}∈{preview}{more}")
            else:
                t = v.get("type") or "?"
                param_hints.append(f"{k}:{t}")
        params_str = ", ".join(param_hints) if param_hints else "(none)"
        lines.append(
            f"- {name}@{version}  in={in_ports}  out={out_ports}  "
            f"params={{{params_str}}}  — {desc}"
        )
    return "\n".join(lines)


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.DOTALL)


def _strip_fence(text: str) -> str:
    text = text.strip()
    text = _FENCE_RE.sub("", text)
    return text.strip()


def _extract_first_json_object(text: str) -> dict[str, Any]:
    """Parse the first balanced JSON object from text. Tolerates trailing
    explanation text (a Haiku habit when the prompt asks for JSON only)."""
    text = _strip_fence(text)
    # Fast path — pure JSON.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Slow path — find the outermost {...} block by brace counting.
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object found in LLM output")
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError("unbalanced JSON object in LLM output")


async def plan_node(state: BuildGraphState) -> dict[str, Any]:
    """LLM produces a structured plan. Errors here downgrade gracefully —
    validate_plan_node will catch them and route to repair_plan."""
    from python_ai_sidecar.pipeline_builder.seedless_registry import SeedlessBlockRegistry

    registry = SeedlessBlockRegistry()
    registry.load()
    catalog_text = _format_catalog(registry.catalog)
    system = _SYSTEM.replace("{BLOCK_CATALOG}", catalog_text)

    base_pipeline = state.get("base_pipeline") or {}
    has_existing = bool(base_pipeline.get("nodes"))
    canvas_hint = (
        f"\n\n目前 canvas 已有 {len(base_pipeline.get('nodes', []))} 個 node、"
        f"{len(base_pipeline.get('edges', []))} 條 edge — incremental modification."
        if has_existing else "\n\n目前 canvas 是空的 — from-scratch build."
    )

    user_msg = state["instruction"] + canvas_hint
    client = get_llm_client()
    try:
        resp = await client.create(
            system=system,
            messages=[{"role": "user", "content": user_msg}],
            max_tokens=8192,  # Haiku 4.5 max; large plans (10+ ops) can overflow 4096
        )
        decision = _extract_first_json_object(resp.text or "")
    except Exception as ex:  # noqa: BLE001
        logger.warning("plan_node: LLM/parse failed (%s) — empty plan returned", ex)
        return {
            "plan": [],
            "plan_validation_errors": [f"plan_node failed: {ex}"],
            "sse_events": [_event("plan_proposed", {
                "plan": [], "summary": "(plan generation failed)",
                "error": str(ex),
            })],
        }

    plan_list = decision.get("plan") or []
    summary = (decision.get("plan_summary") or "").strip() or "(no summary)"

    # Determine FROM_SCRATCH heuristic: empty canvas + plan ≥ 3 ops
    is_from_scratch = (not has_existing) and (len(plan_list) >= 3)

    logger.info(
        "plan_node: produced %d ops, from_scratch=%s, summary=%r",
        len(plan_list), is_from_scratch, summary[:80],
    )

    return {
        "plan": plan_list,
        "is_from_scratch": is_from_scratch,
        "plan_validation_errors": [],
        "summary": summary,
        "sse_events": [_event("plan_proposed", {
            "plan": plan_list,
            "summary": summary,
            "from_scratch": is_from_scratch,
        })],
    }


def _event(name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"event": name, "data": data}
