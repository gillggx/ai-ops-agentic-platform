"""block_filter — 條件過濾 records（支援 nested path 欄位）。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)
from python_ai_sidecar.pipeline_builder.path import get_column_series


# 2026-05-13: accept `=` as an alias of `==`. LLMs trained on SQL use `=`;
# trained on Python/JS use `==`. Same semantics either way.
_OPERATORS = {"==", "=", "!=", ">", "<", ">=", "<=", "contains", "in", "not_in"}


def _apply_op(series: pd.Series, op: str, value: Any) -> pd.Series:
    if op in ("==", "="):
        return series == value
    if op == "!=":
        return series != value
    if op == ">":
        return pd.to_numeric(series, errors="coerce") > value
    if op == "<":
        return pd.to_numeric(series, errors="coerce") < value
    if op == ">=":
        return pd.to_numeric(series, errors="coerce") >= value
    if op == "<=":
        return pd.to_numeric(series, errors="coerce") <= value
    if op == "contains":
        return series.astype(str).str.contains(str(value), na=False)
    if op in ("in", "not_in"):
        # 逗號字串寬容（同 sort 慣例）："A, B" → ["A", "B"]
        if isinstance(value, str) and "," in value:
            value = [v.strip() for v in value.split(",") if v.strip()]
        if not isinstance(value, (list, tuple)):
            raise BlockExecutionError(
                code="INVALID_PARAM",
                message=f"'{op}' operator requires a list value（或逗號分隔字串）",
            )
        mask = series.isin(value)
        return ~mask if op == "not_in" else mask
    raise BlockExecutionError(code="INVALID_PARAM", message=f"Unsupported operator: {op}")


def _series_for(df: pd.DataFrame, column: str) -> pd.Series:
    try:
        return get_column_series(df, column)
    except KeyError:
        raise BlockExecutionError(
            code="COLUMN_NOT_FOUND",
            message=f"Column path '{column}' not found",
            hint=f"Available top-level columns: {list(df.columns)[:10]}",
        ) from None


class FilterBlockExecutor(BlockExecutor):
    block_id = "block_filter"

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

        # B2 (2026-07-13, user 回報)：多條件過濾 — 之前一顆 block 一個條件，
        # 兩個條件要串兩顆。conditions=[{column,operator,value},...] + logic
        # (and|or)。給了 conditions 就忽略單數參數；單數形式照舊（向下相容）。
        conditions = params.get("conditions")
        if isinstance(conditions, list) and conditions:
            logic = str(params.get("logic") or "and").lower()
            if logic not in ("and", "or"):
                raise BlockExecutionError(
                    code="INVALID_PARAM", message="logic must be 'and' or 'or'")
            mask = None
            for i, cond in enumerate(conditions):
                if not isinstance(cond, dict) or not cond.get("column") or not cond.get("operator"):
                    raise BlockExecutionError(
                        code="INVALID_PARAM",
                        message=f"conditions[{i}] 需要 {{column, operator, value}}")
                m = _apply_op(
                    _series_for(df, str(cond["column"])),
                    str(cond["operator"]), cond.get("value"))
                mask = m if mask is None else (mask & m if logic == "and" else mask | m)
            return {"data": df[mask].reset_index(drop=True)}

        column = self.require(params, "column")
        op = self.require(params, "operator")
        value = params.get("value")

        if op not in _OPERATORS:
            raise BlockExecutionError(
                code="INVALID_PARAM",
                message=f"Unsupported operator: {op}",
                hint=f"Allowed: {sorted(_OPERATORS)}",
            )
        # Path-aware column lookup — `column` may be a dot/bracket path
        # (e.g. "spc_summary.ooc_count" or "spc_charts[].name").
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
        return {"data": filtered}
