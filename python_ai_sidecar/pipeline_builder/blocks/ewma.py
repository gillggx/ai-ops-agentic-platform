"""block_ewma — exponentially weighted moving average.

Output:
  data (DataFrame) — input df + <value_column>_ewma column

Params:
  value_column (required)
  alpha (required, 0 < α < 1) — smoothing factor; higher = more responsive to recent
  sort_by  (required)
  group_by (opt)               — each group has its own EWMA state (no cross-group bleed)
  adjust (default False)       — pandas ewm(adjust=); False = recursive form (classic EWMA)
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)


class EwmaBlockExecutor(BlockExecutor):
    block_id = "block_ewma"

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

        value_col: str = self.require(params, "value_column")
        sort_by: str = self.require(params, "sort_by")
        group_by: Optional[str] = params.get("group_by") or None
        alpha_raw = self.require(params, "alpha")
        try:
            alpha = float(alpha_raw)
        except (TypeError, ValueError):
            raise BlockExecutionError(code="INVALID_PARAM", message="alpha must be a number") from None
        if not (0.0 < alpha < 1.0):
            raise BlockExecutionError(code="INVALID_PARAM", message="alpha must be in (0, 1)")
        adjust = bool(params.get("adjust", False))

        for col in (value_col, sort_by):
            if col not in df.columns:
                raise BlockExecutionError(
                    code="COLUMN_NOT_FOUND", message=f"column '{col}' not in data"
                )
        if group_by is not None and group_by not in df.columns:
            raise BlockExecutionError(
                code="COLUMN_NOT_FOUND", message=f"group_by '{group_by}' not in data"
            )

        sort_cols = [group_by, sort_by] if group_by else [sort_by]
        out = df.sort_values(by=sort_cols, kind="mergesort").reset_index(drop=True)
        numeric = pd.to_numeric(out[value_col], errors="coerce")

        ewma_col = f"{value_col}_ewma"
        if group_by:
            # Per-group EWMA — groupby().transform() emits aligned series.
            out[ewma_col] = (
                pd.Series(numeric, index=out.index)
                .groupby(out[group_by])
                .transform(lambda s: s.ewm(alpha=alpha, adjust=adjust).mean())
            )
        else:
            out[ewma_col] = numeric.ewm(alpha=alpha, adjust=adjust).mean()

        return {"data": out}
