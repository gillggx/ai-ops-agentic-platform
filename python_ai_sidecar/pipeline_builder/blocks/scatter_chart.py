"""block_scatter_chart — primitive scatter chart with optional series_field."""

from __future__ import annotations

from typing import Any

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)
from python_ai_sidecar.pipeline_builder.blocks.line_chart import (
    _materialize_paths,
    _normalize_y,
    _records,
    _validate_columns,
)


class ScatterChartBlockExecutor(BlockExecutor):
    block_id = "block_scatter_chart"

    async def execute(
        self,
        *,
        params: dict[str, Any],
        inputs: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        df = inputs.get("data")
        if not isinstance(df, pd.DataFrame):
            raise BlockExecutionError(code="INVALID_INPUT", message="'data' must be a DataFrame")

        x = self.require(params, "x")
        y = _normalize_y(params.get("y"))
        if not y:
            raise BlockExecutionError(code="MISSING_PARAM", message="'y' must be a non-empty string or list")
        series_field = params.get("series_field") or None
        title = params.get("title") or None

        if df.empty:
            return {
                "chart_spec": {
                    "__dsl": True,
                    "type": "empty",
                    "title": title or "No data",
                    "message": "上游資料為空",
                    "data": [],
                }
            }

        cols = [x, *y]
        if series_field:
            cols.append(series_field)
        df = _materialize_paths(df, cols)
        _validate_columns(df, cols, label="scatter_chart")

        rules = params.get("rules") or []
        highlight = None
        hf = params.get("highlight_field")
        if hf is not None:
            if hf not in df.columns:
                raise BlockExecutionError(
                    code="COLUMN_NOT_FOUND",
                    message=f"highlight_field '{hf}' not in data",
                )
            highlight = {"field": hf, "eq": params.get("highlight_eq", True)}

        spec: dict[str, Any] = {
            "__dsl": True,
            "type": "scatter",
            "title": title,
            "data": _records(df),
            "x": x,
            "y": y,
        }
        if rules:
            spec["rules"] = rules
        if highlight:
            spec["highlight"] = highlight
        if series_field:
            spec["series_field"] = series_field
        # P2b (2026-07-13): optional 線性迴歸線 + R² 標註（舊帳 D6 — plan 常寫
        # 「含迴歸線與 R²」但 block 畫不出來）。x 或 y 非數值就 fail-soft 略過
        # 並在 spec 註記，不炸 build。
        if params.get("regression"):
            reg = _linear_regression(df, x, y[0])
            if isinstance(reg, str):
                spec["regression_note"] = reg
            else:
                spec["regression"] = reg
        return {"chart_spec": spec}


def _linear_regression(df: pd.DataFrame, x: str, y: str) -> dict[str, Any] | str:
    """最小平方直線 + R²。回 dict（可畫）或 str（略過原因）。"""
    xs = pd.to_numeric(df[x], errors="coerce")
    ys = pd.to_numeric(df[y], errors="coerce")
    ok = xs.notna() & ys.notna()
    xs, ys = xs[ok], ys[ok]
    if len(xs) < 3:
        return "有效數值點 < 3，略過迴歸線"
    if float(xs.std()) == 0.0:
        return f"x 欄 '{x}' 無變異，略過迴歸線"
    import numpy as np
    slope, intercept = np.polyfit(xs, ys, 1)
    pred = slope * xs + intercept
    ss_res = float(((ys - pred) ** 2).sum())
    ss_tot = float(((ys - ys.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return {"slope": round(float(slope), 6), "intercept": round(float(intercept), 6),
            "r2": round(r2, 4), "x_min": float(xs.min()), "x_max": float(xs.max())}
