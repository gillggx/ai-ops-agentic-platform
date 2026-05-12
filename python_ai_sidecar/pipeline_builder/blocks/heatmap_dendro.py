"""block_heatmap_dendro — clustered correlation/value heatmap with dendrograms."""

from __future__ import annotations

from typing import Any

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)
from python_ai_sidecar.pipeline_builder.blocks.line_chart import _materialize_paths, _records


class HeatmapDendroBlockExecutor(BlockExecutor):
    block_id = "block_heatmap_dendro"

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

        spec: dict[str, Any] = {
            "__dsl": True,
            "type": "heatmap_dendro",
            "title": title,
            "data": [],
            "x": "",
            "y": [],
        }
        # Pre-computed matrix path
        if isinstance(params.get("matrix"), list) and isinstance(params.get("dim_labels"), list):
            spec["matrix"] = params["matrix"]
            spec["params"] = [str(p) for p in params["dim_labels"]]
        else:
            # Long-form path
            x_col = params.get("x_column") or params.get("x")
            y_col = params.get("y_column")
            value_col = params.get("value_column") or None
            if not x_col or not y_col or not value_col:
                raise BlockExecutionError(
                    code="MISSING_PARAM",
                    message="provide either pre-computed `matrix` + `dim_labels`, or long-form `x_column` / `y_column` / `value_column`",
                )
            if df.empty:
                return {"chart_spec": {"__dsl": True, "type": "empty", "title": title or "No data", "message": "上游資料為空", "data": []}}
            df = _materialize_paths(df, [x_col, y_col, value_col])
            for col in (x_col, y_col, value_col):
                if col not in df.columns:
                    raise BlockExecutionError(code="COLUMN_NOT_FOUND", message=f"column '{col}' not in data")
            spec["data"] = _records(df)
            spec["x_column"] = x_col
            spec["y_column"] = y_col
            spec["value_column"] = value_col
        if "cluster" in params:
            spec["cluster"] = bool(params["cluster"])
        return {"chart_spec": spec}
