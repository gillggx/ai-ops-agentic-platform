"""block_delta — 算相鄰點的差值與 trend 旗標。

Input:  data (DataFrame)
Output: data (DataFrame) — 加 3 欄：
          <value_column>_delta   : numeric (current - previous)
          <value_column>_is_rising : bool (delta > 0)
          <value_column>_is_falling: bool (delta < 0)

若指定 group_by，各組內獨立計算（第一筆 delta = NaN）。
value_column / sort_by 必填 — 嚴禁預設 eventTime（原 Q9 原則）。
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)


class DeltaBlockExecutor(BlockExecutor):
    block_id = "block_delta"

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
                code="INVALID_INPUT", message="'data' input must be a DataFrame"
            )

        value_column: str = self.require(params, "value_column")
        sort_by: str = self.require(params, "sort_by")
        group_by: Optional[str] = params.get("group_by") or None

        for col in (value_column, sort_by):
            if col not in df.columns:
                raise BlockExecutionError(
                    code="COLUMN_NOT_FOUND", message=f"column '{col}' not in data"
                )
        if group_by is not None and group_by not in df.columns:
            raise BlockExecutionError(
                code="COLUMN_NOT_FOUND", message=f"group_by '{group_by}' not in data"
            )

        out = df.copy()
        numeric = pd.to_numeric(out[value_column], errors="coerce")
        out["__value_num__"] = numeric

        # Sort (stable) so delta is computed along the intended axis.
        sort_cols = [group_by, sort_by] if group_by else [sort_by]
        out = out.sort_values(by=sort_cols, kind="mergesort").reset_index(drop=True)

        if group_by:
            delta = out.groupby(group_by, dropna=False)["__value_num__"].diff()
        else:
            delta = out["__value_num__"].diff()

        delta_col = f"{value_column}_delta"
        rising_col = f"{value_column}_is_rising"
        falling_col = f"{value_column}_is_falling"
        out[delta_col] = delta
        out[rising_col] = (delta > 0).fillna(False)
        out[falling_col] = (delta < 0).fillna(False)
        out = out.drop(columns=["__value_num__"])

        return {"data": out}
