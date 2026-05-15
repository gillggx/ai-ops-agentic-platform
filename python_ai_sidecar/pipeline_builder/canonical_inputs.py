"""Canonical pipeline-input docs — shared source of truth for what the
common `$tool_id` / `$step` / `$lot_id` etc. inputs **mean**.

Used by:
  - macro_plan + compile_chunk: surface to LLM at build time so it knows
    what value to expect when params reference $name.
  - executor: runtime fallback when an LLM-generated pipeline declares one
    of these as required without supplying a default/example
    (`_CANONICAL_INPUT_FALLBACKS`).

Keep in sync with:
  - python_ai_sidecar/pipeline_builder/executor.py `_CANONICAL_INPUT_FALLBACKS`
  - python_ai_sidecar/agent_orchestrator_v2/nodes/intent_completeness.py `_CANONICAL_INPUTS`
"""
from __future__ import annotations

from typing import TypedDict


class CanonicalInputDoc(TypedDict):
    type: str         # "string" | "integer" | "number" | "boolean"
    sample: object    # representative value used as fallback + LLM hint
    description: str  # short Chinese description for the prompt


CANONICAL_INPUT_DOCS: dict[str, CanonicalInputDoc] = {
    "tool_id": {
        "type": "string",
        "sample": "EQP-01",
        "description": "機台 ID（單值，例 'EQP-01'）",
    },
    "equipment_id": {
        "type": "string",
        "sample": "EQP-01",
        "description": "機台 ID（tool_id 別名）",
    },
    "lot_id": {
        "type": "string",
        "sample": "LOT-0001",
        "description": "批次 ID",
    },
    "step": {
        "type": "string",
        "sample": "STEP_001",
        "description": "站點 step ID",
    },
    "chamber_id": {
        "type": "string",
        "sample": "CH-A",
        "description": "腔體 ID",
    },
    "recipe_id": {
        "type": "string",
        "sample": "RECIPE-A",
        "description": "Recipe 名稱 / ID",
    },
    "apc_id": {
        "type": "string",
        "sample": "APC-001",
        "description": "APC 控制器 ID",
    },
    "spc_chart": {
        "type": "string",
        "sample": "spc_xbar",
        "description": "SPC chart 名稱 (xbar / r / s / p / c)",
    },
    "fault_code": {
        "type": "string",
        "sample": "FC-001",
        "description": "FDC 故障碼",
    },
    "severity": {
        "type": "string",
        "sample": "med",
        "description": "嚴重度等級 (low / med / high)",
    },
    "time_range": {
        "type": "string",
        "sample": "24h",
        "description": "時間窗，Nh / Nd 格式（例 '1h', '24h', '7d'）",
    },
    "threshold": {
        "type": "number",
        "sample": 2,
        "description": "判定門檻值（int / float）",
    },
    "object_name": {
        "type": "string",
        "sample": "SPC",
        "description": "資料維度（'SPC' / 'APC' / 'DC' / 'RECIPE' / 'FDC' / 'EC'）",
    },
}


def lookup(name: str) -> CanonicalInputDoc | None:
    """Lookup by exact name (after stripping leading '$' and lowercasing)."""
    if not name:
        return None
    key = name.lstrip("$").lower()
    return CANONICAL_INPUT_DOCS.get(key)
