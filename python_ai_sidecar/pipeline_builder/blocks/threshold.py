"""block_threshold — 對 numeric column 套 UCL/LCL 判斷。

Logic-node unified schema (PR-A / 2026-04-19):
  output:
    triggered (bool)       — 是否有任一 row 違反 bound
    evidence  (DataFrame)  — **全部被評估的 rows**（不是篩選子集），加欄：
                              triggered_row (bool)    — 該筆是否違規
                              violation_side (str|NaN) — 僅 triggered_row=True 時填
                              violated_bound (float|NaN)
                              explanation    (str|NaN)

  Evidence 永遠包含所有輸入 rows，讓人類可稽核整條資料通過 logic 時的判讀狀態。
  未觸發的 rows → triggered_row=False，其他欄位為 NaN。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)


_BOUNDS = {"upper", "lower", "both"}
_OPERATORS = {"==", "!=", ">=", "<=", ">", "<"}


class ThresholdBlockExecutor(BlockExecutor):
    block_id = "block_threshold"

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

        column = self.require(params, "column")
        if column not in df.columns:
            raise BlockExecutionError(
                code="COLUMN_NOT_FOUND",
                message=f"Column '{column}' not found",
            )

        # Phase 4-A+: `operator + target` path (generalised comparison).
        operator = params.get("operator")
        if operator is not None:
            if operator not in _OPERATORS:
                raise BlockExecutionError(
                    code="INVALID_PARAM",
                    message=f"operator must be one of {_OPERATORS}",
                )
            target = params.get("target")
            if target is None:
                raise BlockExecutionError(
                    code="MISSING_PARAM", message="target is required when operator is set"
                )
            col_series = df[column]
            try:
                # Try numeric comparison first; fall back to lexicographic for strings.
                numeric_col = pd.to_numeric(col_series, errors="coerce")
                numeric_target = pd.to_numeric(pd.Series([target]), errors="coerce").iloc[0]
                if pd.isna(numeric_target) or numeric_col.isna().all():
                    # Non-numeric — string/equality only supported
                    if operator not in {"==", "!="}:
                        raise BlockExecutionError(
                            code="INVALID_PARAM",
                            message=f"operator '{operator}' requires numeric column; got {col_series.dtype}",
                        )
                    cmp_values = col_series
                    cmp_target = target
                else:
                    cmp_values = numeric_col
                    cmp_target = numeric_target
            except BlockExecutionError:
                raise
            except Exception as e:
                raise BlockExecutionError(
                    code="INVALID_PARAM", message=f"comparison failed: {e}"
                ) from None

            ops = {
                "==": lambda s, t: s == t,
                "!=": lambda s, t: s != t,
                ">=": lambda s, t: s >= t,
                "<=": lambda s, t: s <= t,
                ">":  lambda s, t: s > t,
                "<":  lambda s, t: s < t,
            }
            mask = ops[operator](cmp_values, cmp_target).fillna(False).astype(bool)
            evidence = df.copy()
            evidence["triggered_row"] = mask.values
            evidence["operator"] = operator
            evidence["target"] = target
            evidence["explanation"] = [
                f"{v} {operator} {target}" if m else None
                for v, m in zip(cmp_values.tolist(), mask.tolist())
            ]
            return {
                "triggered": bool(mask.any()),
                "evidence": evidence.reset_index(drop=True),
            }

        # Legacy path: bound_type + upper/lower_bound.
        bound_type = params.get("bound_type", "both")
        if bound_type not in _BOUNDS:
            raise BlockExecutionError(
                code="INVALID_PARAM",
                message=f"bound_type must be one of {_BOUNDS}",
            )
        upper = params.get("upper_bound")
        lower = params.get("lower_bound")
        if bound_type in {"upper", "both"} and upper is None:
            raise BlockExecutionError(
                code="MISSING_PARAM", message="upper_bound is required for bound_type 'upper'/'both'"
            )
        if bound_type in {"lower", "both"} and lower is None:
            raise BlockExecutionError(
                code="MISSING_PARAM", message="lower_bound is required for bound_type 'lower'/'both'"
            )

        numeric = pd.to_numeric(df[column], errors="coerce")
        above = numeric > upper if upper is not None else pd.Series(False, index=df.index)
        below = numeric < lower if lower is not None else pd.Series(False, index=df.index)

        if bound_type == "upper":
            mask = above
        elif bound_type == "lower":
            mask = below
        else:
            mask = above | below
        mask = mask.fillna(False).astype(bool)

        evidence = df.copy()
        evidence["triggered_row"] = mask.values
        side = [
            "above" if a else ("below" if b else None)
            for a, b in zip(above.tolist(), below.tolist())
        ]
        bound_used = [
            upper if a else (lower if b else None)
            for a, b in zip(above.tolist(), below.tolist())
        ]
        evidence["violation_side"] = side
        evidence["violated_bound"] = bound_used
        evidence["explanation"] = [
            (
                f"{v} {'>' if s == 'above' else '<'} {'upper_bound' if s == 'above' else 'lower_bound'} {b}"
                if s is not None
                else None
            )
            for v, s, b in zip(numeric.tolist(), side, bound_used)
        ]

        return {
            "triggered": bool(mask.any()),
            "evidence": evidence.reset_index(drop=True),
        }
