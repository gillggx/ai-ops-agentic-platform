"""block_union — 兩個 DataFrame 的縱向合併（row-wise concat）。

Use case: 分別拉 EQP-01、EQP-02 的 process_history 後合併成一張，下游用
         color=toolID 做 overlay 比較。

Input:
  primary   (DataFrame, required)
  secondary (DataFrame, required)

Params:
  on_schema_mismatch: "outer" (default) | "intersect"
    - outer:     所有欄位聯集，缺欄位填 null
    - intersect: 僅保留共同欄位

Output:
  data (DataFrame) — primary rows first, then secondary rows
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)


_STRATEGIES = {"outer", "intersect"}


class UnionBlockExecutor(BlockExecutor):
    block_id = "block_union"

    async def execute(
        self,
        *,
        params: dict[str, Any],
        inputs: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        primary = inputs.get("primary")
        secondary = inputs.get("secondary")
        if not isinstance(primary, pd.DataFrame):
            raise BlockExecutionError(
                code="INVALID_INPUT", message="'primary' input must be a DataFrame"
            )
        if not isinstance(secondary, pd.DataFrame):
            raise BlockExecutionError(
                code="INVALID_INPUT", message="'secondary' input must be a DataFrame"
            )

        strategy = params.get("on_schema_mismatch", "outer")
        if strategy not in _STRATEGIES:
            raise BlockExecutionError(
                code="INVALID_PARAM",
                message=f"on_schema_mismatch must be one of {_STRATEGIES}",
            )

        if strategy == "intersect":
            common = [c for c in primary.columns if c in secondary.columns]
            if not common:
                raise BlockExecutionError(
                    code="INVALID_INPUT",
                    message="primary and secondary have no columns in common",
                )
            out = pd.concat(
                [primary[common], secondary[common]], axis=0, ignore_index=True
            )
        else:  # outer
            out = pd.concat([primary, secondary], axis=0, ignore_index=True, sort=False)

        return {"data": out}
