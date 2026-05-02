"""block_scatter_chart — primitive scatter chart with optional series_field."""

from __future__ import annotations

from typing import Any

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)
from python_ai_sidecar.pipeline_builder.blocks.line_chart import (
    _normalize_y,
    _records,
    _validate_columns,
)


class ScatterChartBlockExecutor(BlockExecutor):
    block_id = "block_scatter_chart"

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

        x = self.require(params, "x")
        y = _normalize_y(params.get("y"))
        if not y:
            raise BlockExecutionError(code="MISSING_PARAM", message="'y' must be a non-empty string or list")
        series_field = params.get("series_field") or None
        title = params.get("title") or None

        if df.empty:
            return {
                "chart_spec": {
                    "__dsl": True,
                    "type": "empty",
                    "title": title or "No data",
                    "message": "上游資料為空",
                    "data": [],
                }
            }

        cols = [x, *y]
        if series_field:
            cols.append(series_field)
        _validate_columns(df, cols, label="scatter_chart")

        rules = params.get("rules") or []
        highlight = None
        hf = params.get("highlight_field")
        if hf is not None:
            if hf not in df.columns:
                raise BlockExecutionError(
                    code="COLUMN_NOT_FOUND",
                    message=f"highlight_field '{hf}' not in data",
                )
            highlight = {"field": hf, "eq": params.get("highlight_eq", True)}

        spec: dict[str, Any] = {
            "__dsl": True,
            "type": "scatter",
            "title": title,
            "data": _records(df),
            "x": x,
            "y": y,
        }
        if rules:
            spec["rules"] = rules
        if highlight:
            spec["highlight"] = highlight
        if series_field:
            spec["series_field"] = series_field
        return {"chart_spec": spec}
