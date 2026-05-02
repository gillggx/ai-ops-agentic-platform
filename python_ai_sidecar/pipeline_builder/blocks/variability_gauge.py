"""block_variability_gauge — multi-level decomposition of a metric."""

from __future__ import annotations

from typing import Any

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)
from python_ai_sidecar.pipeline_builder.blocks.line_chart import _records


class VariabilityGaugeBlockExecutor(BlockExecutor):
    block_id = "block_variability_gauge"

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

        value_col = params.get("value_column") or None
        y = params.get("y")
        if value_col is None and isinstance(y, list) and y:
            value_col = y[0]
        if value_col is None and isinstance(y, str):
            value_col = y
        levels = params.get("levels")
        if not value_col or not isinstance(levels, list) or not levels:
            raise BlockExecutionError(
                code="MISSING_PARAM",
                message="`value_column` and `levels` (string[]) required (e.g. levels=['lot','wafer','tool'])",
            )

        if df.empty:
            return {"chart_spec": {"__dsl": True, "type": "empty", "title": title or "No data", "message": "上游資料為空", "data": []}}

        missing = [c for c in [value_col, *levels] if c not in df.columns]
        if missing:
            raise BlockExecutionError(code="COLUMN_NOT_FOUND", message=f"column(s) not in data: {missing}")

        spec: dict[str, Any] = {
            "__dsl": True,
            "type": "variability_gauge",
            "title": title,
            "data": _records(df),
            "x": levels[-1],
            "y": [value_col],
            "value_column": value_col,
            "levels": [str(l) for l in levels],
        }
        return {"chart_spec": spec}
