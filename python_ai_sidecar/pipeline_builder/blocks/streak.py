"""block_streak — 連續上升/下降偵測（run length）。

S4 (2026-07-13 user 需求)：block_delta 只給單點 is_rising；「連續 N 筆上升」
之前要 delta → rolling_sum → filter 三顆。這顆一次算出每列當下的連續長度，
配 filter 即成「連續 5 筆上升就告警」。

Input:  data (DataFrame)
Params: value_column (required) — 數值欄
        sort_by (required)      — 排序欄（時間或序號；嚴禁隱式預設）
        group_by (opt string | list) — 各組內獨立計算（例：每台機台）
Output: data (DataFrame) — 原欄 + 3 欄：
        <col>_streak_dir : 'up' | 'down' | 'flat'（跟前一筆比）
        <col>_streak_len : int — 目前同方向連續了幾「步」（up/down 才累計；
                           首筆與 flat 為 0）
        例：值 1,2,3,3,2 → dir = flat,up,up,flat,down；len = 0,1,2,0,1
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)
from python_ai_sidecar.pipeline_builder.blocks.line_chart import _materialize_paths


def _streak(vals: pd.Series) -> tuple[list[str], list[int]]:
    dirs: list[str] = []
    lens: list[int] = []
    prev = None
    cur_dir = "flat"
    cur_len = 0
    for v in vals:
        if prev is None or pd.isna(v) or pd.isna(prev):
            d = "flat"
        elif v > prev:
            d = "up"
        elif v < prev:
            d = "down"
        else:
            d = "flat"
        if d == "flat":
            cur_dir, cur_len = "flat", 0
        elif d == cur_dir:
            cur_len += 1
        else:
            cur_dir, cur_len = d, 1
        dirs.append(d)
        lens.append(cur_len)
        prev = v if not pd.isna(v) else prev
    return dirs, lens


class StreakBlockExecutor(BlockExecutor):
    block_id = "block_streak"

    async def execute(
        self,
        *,
        params: dict[str, Any],
        inputs: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        df = inputs.get("data")
        if not isinstance(df, pd.DataFrame):
            raise BlockExecutionError(code="INVALID_INPUT", message="'data' must be DataFrame")
        value_column = self.require(params, "value_column")
        sort_by = self.require(params, "sort_by")
        group_by = params.get("group_by")
        groups = ([group_by] if isinstance(group_by, str) and group_by else
                  [str(g) for g in group_by] if isinstance(group_by, list) else [])

        cols = [value_column, sort_by, *groups]
        df = _materialize_paths(df, cols)
        for c in cols:
            if c not in df.columns:
                raise BlockExecutionError(
                    code="COLUMN_NOT_FOUND", message=f"column '{c}' not in data",
                    hint=f"Available: {list(df.columns)[:10]}")

        out = df.sort_values([*groups, sort_by], ignore_index=True)
        vals = pd.to_numeric(out[value_column], errors="coerce")
        dir_col = f"{value_column}_streak_dir"
        len_col = f"{value_column}_streak_len"
        if groups:
            dirs_all: list[str] = []
            lens_all: list[int] = []
            for _, g in vals.groupby([out[c] for c in groups], sort=False):
                d, l = _streak(g)
                dirs_all.extend(d)
                lens_all.extend(l)
            out[dir_col] = dirs_all
            out[len_col] = lens_all
        else:
            d, l = _streak(vals)
            out[dir_col] = d
            out[len_col] = l
        return {"data": out}
