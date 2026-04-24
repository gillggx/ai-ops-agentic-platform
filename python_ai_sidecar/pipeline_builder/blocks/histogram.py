"""block_histogram — 直方圖 / 分布計算。

Turns a numeric column into bucket counts suitable for bar-chart rendering.

Output:
  data (DataFrame) — cols: bin_left / bin_right / bin_center / count / density / group

bins:
  integer → equal-width bins (fixed count)
  'auto'  → numpy auto-bin (Freedman–Diaconis / Sturges)
"""

from __future__ import annotations

from typing import Any, Optional, Union

import numpy as np
import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)


def _histogram_group(
    sub: pd.DataFrame,
    value_col: str,
    bins: Union[int, str],
    group_label: Any,
) -> pd.DataFrame:
    values = pd.to_numeric(sub[value_col], errors="coerce").dropna().to_numpy(dtype=float)
    if len(values) == 0:
        return pd.DataFrame(
            columns=["bin_left", "bin_right", "bin_center", "count", "density", "group"]
        )
    counts, edges = np.histogram(values, bins=bins)
    densities, _ = np.histogram(values, bins=edges, density=True)
    left = edges[:-1]
    right = edges[1:]
    center = (left + right) / 2.0
    return pd.DataFrame(
        {
            "group": group_label,
            "bin_left": left,
            "bin_right": right,
            "bin_center": center,
            "count": counts.astype(int),
            "density": densities,
        }
    )


class HistogramBlockExecutor(BlockExecutor):
    block_id = "block_histogram"

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
        if value_col not in df.columns:
            raise BlockExecutionError(
                code="COLUMN_NOT_FOUND", message=f"value_column '{value_col}' not in data"
            )
        group_by: Optional[str] = params.get("group_by") or None
        if group_by is not None and group_by not in df.columns:
            raise BlockExecutionError(
                code="COLUMN_NOT_FOUND", message=f"group_by '{group_by}' not in data"
            )

        bins_raw = params.get("bins", 20)
        if isinstance(bins_raw, str):
            if bins_raw != "auto":
                raise BlockExecutionError(
                    code="INVALID_PARAM", message="bins must be an integer or 'auto'"
                )
            bins: Union[int, str] = "auto"
        else:
            try:
                bins = int(bins_raw)
            except (TypeError, ValueError):
                raise BlockExecutionError(
                    code="INVALID_PARAM", message="bins must be an integer or 'auto'"
                ) from None
            if bins < 2:
                raise BlockExecutionError(
                    code="INVALID_PARAM", message="bins must be >= 2"
                )

        if group_by:
            iterable = [(g, sub) for g, sub in df.groupby(group_by, dropna=False)]
        else:
            iterable = [(None, df)]

        frames = [_histogram_group(sub, value_col, bins, g) for g, sub in iterable]
        out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

        # v3.5: stats port — μ / σ / n / skewness per group (empty group → NaN).
        stats_rows: list[dict[str, Any]] = []
        for g_label, sub in iterable:
            vals = pd.to_numeric(sub[value_col], errors="coerce").dropna().to_numpy(dtype=float)
            n = int(len(vals))
            if n < 2:
                stats_rows.append({"group": g_label, "n": n, "mu": None, "sigma": None, "skewness": None})
                continue
            mu = float(np.mean(vals))
            sigma = float(np.std(vals, ddof=1))
            skew = 0.0
            if sigma > 0 and n > 2:
                skew = float(np.mean(((vals - mu) / sigma) ** 3))
            stats_rows.append({"group": g_label, "n": n, "mu": mu, "sigma": sigma, "skewness": skew})
        return {"data": out, "stats": pd.DataFrame(stats_rows)}
