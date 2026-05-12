"""block_groupby_agg — 分組 + 聚合（mean/sum/count/min/max/median）。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)
from python_ai_sidecar.pipeline_builder.path import get_column_series


_AGG_FUNCS = {"mean", "sum", "count", "min", "max", "median", "std"}


_GROUP_KEY_PREFIX = "__group_key_"
_AGG_KEY = "__agg_value__"


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

        if isinstance(group_by, list):
            group_paths = [str(c).strip() for c in group_by if str(c).strip()]
        elif isinstance(group_by, str):
            if "," in group_by:
                group_paths = [c.strip() for c in group_by.split(",") if c.strip()]
            else:
                group_paths = [group_by]
        else:
            raise BlockExecutionError(
                code="INVALID_PARAM",
                message=f"group_by must be string or list, got {type(group_by).__name__}",
            )

        # Path-aware: materialize each path into a scratch column. Final output
        # columns are named by the LAST path segment (so nested paths land as
        # readable column names — e.g. "spc_summary.ooc_count" → "ooc_count").
        df_work = df.copy()
        group_cols: list[str] = []
        group_pretty: dict[str, str] = {}
        for i, path in enumerate(group_paths):
            if "." in path or "[]" in path:
                try:
                    series = get_column_series(df_work, path)
                except KeyError:
                    raise BlockExecutionError(
                        code="COLUMN_NOT_FOUND",
                        message=f"group_by path '{path}' not in data",
                        hint=f"Available top-level: {list(df.columns)[:10]}",
                    ) from None
                key = f"{_GROUP_KEY_PREFIX}{i}"
                df_work[key] = series.values
                group_cols.append(key)
                # readable output name: last segment, stripped of [] markers
                pretty = path.rsplit(".", 1)[-1].replace("[]", "")
                group_pretty[key] = pretty
            else:
                if path not in df_work.columns:
                    raise BlockExecutionError(
                        code="COLUMN_NOT_FOUND", message=f"group_by column '{path}' not in data",
                        hint=f"Available: {list(df_work.columns)[:10]}",
                    )
                group_cols.append(path)
                group_pretty[path] = path

        # agg_column also path-aware
        if "." in agg_column or "[]" in agg_column:
            try:
                df_work[_AGG_KEY] = get_column_series(df_work, agg_column).values
            except KeyError:
                raise BlockExecutionError(
                    code="COLUMN_NOT_FOUND",
                    message=f"agg_column path '{agg_column}' not in data",
                ) from None
            agg_internal = _AGG_KEY
            agg_pretty = agg_column.rsplit(".", 1)[-1].replace("[]", "")
        else:
            if agg_func != "count" and agg_column not in df_work.columns:
                raise BlockExecutionError(
                    code="COLUMN_NOT_FOUND", message=f"agg_column '{agg_column}' not in data"
                )
            agg_internal = agg_column
            agg_pretty = agg_column

        result_col = f"{agg_pretty}_{agg_func}"
        if agg_func == "count":
            grouped = df_work.groupby(group_cols, dropna=False).size().reset_index(name=result_col)
        else:
            grouped = (
                df_work.groupby(group_cols, dropna=False)[agg_internal]
                .agg(agg_func)
                .reset_index(name=result_col)
            )
        # Rename scratch group keys back to readable names
        rename_map = {k: v for k, v in group_pretty.items() if k != v}
        if rename_map:
            grouped = grouped.rename(columns=rename_map)
        return {"data": grouped}
