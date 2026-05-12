"""block_trend_wafer_maps — small-multiples grid of mini wafer maps over time."""

from __future__ import annotations

from typing import Any

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)
from python_ai_sidecar.pipeline_builder.blocks.line_chart import _materialize_paths, _records


class TrendWaferMapsBlockExecutor(BlockExecutor):
    block_id = "block_trend_wafer_maps"

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
            "type": "trend_wafer_maps",
            "title": title,
            "data": [],
            "x": "",
            "y": [],
        }
        # Pre-aggregated `maps` array path
        if isinstance(params.get("maps"), list):
            spec["maps"] = params["maps"]
        else:
            x_col = params.get("x_column") or "x"
            y_col = params.get("y_column") or "y"
            v_col = params.get("value_column") or None
            time_col = params.get("time_column") or None
            if not v_col or not time_col:
                raise BlockExecutionError(
                    code="MISSING_PARAM",
                    message="provide either pre-aggregated `maps` (list) or `value_column` + `time_column` (+ x/y columns)",
                )
            if df.empty:
                return {"chart_spec": {"__dsl": True, "type": "empty", "title": title or "No data", "message": "上游資料為空", "data": []}}
            pm_col = params.get("pm_column")
            df = _materialize_paths(df, [x_col, y_col, v_col, time_col] + ([pm_col] if pm_col else []))
            missing = [c for c in (x_col, y_col, v_col, time_col) if c not in df.columns]
            if missing:
                raise BlockExecutionError(code="COLUMN_NOT_FOUND", message=f"column(s) not in data: {missing}")
            spec["data"] = _records(df)
            spec["x_column"] = x_col
            spec["y_column"] = y_col
            spec["value_column"] = v_col
            spec["time_column"] = time_col
            if pm_col:
                if pm_col not in df.columns:
                    raise BlockExecutionError(code="COLUMN_NOT_FOUND", message=f"pm_column '{pm_col}' not in data")
                spec["pm_column"] = pm_col
        if isinstance(params.get("wafer_radius_mm"), (int, float)):
            spec["wafer_radius_mm"] = float(params["wafer_radius_mm"])
        if params.get("notch") in ("top", "bottom", "left", "right"):
            spec["notch"] = params["notch"]
        if isinstance(params.get("cols"), int) and params["cols"] > 0:
            spec["cols"] = int(params["cols"])
        if isinstance(params.get("grid_n"), int) and params["grid_n"] > 0:
            spec["grid_n"] = int(params["grid_n"])
        return {"chart_spec": spec}
