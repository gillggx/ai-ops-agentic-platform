"""block_box_plot — IQR + whiskers + outliers, optional nested grouping bracket.

Spec:
  inputs.data: DataFrame
  params.x:                 group column (inner bracket label, e.g. chamber)
  params.y:                 value column to compute quartiles on (string)
  params.group_by_secondary?: outer bracket column (e.g. tool)
  params.show_outliers?:    bool, default true
  params.expanded?:         bool, default true (only meaningful with secondary)
  params.y_label?:          y-axis title (defaults to value column name)
  params.title?
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)
from python_ai_sidecar.pipeline_builder.blocks.line_chart import _materialize_paths, _records


class BoxPlotBlockExecutor(BlockExecutor):
    block_id = "block_box_plot"

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
        y_raw = self.require(params, "y")
        y = y_raw[0] if isinstance(y_raw, list) and y_raw else y_raw
        if not isinstance(y, str):
            raise BlockExecutionError(code="MISSING_PARAM", message="'y' must be a column name (string)")
        secondary = params.get("group_by_secondary") or None
        title = params.get("title") or None
        y_label = params.get("y_label") or y

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

        df = _materialize_paths(df, [x, y] + ([secondary] if secondary else []))
        for col in [x, y] + ([secondary] if secondary else []):
            if col not in df.columns:
                raise BlockExecutionError(
                    code="COLUMN_NOT_FOUND",
                    message=f"box_plot column '{col}' not in data",
                )

        spec: dict[str, Any] = {
            "__dsl": True,
            "type": "box_plot",
            "title": title,
            "data": _records(df),
            "x": x,
            "y": [y],
            "y_label": y_label,
            "show_outliers": bool(params.get("show_outliers", True)),
            "expanded": bool(params.get("expanded", True)),
        }
        if secondary:
            spec["group_by_secondary"] = secondary
        return {"chart_spec": spec}
