"""block_step_check — Phase 11 Skill terminal block.

Every Skill step's pipeline MUST end in this block. Aggregates the upstream
DataFrame to a scalar value, compares against a threshold, and emits a
structured check record SkillRunner can collect:
    { pass: bool, value: <scalar>, note: <str> }

Operators (matches prototype `USER_OPS`):
    >=, >, =, <, <=  — numeric comparison
    changed          — value differs from `baseline` param
    drift            — abs(value - baseline) >= threshold

Aggregations:
    count   — number of rows (default — most common: "if N OOC events")
    sum     — sum of `column`
    mean    — mean of `column`
    max     — max of `column`
    min     — min of `column`
    last    — last row's `column`
    exists  — bool(rows > 0); pairs with operator='=='

Output format mirrors block_alert's "evidence + result" pattern so
downstream blocks (in Skill mode there are usually none after the
check) can still consume rows. Returns a single-row DataFrame:
    pass | value | threshold | operator | note
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


_VALID_OPS = {">=", ">", "=", "==", "<", "<=", "changed", "drift"}


def _coerce_numeric(value):
    """Accept Python int/float, numpy scalar types, and numeric strings.
    Pandas aggregations (sum/mean/max/min/last) on int columns produce
    `numpy.int64` / `numpy.float64`, neither of which is isinstance(int|float).
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
_VALID_AGG = {"count", "sum", "mean", "max", "min", "last", "exists"}


class StepCheckBlockExecutor(BlockExecutor):
    block_id = "block_step_check"

    async def execute(
        self,
        *,
        params: dict[str, Any],
        inputs: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        df = inputs.get("data")
        if df is None or not isinstance(df, pd.DataFrame):
            raise BlockExecutionError(
                code="INVALID_INPUT",
                message="block_step_check requires 'data' (dataframe)",
            )

        operator = (params.get("operator") or ">=").strip()
        if operator == "==":
            operator = "="
        if operator not in _VALID_OPS:
            raise BlockExecutionError(
                code="INVALID_PARAM",
                message=f"operator must be one of {sorted(_VALID_OPS)}, got {operator!r}",
            )

        aggregate = (params.get("aggregate") or "count").strip()
        if aggregate not in _VALID_AGG:
            raise BlockExecutionError(
                code="INVALID_PARAM",
                message=f"aggregate must be one of {sorted(_VALID_AGG)}, got {aggregate!r}",
            )

        column = params.get("column")
        threshold = params.get("threshold")
        baseline = params.get("baseline")

        # ── Compute scalar value from the dataframe ──────────────────
        value: Any
        if aggregate == "count":
            value = int(len(df))
        elif aggregate == "exists":
            value = bool(len(df) > 0)
        else:
            if not column:
                raise BlockExecutionError(
                    code="MISSING_PARAM",
                    message=f"aggregate={aggregate!r} requires `column`",
                )
            try:
                series = get_column_series(df, column)
            except KeyError:
                raise BlockExecutionError(
                    code="COLUMN_NOT_FOUND",
                    message=f"column path '{column}' not in data. Available top-level: {list(df.columns)[:10]}",
                ) from None
            if aggregate == "sum":
                value = float(pd.to_numeric(series, errors="coerce").sum())
            elif aggregate == "mean":
                num = pd.to_numeric(series, errors="coerce").dropna()
                value = float(num.mean()) if not num.empty else None
            elif aggregate == "max":
                num = pd.to_numeric(series, errors="coerce").dropna()
                value = float(num.max()) if not num.empty else None
            elif aggregate == "min":
                num = pd.to_numeric(series, errors="coerce").dropna()
                value = float(num.min()) if not num.empty else None
            elif aggregate == "last":
                value = None if series.empty else series.iloc[-1]
            else:
                # unreachable — already validated against _VALID_AGG
                raise BlockExecutionError(code="INTERNAL", message="aggregate dispatch failure")

        # ── Compare ──────────────────────────────────────────────────
        passed: bool
        note: str

        try:
            if operator in {">=", ">", "=", "<", "<="}:
                if threshold is None:
                    raise BlockExecutionError(
                        code="MISSING_PARAM",
                        message=f"operator={operator!r} requires `threshold`",
                    )
                t = float(threshold)
                v = _coerce_numeric(value)
                if v is None:
                    passed = False
                    note = f"value not numeric: {value!r}"
                elif operator == ">=":
                    passed = v >= t; note = f"{v} {'≥' if passed else '<'} {t}"
                elif operator == ">":
                    passed = v > t;  note = f"{v} {'>' if passed else '≤'} {t}"
                elif operator == "=":
                    passed = v == t; note = f"{v} {'==' if passed else '≠'} {t}"
                elif operator == "<":
                    passed = v < t;  note = f"{v} {'<' if passed else '≥'} {t}"
                elif operator == "<=":
                    passed = v <= t; note = f"{v} {'≤' if passed else '>'} {t}"
                else:
                    passed = False; note = "unreachable"
            elif operator == "changed":
                passed = (value != baseline)
                note = f"value={value!r} {'≠' if passed else '=='} baseline={baseline!r}"
            elif operator == "drift":
                if threshold is None or baseline is None:
                    raise BlockExecutionError(
                        code="MISSING_PARAM",
                        message="operator='drift' requires both `baseline` and `threshold`",
                    )
                t = float(threshold)
                b = float(baseline)
                v = _coerce_numeric(value)
                if v is None:
                    passed = False
                    note = f"value not numeric: {value!r}"
                else:
                    delta = abs(v - b)
                    passed = delta >= t
                    note = f"|{v} - {b}| = {delta} {'≥' if passed else '<'} {t}"
            else:
                # unreachable
                passed = False; note = "unreachable"
        except (TypeError, ValueError) as ex:
            raise BlockExecutionError(
                code="INVALID_PARAM",
                message=f"compare failed ({type(ex).__name__}: {ex})",
            )

        # SkillRunner reads this single-row DataFrame to fill skill_runs.step_results.
        # Frontend's SuggestionPanel surfaces `note` to the user when the step fails.
        result_df = pd.DataFrame([{
            "pass":      bool(passed),
            "value":     value,
            "threshold": threshold,
            "operator":  operator,
            "aggregate": aggregate,
            "column":    column,
            "note":      note,
            "evidence_rows": int(len(df)),
        }])
        return {"check": result_df}
