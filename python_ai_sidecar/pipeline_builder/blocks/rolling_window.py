"""block_rolling_window — rolling window stats (mean / std / min / max / sum).

輸出加上 `<column>_rolling_<func>` 欄位。支援 group_by（各 group 獨立 rolling）。
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)
from python_ai_sidecar.pipeline_builder.blocks.line_chart import _materialize_paths


_FUNCS = {"mean", "std", "min", "max", "sum", "median"}


class RollingWindowBlockExecutor(BlockExecutor):
    block_id = "block_rolling_window"

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
        window = int(self.require(params, "window"))
        func = params.get("func", "mean")
        group_by: Optional[str] = params.get("group_by") or None
        sort_by: Optional[str] = params.get("sort_by") or None
        min_periods = int(params.get("min_periods", 1))

        if func not in _FUNCS:
            raise BlockExecutionError(
                code="INVALID_PARAM", message=f"func must be one of {sorted(_FUNCS)}"
            )
        if window < 1:
            raise BlockExecutionError(code="INVALID_PARAM", message="window must be >= 1")
        df = _materialize_paths(df, [c for c in (column, group_by, sort_by) if c])
        if column not in df.columns:
            raise BlockExecutionError(
                code="COLUMN_NOT_FOUND", message=f"column '{column}' not in data"
            )

        out = df.copy()
        if sort_by and sort_by in out.columns:
            out = out.sort_values(by=sort_by).reset_index(drop=True)

        numeric = pd.to_numeric(out[column], errors="coerce")

        if group_by and group_by in out.columns:
            rolled = (
                numeric.groupby(out[group_by])
                .rolling(window=window, min_periods=min_periods)
                .agg(func)
                .reset_index(level=0, drop=True)
            )
        else:
            rolled = numeric.rolling(window=window, min_periods=min_periods).agg(func)

        out[f"{column}_rolling_{func}"] = rolled.values
        return {"data": out}
