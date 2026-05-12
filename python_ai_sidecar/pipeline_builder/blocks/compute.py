"""block_compute — evaluate an expression tree into a NEW column.

Purpose:
  Pipeline DAGs need to derive boolean / numeric columns from existing ones
  (e.g. ``spc_is_any_ooc = (spc_status != 'PASS')`` so downstream
  rolling_window / threshold can count them). Without this block, pipelines
  fall back to a single hard-coded column (e.g. ``spc_xbar_chart_is_ooc``)
  which under-reports alarms.

Expression grammar (JSON-encoded tree, one node = one operator):
  Literal:        42, "PASS", true, null, [ ... ]
  Column ref:     {"column": "spc_status"}
  Op node:        {"op": "<name>", "operands": [<expr>, ...]}

Supported ops:
  Comparison:  eq ne gt gte lt lte
  Logical:     and or not
  Set:         in not_in                 (second operand must be a list)
  Arithmetic:  add sub mul div
  Cast:        as_int as_float as_str as_bool
  Null:        coalesce is_null is_not_null

Example: ``spc_is_any_ooc = (spc_status != 'PASS') as int``
    {
      "column": "spc_is_any_ooc",
      "expression": {
        "op": "as_int",
        "operands": [{
          "op": "ne",
          "operands": [{"column": "spc_status"}, "PASS"]
        }]
      }
    }
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


# --- expression evaluator (vectorised over a DataFrame) ---

def _eval(node: Any, df: pd.DataFrame) -> Any:
    """Return a pandas Series (aligned to df.index) OR a scalar literal."""
    if not isinstance(node, dict):
        return node  # plain literal: int / str / bool / list / None
    if "column" in node:
        col = node["column"]
        try:
            return get_column_series(df, col)
        except KeyError:
            raise BlockExecutionError(
                code="COLUMN_NOT_FOUND",
                message=f"Column path '{col}' not in input",
                hint=f"Available top-level: {list(df.columns)[:10]}",
            ) from None
    op = node.get("op")
    if not op:
        raise BlockExecutionError(
            code="INVALID_EXPRESSION",
            message="Expression node must be literal, {column: ...}, or {op: ..., operands: [...]}",
        )
    args = [_eval(o, df) for o in node.get("operands", [])]
    return _dispatch(op, args)


def _dispatch(op: str, args: list[Any]) -> Any:
    # Comparisons
    if op == "eq":  return _binop(args, lambda a, b: a == b)
    if op == "ne":  return _binop(args, lambda a, b: a != b)
    if op == "gt":  return _binop(args, lambda a, b: _numeric(a) > _numeric(b))
    if op == "gte": return _binop(args, lambda a, b: _numeric(a) >= _numeric(b))
    if op == "lt":  return _binop(args, lambda a, b: _numeric(a) < _numeric(b))
    if op == "lte": return _binop(args, lambda a, b: _numeric(a) <= _numeric(b))
    # Set
    if op == "in":
        base, values = args[0], args[1]
        if not isinstance(values, (list, tuple)):
            raise BlockExecutionError(code="INVALID_PARAM", message="'in' needs list operand")
        if isinstance(base, pd.Series):
            return base.isin(values)
        return base in values
    if op == "not_in":
        base, values = args[0], args[1]
        if not isinstance(values, (list, tuple)):
            raise BlockExecutionError(code="INVALID_PARAM", message="'not_in' needs list operand")
        if isinstance(base, pd.Series):
            return ~base.isin(values)
        return base not in values
    # Logical
    if op == "and": return _reduce(args, lambda a, b: _asbool(a) & _asbool(b))
    if op == "or":  return _reduce(args, lambda a, b: _asbool(a) | _asbool(b))
    if op == "not": return ~_asbool(args[0])
    # Arithmetic
    if op == "add": return _reduce(args, lambda a, b: _numeric(a) + _numeric(b))
    if op == "sub": return _binop(args, lambda a, b: _numeric(a) - _numeric(b))
    if op == "mul": return _reduce(args, lambda a, b: _numeric(a) * _numeric(b))
    if op == "div": return _binop(args, lambda a, b: _numeric(a) / _numeric(b))
    # Cast
    if op == "as_int":
        v = args[0]
        if isinstance(v, pd.Series):
            return v.astype(bool).astype(int) if v.dtype == bool else pd.to_numeric(v, errors="coerce").fillna(0).astype(int)
        return int(bool(v))
    if op == "as_float":
        v = args[0]
        return pd.to_numeric(v, errors="coerce") if isinstance(v, pd.Series) else float(v)
    if op == "as_str":
        v = args[0]
        return v.astype(str) if isinstance(v, pd.Series) else str(v)
    if op == "as_bool":
        return _asbool(args[0])
    # Null handling
    if op == "coalesce":
        out = args[0]
        for nxt in args[1:]:
            if isinstance(out, pd.Series):
                out = out.fillna(nxt) if not isinstance(nxt, pd.Series) else out.fillna(nxt)
            elif out is None:
                out = nxt
        return out
    if op == "is_null":
        v = args[0]
        return v.isna() if isinstance(v, pd.Series) else v is None
    if op == "is_not_null":
        v = args[0]
        return v.notna() if isinstance(v, pd.Series) else v is not None

    raise BlockExecutionError(code="UNSUPPORTED_OP", message=f"Unknown op '{op}'")


def _binop(args, fn):
    if len(args) != 2:
        raise BlockExecutionError(code="INVALID_PARAM", message="Binary op needs exactly 2 operands")
    return fn(args[0], args[1])


def _reduce(args, fn):
    if not args:
        raise BlockExecutionError(code="INVALID_PARAM", message="Reduce op needs ≥1 operand")
    out = args[0]
    for nxt in args[1:]:
        out = fn(out, nxt)
    return out


def _numeric(v):
    if isinstance(v, pd.Series):
        return pd.to_numeric(v, errors="coerce")
    return v


def _asbool(v):
    if isinstance(v, pd.Series):
        return v.astype(bool)
    return bool(v)


# --- block ---

class ComputeBlockExecutor(BlockExecutor):
    block_id = "block_compute"

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
                code="INVALID_INPUT",
                message="'data' input must be a DataFrame",
            )
        column = self.require(params, "column")
        expression = self.require(params, "expression")

        result = _eval(expression, df)

        out = df.copy()
        if isinstance(result, pd.Series):
            out[column] = result.reset_index(drop=True) if len(result) == len(df) else result
        else:
            out[column] = result  # scalar broadcast

        return {"data": out}
