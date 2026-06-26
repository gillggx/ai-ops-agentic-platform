"""block_time_bucket — 把時間欄截斷成等距時間桶（hour / day / 15min…）。

解鎖「事件次數 by hour」類分析：process_history 的 eventTime 是毫秒級唯一的 ISO
字串，直接 groupby 會每筆一桶。本 block 把它截斷到指定粒度，輸出一個可直接
groupby 的桶欄，下游接 block_groupby_agg(count) + bar/line chart。
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

# interval -> pandas floor frequency
_FREQ = {"15min": "15min", "30min": "30min", "1h": "1h", "4h": "4h", "1d": "1D"}


class TimeBucketBlockExecutor(BlockExecutor):
    block_id = "block_time_bucket"

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

        column = self.require(params, "column")
        interval = str(params.get("interval") or "1h").lower()
        if interval not in _FREQ:
            raise BlockExecutionError(
                code="INVALID_PARAM", message=f"interval must be one of {sorted(_FREQ)}"
            )
        output_column = str(params.get("output_column") or "time_bucket")
        tz = str(params.get("tz") or "UTC")
        label = str(params.get("label") or "start").lower()
        if label not in ("start", "center"):
            raise BlockExecutionError(code="INVALID_PARAM", message="label must be start|center")

        try:
            series = get_column_series(df, str(column))
        except Exception:
            series = df[column] if column in df.columns else None
        if series is None:
            raise BlockExecutionError(
                code="COLUMN_NOT_FOUND", message=f"column '{column}' not in data"
            )

        # Parse to UTC-aware datetime (naive ISO strings are treated as UTC), then
        # align hours in the requested tz so "by hour" buckets are in local time.
        # format="ISO8601" so varying precision (with/without microseconds) all
        # parse — otherwise pandas infers one format from the first row and NaTs
        # the rest. Fall back to free inference for non-ISO / already-datetime data.
        try:
            ts = pd.to_datetime(series, errors="coerce", utc=True, format="ISO8601")
        except (ValueError, TypeError):
            ts = pd.to_datetime(series, errors="coerce", utc=True)
        if tz and tz.upper() != "UTC":
            try:
                ts = ts.dt.tz_convert(tz)
            except Exception as exc:
                raise BlockExecutionError(
                    code="INVALID_PARAM", message=f"invalid tz '{tz}': {exc}"
                ) from exc

        freq = _FREQ[interval]
        bucket = ts.dt.floor(freq)
        if label == "center":
            bucket = bucket + (pd.to_timedelta(freq) / 2)

        # Stable, groupable string label (NaT -> None so bad rows don't crash chart).
        labels = bucket.dt.strftime("%Y-%m-%dT%H:%M")
        labels = labels.where(bucket.notna(), None)

        out = df.copy()
        out[output_column] = labels.values
        return {"data": out}
