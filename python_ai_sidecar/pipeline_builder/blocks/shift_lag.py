"""block_shift_lag — shift a column N rows; add <column>_lag<N> column.

用於計算本批次與上一批次參數的 delta（例如 APC rf_power_bias 的 drift）。
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)


class ShiftLagBlockExecutor(BlockExecutor):
    block_id = "block_shift_lag"

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

        column = self.require(params, "column")
        offset = int(params.get("offset", 1))
        if offset == 0:
            raise BlockExecutionError(code="INVALID_PARAM", message="offset must be non-zero")
        group_by: Optional[str] = params.get("group_by") or None
        sort_by: Optional[str] = params.get("sort_by") or None
        compute_delta = bool(params.get("compute_delta", True))

        if column not in df.columns:
            raise BlockExecutionError(
                code="COLUMN_NOT_FOUND",
                message=f"column '{column}' not in data",
            )

        out = df.copy()
        if sort_by and sort_by in out.columns:
            out = out.sort_values(by=sort_by).reset_index(drop=True)

        lag_col = f"{column}_lag{offset}"
        delta_col = f"{column}_delta"

        numeric = pd.to_numeric(out[column], errors="coerce")

        if group_by and group_by in out.columns:
            out[lag_col] = numeric.groupby(out[group_by]).shift(offset)
        else:
            out[lag_col] = numeric.shift(offset)

        if compute_delta:
            out[delta_col] = numeric - out[lag_col]

        return {"data": out}
