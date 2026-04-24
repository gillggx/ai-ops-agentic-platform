"""block_sort — 多欄排序 + optional top-N cap.

Params:
  columns (required, array) — [{column: str, order: "asc"|"desc"}]
  limit   (optional, int)   — 保留前 N 列（e.g. top-3 機台）

Output:
  data (DataFrame)
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)


_ORDERS = {"asc", "desc"}


class SortBlockExecutor(BlockExecutor):
    block_id = "block_sort"

    async def execute(
        self,
        *,
        params: dict[str, Any],
        inputs: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        df = inputs.get("data")
        if not isinstance(df, pd.DataFrame):
            raise BlockExecutionError(code="INVALID_INPUT", message="'data' must be DataFrame")

        columns_spec = self.require(params, "columns")
        if not isinstance(columns_spec, list) or not columns_spec:
            raise BlockExecutionError(
                code="INVALID_PARAM",
                message="columns must be a non-empty list of {column, order}",
            )

        by: list[str] = []
        ascending: list[bool] = []
        for entry in columns_spec:
            if not isinstance(entry, dict):
                raise BlockExecutionError(
                    code="INVALID_PARAM",
                    message="each columns entry must be an object with column + order",
                )
            col = entry.get("column")
            order = entry.get("order", "asc")
            if not isinstance(col, str) or col not in df.columns:
                raise BlockExecutionError(
                    code="COLUMN_NOT_FOUND", message=f"sort column '{col}' not in data"
                )
            if order not in _ORDERS:
                raise BlockExecutionError(
                    code="INVALID_PARAM",
                    message=f"order must be 'asc' or 'desc' (got '{order}')",
                )
            by.append(col)
            ascending.append(order == "asc")

        limit = params.get("limit")
        if limit is not None:
            try:
                limit_n = int(limit)
            except (TypeError, ValueError):
                raise BlockExecutionError(
                    code="INVALID_PARAM", message="limit must be integer"
                ) from None
            if limit_n < 1:
                raise BlockExecutionError(
                    code="INVALID_PARAM", message="limit must be >= 1"
                )
        else:
            limit_n = None

        # kind="mergesort" preserves original order on ties (stable).
        out = df.sort_values(by=by, ascending=ascending, kind="mergesort").reset_index(drop=True)
        if limit_n is not None:
            out = out.head(limit_n)
        return {"data": out}
