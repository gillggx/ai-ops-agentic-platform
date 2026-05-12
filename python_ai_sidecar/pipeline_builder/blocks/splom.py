"""block_splom — Scatter Plot Matrix for N FDC parameters.

Spec:
  inputs.data: DataFrame
  params.dimensions:        list of column names (2..N) to include in N×N grid
  params.outlier_field?:    boolean column → outliers rendered in alert color
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


class SplomBlockExecutor(BlockExecutor):
    block_id = "block_splom"

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

        dims_raw = self.require(params, "dimensions")
        if not isinstance(dims_raw, list) or len(dims_raw) < 2:
            raise BlockExecutionError(
                code="MISSING_PARAM",
                message="'dimensions' must be a list of >= 2 column names",
            )
        dims = [str(d) for d in dims_raw]
        outlier_field = params.get("outlier_field") or None
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

        df = _materialize_paths(df, dims + ([outlier_field] if outlier_field else []))
        missing = [d for d in dims if d not in df.columns]
        if missing:
            raise BlockExecutionError(
                code="COLUMN_NOT_FOUND",
                message=f"splom dimension column(s) not in data: {missing}",
            )
        if outlier_field and outlier_field not in df.columns:
            raise BlockExecutionError(
                code="COLUMN_NOT_FOUND",
                message=f"outlier_field '{outlier_field}' not in data",
            )

        spec: dict[str, Any] = {
            "__dsl": True,
            "type": "splom",
            "title": title,
            "data": _records(df),
            "x": "",
            "y": [],
            "dimensions": dims,
        }
        if outlier_field:
            spec["outlier_field"] = outlier_field
        return {"chart_spec": spec}
