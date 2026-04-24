"""block_linear_regression — OLS regression with residuals + CI band.

Fit y = slope * x + intercept per-group (or on the whole series if group_by is
unset). Emits three output ports:

  stats (DataFrame):  group / slope / intercept / r_squared / p_value / n / stderr
  data  (DataFrame):  original rows + <y>_pred + <y>_residual + group
  ci    (DataFrame):  dense grid for plotting the confidence band
                       group / x / pred / ci_lower / ci_upper

We use scipy.stats.linregress for the OLS fit and the t-distribution for CI.
Emits BlockExecutionError(INSUFFICIENT_DATA) when a group has n<3 or x variance=0.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd
from scipy import stats as _stats

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)


_CI_GRID_SIZE = 60  # number of x points in CI band output


def _fit_group(
    sub: pd.DataFrame,
    x_col: str,
    y_col: str,
    confidence: float,
    group_label: Any,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    """Fit one group. Returns (stats_row, data_with_preds, ci_rows)."""
    # PR-F runtime-QA: if x column is string datetime (e.g. eventTime), parse
    # to epoch seconds so regression works on time-series. Previously this
    # coerced-to-NaN and n=0.
    x_series = sub[x_col]
    x_raw = pd.to_numeric(x_series, errors="coerce")
    if x_raw.isna().all():
        try:
            x_dt = pd.to_datetime(x_series, errors="coerce", utc=True)
            if not x_dt.isna().all():
                x_raw = x_dt.astype("int64") / 10**9  # epoch seconds
        except Exception:  # noqa: BLE001
            pass
    y_raw = pd.to_numeric(sub[y_col], errors="coerce")
    mask = x_raw.notna() & y_raw.notna()
    x = x_raw[mask].to_numpy(dtype=float)
    y = y_raw[mask].to_numpy(dtype=float)
    n = int(len(x))
    if n < 3:
        raise BlockExecutionError(
            code="INSUFFICIENT_DATA",
            message=f"Linear regression needs n>=3 (group={group_label!r}, n={n})",
        )
    if float(np.std(x, ddof=0)) == 0.0:
        raise BlockExecutionError(
            code="INSUFFICIENT_DATA",
            message=f"x column '{x_col}' has zero variance (group={group_label!r})",
        )

    res = _stats.linregress(x, y)
    slope = float(res.slope)
    intercept = float(res.intercept)
    r2 = float(res.rvalue ** 2)
    p_value = float(res.pvalue)
    stderr = float(res.stderr)

    # Predictions on the original (sorted) x — same datetime coercion
    data_out = sub.copy()
    x_num = pd.to_numeric(data_out[x_col], errors="coerce")
    if x_num.isna().all():
        try:
            x_dt = pd.to_datetime(data_out[x_col], errors="coerce", utc=True)
            if not x_dt.isna().all():
                x_num = x_dt.astype("int64") / 10**9
        except Exception:  # noqa: BLE001
            pass
    data_out[f"{y_col}_pred"] = slope * x_num + intercept
    data_out[f"{y_col}_residual"] = pd.to_numeric(data_out[y_col], errors="coerce") - data_out[f"{y_col}_pred"]

    # CI grid for the mean response
    x_mean = float(np.mean(x))
    ss_x = float(np.sum((x - x_mean) ** 2))
    y_pred = slope * x + intercept
    residuals = y - y_pred
    if n > 2:
        s_err = float(np.sqrt(np.sum(residuals ** 2) / (n - 2)))
    else:
        s_err = 0.0
    t_crit = float(_stats.t.ppf((1.0 + confidence) / 2.0, df=n - 2))

    x_min, x_max = float(np.min(x)), float(np.max(x))
    xs = np.linspace(x_min, x_max, _CI_GRID_SIZE)
    preds = slope * xs + intercept
    # SE of the mean response at each x
    se_mean = s_err * np.sqrt(1.0 / n + (xs - x_mean) ** 2 / ss_x) if ss_x > 0 else np.zeros_like(xs)
    margin = t_crit * se_mean
    ci_df = pd.DataFrame(
        {
            "group": group_label,
            "x": xs,
            "pred": preds,
            "ci_lower": preds - margin,
            "ci_upper": preds + margin,
        }
    )

    stats_row = {
        "group": group_label,
        "n": n,
        "slope": slope,
        "intercept": intercept,
        "r_squared": r2,
        "p_value": p_value,
        "stderr": stderr,
    }
    data_out["group"] = group_label
    return stats_row, data_out, ci_df


class LinearRegressionBlockExecutor(BlockExecutor):
    block_id = "block_linear_regression"

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

        x_col: str = self.require(params, "x_column")
        y_col: str = self.require(params, "y_column")
        group_by: Optional[str] = params.get("group_by") or None
        confidence = float(params.get("confidence", 0.95))
        if not (0.0 < confidence < 1.0):
            raise BlockExecutionError(
                code="INVALID_PARAM", message="confidence must be in (0, 1)"
            )

        for col in (x_col, y_col):
            if col not in df.columns:
                raise BlockExecutionError(
                    code="COLUMN_NOT_FOUND", message=f"column '{col}' not in data"
                )
        if group_by is not None and group_by not in df.columns:
            raise BlockExecutionError(
                code="COLUMN_NOT_FOUND", message=f"group_by '{group_by}' not in data"
            )

        if group_by:
            iterable = [(g, sub) for g, sub in df.groupby(group_by, dropna=False)]
        else:
            iterable = [(None, df)]

        stats_rows: list[dict[str, Any]] = []
        data_frames: list[pd.DataFrame] = []
        ci_frames: list[pd.DataFrame] = []
        for group_label, sub in iterable:
            s, d, c = _fit_group(sub, x_col, y_col, confidence, group_label)
            stats_rows.append(s)
            data_frames.append(d)
            ci_frames.append(c)

        return {
            "stats": pd.DataFrame(stats_rows),
            "data": pd.concat(data_frames, ignore_index=True),
            "ci": pd.concat(ci_frames, ignore_index=True),
        }
