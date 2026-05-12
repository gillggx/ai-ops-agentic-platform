"""block_probability_plot — normal Q-Q with Anderson-Darling p-value."""

from __future__ import annotations

from typing import Any

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)
from python_ai_sidecar.pipeline_builder.blocks.line_chart import _materialize_paths, _records


class ProbabilityPlotBlockExecutor(BlockExecutor):
    block_id = "block_probability_plot"

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

        if df.empty:
            return {"chart_spec": {"__dsl": True, "type": "empty", "title": title or "No data", "message": "上游資料為空", "data": []}}

        # Resolve value_col + materialize nested paths up-front so _records picks them up.
        _value_col_pre = params.get("value_column") or None
        if _value_col_pre is None:
            _y_pre = params.get("y")
            if isinstance(_y_pre, list) and _y_pre:
                _value_col_pre = _y_pre[0]
            elif isinstance(_y_pre, str):
                _value_col_pre = _y_pre
        if not isinstance(params.get("values"), list) and _value_col_pre:
            df = _materialize_paths(df, [_value_col_pre])

        spec: dict[str, Any] = {
            "__dsl": True,
            "type": "probability_plot",
            "title": title,
            "data": _records(df),
            "x": "",
            "y": [],
        }
        if isinstance(params.get("values"), list):
            spec["values"] = params["values"]
        else:
            value_col = params.get("value_column") or None
            y = params.get("y")
            if value_col is None and isinstance(y, list) and y:
                value_col = y[0]
            if value_col is None and isinstance(y, str):
                value_col = y
            if not value_col:
                raise BlockExecutionError(code="MISSING_PARAM", message="provide either `values` or `value_column`")
            if value_col not in df.columns:
                raise BlockExecutionError(code="COLUMN_NOT_FOUND", message=f"value_column '{value_col}' not in data")
            spec["value_column"] = value_col
        return {"chart_spec": spec}
