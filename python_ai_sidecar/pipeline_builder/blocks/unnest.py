"""block_unnest — explode an array column into rows.

Turns this:
    [{tool_id: 'A', spc_charts: [{name: 'TEMP'}, {name: 'PRESS'}]}]
into:
    [{tool_id: 'A', name: 'TEMP'}, {tool_id: 'A', name: 'PRESS'}]

Use BEFORE block_groupby_agg / block_filter when you need per-array-element
analytics. Sibling columns broadcast to every expanded row.

Path support: the `column` param accepts a path. For nested arrays
(`spc_charts[].defects`), call unnest twice.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)
from python_ai_sidecar.pipeline_builder.path import expand_array_column, get_column_series


class UnnestBlockExecutor(BlockExecutor):
    block_id = "block_unnest"

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

        column = self.require(params, "column")
        # Normalize: "spc_charts" and "spc_charts[]" mean the same thing for unnest.
        path = column[:-2] if column.endswith("[]") else column

        # If the column is a path that addresses into a nested object (e.g.
        # `obj.list_field`), first materialize a top-level column for it.
        if "." in path:
            try:
                series = get_column_series(df, path)
            except KeyError:
                raise BlockExecutionError(
                    code="COLUMN_NOT_FOUND",
                    message=f"path '{column}' not found in input",
                ) from None
            df = df.copy()
            scratch_name = path.replace(".", "_")
            df[scratch_name] = series.values
            path = scratch_name

        if path not in df.columns:
            raise BlockExecutionError(
                code="COLUMN_NOT_FOUND",
                message=f"column '{column}' not in data",
                hint=f"Available: {list(df.columns)[:10]}",
            )

        try:
            out = expand_array_column(df, path)
        except KeyError as ex:
            raise BlockExecutionError(
                code="COLUMN_NOT_FOUND", message=str(ex)
            ) from None
        return {"data": out}
