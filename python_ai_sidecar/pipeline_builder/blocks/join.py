"""block_join — 兩個 DataFrame by key 合併。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)


_HOW = {"inner", "left", "right", "outer"}


class JoinBlockExecutor(BlockExecutor):
    block_id = "block_join"

    async def execute(
        self,
        *,
        params: dict[str, Any],
        inputs: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        left = inputs.get("left")
        right = inputs.get("right")
        if not isinstance(left, pd.DataFrame):
            raise BlockExecutionError(code="INVALID_INPUT", message="'left' must be DataFrame")
        if not isinstance(right, pd.DataFrame):
            raise BlockExecutionError(code="INVALID_INPUT", message="'right' must be DataFrame")

        key = self.require(params, "key")
        how = params.get("how", "inner")
        if how not in _HOW:
            raise BlockExecutionError(
                code="INVALID_PARAM", message=f"how must be one of {_HOW}"
            )
        keys = key if isinstance(key, list) else [key]
        for k in keys:
            if k not in left.columns:
                raise BlockExecutionError(
                    code="COLUMN_NOT_FOUND", message=f"key '{k}' not in left"
                )
            if k not in right.columns:
                raise BlockExecutionError(
                    code="COLUMN_NOT_FOUND", message=f"key '{k}' not in right"
                )

        merged = left.merge(right, on=keys, how=how, suffixes=("", "_r"))
        return {"data": merged}
