"""block_data_view — PR-E1 output node that pins any DataFrame to the
Pipeline Results panel as a user-visible data view.

Unlike block_chart(chart_type=table) this is semantically an "output of raw
data" (not a chart spec). Pipeline Results renders these in a dedicated
`data_views` section so users see every tabular side-output they declared.

Multiple block_data_view nodes per pipeline are allowed — ordered by
`sequence` param (ascending), then by canvas position.x as tiebreaker.
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)


class DataViewBlockExecutor(BlockExecutor):
    block_id = "block_data_view"

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

        title: Optional[str] = params.get("title") or None
        description: Optional[str] = params.get("description") or None
        max_rows_param = params.get("max_rows")
        try:
            max_rows = int(max_rows_param) if max_rows_param is not None else 200
        except (TypeError, ValueError):
            raise BlockExecutionError(
                code="INVALID_PARAM", message=f"max_rows must be integer, got {max_rows_param!r}"
            ) from None

        columns_param = params.get("columns")
        dropped_columns: list[str] = []
        if isinstance(columns_param, list) and columns_param:
            # Graceful: drop missing cols rather than raising — migrated
            # pipelines often list cols the skill's Python constructed;
            # the user can refine in Inspector.
            keep = [c for c in columns_param if c in df.columns]
            dropped_columns = [c for c in columns_param if c not in df.columns]
            if not keep:
                # fallback: show everything if all requested cols are missing
                keep = list(df.columns)
        else:
            keep = list(df.columns)

        trimmed = df[keep].head(max_rows)
        sequence_raw = params.get("sequence")
        sequence = int(sequence_raw) if isinstance(sequence_raw, (int, float)) else None

        data_view_spec: dict[str, Any] = {
            "type": "data_view",  # Distinct from chart_spec — Pipeline Results
                                   # renders this in its own section.
            "title": title or "Data View",
            "columns": keep,
            "rows": trimmed.to_dict(orient="records"),
            "total_rows": int(len(df)),
            "sequence": sequence,
        }
        if description:
            data_view_spec["description"] = description
        if dropped_columns:
            data_view_spec["dropped_columns"] = dropped_columns  # surface to UI

        return {"data_view": data_view_spec}
