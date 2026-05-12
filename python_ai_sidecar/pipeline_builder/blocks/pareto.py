"""block_pareto — descending bar + cumulative %, 80/20 attribution chart."""

from __future__ import annotations

from typing import Any

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)
from python_ai_sidecar.pipeline_builder.blocks.line_chart import _materialize_paths, _records


class ParetoBlockExecutor(BlockExecutor):
    block_id = "block_pareto"

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
        category_col = params.get("category_column") or params.get("x")
        value_col = params.get("value_column") or None
        y = params.get("y")
        if value_col is None and isinstance(y, list) and y:
            value_col = y[0]
        if value_col is None and isinstance(y, str):
            value_col = y
        if not category_col or not value_col:
            raise BlockExecutionError(code="MISSING_PARAM", message="`category_column` and `value_column` (or x/y) required")

        if df.empty:
            return {"chart_spec": {"__dsl": True, "type": "empty", "title": title or "No data", "message": "上游資料為空", "data": []}}

        df = _materialize_paths(df, [category_col, value_col])
        for col in (category_col, value_col):
            if col not in df.columns:
                raise BlockExecutionError(code="COLUMN_NOT_FOUND", message=f"column '{col}' not in data")

        spec: dict[str, Any] = {
            "__dsl": True,
            "type": "pareto",
            "title": title,
            "data": _records(df),
            "x": category_col,
            "y": [value_col],
            "category_column": category_col,
            "value_column": value_col,
        }
        threshold = params.get("cumulative_threshold")
        if isinstance(threshold, (int, float)):
            spec["cumulative_threshold"] = float(threshold)
        return {"chart_spec": spec}
