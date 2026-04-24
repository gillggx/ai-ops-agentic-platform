"""block_correlation — pairwise correlation matrix in long format.

Input:  data (DataFrame)
Params:
  columns (required, array) — numeric columns to include
  method  (default "pearson") — "pearson" | "spearman" | "kendall"
Output:
  matrix (DataFrame, long) — cols: col_a / col_b / correlation / p_value / n

Long format makes this a drop-in for block_chart(heatmap,
  x=col_a, y=col_b, value_column=correlation).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as _stats

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)


_METHODS = {"pearson", "spearman", "kendall"}


def _pair_stat(a: np.ndarray, b: np.ndarray, method: str) -> tuple[float, float, int]:
    mask = ~np.isnan(a) & ~np.isnan(b)
    a_valid = a[mask]
    b_valid = b[mask]
    n = int(len(a_valid))
    if n < 3:
        return (float("nan"), float("nan"), n)
    if float(np.std(a_valid)) == 0.0 or float(np.std(b_valid)) == 0.0:
        return (float("nan"), float("nan"), n)
    if method == "pearson":
        r, p = _stats.pearsonr(a_valid, b_valid)
    elif method == "spearman":
        r, p = _stats.spearmanr(a_valid, b_valid)
    else:
        r, p = _stats.kendalltau(a_valid, b_valid)
    return (float(r), float(p), n)


class CorrelationBlockExecutor(BlockExecutor):
    block_id = "block_correlation"

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

        columns = self.require(params, "columns")
        if not isinstance(columns, list) or not all(isinstance(c, str) for c in columns):
            raise BlockExecutionError(
                code="INVALID_PARAM", message="columns must be a list of strings"
            )
        if len(columns) < 2:
            raise BlockExecutionError(
                code="INVALID_PARAM", message="need at least 2 columns to correlate"
            )
        missing = [c for c in columns if c not in df.columns]
        if missing:
            raise BlockExecutionError(
                code="COLUMN_NOT_FOUND", message=f"columns not in data: {missing}"
            )

        method = params.get("method", "pearson")
        if method not in _METHODS:
            raise BlockExecutionError(
                code="INVALID_PARAM", message=f"method must be one of {_METHODS}"
            )

        # Coerce numeric; non-numeric columns become NaN and contribute nothing.
        numeric_cols: dict[str, np.ndarray] = {}
        for c in columns:
            numeric_cols[c] = pd.to_numeric(df[c], errors="coerce").to_numpy(dtype=float)

        rows: list[dict[str, Any]] = []
        for a in columns:
            for b in columns:
                r, p, n = _pair_stat(numeric_cols[a], numeric_cols[b], method)
                rows.append(
                    {
                        "col_a": a,
                        "col_b": b,
                        "correlation": r,
                        "p_value": p,
                        "n": n,
                    }
                )
        return {"matrix": pd.DataFrame(rows)}
