"""block_bar_chart — primitive bar / grouped-bar chart."""

from __future__ import annotations

from typing import Any

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)
from python_ai_sidecar.pipeline_builder.blocks.line_chart import (
    _materialize_paths,
    _normalize_y,
    _records,
    _validate_columns,
)


class BarChartBlockExecutor(BlockExecutor):
    block_id = "block_bar_chart"

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
        y = _normalize_y(params.get("y"))
        if not y:
            raise BlockExecutionError(code="MISSING_PARAM", message="'y' must be a non-empty string or list")
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

        df = _materialize_paths(df, [x, *y])
        _validate_columns(df, [x, *y], label="bar_chart")

        # 2026-06-25 (hardening #1): rank the bars in-block. "由多到少 / top-N /
        # 最多 / ranking" no longer needs a separate block_sort upstream — set
        # order='desc'. Sorts by the FIRST y measure (numeric). order='none'
        # (default) preserves the upstream row order = fully backward compatible.
        order = str(params.get("order") or "none").lower()
        if order in ("asc", "desc"):
            sort_col = y[0]
            df = df.copy()
            df["__bar_order"] = pd.to_numeric(df[sort_col], errors="coerce")
            df = (
                df.sort_values("__bar_order", ascending=(order == "asc"), kind="mergesort")
                .drop(columns="__bar_order")
                .reset_index(drop=True)
            )

        rules = params.get("rules") or []
        highlight = None
        hf = params.get("highlight_field")
        if hf is not None:
            if hf not in df.columns:
                raise BlockExecutionError(
                    code="COLUMN_NOT_FOUND",
                    message=f"highlight_field '{hf}' not in data",
                )
            highlight = {"field": hf, "eq": params.get("highlight_eq", True)}

        spec: dict[str, Any] = {
            "__dsl": True,
            "type": "bar",
            "title": title,
            "data": _records(df),
            "x": x,
            "y": y,
        }
        if rules:
            spec["rules"] = rules
        if highlight:
            spec["highlight"] = highlight
        return {"chart_spec": spec}
