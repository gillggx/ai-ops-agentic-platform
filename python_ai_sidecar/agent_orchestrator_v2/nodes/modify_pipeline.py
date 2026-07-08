"""Modify-mode delta flow — Coordinator sees, Planner decides, Builder acts.

(2026-07-08) The chat iteration story: after a pipeline is on screen, a
follow-up like「拿掉區帶」/「加 tooltip 要有 lot ID」/「改看 EQP-05」must be a
MINIMAL DELTA on the existing pipeline, not a full rebuild + plan-confirm.

Division of labour (user-driven design, validated by planner_sim on the
real xbar SPC pipeline — all three cases produced one-line deltas):

  Coordinator (repair)  — the ONLY agent that touches reality. Reads the
      on-screen pipeline + its executed columns + the touched blocks'
      adjustable surface, and hands Planner an evidence-rich SITUATION
      REPORT (not a verdict).
  Planner               — pure function: report in → delta out. No tools.
  Builder               — applies the delta on the live canvas (source
      cache → the data fetch is reused, so the delta is nearly free).

Any failure at any step returns None → the caller falls through to the
existing rebuild path (G3 structural fallback). Worst case the user pays
the old rebuild price; never a wrong chart.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import AIMessage

from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client
from python_ai_sidecar.observability.episode_recorder import get_current_recorder
from python_ai_sidecar.pipeline_builder.parameterize import IDENTITY_KEYS

logger = logging.getLogger(
    "python_ai_sidecar.agent_orchestrator_v2.nodes.modify_pipeline")

# Chart blocks + the presentation params a delta may set on them.
# Kept in sync with coordinator_triage (imported to avoid drift).
from python_ai_sidecar.agent_orchestrator_v2.nodes.coordinator_triage import (
    _CHART_BLOCKS,
    _PATCHABLE as _CHART_PRESENTATION_PARAMS,
)

# Source-node identity params a delta may set (data-scope change = delta,
# not rebuild — user decision 2026-07-08).
_SOURCE_IDENTITY_PARAMS = set(IDENTITY_KEYS.keys())


def _source_node_ids(pj: Dict[str, Any]) -> set[str]:
    has_inbound = {(e.get("to") or {}).get("node") for e in (pj.get("edges") or [])}
    return {str(n.get("id")) for n in (pj.get("nodes") or [])
            if n.get("id") and n.get("id") not in has_inbound}


def columns_from_node_results(node_results: Dict[str, Any]) -> Dict[str, List[str]]:
    """Extract per-node output columns from an execute_native result."""
    out: Dict[str, List[str]] = {}
    for nid, nr in (node_results or {}).items():
        if not isinstance(nr, dict):
            continue
        prev = nr.get("preview")
        data = prev.get("data") if isinstance(prev, dict) else None
        cols = data.get("columns") if isinstance(data, dict) else None
        if isinstance(cols, list) and cols:
            out[str(nid)] = [str(c) for c in cols]
    return out


def _editable_params(node: Dict[str, Any], sources: set[str]) -> List[str]:
    nid = str(node.get("id"))
    if node.get("block_id") in _CHART_BLOCKS:
        return sorted(_CHART_PRESENTATION_PARAMS)
    if nid in sources:
        return sorted(_SOURCE_IDENTITY_PARAMS)
    return []


def build_situation_report(
    snapshot: Dict[str, Any],
    columns: Dict[str, List[str]],
    route: str,
    user_request: str,
) -> Dict[str, Any]:
    """Deterministic. Everything Planner needs, nothing it doesn't.

    Per node we surface: current params, its OUTPUT columns (so Planner
    knows what a tooltip/field reference can resolve to), and which params
    are editable in delta mode."""
    sources = _source_node_ids(snapshot)
    nodes_report = []
    for n in snapshot.get("nodes") or []:
        nid = str(n.get("id"))
        nodes_report.append({
            "id": nid,
            "block": n.get("block_id"),
            "params": n.get("params") or {},
            "output_columns": columns.get(nid, []),
            "editable_params": _editable_params(n, sources),
        })
    return {
        "user_request": user_request,
        "route": route,
        "nodes": nodes_report,
        "edges": [(e.get("from", {}).get("node"), e.get("to", {}).get("node"))
                  for e in (snapshot.get("edges") or [])],
        "rules": {
            "chart_presentation_params": sorted(_CHART_PRESENTATION_PARAMS),
            "source_identity_params": sorted(_SOURCE_IDENTITY_PARAMS),
            "note": "tooltip/欄位引用只能用該節點 output_columns 裡真實存在的欄位名。",
        },
    }


_PLANNER_SYS = """你是 Planner（修改模式，純推理，禁止呼叫任何工具）。
你會收到一份「現況報告」：現有 pipeline 每個節點的 block、目前參數、
該節點的 output_columns（實際有的欄位）、以及該節點在修改模式下可改的
editable_params。

針對使用者這句修改請求，輸出「最小增量」JSON：
{"mode": "delta" | "rebuild",
 "reason": "一句話",
 "ops": [{"op":"set_param","node":"<id>","params":{...}}]}

規則（硬性）：
- 只要在現有節點上改參數就能達成 → mode=delta，絕不 rebuild。
- 只能動報告裡該節點的 editable_params 列出的參數。
- tooltip / 欲顯示的欄位，若某節點的 output_columns 已含該欄位 → 直接
  set tooltip_fields，用真實欄位名；不要新增 select 或任何節點。
- 換機台 / 站點 / 時間窗 → 改來源節點的身分參數（如 tool_id / step /
  time_range），結構不動，這也是 delta。
- 只有當現有結構「根本無法」達成（需要全新的資料來源結構、或需要的欄位
  任何現有節點的 output_columns 都沒有且無法用改參數取得）才 mode=rebuild、
  ops 留空。
- style 類參數用巢狀物件，例如關掉區帶 = {"style":{"spc_zones":false}}。
只輸出 JSON，不要解釋。"""


async def planner_delta(report: Dict[str, Any], user_msg: str) -> Dict[str, Any]:
    client = get_llm_client()
    payload = json.dumps(report, ensure_ascii=False, default=str)
    resp = await client.create(
        system=_PLANNER_SYS,
        messages=[{"role": "user", "content": payload}],
        max_tokens=900,
    )
    raw = (resp.text or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        if raw.rstrip().endswith("```"):
            raw = raw.rstrip()[:-3]
    rec = get_current_recorder()
    if rec:
        rec.record("llm_usage", agent="planner",
                   input_tokens=getattr(resp, "input_tokens", None),
                   output_tokens=getattr(resp, "output_tokens", None),
                   cache_read=getattr(resp, "cache_read_input_tokens", None),
                   latency_ms=getattr(resp, "latency_ms", None))
    return json.loads(raw)


def apply_delta(
    snapshot: Dict[str, Any], ops: List[Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], str]:
    """Deterministic + whitelisted. set_param on an existing node only;
    chart nodes → presentation params; source nodes → identity params.
    style dicts merge. Never trusted; unknown node/param → reject."""
    if not isinstance(ops, list) or not ops:
        return None, "empty ops"
    nodes = {str(n.get("id")): n for n in (snapshot.get("nodes") or [])}
    sources = _source_node_ids(snapshot)
    out = json.loads(json.dumps(snapshot))  # deep copy (json-safe by construction)
    out_nodes = {str(n.get("id")): n for n in (out.get("nodes") or [])}
    touched = 0
    for item in ops:
        if not isinstance(item, dict) or item.get("op") != "set_param":
            return None, f"unsupported op {item.get('op') if isinstance(item, dict) else item!r}"
        nid = str(item.get("node") or "")
        sets = item.get("params")
        if nid not in nodes:
            return None, f"unknown node '{nid}'"
        if not isinstance(sets, dict) or not sets:
            return None, f"node '{nid}' has no params object"
        allowed = set(_editable_params(nodes[nid], sources))
        illegal = [k for k in sets if k not in allowed]
        if illegal:
            return None, f"params {illegal} not editable on node '{nid}' (allowed: {sorted(allowed)})"
        params = dict(out_nodes[nid].get("params") or {})
        for k, v in sets.items():
            if k == "style" and isinstance(v, dict) and isinstance(params.get("style"), dict):
                params["style"] = {**params["style"], **v}
            else:
                params[k] = v
        out_nodes[nid]["params"] = params
        touched += 1
    if touched == 0:
        return None, "ops touched nothing"
    return out, ""


async def run_modify(
    state: Dict[str, Any], snapshot: Dict[str, Any], route: str,
    reason: str, user_msg: str,
) -> Optional[Dict[str, Any]]:
    """Orchestrate report → planner delta → apply → execute. Returns the
    node dict on success, or None to fall through to rebuild (G3)."""
    from python_ai_sidecar.executor.real_executor import (
        all_blocks_native, execute_native,
    )
    from python_ai_sidecar.pipeline_builder.source_cache import get_session_cache

    if not all_blocks_native(snapshot):
        logger.info("modify: non-native blocks — pass through (G3)")
        return None
    sc = get_session_cache("chat-" + str(state.get("session_id") or "anon"))
    rec = get_current_recorder()

    # 1. columns — prefer the artifact the frontend shipped; else harvest once.
    columns = state.get("pipeline_columns") or {}
    if not columns:
        try:
            harvest = await execute_native(snapshot, source_cache=sc)
            if harvest.get("status") == "success":
                columns = columns_from_node_results(harvest.get("node_results") or {})
        except Exception as ex:  # noqa: BLE001
            logger.info("modify: column harvest failed (%s) — proceeding w/o columns", ex)

    # 2. situation report (deterministic) + observability step
    report = build_situation_report(snapshot, columns, route, user_msg)
    if rec:
        rec.record("situation_report", agent="repair", payload={
            "route": route,
            "nodes": [{"id": n["id"], "block": n["block"],
                       "output_columns": n["output_columns"],
                       "editable_params": n["editable_params"]}
                      for n in report["nodes"]],
        })

    # 3. planner delta (pure LLM) + observability step
    try:
        delta = await planner_delta(report, user_msg)
    except Exception as ex:  # noqa: BLE001 — G3 fallback
        logger.warning("modify: planner_delta failed (%s) — pass through", ex)
        return None
    mode = str((delta or {}).get("mode") or "")
    ops = (delta or {}).get("ops") or []
    if rec:
        rec.record("modify_plan", agent="planner", payload={
            "mode": mode, "reason": str((delta or {}).get("reason") or "")[:200],
            "ops": ops,
        })
    if mode != "delta" or not ops:
        logger.info("modify: planner says mode=%s — pass through to rebuild (G3)", mode)
        return None

    # 4. apply (deterministic, whitelisted)
    patched, why = apply_delta(snapshot, ops)
    if patched is None:
        logger.info("modify: delta rejected (%s) — pass through (G3)", why)
        return None

    # 5. execute (source cache → data reused) + card
    try:
        result = await execute_native(patched, source_cache=sc)
        if result.get("status") != "success":
            logger.info("modify: exec %s — pass through (G3)", result.get("status"))
            return None
    except Exception as ex:  # noqa: BLE001
        logger.warning("modify: exec failed (%s) — pass through", ex)
        return None

    ops_txt = "、".join(
        f"{o.get('node')}: {', '.join((o.get('params') or {}).keys())}"
        for o in ops if isinstance(o, dict))
    logger.info("modify: delta applied route=%s ops=%s", route, ops_txt)
    return {
        "pipeline_snapshot": patched,
        "render_cards": [{
            "type": "pb_pipeline",
            "pipeline_json": patched,
            "node_results": result.get("node_results") or {},
            "result_summary": result.get("result_summary"),
            "run_id": None,
        }],
        "force_synthesis": True,
        "messages": [AIMessage(content=f"已依需求微調（{reason or ops_txt}）。")],
        "coordinator_route": {"route": route, "reason": reason, "fast_path": True},
    }
