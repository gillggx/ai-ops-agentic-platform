"""block_defect_stack — wafer outline + defect points colored by code."""

from __future__ import annotations

from typing import Any

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)
from python_ai_sidecar.pipeline_builder.blocks.line_chart import _records


class DefectStackBlockExecutor(BlockExecutor):
    block_id = "block_defect_stack"

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
        code_col = params.get("defect_column") or "defect_code"

        if df.empty:
            return {"chart_spec": {"__dsl": True, "type": "empty", "title": title or "No data", "message": "上游資料為空", "data": []}}

        missing = [c for c in (x_col, y_col, code_col) if c not in df.columns]
        if missing:
            raise BlockExecutionError(code="COLUMN_NOT_FOUND", message=f"column(s) not in data: {missing}")

        spec: dict[str, Any] = {
            "__dsl": True,
            "type": "defect_stack",
            "title": title,
            "data": _records(df),
            "x": x_col,
            "y": [code_col],
            "x_column": x_col,
            "y_column": y_col,
            "defect_column": code_col,
        }
        if isinstance(params.get("codes"), list):
            spec["codes"] = [str(c) for c in params["codes"]]
        if isinstance(params.get("wafer_radius_mm"), (int, float)):
            spec["wafer_radius_mm"] = float(params["wafer_radius_mm"])
        if params.get("notch") in ("top", "bottom", "left", "right"):
            spec["notch"] = params["notch"]
        return {"chart_spec": spec}
