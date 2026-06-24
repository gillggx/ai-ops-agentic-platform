"""2026-06-24 — flat-string param forms for block_select / block_sort + the
schema-aware coercion safety net.

block_select.fields and block_sort.columns were array-of-objects ({path,as} /
{column,order}) — the only two params platform-wide with that shape, and LLMs
miswrote them (apc-recipe-compare stringified the whole array → C6 fail). Now
both accept a FLAT string list (common case); the object form stays for
rename/desc. The coercion net additionally parses any array/object param the
LLM stringified.
"""
from __future__ import annotations

import asyncio

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import ExecutionContext
from python_ai_sidecar.pipeline_builder.blocks.select import SelectBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.sort import SortBlockExecutor
from python_ai_sidecar.agent_builder.tools import (
    _coerce_param_value,
    _coerce_param_values,
)


def _run(executor, params, df):
    return asyncio.run(executor.execute(
        params=params, inputs={"data": df}, context=ExecutionContext(run_id="t")))


# ── block_select flat-string form ───────────────────────────────────

def test_select_flat_string_list():
    df = pd.DataFrame({"a": [1, 2], "b": [3, 4], "c": [5, 6]})
    out = _run(SelectBlockExecutor(), {"fields": ["a", "c"]}, df)
    res = out["data"]
    assert list(res.columns) == ["a", "c"]


def test_select_flat_matches_object_form():
    df = pd.DataFrame({"a": [1], "b": [2]})
    flat = _run(SelectBlockExecutor(), {"fields": ["a", "b"]}, df)["data"]
    obj = _run(SelectBlockExecutor(), {"fields": [{"path": "a"}, {"path": "b"}]}, df)["data"]
    assert list(flat.columns) == list(obj.columns) == ["a", "b"]


def test_select_mixed_string_and_rename_object():
    df = pd.DataFrame({"tool_id": ["EQP-01"], "n": [9]})
    out = _run(SelectBlockExecutor(),
               {"fields": ["tool_id", {"path": "n", "as": "count"}]}, df)["data"]
    assert list(out.columns) == ["tool_id", "count"]


# ── block_sort flat-string form ─────────────────────────────────────

def test_sort_flat_string_defaults_asc():
    df = pd.DataFrame({"x": [3, 1, 2]})
    out = _run(SortBlockExecutor(), {"columns": ["x"]}, df)["data"]
    assert list(out["x"]) == [1, 2, 3]


def test_sort_mixed_string_and_desc_object():
    df = pd.DataFrame({"g": ["a", "a", "b"], "v": [1, 2, 3]})
    out = _run(SortBlockExecutor(),
               {"columns": ["g", {"column": "v", "order": "desc"}]}, df)["data"]
    # g asc then v desc → within g='a', v: 2 before 1
    assert list(out["v"])[:2] == [2, 1]


# ── coercion safety net (_coerce_param_value) ───────────────────────

_SCHEMA = {"properties": {
    "fields": {"type": "array"},
    "cfg": {"type": "object"},
    "column": {"type": "string"},
}}


def test_coerce_stringified_array():
    v = _coerce_param_value("fields", '[{"path": "a"}, {"path": "b"}]', _SCHEMA)
    assert v == [{"path": "a"}, {"path": "b"}]


def test_coerce_stringified_object():
    assert _coerce_param_value("cfg", '{"k": 1}', _SCHEMA) == {"k": 1}


def test_string_typed_param_untouched():
    assert _coerce_param_value("column", "eventTime", _SCHEMA) == "eventTime"


def test_dollar_ref_untouched():
    assert _coerce_param_value("fields", "$input.cols", _SCHEMA) == "$input.cols"


def test_non_json_string_untouched():
    # array-typed but not JSON → leave for C6 to flag, don't silently swallow.
    assert _coerce_param_value("fields", "a, b, c", _SCHEMA) == "a, b, c"


def test_type_mismatch_untouched():
    # parses to dict but the param expects an array → leave as-is.
    assert _coerce_param_value("fields", '{"k": 1}', _SCHEMA) == '{"k": 1}'


def test_already_list_untouched():
    assert _coerce_param_value("fields", ["a", "b"], _SCHEMA) == ["a", "b"]


def test_coerce_values_across_dict():
    out = _coerce_param_values(
        {"fields": '["a","b"]', "column": "x"}, _SCHEMA)
    assert out == {"fields": ["a", "b"], "column": "x"}


def test_coerce_values_empty_schema_noop():
    assert _coerce_param_values({"fields": '["a"]'}, {}) == {"fields": '["a"]'}
