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
from python_ai_sidecar.pipeline_builder.blocks._chart_facet import maybe_facet


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

        # Facet (small multiples) — split by column, render one panel per
        # group. Pass `_render_one` as the inner so we don't recurse into
        # facet inside facet. Returns None when `facet` param isn't set.
        faceted = await maybe_facet(
            params=params, inputs=inputs, context=context,
            inner=self._render_one,
        )
        if faceted is not None:
            return faceted

        return await self._render_one(params, inputs, context)

    async def _render_one(
        self,
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

        rules = list(params.get("rules") or [])

        # SPC-style column shorthands — `ucl_column` / `lcl_column` / `center_column`
        # take the first row's value of the named column and emit a rule line.
        # Inherited from block_chart (which is being retired); lets users
        # author SPC charts without computing static rule values up front.
        # Multiple rows must share the same control limits; if upstream emits
        # per-row varying values we just use row 0 (good enough for static
        # control charts where UCL/LCL come from the SPC config table).
        def _row0(col_name: str | None) -> Any:
            if not col_name or col_name not in df.columns or df.empty:
                return None
            v = df[col_name].iloc[0]
            try:
                fv = float(v)
                return fv if pd.notna(v) else None
            except (TypeError, ValueError):
                return None

        ucl = _row0(params.get("ucl_column"))
        lcl = _row0(params.get("lcl_column"))
        center = _row0(params.get("center_column"))
        if ucl is not None:
            rules.append({"value": ucl, "label": "UCL", "style": "danger"})
        if center is not None:
            rules.append({"value": center, "label": "Center", "style": "center"})
        if lcl is not None:
            rules.append({"value": lcl, "label": "LCL", "style": "danger"})

        highlight = None
        # `highlight_column` is the legacy block_chart name; `highlight_field`
        # is the new canonical name. Accept both for migration ease.
        hf = params.get("highlight_field") or params.get("highlight_column")
        if hf is not None:
            if hf not in df.columns:
                raise BlockExecutionError(
                    code="COLUMN_NOT_FOUND",
                    message=f"highlight column '{hf}' not in data",
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
