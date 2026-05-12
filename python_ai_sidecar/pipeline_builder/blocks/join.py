"""block_join — 兩個 DataFrame by key 合併。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)
from python_ai_sidecar.pipeline_builder.path import get_column_series


_HOW = {"inner", "left", "right", "outer"}
_JOIN_KEY_PREFIX = "__join_key_"


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
        # Path-aware: materialize each key path into scratch columns on both
        # frames, merge on the scratch names, then drop them.
        left_work = left
        right_work = right
        scratch_keys: list[str] = []
        join_on: list[str] = []

        for i, k in enumerate(keys):
            if not isinstance(k, str) or not k:
                raise BlockExecutionError(
                    code="INVALID_PARAM", message=f"join key must be non-empty string, got {k!r}"
                )
            if "." in k or "[]" in k:
                try:
                    left_series = get_column_series(left_work, k)
                except KeyError:
                    raise BlockExecutionError(
                        code="COLUMN_NOT_FOUND", message=f"key path '{k}' not in left",
                    ) from None
                try:
                    right_series = get_column_series(right_work, k)
                except KeyError:
                    raise BlockExecutionError(
                        code="COLUMN_NOT_FOUND", message=f"key path '{k}' not in right",
                    ) from None
                scratch = f"{_JOIN_KEY_PREFIX}{i}"
                if left_work is left:
                    left_work = left.copy()
                if right_work is right:
                    right_work = right.copy()
                left_work[scratch] = left_series.values
                right_work[scratch] = right_series.values
                scratch_keys.append(scratch)
                join_on.append(scratch)
            else:
                if k not in left_work.columns:
                    raise BlockExecutionError(
                        code="COLUMN_NOT_FOUND", message=f"key '{k}' not in left"
                    )
                if k not in right_work.columns:
                    raise BlockExecutionError(
                        code="COLUMN_NOT_FOUND", message=f"key '{k}' not in right"
                    )
                join_on.append(k)

        merged = left_work.merge(right_work, on=join_on, how=how, suffixes=("", "_r"))
        if scratch_keys:
            merged = merged.drop(columns=scratch_keys, errors="ignore")
        return {"data": merged}
