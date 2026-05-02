"""block_histogram_chart — distribution histogram + USL/LSL spec lines + Cpk.

Note the suffix `_chart`: the existing `block_histogram` is a transform that
emits binned counts; this block renders the chart directly from raw values
(or accepts pre-binned `bin_center`/`count` rows).

Spec:
  inputs.data: DataFrame
  params.value_column:      raw values column (or use pre-binned input
                              with bin_center + count columns)
  params.usl?, lsl?, target?: spec window in raw value units
  params.bins?:             bin count (default 28; raw mode only)
  params.show_normal?:      overlay normal-fit PDF (default true)
  params.unit?:             axis title unit suffix (e.g. 'nm')
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
from python_ai_sidecar.pipeline_builder.blocks.line_chart import _records


class HistogramChartBlockExecutor(BlockExecutor):
    block_id = "block_histogram_chart"

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
            return {
                "chart_spec": {
                    "__dsl": True,
                    "type": "empty",
                    "title": title or "No data",
                    "message": "上游資料為空",
                    "data": [],
                }
            }

        # Detect input mode
        is_pre_binned = "bin_center" in df.columns and "count" in df.columns
        value_col = params.get("value_column") or None
        if not is_pre_binned:
            if not value_col:
                raise BlockExecutionError(
                    code="MISSING_PARAM",
                    message=(
                        "Provide either pre-binned data (bin_center + count columns) or"
                        " set 'value_column' to point at the raw value column"
                    ),
                )
            if value_col not in df.columns:
                raise BlockExecutionError(
                    code="COLUMN_NOT_FOUND",
                    message=f"value_column '{value_col}' not in data",
                )

        spec: dict[str, Any] = {
            "__dsl": True,
            "type": "histogram",
            "title": title,
            "data": _records(df),
            "x": "",
            "y": [],
        }
        if value_col:
            spec["value_column"] = value_col
        for k in ("usl", "lsl", "target"):
            v = params.get(k)
            if isinstance(v, (int, float)):
                spec[k] = float(v)
        if isinstance(params.get("bins"), int) and params["bins"] > 0:
            spec["bins"] = int(params["bins"])
        if "show_normal" in params:
            spec["show_normal"] = bool(params["show_normal"])
        if isinstance(params.get("unit"), str):
            spec["unit"] = params["unit"]
        return {"chart_spec": spec}
