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
只判斷使用者這句話屬於哪一類，輸出 JSON（不要給任何修改內容，那是後面 Planner 的事）：

{"route": "presentation_change" | "data_scope_change" | "new_build" | "fix_request" | "question",
 "reason": "一句話"}

route 判準：
- presentation_change：只改「呈現」— 樣式/區帶/提示欄位(tooltip)/標題/軸標籤/排序/柱上數值等，
  資料範圍不變。
- data_scope_change：換機台/站點/時間窗/指標，只是換「看誰的資料」，pipeline 結構不變。
- new_build：跟現有 pipeline 無關的全新需求。
- fix_request：使用者說結果錯了 / 圖不對 / 要修。
- question：純提問，不要求改東西。
presentation_change 與 data_scope_change 都會走「微調（delta）」路徑，
不會重建；其餘走既有流程。只輸出 JSON。"""

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
    """G1 entry triage — classify the follow-up against the on-screen
    pipeline. presentation_change / data_scope_change both delegate to the
    modify-mode delta flow (Coordinator report → Planner delta → Builder
    apply). Every other route (and any modify failure) falls through to the
    existing rebuild path.

    2026-07-08: triage now classifies ROUTE ONLY — the actual edit is the
    Planner's job (column-aware delta), so data-scope changes (換機台/站點)
    become deltas too instead of triggering a rebuild."""
    # ── deterministic pre-checks — zero LLM, zero latency ────────────
    snap = state.get("pipeline_snapshot")
    msg = str(state.get("user_message") or "")
    if not isinstance(snap, dict) or not (snap.get("nodes") or []):
        return {}
    if not msg.strip() or _CTRL_PREFIX.match(msg):
        return {}

    # ── narrow LLM classify (route only, one call) ───────────────────
    user_msg = (
        "== 使用者這句話 ==\n" + msg[:400]
        + "\n\n== 現役 pipeline 節點（id/block）==\n"
        + json.dumps([{"id": n.get("id"), "block": n.get("block_id")}
                      for n in (snap.get("nodes") or [])], ensure_ascii=False)[:800]
    )
    try:
        client = get_llm_client()
        resp = await client.create(
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
            max_tokens=300,
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
    if route not in ("presentation_change", "data_scope_change"):
        return {}  # existing flow owns new_build / fix_request / question

    # ── delegate to modify-mode delta flow (Coordinator → Planner) ───
    from python_ai_sidecar.agent_orchestrator_v2.nodes.modify_pipeline import (
        run_modify,
    )
    out = await run_modify(state, snap, route, reason, msg)
    if out is None:
        logger.info("triage: modify fell through (G3) — rebuild path")
        return {}  # G3 structural fallback: existing rebuild flow
    return out
