"""block_alert — 當上游 logic node 觸發時產出告警 record。

Logic-node 統一 schema（v3.2+）下，Alert 變得很簡單：
  input:
    triggered (bool)       — 上游 logic node 是否觸發
    evidence  (DataFrame)  — 佐證 rows（未觸發時為空）

  output:
    alert (DataFrame, 0 or 1 row)
      severity, title, message, triggered, evidence_count,
      first_event_time, last_event_time, emitted_at

  triggered=False → output 空 DF（不做事）
  triggered=True  → output 一筆 alert；若 evidence 有 eventTime 欄，帶進 first/last

  title_template / message_template 支援 {column_name} 佔位符（從 evidence 第一筆取）
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)


_SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}


def _render_template(tpl: str, row: dict[str, Any]) -> str:
    """Substitute every {key} in `tpl` whose key is present in `row`; leave
    unknown placeholders as-is so a downstream layer (e.g. Java patrol's
    fillPlaceholdersFromTarget) can fill them from the event payload.

    str.format with `**row` aborts the whole substitution on the first
    KeyError, so {count} stayed literal whenever the template also had
    {toolID} (toolID wasn't in the count_rows evidence row).
    """
    import re
    if not tpl or "{" not in tpl:
        return tpl

    def _sub(m: "re.Match[str]") -> str:
        key = m.group(1)
        if key not in row:
            return m.group(0)  # leave {key} for downstream substitution
        v = row[key]
        if v is None:
            return ""
        return str(v)

    try:
        return re.sub(r"\{([A-Za-z_][A-Za-z_0-9]*)\}", _sub, tpl)
    except Exception:  # noqa: BLE001 — defensive; never break pipeline on template
        return tpl


def _find_time_range(evidence: pd.DataFrame) -> tuple[Optional[str], Optional[str]]:
    """If evidence has an 'eventTime' column, return (first, last) as iso strings."""
    if "eventTime" not in evidence.columns or evidence.empty:
        return None, None
    col = evidence["eventTime"]
    try:
        return str(col.min()), str(col.max())
    except (TypeError, ValueError):
        return None, None


class AlertBlockExecutor(BlockExecutor):
    block_id = "block_alert"

    async def execute(
        self,
        *,
        params: dict[str, Any],
        inputs: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        triggered = inputs.get("triggered")
        evidence = inputs.get("evidence")
        if not isinstance(triggered, (bool,)):
            raise BlockExecutionError(
                code="INVALID_INPUT",
                message="'triggered' input must be a bool (expect upstream logic node)",
            )
        if not isinstance(evidence, pd.DataFrame):
            raise BlockExecutionError(
                code="INVALID_INPUT",
                message="'evidence' input must be a DataFrame (expect upstream logic node)",
            )

        severity = params.get("severity", "MEDIUM")
        if severity not in _SEVERITIES:
            raise BlockExecutionError(
                code="INVALID_PARAM",
                message=f"severity must be one of {_SEVERITIES}",
            )

        if not triggered:
            # Not triggered → emit nothing. Pipeline result_summary still reflects
            # upstream logic node's triggered=False.
            return {"alert": pd.DataFrame()}

        title_tpl = params.get("title_template", "Pipeline Alert")
        message_tpl = params.get(
            "message_template",
            "Pipeline triggered with {evidence_count} evidence row(s)",
        )

        first_row_dict: dict[str, Any] = (
            evidence.iloc[0].to_dict() if not evidence.empty else {}
        )
        first_t, last_t = _find_time_range(evidence)
        evidence_count = int(len(evidence))
        ctx_for_tpl = {**first_row_dict, "evidence_count": evidence_count}

        alert_row = {
            "severity": severity,
            "title": _render_template(title_tpl, ctx_for_tpl),
            "message": _render_template(message_tpl, ctx_for_tpl),
            "triggered": True,
            "evidence_count": evidence_count,
            "first_event_time": first_t,
            "last_event_time": last_t,
            "emitted_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        return {"alert": pd.DataFrame([alert_row])}
