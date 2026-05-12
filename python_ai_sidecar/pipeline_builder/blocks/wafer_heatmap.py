"""block_wafer_heatmap — IDW-interpolated value field over a wafer outline."""

from __future__ import annotations

from typing import Any

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)
from python_ai_sidecar.pipeline_builder.blocks.line_chart import _materialize_paths, _records


def _validate_xyv(df: pd.DataFrame, x_col: str, y_col: str, v_col: str) -> None:
    missing = [c for c in (x_col, y_col, v_col) if c not in df.columns]
    if missing:
        raise BlockExecutionError(code="COLUMN_NOT_FOUND", message=f"column(s) not in data: {missing}")


class WaferHeatmapBlockExecutor(BlockExecutor):
    block_id = "block_wafer_heatmap"

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
        x_col = params.get("x_column") or "x"
        y_col = params.get("y_column") or "y"
        v_col = params.get("value_column") or None
        if not v_col:
            raise BlockExecutionError(code="MISSING_PARAM", message="`value_column` is required")

        if df.empty:
            return {"chart_spec": {"__dsl": True, "type": "empty", "title": title or "No data", "message": "上游資料為空", "data": []}}
        df = _materialize_paths(df, [x_col, y_col, v_col])
        _validate_xyv(df, x_col, y_col, v_col)

        spec: dict[str, Any] = {
            "__dsl": True,
            "type": "wafer_heatmap",
            "title": title,
            "data": _records(df),
            "x": x_col,
            "y": [v_col],
            "x_column": x_col,
            "y_column": y_col,
            "value_column": v_col,
        }
        if isinstance(params.get("wafer_radius_mm"), (int, float)):
            spec["wafer_radius_mm"] = float(params["wafer_radius_mm"])
        if params.get("notch") in ("top", "bottom", "left", "right"):
            spec["notch"] = params["notch"]
        if isinstance(params.get("unit"), str):
            spec["unit"] = params["unit"]
        if params.get("color_mode") in ("viridis", "diverging"):
            spec["color_mode"] = params["color_mode"]
        if "show_points" in params:
            spec["show_points"] = bool(params["show_points"])
        if isinstance(params.get("grid_n"), int) and params["grid_n"] > 0:
            spec["grid_n"] = int(params["grid_n"])
        return {"chart_spec": spec}
