"""2026-06-25 hardening #1 — in-block ranking for bar_chart / pareto.

"由多到少 / top-N / ranking" used to need a separate block_sort upstream, which
goal_plan bundled into the groupby phase and the verifier then dropped
(miss:sort, both KIMI and GLM). bar_chart now sorts by its first y measure when
order='desc'/'asc'; pareto always self-sorts descending. No separate sort block.
"""
from __future__ import annotations

import asyncio

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import ExecutionContext
from python_ai_sidecar.pipeline_builder.blocks.bar_chart import BarChartBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.pareto import ParetoBlockExecutor


def _run(executor, params, df):
    return asyncio.run(executor.execute(
        params=params, inputs={"data": df}, context=ExecutionContext(run_id="t")))


_DF = pd.DataFrame({"tool": ["A", "B", "C"], "ooc": [3, 9, 5]})


def test_bar_order_desc_ranks_high_to_low():
    spec = _run(BarChartBlockExecutor(), {"x": "tool", "y": "ooc", "order": "desc"}, _DF)["chart_spec"]
    assert [r["tool"] for r in spec["data"]] == ["B", "C", "A"]
    assert [r["ooc"] for r in spec["data"]] == [9, 5, 3]


def test_bar_order_asc():
    spec = _run(BarChartBlockExecutor(), {"x": "tool", "y": "ooc", "order": "asc"}, _DF)["chart_spec"]
    assert [r["ooc"] for r in spec["data"]] == [3, 5, 9]


def test_bar_order_none_preserves_upstream_order():
    spec = _run(BarChartBlockExecutor(), {"x": "tool", "y": "ooc"}, _DF)["chart_spec"]
    assert [r["tool"] for r in spec["data"]] == ["A", "B", "C"]


def test_bar_order_desc_first_y_when_list():
    df = pd.DataFrame({"tool": ["A", "B"], "ooc": [2, 7], "warn": [9, 1]})
    spec = _run(BarChartBlockExecutor(), {"x": "tool", "y": ["ooc", "warn"], "order": "desc"}, df)["chart_spec"]
    # sorts by first y (ooc): B(7) before A(2)
    assert [r["tool"] for r in spec["data"]] == ["B", "A"]


def test_pareto_self_sorts_descending():
    spec = _run(ParetoBlockExecutor(),
                {"category_column": "tool", "value_column": "ooc"}, _DF)["chart_spec"]
    assert [r["ooc"] for r in spec["data"]] == [9, 5, 3]


def test_bar_order_empty_df_safe():
    out = _run(BarChartBlockExecutor(), {"x": "tool", "y": "ooc", "order": "desc"}, _DF.iloc[0:0])
    assert out["chart_spec"]["type"] == "empty"
