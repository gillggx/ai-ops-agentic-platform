"""block_consecutive_rule — Tail-based 連續 N 次 True 偵測。

Semantics (PR-A / 2026-04-19):
  針對每個 group（或整個序列），檢查 **按 sort_by 排序後的最後 N 筆** 是否全為 True。
  - 是：該 group 觸發，該 group 的 tail N rows `triggered_row=True`
  - 否：不觸發（即使歷史上曾有 run >= N）
  用於即時告警 — 反映「當下狀態」，不回頭掃歷史。

Logic-node unified schema:
  output:
    triggered (bool)       — 任一 group 的最後 N 筆全為 True
    evidence  (DataFrame)  — **全部輸入 rows（按 group + sort_by 排序）**，加欄：
                              triggered_row (bool) — 該筆是否屬於觸發 tail
                              group          — group_by 的值（若無 group_by 則 None）
                              trigger_id     — 觸發時的 deterministic id（非觸發列為 None）
                              run_position   — tail 內第幾筆（1..N；非觸發列為 None）
                              run_length     — tail 長度（=count；非觸發列為 None）
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)
from python_ai_sidecar.pipeline_builder.blocks.line_chart import _materialize_paths
from python_ai_sidecar.pipeline_builder.path import ensure_flat_spc


def _make_trigger_id(group_value: Any, last_sort_value: Any) -> str:
    """Deterministic per-(group, last event) — same data → same id (idempotent)."""
    g = "_" if group_value is None else str(group_value)
    t = "_" if last_sort_value is None else str(last_sort_value)
    return f"{g}__{t}"


class ConsecutiveRuleBlockExecutor(BlockExecutor):
    block_id = "block_consecutive_rule"

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
        df = ensure_flat_spc(df)  # accept nested upstream

        flag_col = self.require(params, "flag_column")
        count = int(self.require(params, "count"))
        sort_by: str = self.require(params, "sort_by")
        group_by: Optional[str] = params.get("group_by") or None

        df = _materialize_paths(df, [c for c in (flag_col, sort_by, group_by) if c])
        if flag_col not in df.columns:
            raise BlockExecutionError(
                code="COLUMN_NOT_FOUND",
                message=f"flag_column '{flag_col}' not in data",
            )
        if sort_by not in df.columns:
            raise BlockExecutionError(
                code="COLUMN_NOT_FOUND",
                message=f"sort_by '{sort_by}' not in data",
            )
        if group_by is not None and group_by not in df.columns:
            raise BlockExecutionError(
                code="COLUMN_NOT_FOUND",
                message=f"group_by '{group_by}' not in data",
            )
        if count < 2:
            raise BlockExecutionError(
                code="INVALID_PARAM", message="count must be >= 2"
            )

        # Evidence = full rows, ordered by group + sort_by for human readability.
        if group_by:
            iterable: list[tuple[Any, pd.DataFrame]] = [
                (g, sub) for g, sub in df.groupby(group_by, dropna=False)
            ]
        else:
            iterable = [(None, df)]

        chunks: list[pd.DataFrame] = []
        triggered_any = False

        for group_value, sub in iterable:
            sub_sorted = sub.sort_values(by=sort_by, kind="mergesort").copy()
            sub_sorted = sub_sorted.reset_index(drop=True)
            n = len(sub_sorted)

            # Defaults — no trigger annotation.
            sub_sorted["triggered_row"] = False
            sub_sorted["group"] = group_value
            sub_sorted["trigger_id"] = None
            sub_sorted["run_position"] = None
            sub_sorted["run_length"] = None

            if n >= count:
                tail_slice = slice(n - count, n)
                tail_flags = sub_sorted[flag_col].iloc[tail_slice].fillna(False).astype(bool)
                if tail_flags.all():
                    triggered_any = True
                    trigger_id = _make_trigger_id(
                        group_value, sub_sorted.iloc[-1][sort_by]
                    )
                    sub_sorted.loc[sub_sorted.index[tail_slice], "triggered_row"] = True
                    sub_sorted.loc[sub_sorted.index[tail_slice], "trigger_id"] = trigger_id
                    sub_sorted.loc[sub_sorted.index[tail_slice], "run_position"] = list(
                        range(1, count + 1)
                    )
                    sub_sorted.loc[sub_sorted.index[tail_slice], "run_length"] = count

            chunks.append(sub_sorted)

        evidence = (
            pd.concat(chunks, ignore_index=True)
            if chunks
            else pd.DataFrame()
        )
        return {"triggered": triggered_any, "evidence": evidence}
