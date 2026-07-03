"""block_select duplicate-label regression (spc-ooc gate 2026-07-04).

A DataFrame with duplicate column labels (e.g. produced by an upstream union /
merge) made get_column_series return a DataFrame; its 2-D .values crashed
pd.DataFrame(out_cols) with "Per-column arrays must each be 1-dimensional",
and the node crash-looped the build to timeout. The fix takes the first
occurrence deterministically.
"""
from __future__ import annotations

import asyncio

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.select import SelectBlockExecutor


def _run(df: pd.DataFrame, fields: list) -> pd.DataFrame:
    ex = SelectBlockExecutor()
    out = asyncio.run(ex.execute(params={"fields": fields},
                                 inputs={"data": df}, context=None))
    return out["data"]


def test_duplicate_labels_take_first_occurrence():
    df = pd.DataFrame([[1, "a", 10], [2, "b", 20]],
                      columns=["tool_id", "step", "tool_id"])  # dup label
    out = _run(df, ["tool_id", "step"])
    assert list(out.columns) == ["tool_id", "step"]
    assert out["tool_id"].tolist() == [1, 2]   # first occurrence, not 2-D crash


def test_normal_select_unchanged():
    df = pd.DataFrame({"tool_id": ["EQP-01"], "spc_status": ["OOC"]})
    out = _run(df, [{"path": "tool_id", "as": "tool"}, "spc_status"])
    assert list(out.columns) == ["tool", "spc_status"]
    assert out["tool"].tolist() == ["EQP-01"]
