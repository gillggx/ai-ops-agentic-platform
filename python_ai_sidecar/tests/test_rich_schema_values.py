"""Unit tests for rich_schema_values (2026-06-17).

Covers the two pieces that let the agent skip inspect_node_output:
  - executor._compute_distinct_values: TRUE full-output distinct per low-card
    string column (the thing the 5-row sample can't see).
  - schema_doc.infer_runtime_schema(col_distincts=...): renders those as a
    complete `enum[...]`, with declared column_docs still taking precedence.
"""
from __future__ import annotations

import pandas as pd

from python_ai_sidecar.pipeline_builder.executor import _compute_distinct_values
from python_ai_sidecar.pipeline_builder.schema_doc import (
    _format_true_enum,
    infer_runtime_schema,
)


def test_compute_distinct_lists_low_card_string():
    df = pd.DataFrame({
        "name": ["xbar_chart", "r_chart", "xbar_chart", "s_chart"],
        "value": [1.0, 2.0, 3.0, 4.0],          # numeric → skipped
    })
    out = _compute_distinct_values(df, ["name", "value"], cap=16)
    assert out["name"] == ["xbar_chart", "r_chart", "s_chart"]  # first-seen order, deduped
    assert "value" not in out


def test_compute_distinct_respects_cap():
    df = pd.DataFrame({"id": [f"v{i}" for i in range(20)]})  # 20 distinct > cap
    out = _compute_distinct_values(df, ["id"], cap=16)
    assert "id" not in out  # too many distinct → not listed (agent gets [unique:N])


def test_compute_distinct_skips_nested_and_huge():
    df = pd.DataFrame({"obj": [{"k": 1}, {"k": 2}]})  # non-string values
    assert _compute_distinct_values(df, ["obj"], cap=16) == {}
    big = pd.DataFrame({"name": ["a"] * 10})
    assert _compute_distinct_values(big, ["name"], cap=16, max_rows=5) == {}  # > max_rows


def test_format_true_enum():
    assert _format_true_enum(["xbar_chart", "r_chart"]) == "enum['xbar_chart', 'r_chart']"
    assert _format_true_enum([]) == ""
    assert _format_true_enum(None) == ""


def test_infer_schema_renders_true_enum():
    df = pd.DataFrame({"name": ["xbar_chart", "r_chart"], "value": [1.0, 2.0]})
    md = infer_runtime_schema(
        df, block_spec=None, node_id="n2",
        col_distincts={"name": ["xbar_chart", "r_chart", "s_chart", "cpk_chart"]},
    )
    # the filter column now shows the full value set, not `string [unique:N]`
    assert "enum['xbar_chart', 'r_chart', 's_chart', 'cpk_chart']" in md
    assert "[unique:" not in md.split("| name |")[1].split("|")[1]  # name row is enum


def test_infer_schema_no_distinct_falls_back():
    df = pd.DataFrame({"name": ["a", "b", "a"]})
    md = infer_runtime_schema(df, block_spec=None, node_id="n2", col_distincts=None)
    # without col_distincts, name (a repeats) still enum-able by sample; the
    # point is no crash + a name row exists
    assert "| name |" in md
