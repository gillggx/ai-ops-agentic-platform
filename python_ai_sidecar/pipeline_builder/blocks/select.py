"""block_select — project / rename fields. jq-lite for objects.

Param `fields` is a list of mappings:
    [{path: "tool_id", as: "tool"},
     {path: "spc_summary.ooc_count"},          # default `as` = leaf name
     {path: "spc_charts[].name", as: "names"}]

Output is a new DataFrame containing only those columns (flat or list values).
Drops every other column. Use when you want to slim down a wide record before
passing it to a chart or downstream MCP call.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)
from python_ai_sidecar.pipeline_builder.path import get_column_series


class SelectBlockExecutor(BlockExecutor):
    block_id = "block_select"

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
                code="INVALID_INPUT", message="'data' must be DataFrame"
            )
        fields = self.require(params, "fields")
        if not isinstance(fields, list) or not fields:
            raise BlockExecutionError(
                code="INVALID_PARAM",
                message="fields must be a non-empty list of {path, as?}",
            )

        out_cols: dict[str, Any] = {}
        for i, f in enumerate(fields):
            if not isinstance(f, dict):
                raise BlockExecutionError(
                    code="INVALID_PARAM",
                    message=f"fields[{i}] must be an object with 'path' (+ optional 'as')",
                )
            path = f.get("path")
            if not isinstance(path, str) or not path:
                raise BlockExecutionError(
                    code="INVALID_PARAM",
                    message=f"fields[{i}].path must be a non-empty string",
                )
            try:
                series = get_column_series(df, path)
            except KeyError:
                raise BlockExecutionError(
                    code="COLUMN_NOT_FOUND",
                    message=f"fields[{i}].path '{path}' not in input",
                    hint=f"Available top-level: {list(df.columns)[:10]}",
                ) from None
            name = f.get("as") or path.rsplit(".", 1)[-1].replace("[]", "")
            out_cols[name] = series.values

        out = pd.DataFrame(out_cols)
        return {"data": out}
