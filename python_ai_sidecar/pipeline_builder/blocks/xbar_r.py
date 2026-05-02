"""block_xbar_r — proper X̄/R control chart with WECO R1-R8 highlighting."""

from __future__ import annotations

from typing import Any

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)
from python_ai_sidecar.pipeline_builder.blocks.line_chart import _records


class XbarRBlockExecutor(BlockExecutor):
    block_id = "block_xbar_r"

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
            return {"chart_spec": {"__dsl": True, "type": "empty", "title": title or "No data", "message": "上游資料為空", "data": []}}

        spec: dict[str, Any] = {
            "__dsl": True,
            "type": "xbar_r",
            "title": title,
            "data": _records(df),
            "x": "",
            "y": [],
        }
        # Optional pre-aggregated path
        if isinstance(params.get("subgroups"), list):
            spec["subgroups"] = params["subgroups"]
        else:
            value_col = params.get("value_column") or None
            subgroup_col = params.get("subgroup_column") or None
            if not value_col:
                raise BlockExecutionError(
                    code="MISSING_PARAM",
                    message="provide either pre-aggregated `subgroups` (number[][]) or `value_column` (+ optional `subgroup_column`)",
                )
            if value_col not in df.columns:
                raise BlockExecutionError(code="COLUMN_NOT_FOUND", message=f"value_column '{value_col}' not in data")
            if subgroup_col and subgroup_col not in df.columns:
                raise BlockExecutionError(code="COLUMN_NOT_FOUND", message=f"subgroup_column '{subgroup_col}' not in data")
            spec["value_column"] = value_col
            if subgroup_col:
                spec["subgroup_column"] = subgroup_col
        if isinstance(params.get("subgroup_size"), int) and params["subgroup_size"] >= 2:
            spec["subgroup_size"] = int(params["subgroup_size"])
        if isinstance(params.get("weco_rules"), list):
            spec["weco_rules"] = [str(r) for r in params["weco_rules"]]
        return {"chart_spec": spec}
