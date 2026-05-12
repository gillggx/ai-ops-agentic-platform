"""block_imr — Individual + Moving Range chart for un-subgrouped data."""

from __future__ import annotations

from typing import Any

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)
from python_ai_sidecar.pipeline_builder.blocks.line_chart import _materialize_paths, _records
from python_ai_sidecar.pipeline_builder.path import ensure_flat_spc


class IMRBlockExecutor(BlockExecutor):
    block_id = "block_imr"

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
        df = ensure_flat_spc(df)  # accept nested upstream
        title = params.get("title") or None

        if df.empty:
            return {"chart_spec": {"__dsl": True, "type": "empty", "title": title or "No data", "message": "上游資料為空", "data": []}}

        # Materialize nested paths up-front so downstream column check + _records pick them up.
        if not isinstance(params.get("values"), list):
            _value_col = params.get("value_column") or None
            if _value_col:
                df = _materialize_paths(df, [_value_col])

        spec: dict[str, Any] = {
            "__dsl": True,
            "type": "imr",
            "title": title,
            "data": _records(df),
            "x": "",
            "y": [],
        }
        if isinstance(params.get("values"), list):
            spec["values"] = params["values"]
        else:
            value_col = params.get("value_column") or None
            if not value_col:
                raise BlockExecutionError(
                    code="MISSING_PARAM",
                    message="provide either `values` (number[]) or `value_column` (column in data)",
                )
            if value_col not in df.columns:
                raise BlockExecutionError(code="COLUMN_NOT_FOUND", message=f"value_column '{value_col}' not in data")
            spec["value_column"] = value_col
        if isinstance(params.get("weco_rules"), list):
            spec["weco_rules"] = [str(r) for r in params["weco_rules"]]
        return {"chart_spec": spec}
