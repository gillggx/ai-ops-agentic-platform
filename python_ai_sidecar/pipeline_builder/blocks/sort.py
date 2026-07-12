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
from python_ai_sidecar.pipeline_builder.path import get_column_series


_ORDERS = {"asc", "desc"}


_SORT_KEY_PREFIX = "__sort_key_"


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
        # 2026-07-13 (user 實測)：GUI 直接打 "toolID,eventTime" 期待多鍵排序
        # — 之前整串當一個欄名炸 COLUMN_NOT_FOUND。寬容解析：字串先按逗號
        # 切開，每段再走既有的 flat-string 正規化（= asc）。
        if isinstance(columns_spec, str):
            columns_spec = [p.strip() for p in columns_spec.split(",") if p.strip()]
        if not isinstance(columns_spec, list) or not columns_spec:
            raise BlockExecutionError(
                code="INVALID_PARAM",
                message="columns must be a non-empty list of {column, order}",
            )
        expanded: list[Any] = []
        for entry in columns_spec:
            if isinstance(entry, str) and "," in entry:
                expanded.extend(p.strip() for p in entry.split(",") if p.strip())
            else:
                expanded.append(entry)
        columns_spec = expanded

        # Path-aware sort: for nested columns we materialize a temporary
        # __sort_key_<i> column via get_column_series, sort by it, then drop.
        # Flat columns sort in place via pandas (faster, no extra copy).
        by: list[str] = []
        ascending: list[bool] = []
        materialized_keys: list[str] = []
        df_work = df

        for i, entry in enumerate(columns_spec):
            # Flat-string form: "ooc_count" == {"column": "ooc_count", "order":
            # "asc"}. The object form {column, order} stays supported for desc —
            # a flat string list is far easier for an LLM (2026-06-24).
            if isinstance(entry, str):
                entry = {"column": entry, "order": "asc"}
            if not isinstance(entry, dict):
                raise BlockExecutionError(
                    code="INVALID_PARAM",
                    message="each columns entry must be a column-name string or an object with column + order",
                )
            col = entry.get("column")
            order = entry.get("order", "asc")
            if not isinstance(col, str) or not col:
                raise BlockExecutionError(
                    code="INVALID_PARAM", message=f"sort column must be non-empty string, got {col!r}"
                )
            if order not in _ORDERS:
                raise BlockExecutionError(
                    code="INVALID_PARAM",
                    message=f"order must be 'asc' or 'desc' (got '{order}')",
                )

            if "." in col or "[]" in col:
                try:
                    series = get_column_series(df_work, col)
                except KeyError:
                    raise BlockExecutionError(
                        code="COLUMN_NOT_FOUND",
                        message=f"sort path '{col}' not in data",
                        hint=f"Available top-level columns: {list(df_work.columns)[:10]}",
                    ) from None
                key = f"{_SORT_KEY_PREFIX}{i}"
                # Use a fresh copy on first materialization so we don't mutate
                # the upstream block's DataFrame in-place.
                if df_work is df:
                    df_work = df.copy()
                df_work[key] = series.values
                by.append(key)
                materialized_keys.append(key)
            else:
                if col not in df_work.columns:
                    raise BlockExecutionError(
                        code="COLUMN_NOT_FOUND", message=f"sort column '{col}' not in data",
                        hint=f"Available columns: {list(df_work.columns)[:10]}",
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
        out = df_work.sort_values(by=by, ascending=ascending, kind="mergesort").reset_index(drop=True)
        if limit_n is not None:
            out = out.head(limit_n)
        # Drop scratch columns introduced for nested-path sorting.
        if materialized_keys:
            out = out.drop(columns=materialized_keys, errors="ignore")
        return {"data": out}
