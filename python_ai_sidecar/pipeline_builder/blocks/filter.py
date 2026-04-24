"""block_filter — 條件過濾 dataframe 的列。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)


_OPERATORS = {"==", "!=", ">", "<", ">=", "<=", "contains", "in"}


def _apply_op(series: pd.Series, op: str, value: Any) -> pd.Series:
    if op == "==":
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
    if op == "in":
        if not isinstance(value, (list, tuple)):
            raise BlockExecutionError(
                code="INVALID_PARAM",
                message="'in' operator requires a list value",
            )
        return series.isin(value)
    raise BlockExecutionError(code="INVALID_PARAM", message=f"Unsupported operator: {op}")


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

        column = self.require(params, "column")
        op = self.require(params, "operator")
        value = params.get("value")

        if op not in _OPERATORS:
            raise BlockExecutionError(
                code="INVALID_PARAM",
                message=f"Unsupported operator: {op}",
                hint=f"Allowed: {sorted(_OPERATORS)}",
            )
        if column not in df.columns:
            raise BlockExecutionError(
                code="COLUMN_NOT_FOUND",
                message=f"Column '{column}' not found",
                hint=f"Available columns: {list(df.columns)[:10]}",
            )

        mask = _apply_op(df[column], op, value)
        filtered = df[mask].reset_index(drop=True)
        return {"data": filtered}
