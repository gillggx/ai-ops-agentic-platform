"""block_count_rows — count upstream DataFrame rows (optionally grouped).

Output a small DataFrame with `count` column (1 row per group, or 1 row total).
Plays nicely with downstream `block_threshold` for "count == N" style checks.

Use case: "are all OOC events from the same recipe?" → filter(OOC) + groupby_agg(recipeID, count)
produces N rows (N = unique recipes). block_count_rows then reduces to a single
row with `count=N`; threshold(upper=1) → triggers if N > 1 (i.e. NOT same recipe).
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)


class CountRowsBlockExecutor(BlockExecutor):
    block_id = "block_count_rows"

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

        group_by: Optional[str] = params.get("group_by") or None
        missing_group = group_by is not None and group_by not in df.columns
        if missing_group:
            # PR-F runtime-QA: fall back to total count if group column missing
            # (common in migrated pipelines where the skill used a nested field).
            group_by = None

        if group_by:
            out = df.groupby(group_by, dropna=False).size().reset_index(name="count")
        else:
            out = pd.DataFrame([{"count": int(len(df))}])
        return {"data": out}
