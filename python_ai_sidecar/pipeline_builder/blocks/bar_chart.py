"""block_bar_chart — primitive bar / grouped-bar chart."""

from __future__ import annotations

from typing import Any

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)
from python_ai_sidecar.pipeline_builder.blocks.line_chart import (
    _materialize_paths,
    _normalize_y,
    _records,
    _validate_columns,
)


class BarChartBlockExecutor(BlockExecutor):
    block_id = "block_bar_chart"

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

        df = _materialize_paths(df, [x, *y])
        _validate_columns(df, [x, *y], label="bar_chart")

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
            "type": "bar",
            "title": title,
            "data": _records(df),
            "x": x,
            "y": y,
        }
        if rules:
            spec["rules"] = rules
        if highlight:
            spec["highlight"] = highlight
        return {"chart_spec": spec}
