"""block_ewma_cusum — EWMA + CUSUM small-shift detector with mode toggle.

Distinct from `block_ewma` (transform that emits smoothed values for downstream).
This block produces a chart_spec only.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)
from python_ai_sidecar.pipeline_builder.blocks.line_chart import _records


class EwmaCusumBlockExecutor(BlockExecutor):
    block_id = "block_ewma_cusum"

    async def execute(
        self,
        *,
        params: dict[str, Any],
        inputs: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        df = inputs.get("data")
        if not isinstance(df, pd.DataFrame):
            raise BlockExecutionError(code="INVALID_INPUT", message="'data' must be a DataFrame")
        title = params.get("title") or None
        mode = params.get("mode", "ewma")
        if mode not in ("ewma", "cusum"):
            raise BlockExecutionError(code="INVALID_PARAM", message="mode must be 'ewma' or 'cusum'")

        if df.empty:
            return {"chart_spec": {"__dsl": True, "type": "empty", "title": title or "No data", "message": "上游資料為空", "data": []}}

        spec: dict[str, Any] = {
            "__dsl": True,
            "type": "ewma_cusum",
            "title": title,
            "data": _records(df),
            "x": "",
            "y": [],
            "mode": mode,
        }
        if isinstance(params.get("values"), list):
            spec["values"] = params["values"]
        else:
            value_col = params.get("value_column") or None
            if not value_col:
                raise BlockExecutionError(code="MISSING_PARAM", message="provide either `values` or `value_column`")
            if value_col not in df.columns:
                raise BlockExecutionError(code="COLUMN_NOT_FOUND", message=f"value_column '{value_col}' not in data")
            spec["value_column"] = value_col
        for k in ("lambda", "k", "h", "target"):
            v = params.get(k)
            if isinstance(v, (int, float)):
                spec[k] = float(v)
        return {"chart_spec": spec}
