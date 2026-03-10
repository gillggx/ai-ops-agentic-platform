"""TaskContextExtractor — v14.1 Hybrid Memory

Derives task_type, data_subject, tool_name from user message + canvas_overrides
heuristically (no LLM call) so Stage 1 can pre-filter memory retrieval.

Called at the very start of agent_orchestrator._run_impl() before any LLM calls.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

# ── Keyword → task_type mapping ────────────────────────────────────────────────
# (keyword_list, task_type) pairs — first match wins
_KEYWORD_TASK_MAP: list[tuple[list[str], str]] = [
    (["spc", "管制圖", "chart", "draw_spc", "draw_chart", "畫圖", "趨勢圖", "trend"], "draw_chart"),
    (["診斷", "troubleshoot", "abnormal", "異常", "triage", "判斷", "診斷"], "troubleshooting"),
    (["排程", "routine", "巡檢", "schedule", "routine_check"], "routine_check"),
    (["draft skill", "建立技能", "新增技能", "建立 skill"], "skill_draft"),
    (["draft mcp", "建立 mcp", "新增 mcp", "新增資料源"], "mcp_draft"),
    (["記憶", "memory", "歷史", "history", "查詢記憶"], "memory_search"),
    (["偏好", "preference", "設定", "setting", "更改"], "preference"),
    (["data cleaning", "資料清洗", "清洗", "preprocessing"], "data_cleaning"),
]

# Equipment name pattern: 2-6 uppercase letters + 2-4 digits (e.g. TETCH01, CVDP02)
_EQUIPMENT_RE = re.compile(r"\b([A-Z]{2,6}\d{2,4})\b")

# Lot/wafer patterns (e.g. L2603001, W12345)
_LOT_RE = re.compile(r"\b([LWlw]\d{5,})\b")


def extract(
    message: str,
    canvas_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Return (task_type, data_subject, tool_name).

    Priority:
    1. canvas_overrides explicit _task_type / _data_subject / _tool_name
    2. canvas_overrides implicit (e.g. chart_name present → draw_chart)
    3. Message keyword matching → task_type
    4. Regex equipment/lot detection → data_subject
    tool_name is always None at Stage 1 (no tool has been called yet)
    """
    task_type: Optional[str] = None
    data_subject: Optional[str] = None
    tool_name: Optional[str] = None

    msg_lower = message.lower()

    # 1. Explicit metadata from canvas_overrides
    if canvas_overrides:
        task_type = canvas_overrides.get("_task_type") or task_type
        data_subject = canvas_overrides.get("_data_subject") or data_subject
        tool_name = canvas_overrides.get("_tool_name") or tool_name
        # Implicit: chart_name override → draw_chart task
        if not task_type and "chart_name" in canvas_overrides:
            task_type = "draw_chart"
        # Implicit: sigma_level / ucl / lcl override → draw_chart
        if not task_type and any(k in canvas_overrides for k in ("sigma_level", "ucl", "lcl")):
            task_type = "draw_chart"

    # 2. Keyword matching → task_type
    if not task_type:
        for keywords, t in _KEYWORD_TASK_MAP:
            if any(kw in msg_lower for kw in keywords):
                task_type = t
                break

    # 3. Equipment detection → data_subject (first match, uppercase)
    if not data_subject:
        matches = _EQUIPMENT_RE.findall(message)
        if matches:
            data_subject = matches[0].upper()
        else:
            # Fallback: lot id
            lot_matches = _LOT_RE.findall(message)
            if lot_matches:
                data_subject = lot_matches[0].upper()

    return task_type, data_subject, tool_name
