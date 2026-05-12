"""block_pluck — extract a single (possibly nested) field from each record.

Useful when downstream wants just one column out of a wide object, or when
turning `[{a:1, b:2}, {a:3, b:4}]` into `[1, 3]` semantically — keeps the
DataFrame shape but with a single column named after the leaf.

Path support:
  "tool_id"            → column with top-level value (no-op rename if already top-level)
  "spc_summary.ooc_count" → flattened scalar column "ooc_count"
  "spc_charts[].name"  → column of list-of-values (use block_unnest to explode)
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)
from python_ai_sidecar.pipeline_builder.path import get_column_series


class PluckBlockExecutor(BlockExecutor):
    block_id = "block_pluck"

    async def execute(
        self,
        *,
        params: dict[str, Any],
        inputs: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        df = inputs.get("data")
        if not isinstance(df, pd.DataFrame):
            raise BlockExecutionError(
                code="INVALID_INPUT", message="'data' must be DataFrame"
            )
        path = self.require(params, "path")
        as_column = params.get("as_column") or path.rsplit(".", 1)[-1].replace("[]", "")
        keep_other = bool(params.get("keep_other", False))

        try:
            series = get_column_series(df, path)
        except KeyError:
            raise BlockExecutionError(
                code="COLUMN_NOT_FOUND",
                message=f"path '{path}' not found in input",
                hint=f"Available top-level: {list(df.columns)[:10]}",
            ) from None

        if keep_other:
            out = df.copy()
            out[as_column] = series.values
        else:
            out = pd.DataFrame({as_column: series.values})
        return {"data": out}
