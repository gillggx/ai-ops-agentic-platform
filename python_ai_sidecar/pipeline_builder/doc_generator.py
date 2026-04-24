"""Auto-doc generator — turns a Pipeline JSON into structured Agent-facing docs.

PR-C / Phase 4-D. The first cut is template-based (deterministic walk of nodes +
inputs). When AUTO_DOC_USE_LLM=True in settings, a future branch will swap in
an Anthropic call with few-shot examples; the output shape stays identical.
"""

from __future__ import annotations

import json
import re
from typing import Any


def _slugify(text: str) -> str:
    """Lowercase, spaces→hyphens, strip non-alphanumeric. Keeps it stable across time."""
    cleaned = re.sub(r"[^a-zA-Z0-9\s\-_]", "", text or "").strip().lower()
    cleaned = re.sub(r"[\s_]+", "-", cleaned)
    cleaned = re.sub(r"-+", "-", cleaned)
    return cleaned.strip("-")[:60] or "pipeline"


def _summarize_nodes(nodes: list[dict[str, Any]]) -> str:
    """Summarize the node chain in human form."""
    if not nodes:
        return "（空）"
    parts = []
    for n in nodes[:8]:
        label = n.get("display_label") or n.get("block_id", "?")
        parts.append(label)
    tail = "" if len(nodes) <= 8 else f" +{len(nodes) - 8} more"
    return " → ".join(parts) + tail


def generate_draft_doc(
    *,
    pipeline_id: int,
    pipeline_name: str,
    pipeline_version: str,
    pipeline_kind: str,
    description: str,
    pipeline_json: dict[str, Any],
) -> dict[str, Any]:
    """Template-based DraftDoc generator.

    Returned shape matches the planned LLM output so the Review Modal has a
    stable contract regardless of generator mode.
    """
    nodes = pipeline_json.get("nodes") or []
    declared_inputs = pipeline_json.get("inputs") or []

    has_alert = any(n.get("block_id") == "block_alert" for n in nodes)
    has_chart = any(n.get("block_id") == "block_chart" for n in nodes)

    # use_case — fall back to description; if empty, synthesize from node chain
    use_case = description.strip()
    if not use_case:
        use_case = (
            f"{_summarize_nodes(nodes)} — 使用者可用於{'巡檢並告警' if has_alert else '查詢並視覺化'}"
            f"（{pipeline_kind}）。"
        )

    # when_to_use — one-liner per logic node
    when_to_use: list[str] = []
    for n in nodes:
        bid = n.get("block_id", "")
        params = n.get("params") or {}
        if bid == "block_threshold":
            col = params.get("column", "?")
            if params.get("operator"):
                when_to_use.append(f"需偵測 {col} {params['operator']} {params.get('target')} 的情境")
            elif params.get("bound_type"):
                when_to_use.append(f"需偵測 {col} 超出 {params['bound_type']} bound 的情境")
        elif bid == "block_consecutive_rule":
            when_to_use.append(
                f"需偵測 {params.get('flag_column', '?')} 最近 {params.get('count', '?')} 次連續觸發"
            )
        elif bid == "block_weco_rules":
            rules = params.get("rules") or ["R1", "R2", "R5", "R6"]
            when_to_use.append(f"套用 SPC WECO rules（{','.join(rules)}）偵測異常 pattern")

    if not when_to_use:
        when_to_use.append(
            "無明確條件邏輯 — 建議補充 use_case + 觸發情境（手動編輯 description 重新產生）"
        )

    # inputs_schema — derived from declared inputs; descriptions come from user's
    # pipeline inputs (names must match exactly — we don't let LLM rename).
    inputs_schema: list[dict[str, Any]] = []
    for inp in declared_inputs:
        inputs_schema.append({
            "name": inp.get("name"),
            "type": inp.get("type", "string"),
            "required": bool(inp.get("required")),
            "description": inp.get("description") or f"Pipeline input '{inp.get('name')}'",
            "example": inp.get("example"),
        })

    # outputs_schema — infer from pipeline_kind + presence of chart/alert
    outputs_schema: dict[str, Any] = {
        "triggered_meaning": "True 表示 pipeline 的 terminal logic node 認定有異常 / 條件成立",
        "evidence_schema": (
            "DataFrame — 全部被評估的 rows + `triggered_row` bool column；"
            "額外欄位隨 logic 類型不同（threshold: violation_side/violated_bound；"
            "weco: triggered_rules/violation_side；consecutive: trigger_id/run_position 等）"
        ),
        "chart_summary": (
            "Pipeline Results 面板會按 sequence 順序顯示各 chart_spec"
            if has_chart
            else None
        ),
    }

    # example_invocation: example values from declared inputs (or name-based stub)
    example_values: dict[str, Any] = {}
    for inp in declared_inputs:
        if inp.get("example") is not None:
            example_values[inp["name"]] = inp["example"]
        elif inp.get("default") is not None:
            example_values[inp["name"]] = inp["default"]

    example_invocation = {
        "inputs": example_values or {"# hint": "no declared inputs on this pipeline"},
    }

    # tags — derived from pipeline_kind + detected block patterns
    tags: list[str] = [pipeline_kind]
    if any(n.get("block_id") == "block_process_history" for n in nodes):
        tags.append("spc")
    if any(n.get("block_id") == "block_weco_rules" for n in nodes):
        tags.append("weco")
    if any(n.get("block_id") == "block_cpk" for n in nodes):
        tags.append("capability")
    if any(n.get("block_id") == "block_correlation" for n in nodes):
        tags.append("correlation")

    slug = f"{_slugify(pipeline_name)}-v{pipeline_version}-p{pipeline_id}"

    return {
        "slug": slug,
        "name": pipeline_name,
        "use_case": use_case,
        "when_to_use": when_to_use,
        "inputs_schema": inputs_schema,
        "outputs_schema": outputs_schema,
        "example_invocation": example_invocation,
        "tags": tags,
    }
