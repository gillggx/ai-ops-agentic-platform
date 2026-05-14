"""Shared base for block_spc_panel + block_apc_panel.

Both panels collapse a 3-5 step composition (unnest → filter →
sort/keep-latest → multi-series chart) into one deterministic block, so
the LLM can pick a single block instead of composing primitives (where
it routinely makes mistakes — see 2026-05-14 lastooc smoke: `sort +
limit=1` killed multi-SPC by reducing to 1 row).

Subclass `_ParamPanelBase` and set:
    nested_col            : "spc_charts" | "apc_params"
    name_field            : "name" | "param_name"
    value_field           : "value"
    bound_fields          : {"ucl": "ucl", "lcl": "lcl"}  (or {} for APC)
    violation_field       : "is_ooc"  (or "" / None for APC)
    default_title         : "SPC Charts" | "APC Parameters"
    latest_violation_label : "latest_ooc" | "latest_drift"

The executor handles the four event_filter modes uniformly.
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)


class _ParamPanelBase(BlockExecutor):
    # Subclass overrides — see module docstring.
    nested_col: str = ""
    name_field: str = "name"
    value_field: str = "value"
    bound_fields: dict[str, str] = {}      # {"ucl": "ucl", "lcl": "lcl"}
    violation_field: Optional[str] = None  # "is_ooc" or None
    default_title: str = "Panel"
    latest_violation_label: str = "latest_violation"
    # v18 source mode: object_name to pass to process_history when panel
    # fetches data itself. "SPC" → only nest SPC fields; "APC" → APC only.
    process_history_object_name: str = "SPC"

    async def execute(
        self,
        *,
        params: dict[str, Any],
        inputs: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        title = str(params.get("title") or self.default_title)

        # v18 (2026-05-14): hybrid source mode. If no upstream data is
        # connected AND user gave fetch params (tool_id), call
        # ProcessHistoryBlockExecutor internally so panel works as a
        # self-contained "give me SPC chart for X" block.
        df = inputs.get("data") if isinstance(inputs, dict) else None
        if df is None and params.get("tool_id"):
            df = await self._fetch_process_history(params, context)
        if not isinstance(df, pd.DataFrame):
            raise BlockExecutionError(
                code="INVALID_INPUT",
                message=(
                    "'data' input missing — connect an upstream process_history, "
                    "OR set source params (tool_id + optional step/time_range) on "
                    f"{self.block_id} to fetch internally."
                ),
            )

        if df.empty:
            return {"chart_spec": self._empty_chart(title, "上游資料為空")}

        # Step 1: detect input shape — nested vs already-unnested.
        long = self._coerce_to_long(df)
        if long.empty:
            return {"chart_spec": self._empty_chart(title, "No data after unnesting")}

        # Step 2: filter by specific chart_name / param_name when given.
        chart_name = params.get("chart_name")
        if chart_name and self.name_field in long.columns:
            long = long[long[self.name_field].astype(str) == str(chart_name)].reset_index(drop=True)
            if long.empty:
                return {"chart_spec": self._empty_chart(
                    title, f"No data for {self.name_field}={chart_name!r}"
                )}

        # Step 3: apply event_filter.
        event_filter = str(params.get("event_filter") or self.latest_violation_label)
        event_time = params.get("event_time")
        long, filter_note = self._apply_event_filter(long, event_filter, event_time)

        # Step 4: show_only_violations flag.
        if bool(params.get("show_only_violations")) and self.violation_field:
            if self.violation_field in long.columns:
                long = long[long[self.violation_field] == True].reset_index(drop=True)  # noqa: E712

        if long.empty:
            note = filter_note or "No data after filter"
            return {"chart_spec": self._empty_chart(title, note)}

        # Step 5: assemble chart_spec with color customization.
        chart_spec = self._build_chart_spec(long, title, event_filter, filter_note, params)
        return {"chart_spec": chart_spec}

    async def _fetch_process_history(
        self,
        params: dict[str, Any],
        context: ExecutionContext,
    ) -> "pd.DataFrame":
        """v18: source mode. Run ProcessHistoryBlockExecutor inline."""
        from python_ai_sidecar.pipeline_builder.blocks.process_history import (
            ProcessHistoryBlockExecutor,
        )
        ph = ProcessHistoryBlockExecutor()
        ph_params = {
            "tool_id": params.get("tool_id"),
            "lot_id": params.get("lot_id"),
            "step": params.get("step"),
            "time_range": params.get("time_range") or "7d",
            "limit": params.get("limit") or 200,
            "nested": True,
            "object_name": self.process_history_object_name,
        }
        # Drop None so process_history's tri-state required check works.
        ph_params = {k: v for k, v in ph_params.items() if v is not None}
        result = await ph.execute(params=ph_params, inputs={}, context=context)
        return result.get("data")  # type: ignore[return-value]

    # ── Subclass-friendly helpers ──────────────────────────────────────

    def _coerce_to_long(self, df: pd.DataFrame) -> pd.DataFrame:
        """If input has the nested list column → explode + lift. Otherwise
        assume already long-form and pass through.
        """
        if self.nested_col and self.nested_col in df.columns and df[self.nested_col].apply(
            lambda v: isinstance(v, list)
        ).any():
            exploded = df.explode(self.nested_col, ignore_index=True)
            exploded = exploded[exploded[self.nested_col].notna()].reset_index(drop=True)
            if exploded.empty:
                return exploded
            normalized = pd.json_normalize(exploded[self.nested_col])
            # Keep id-like columns from upstream (eventTime/toolID/lotID/step).
            id_cols = [
                c for c in ("eventTime", "toolID", "lotID", "step", "spc_status", "fdc_classification")
                if c in df.columns
            ]
            base = exploded[id_cols].reset_index(drop=True)
            normalized = normalized.reset_index(drop=True)
            out = pd.concat([base, normalized], axis=1)
            return out
        # Already long-form (downstream of block_unnest / block_spc_long_form).
        return df.copy()

    def _apply_event_filter(
        self,
        long: pd.DataFrame,
        mode: str,
        event_time: Any,
    ) -> tuple[pd.DataFrame, str]:
        """Returns (filtered_df, human_note). Note empty when no filter applied."""
        # Mode: "all" — keep everything, trend mode.
        if mode == "all":
            return long, ""

        # Mode: custom_time — exact eventTime match.
        if mode == "custom_time":
            if not event_time or "eventTime" not in long.columns:
                return long, f"event_filter=custom_time but event_time empty — kept all"
            filtered = long[long["eventTime"].astype(str) == str(event_time)]
            return filtered.reset_index(drop=True), f"eventTime={event_time}"

        # Mode: latest_event — pick max eventTime, keep all rows at that timestamp.
        if mode == "latest_event":
            if "eventTime" not in long.columns or long.empty:
                return long, "no eventTime column"
            latest_ts = long["eventTime"].max()
            filtered = long[long["eventTime"] == latest_ts].reset_index(drop=True)
            return filtered, f"latest_event @ {latest_ts}"

        # Mode: latest_violation (latest_ooc / latest_drift) — find latest
        # eventTime where any row has violation=true, then keep all rows at
        # that timestamp. Fallback to latest_event if no violations.
        if mode == self.latest_violation_label and self.violation_field:
            if self.violation_field not in long.columns or "eventTime" not in long.columns:
                # Fall through to latest_event semantics.
                return self._apply_event_filter(long, "latest_event", None)
            violating = long[long[self.violation_field] == True]  # noqa: E712
            if violating.empty:
                fallback, _ = self._apply_event_filter(long, "latest_event", None)
                return fallback, "no violations found — fell back to latest_event"
            latest_violation_ts = violating["eventTime"].max()
            filtered = long[long["eventTime"] == latest_violation_ts].reset_index(drop=True)
            return filtered, f"{self.latest_violation_label} @ {latest_violation_ts}"

        # Unknown mode — keep all and note it.
        return long, f"unknown event_filter={mode!r} — kept all"

    def _build_chart_spec(
        self,
        long: pd.DataFrame,
        title: str,
        event_filter: str,
        filter_note: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Multi-series line chart by name_field. SPC subclass adds UCL/LCL
        rules + OOC highlight via violation_field; APC just plots value.

        v18: color customization via params:
          - value_color (default green) — colors the value line(s)
          - bound_color (default orange) — colors UCL/LCL rules
          - color_by (string col name) — series colored by that column;
            overrides series_field which defaults to name_field
        """
        value_color = str(params.get("value_color") or "#16a34a")  # green-600
        bound_color = str(params.get("bound_color") or "#f59e0b")  # amber-500
        color_by = params.get("color_by")

        # x axis: eventTime if available + multi-row, else name_field (single-event mode).
        n_distinct_ts = (
            long["eventTime"].nunique() if "eventTime" in long.columns else 0
        )

        # series_field priority:
        #   1) user color_by overrides everything (e.g. color by toolID)
        #   2) name_field BUT only when there are >= 2 distinct names —
        #      otherwise it's a single trace and seriesing adds nothing,
        #      drops user's value_color override since renderer falls back
        #      to SERIES_COLORS palette
        if color_by and isinstance(color_by, str) and color_by in long.columns:
            series_field: Optional[str] = color_by
        elif self.name_field in long.columns and long[self.name_field].nunique() >= 2:
            series_field = self.name_field
        else:
            series_field = None

        if n_distinct_ts > 1:
            x_field = "eventTime"
            chart_type = "line"
        else:
            # Single timestamp: switch to bar so each `name` is a category.
            x_field = self.name_field if self.name_field in long.columns else "name"
            # Bar mode doesn't need series_field — each category is its own bar.
            series_field = None if not color_by else series_field
            chart_type = "bar"

        # Coerce datetime to ISO string for JSON.
        out = long.copy()
        for c in out.columns:
            if pd.api.types.is_datetime64_any_dtype(out[c]):
                out[c] = out[c].dt.strftime("%Y-%m-%dT%H:%M:%S")
        # Drop heavy nested cols that bloat JSON & confuse renderer.
        for heavy in ("spc_charts", "apc_params", "spc_summary"):
            if heavy in out.columns:
                out = out.drop(columns=[heavy])

        data = out.to_dict(orient="records")

        # SPC subclass: add UCL/LCL bound rules using first row's values.
        rules: list[dict[str, Any]] = []
        if self.bound_fields and not out.empty:
            for label, col in self.bound_fields.items():
                if col in out.columns:
                    v = out[col].iloc[0]
                    try:
                        vf = float(v)
                        if not pd.isna(vf):
                            rules.append({
                                "value": vf,
                                "label": label.upper(),
                                "style": "danger",
                                "color": bound_color,
                            })
                    except (TypeError, ValueError):
                        pass

        spec: dict[str, Any] = {
            "__dsl": True,
            "type": chart_type,
            "title": title + (f"  ({filter_note})" if filter_note else ""),
            "data": data,
            "x": x_field,
            "y": [self.value_field],
            # v18: pass default color for value line — frontend renderer
            # uses spec.colors[i] (if present) per y[] entry, otherwise
            # falls back to its palette. We only set when single y series.
            "colors": [value_color] if not series_field else None,
        }
        # Drop None to keep JSON clean.
        spec = {k: v for k, v in spec.items() if v is not None}

        if series_field:
            spec["series_field"] = series_field
        if rules:
            spec["rules"] = rules
        if self.violation_field and self.violation_field in out.columns:
            spec["highlight"] = {"field": self.violation_field, "eq": True}
        # Metadata — useful for admin trace.
        spec["meta"] = {
            "event_filter": event_filter,
            "n_rows": len(data),
            "n_series": int(out[series_field].nunique()) if series_field and series_field in out.columns else 1,
            "color_by": color_by or None,
        }
        return spec

    def _empty_chart(self, title: str, message: str) -> dict[str, Any]:
        return {
            "__dsl": True,
            "type": "empty",
            "title": title,
            "message": message,
            "data": [],
        }
