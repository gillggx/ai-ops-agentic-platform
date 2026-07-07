"""coordinator_triage_node — G1 入口分診 + 波3 調圖秒改 (2026-07-07).

The unnatural interaction this fixes: the user iterates on a chart
(「底色改白」「提示加 recipe」「拆成兩張」) and every utterance was treated
as a BRAND-NEW pipeline build — 60-150s of plan/confirm/fetch for what is
a parameter tweak on an artifact that is already on screen.

Placement: right after load_context, ONLY when the conversation holds an
active pipeline (pipeline_snapshot with nodes). Decision ladder:

  deterministic pre-checks (zero LLM)
    - no active canvas / control-prefix message → pass through unchanged
    - message names a machine/step NOT in the current pipeline → this IS a
      data-scope change → pass through (rebuild path is correct)
  narrow LLM classify (one call)
    - presentation_change + param patch → FAST PATH: apply whitelisted
      chart-param patch, re-execute (wave-1 source cache → data reused),
      emit the updated pb_pipeline card, force_synthesis. Seconds.
    - anything else (new_build / data_scope_change / fix_request /
      question) → pass through to the existing flow (its classifiers own
      those routes; G1 just records the triage decision).

G3 兜底 is structural: any patch/exec failure falls through to the normal
flow — worst case the user pays the old rebuild price, never a wrong chart.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict

from langchain_core.messages import AIMessage

from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client

logger = logging.getLogger(
    "python_ai_sidecar.agent_orchestrator_v2.nodes.coordinator_triage")

# chart blocks whose params the fast path may touch
_CHART_BLOCKS = {
    "block_line_chart", "block_bar_chart", "block_xbar_r", "block_imr",
    "block_spc_panel", "block_apc_panel", "block_box_plot",
    "block_scatter_chart", "block_histogram_chart", "block_pareto",
    "block_probability_plot", "block_ewma_cusum", "block_data_view",
}
# params the fast path may set (presentation-only surface)
_PATCHABLE = {
    "style", "tooltip_fields", "weco_annotate", "title", "order",
    "show_values", "y_label", "x_label", "line_style", "show_markers",
    "marker_size", "spc_zones", "legend", "series_field", "max_rows",
}

_SYSTEM = """你是 Coordinator（入口分診）。對話中已經有一條建好的 pipeline（會給你摘要）。
判斷使用者這句話屬於哪一類，輸出 JSON：

{"route": "presentation_change" | "data_scope_change" | "new_build" | "fix_request" | "question",
 "reason": "一句話",
 "patch": [{"node": "<chart node id>", "set": {"<param>": <value>}}]}

route 判準：
- presentation_change：只改「呈現」— 樣式/區帶/提示欄位/標題/軸標籤/排序/柱上數值等，
  資料範圍（機台/站點/時間/指標）完全不變。此時必須給 patch（只能動 chart 節點的呈現參數）。
- data_scope_change：換機台/站點/時間窗/指標，或要新的資料。patch 留空。
- new_build：跟現有 pipeline 無關的新需求。patch 留空。
- fix_request：使用者說結果錯了/圖不對。patch 留空。
- question：純提問。patch 留空。
patch 的參數值必須具體可用（tooltip_fields 用資料真實欄位名）。
呈現參數面（只能動這些）：style:{spc_zones,line_style,show_markers,marker_size,x_label,y_label} /
tooltip_fields / weco_annotate / title / order / show_values。
「不要區帶/簡潔版」→ style:{"spc_zones":false}；「軸標籤」→ style:{"y_label":...} —
一律用 style 開關，不要動資料欄位參數（ucl_column 等是資料，不是樣式）。只輸出 JSON。"""

_CTRL_PREFIX = re.compile(r"^\s*\[(intent_confirmed|plan_decision|judge_decision|resume)")
_DIM_TOKEN = re.compile(r"(EQP-\d+|STEP_\d+)", re.IGNORECASE)


def _pipeline_dims(pj: Dict[str, Any]) -> set[str]:
    blob = json.dumps(pj.get("nodes") or [], ensure_ascii=False, default=str)
    return {m.upper() for m in _DIM_TOKEN.findall(blob)}


def apply_presentation_patch(
    pj: Dict[str, Any], patch: list[dict[str, Any]],
) -> tuple[Dict[str, Any] | None, str]:
    """Deterministic patch application. Whitelist enforced; never trusted."""
    if not isinstance(patch, list) or not patch:
        return None, "empty patch"
    nodes = {str(n.get("id")): n for n in (pj.get("nodes") or [])}
    out = json.loads(json.dumps(pj))  # deep copy (json-safe by construction)
    out_nodes = {str(n.get("id")): n for n in (out.get("nodes") or [])}
    touched = 0
    for item in patch:
        if not isinstance(item, dict):
            return None, "patch item is not an object"
        nid = str(item.get("node") or "")
        sets = item.get("set")
        if nid not in nodes:
            return None, f"unknown node '{nid}'"
        if nodes[nid].get("block_id") not in _CHART_BLOCKS:
            return None, f"node '{nid}' is not a chart block"
        if not isinstance(sets, dict) or not sets:
            return None, f"node '{nid}' patch has no set object"
        illegal = [k for k in sets if k not in _PATCHABLE]
        if illegal:
            return None, f"params {illegal} not presentation-patchable"
        params = dict(out_nodes[nid].get("params") or {})
        for k, v in sets.items():
            if k == "style" and isinstance(v, dict) and isinstance(params.get("style"), dict):
                params["style"] = {**params["style"], **v}
            else:
                params[k] = v
        out_nodes[nid]["params"] = params
        touched += 1
    if touched == 0:
        return None, "patch touched nothing"
    return out, ""


async def coordinator_triage_node(state: Dict[str, Any]) -> Dict[str, Any]:
    # ── deterministic pre-checks — zero LLM, zero latency ────────────
    snap = state.get("pipeline_snapshot")
    msg = str(state.get("user_message") or "")
    if not isinstance(snap, dict) or not (snap.get("nodes") or []):
        return {}
    if not msg.strip() or _CTRL_PREFIX.match(msg):
        return {}
    msg_dims = {m.upper() for m in _DIM_TOKEN.findall(msg)}
    new_dims = msg_dims - _pipeline_dims(snap)
    if new_dims:
        logger.info("triage[deterministic]: new data dims %s → rebuild path", new_dims)
        return {}  # data-scope change — existing flow owns it

    # ── narrow LLM classify (one call) ───────────────────────────────
    chart_nodes = [
        {"id": n.get("id"), "block": n.get("block_id"), "params": n.get("params")}
        for n in (snap.get("nodes") or [])
        if n.get("block_id") in _CHART_BLOCKS
    ]
    if not chart_nodes:
        return {}
    user_msg = (
        "== 使用者這句話 ==\n" + msg[:400]
        + "\n\n== 現役 pipeline 的 chart 節點 ==\n"
        + json.dumps(chart_nodes, ensure_ascii=False, default=str)[:1800]
        + "\n\n== 全部節點（id/block）==\n"
        + json.dumps([{"id": n.get("id"), "block": n.get("block_id")}
                      for n in (snap.get("nodes") or [])], ensure_ascii=False)[:600]
    )
    try:
        client = get_llm_client()
        resp = await client.create(
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
            max_tokens=700,
        )
        raw = (resp.text or "").strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            if raw.rstrip().endswith("```"):
                raw = raw.rstrip()[:-3]
        decision = json.loads(raw)
    except Exception as ex:  # noqa: BLE001 — G3 兜底: triage 失敗走原路
        logger.warning("triage: classify failed (%s) — pass through", ex)
        return {}

    route = str((decision or {}).get("route") or "")
    reason = str((decision or {}).get("reason") or "")[:200]
    logger.info("triage: route=%s reason=%s", route, reason[:80])
    if route != "presentation_change":
        return {}  # existing flow owns every other route (v1 pass-through)

    patched, why = apply_presentation_patch(
        snap, (decision or {}).get("patch") or [])
    if patched is None:
        logger.info("triage: patch rejected (%s) — pass through (G3)", why)
        return {}

    # ── FAST PATH: re-execute with the wave-1 source cache ───────────
    try:
        from python_ai_sidecar.executor.real_executor import (
            all_blocks_native, execute_native,
        )
        from python_ai_sidecar.pipeline_builder.source_cache import get_session_cache
        if not all_blocks_native(patched):
            return {}
        sc = get_session_cache("chat-" + str(state.get("session_id") or "anon"))
        result = await execute_native(patched, source_cache=sc)
        if result.get("status") != "success":
            logger.info("triage: fast-path exec %s — pass through (G3)",
                        result.get("status"))
            return {}
    except Exception as ex:  # noqa: BLE001
        logger.warning("triage: fast-path exec failed (%s) — pass through", ex)
        return {}

    ops_txt = "、".join(
        f"{i.get('node')}: {', '.join((i.get('set') or {}).keys())}"
        for i in (decision or {}).get("patch") or [] if isinstance(i, dict))
    logger.info("triage: presentation patch applied (%s)", ops_txt)
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
        "messages": [AIMessage(content=f"已更新圖表樣式（{reason or ops_txt}）。")],
        "coordinator_route": {"route": route, "reason": reason, "fast_path": True},
    }
