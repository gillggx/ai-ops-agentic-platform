"""block_line_chart — primitive line/multi-line chart.

Equivalent to block_chart(chart_type='line', ...) but as a dedicated block
in the new uniformly-named chart family. Frontend route via the SVG
LineChart component (Stage 4 dispatcher).

Output `chart_spec` is the same ChartDSL shape the existing block_chart
emits, so Stage 5 pipeline migration is a block_id rename — params + spec
are identical.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)


def _normalize_y(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [str(v) for v in raw]
    return []


def _validate_columns(df: pd.DataFrame, cols: list[str], label: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise BlockExecutionError(
            code="COLUMN_NOT_FOUND",
            message=f"{label} column(s) not in data: {missing}",
        )


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    # Coerce datetime columns to ISO strings so JSON-serializability holds
    # and frontend axis detection picks them up as time-typed.
    out = df.copy()
    for c in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[c]):
            out[c] = out[c].dt.strftime("%Y-%m-%dT%H:%M:%S")
    return out.to_dict(orient="records")


class LineChartBlockExecutor(BlockExecutor):
    block_id = "block_line_chart"

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
        y_secondary = _normalize_y(params.get("y_secondary"))
        series_field = params.get("series_field") or None
        title = params.get("title") or None

        if df.empty:
            return {
                "chart_spec": {
                    "__dsl": True,
                    "type": "empty",
                    "title": title or "No data",
                    "message": "上游資料為空 — 可能是 logic 沒觸發或 filter 篩光",
                    "data": [],
                }
            }

        cols = [x, *y, *y_secondary]
        if series_field:
            cols.append(series_field)
        _validate_columns(df, cols, label="line_chart")

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
            "type": "line",
            "title": title,
            "data": _records(df),
            "x": x,
            "y": y,
        }
        if y_secondary:
            spec["y_secondary"] = y_secondary
        if rules:
            spec["rules"] = rules
        if highlight:
            spec["highlight"] = highlight
        if series_field:
            spec["series_field"] = series_field
        return {"chart_spec": spec}
