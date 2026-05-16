"""block_find — 1-block 「find specific rows」: filter + (optional) sort + take.

合併 block_filter + block_sort + limit 三件常見組合：
  "找最後一次 OOC 事件" -> block_find(column='spc_status', operator='==', value='OOC',
                                       order_by='eventTime', order_dir='desc', take='last')
  "找最早違規 lot"      -> block_find(column='violated', operator='==', value=True,
                                       order_by='eventTime', order_dir='asc', take='first')
  "找全部 PASS events"  -> block_find(column='spc_status', operator='==', value='PASS', take='all')
  "top 5 by score"      -> block_find(column='status', operator='==', value='OK',
                                       order_by='score', order_dir='desc', take=5)
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)
from python_ai_sidecar.pipeline_builder.blocks.filter import _OPERATORS, _apply_op
from python_ai_sidecar.pipeline_builder.path import get_column_series


_TAKE_KEYWORDS = {"first", "last", "all"}


class FindBlockExecutor(BlockExecutor):
    block_id = "block_find"

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
                code="INVALID_INPUT",
                message="'data' input must be a DataFrame",
            )

        column = self.require(params, "column")
        op = self.require(params, "operator")
        value = params.get("value")
        order_by = params.get("order_by")
        order_dir = str(params.get("order_dir") or "desc").lower()
        take = params.get("take", "all")

        if op not in _OPERATORS:
            raise BlockExecutionError(
                code="INVALID_PARAM",
                message=f"Unsupported operator: {op}",
                hint=f"Allowed: {sorted(_OPERATORS)}",
            )
        if order_dir not in ("asc", "desc"):
            raise BlockExecutionError(
                code="INVALID_PARAM",
                message=f"Unsupported order_dir: {order_dir!r} (expected 'asc' or 'desc')",
            )
        if isinstance(take, str):
            if take not in _TAKE_KEYWORDS:
                raise BlockExecutionError(
                    code="INVALID_PARAM",
                    message=f"Unsupported take: {take!r}",
                    hint=f"Allowed: 'first' | 'last' | 'all' | <int N>",
                )
        elif isinstance(take, bool) or not isinstance(take, int):
            # bool is subclass of int — reject explicitly
            raise BlockExecutionError(
                code="INVALID_PARAM",
                message=f"take must be 'first'/'last'/'all' or int N (got {type(take).__name__})",
            )
        elif take < 1:
            raise BlockExecutionError(
                code="INVALID_PARAM",
                message=f"take int N must be >= 1 (got {take})",
            )

        # 1. filter
        try:
            series = get_column_series(df, column)
        except KeyError:
            raise BlockExecutionError(
                code="COLUMN_NOT_FOUND",
                message=f"Column path '{column}' not found",
                hint=f"Available top-level columns: {list(df.columns)[:10]}",
            ) from None

        mask = _apply_op(series, op, value)
        filtered = df[mask].reset_index(drop=True)

        # 2. optional sort
        if order_by:
            if order_by not in filtered.columns:
                raise BlockExecutionError(
                    code="COLUMN_NOT_FOUND",
                    message=f"order_by column '{order_by}' not in filtered output",
                    hint=f"Available columns: {list(filtered.columns)[:10]}",
                )
            ascending = (order_dir == "asc")
            filtered = filtered.sort_values(
                by=order_by, ascending=ascending, kind="mergesort",
            ).reset_index(drop=True)

        # 3. take
        if filtered.empty:
            return {"data": filtered}
        if take == "all":
            out = filtered
        elif take == "first":
            out = filtered.head(1).reset_index(drop=True)
        elif take == "last":
            out = filtered.tail(1).reset_index(drop=True)
        else:  # int N
            out = filtered.head(int(take)).reset_index(drop=True)

        return {"data": out}
