"""block_groupby_agg — 分組 + 聚合（mean/sum/count/min/max/median）。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)


_AGG_FUNCS = {"mean", "sum", "count", "min", "max", "median", "std"}


class GroupByAggBlockExecutor(BlockExecutor):
    block_id = "block_groupby_agg"

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

        group_by = self.require(params, "group_by")
        agg_column = self.require(params, "agg_column")
        agg_func = self.require(params, "agg_func")

        if agg_func not in _AGG_FUNCS:
            raise BlockExecutionError(
                code="INVALID_PARAM", message=f"agg_func must be one of {_AGG_FUNCS}"
            )

        group_cols = group_by if isinstance(group_by, list) else [group_by]
        for c in group_cols + [agg_column]:
            if c not in df.columns:
                raise BlockExecutionError(
                    code="COLUMN_NOT_FOUND", message=f"Column '{c}' not in data"
                )

        result_col = f"{agg_column}_{agg_func}"
        if agg_func == "count":
            grouped = df.groupby(group_cols, dropna=False).size().reset_index(name=result_col)
        else:
            grouped = (
                df.groupby(group_cols, dropna=False)[agg_column]
                .agg(agg_func)
                .reset_index(name=result_col)
            )
        return {"data": grouped}
