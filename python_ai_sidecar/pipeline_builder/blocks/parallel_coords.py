"""block_parallel_coords — N parallel axes with brush filtering."""

from __future__ import annotations

from typing import Any

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)
from python_ai_sidecar.pipeline_builder.blocks.line_chart import _records


class ParallelCoordsBlockExecutor(BlockExecutor):
    block_id = "block_parallel_coords"

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

        dims = params.get("dimensions")
        if not isinstance(dims, list) or len(dims) < 2:
            raise BlockExecutionError(
                code="MISSING_PARAM",
                message="`dimensions` must be a list of >= 2 column names",
            )

        if df.empty:
            return {"chart_spec": {"__dsl": True, "type": "empty", "title": title or "No data", "message": "上游資料為空", "data": []}}

        dims = [str(d) for d in dims]
        missing = [d for d in dims if d not in df.columns]
        color_by = params.get("color_by") or None
        if color_by and color_by not in df.columns:
            missing.append(color_by)
        if missing:
            raise BlockExecutionError(code="COLUMN_NOT_FOUND", message=f"column(s) not in data: {missing}")

        spec: dict[str, Any] = {
            "__dsl": True,
            "type": "parallel_coords",
            "title": title,
            "data": _records(df),
            "x": "",
            "y": [],
            "dimensions": dims,
        }
        if color_by:
            spec["color_by"] = color_by
        if isinstance(params.get("alert_below"), (int, float)):
            spec["alert_below"] = float(params["alert_below"])
        return {"chart_spec": spec}
