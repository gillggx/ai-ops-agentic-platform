"""block_spc_long_form — process_history wide → SPC long format.

Purpose-built reshape for SPC patrol pipelines.
process_history returns one row per event with `spc_<chart>_<field>` columns
(value/ucl/lcl/is_ooc) for every chart at the station — a wide layout that
makes "any chart consecutive OOC" pipelines awkward (LLM has to compose
generic block_unpivot + rename + groupby and routinely picks wrong column
names like `chart_type` instead of `chart_name`).

This block bakes in the canonical reshape:
  spc_X1_value, spc_X1_is_ooc, spc_X2_value, spc_X2_is_ooc, ...
  → long DF with [<id_cols>, chart_name, value, ucl, lcl, is_ooc]

so the downstream pipeline becomes a clean
  spc_long_form → consecutive_rule(group_by=chart_name, flag_column=is_ooc, ...)
"""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)


_ID_COLUMNS_DEFAULT = (
    "eventTime", "toolID", "lotID", "step", "spc_status", "fdc_classification",
)
_SPC_FIELD_RE = re.compile(r"^spc_(.+)_(value|ucl|lcl|is_ooc)$")


class SpcLongFormBlockExecutor(BlockExecutor):
    block_id = "block_spc_long_form"

    async def execute(
        self,
        *,
        params: dict[str, Any],
        inputs: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        df = inputs.get("data")
        if not isinstance(df, pd.DataFrame):
            raise BlockExecutionError(
                code="INVALID_INPUT", message="'data' input must be a DataFrame"
            )

        if df.empty:
            return {"data": df.iloc[0:0].assign(
                chart_name=pd.Series(dtype="object"),
                value=pd.Series(dtype="float64"),
                ucl=pd.Series(dtype="float64"),
                lcl=pd.Series(dtype="float64"),
                is_ooc=pd.Series(dtype="bool"),
            )}

        # Group spc_*_<field> columns by chart name
        chart_fields: dict[str, dict[str, str]] = {}
        for col in df.columns:
            m = _SPC_FIELD_RE.match(col)
            if not m:
                continue
            chart, field = m.group(1), m.group(2)
            chart_fields.setdefault(chart, {})[field] = col

        if not chart_fields:
            raise BlockExecutionError(
                code="NO_SPC_COLUMNS",
                message="No 'spc_<chart>_<field>' columns found — does the upstream "
                        "process_history include SPC data? (object_name='SPC' or unset)",
            )

        present_id_cols = [c for c in _ID_COLUMNS_DEFAULT if c in df.columns]

        # Build one frame per chart, then concat. Each frame:
        #   [id_cols..., chart_name=<chart>, value, ucl, lcl, is_ooc]
        frames: list[pd.DataFrame] = []
        for chart, field_map in chart_fields.items():
            sub = df[present_id_cols].copy()
            sub["chart_name"] = chart
            for f in ("value", "ucl", "lcl", "is_ooc"):
                src = field_map.get(f)
                sub[f] = df[src] if src is not None else pd.NA
            frames.append(sub)

        out = pd.concat(frames, axis=0, ignore_index=True)
        return {"data": out}
