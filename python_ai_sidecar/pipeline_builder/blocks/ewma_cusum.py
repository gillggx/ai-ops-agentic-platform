"""block_ewma_cusum — EWMA + CUSUM small-shift detector with mode toggle.

Distinct from `block_ewma` (transform that emits smoothed values for downstream).
This block produces a chart_spec only.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)
from python_ai_sidecar.pipeline_builder.blocks.line_chart import _records


logger = logging.getLogger(__name__)


class EwmaCusumBlockExecutor(BlockExecutor):
    block_id = "block_ewma_cusum"

    async def execute(
        self,
        *,
        params: dict[str, Any],
        inputs: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        df = inputs.get("data")
        if not isinstance(df, pd.DataFrame):
            raise BlockExecutionError(code="INVALID_INPUT", message="'data' must be a DataFrame")
        title = params.get("title") or None
        mode = params.get("mode", "ewma")
        if mode not in ("ewma", "cusum"):
            raise BlockExecutionError(code="INVALID_PARAM", message="mode must be 'ewma' or 'cusum'")

        if df.empty:
            return {"chart_spec": {"__dsl": True, "type": "empty", "title": title or "No data", "message": "上游資料為空", "data": []}}

        spec: dict[str, Any] = {
            "__dsl": True,
            "type": "ewma_cusum",
            "title": title,
            "data": _records(df),
            "x": "",
            "y": [],
            "mode": mode,
        }
        if isinstance(params.get("values"), list):
            spec["values"] = params["values"]
            target_data: pd.Series | None = pd.Series(params["values"], dtype="float64")
        else:
            value_col = params.get("value_column") or None
            if not value_col:
                raise BlockExecutionError(code="MISSING_PARAM", message="provide either `values` or `value_column`")
            if value_col not in df.columns:
                raise BlockExecutionError(code="COLUMN_NOT_FOUND", message=f"value_column '{value_col}' not in data")
            spec["value_column"] = value_col
            try:
                target_data = pd.to_numeric(df[value_col], errors="coerce").dropna()
            except Exception:  # noqa: BLE001
                target_data = None

        for k in ("lambda", "k", "h"):
            v = params.get(k)
            if isinstance(v, (int, float)):
                spec[k] = float(v)

        # Phase 10-D Fix B — defensive target handling.
        # CUSUM = Σ max(0, x_i − target − k). Without a sensible target,
        # values stay positive every step → S(t) ramps linearly to a meaningless
        # plot. LLM frequently omits target or sets it to 0 (especially when
        # user prompt didn't mention a setpoint). Default behavior:
        #   - target is set + non-zero: honor it
        #   - target missing / null: use data mean
        #   - target == 0: log warn, still substitute mean (matches the
        #     "almost always wrong on real metrology data" reality)
        target = params.get("target")
        if isinstance(target, (int, float)) and target != 0:
            spec["target"] = float(target)
        elif target_data is not None and not target_data.empty:
            auto = float(target_data.mean())
            spec["target"] = auto
            if isinstance(target, (int, float)) and target == 0:
                logger.warning(
                    "ewma_cusum: target=0 substituted with data mean=%.3f "
                    "(target=0 produces a monotonic ramp on non-zero data)",
                    auto,
                )
        # else: leave spec["target"] unset; frontend will fall back to its own default
        return {"chart_spec": spec}
