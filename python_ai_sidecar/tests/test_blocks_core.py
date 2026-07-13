"""Block 核心行為測試套件（2026-07-13, user 要求）。

涵蓋 2026-07-12/13 動過的 blocks + 統計三顆 — 每案例對應 block 文件裡
宣稱的行為（文件說謊測試會抓到）。跑法：
    venv/bin/python -m pytest python_ai_sidecar/tests/test_blocks_core.py -q
也被 tools/regression_pack/run.sh 的 case 0 引用（deterministic、免 LLM）。
"""

from __future__ import annotations

import pandas as pd
import pytest

from python_ai_sidecar.pipeline_builder.blocks.base import BlockExecutionError
from python_ai_sidecar.pipeline_builder.blocks.compute import ComputeBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.correlation import CorrelationBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.data_view import DataViewBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.filter import FilterBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.groupby_agg import GroupByAggBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.line_chart import LineChartBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.linear_regression import (
    LinearRegressionBlockExecutor,
)
from python_ai_sidecar.pipeline_builder.blocks.scatter_chart import ScatterChartBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.sort import SortBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.streak import StreakBlockExecutor


@pytest.fixture()
def df() -> pd.DataFrame:
    return pd.DataFrame({
        "toolID": ["EQP-01", "EQP-01", "EQP-02", "EQP-02", "EQP-02"],
        "step": ["S1", "S2", "S1", "S2", "S3"],
        "eventTime": ["2026-07-10 01:00", "2026-07-10 02:00", "2026-07-10 01:00",
                      "2026-07-10 02:00", "2026-07-10 03:00"],
        "value": [10.0, 12.0, 20.0, 22.0, 24.0],
        "spc_status": ["PASS", "OOC", "PASS", "OOC", "OOC"],
    })


async def run(executor, params, data):
    return await executor.execute(params=params, inputs={"data": data}, context=None)


# ── block_sort ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("spec", ["toolID,step", ["toolID,step"], ["toolID", "step"]])
async def test_sort_multikey_and_comma_tolerance(df, spec):
    out = (await run(SortBlockExecutor(), {"columns": spec}, df))["data"]
    assert out.iloc[0]["toolID"] == "EQP-01" and out.iloc[0]["step"] == "S1"


@pytest.mark.asyncio
async def test_sort_desc_object_form(df):
    out = (await run(SortBlockExecutor(),
                     {"columns": [{"column": "value", "order": "desc"}], "limit": 1}, df))["data"]
    assert out.iloc[0]["value"] == 24.0 and len(out) == 1


# ── block_compute ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_compute_concat(df):
    out = (await run(ComputeBlockExecutor(), {
        "column": "key",
        "expression": {"op": "concat", "operands": [{"column": "toolID"}, "-", {"column": "step"}]},
    }, df))["data"]
    assert out["key"].tolist()[0] == "EQP-01-S1"


@pytest.mark.asyncio
async def test_compute_if(df):
    out = (await run(ComputeBlockExecutor(), {
        "column": "flag",
        "expression": {"op": "if", "operands": [
            {"op": "eq", "operands": [{"column": "spc_status"}, "OOC"]}, 1, 0]},
    }, df))["data"]
    assert out["flag"].tolist() == [0, 1, 0, 1, 1]


@pytest.mark.asyncio
async def test_compute_abs(df):
    d = df.assign(delta=[-1.5, 2.0, -3.0, 0.5, -0.1])
    out = (await run(ComputeBlockExecutor(), {
        "column": "mag", "expression": {"op": "abs", "operands": [{"column": "delta"}]},
    }, d))["data"]
    assert out["mag"].tolist() == [1.5, 2.0, 3.0, 0.5, 0.1]


@pytest.mark.asyncio
async def test_compute_missing_column_error_names_new_field(df):
    with pytest.raises(BlockExecutionError) as ei:
        await run(ComputeBlockExecutor(), {"expression": {"op": "abs", "operands": [1]}}, df)
    assert "新欄位名稱" in ei.value.message


# ── block_filter ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_filter_multi_conditions_and_or(df):
    both = (await run(FilterBlockExecutor(), {"conditions": [
        {"column": "toolID", "operator": "==", "value": "EQP-02"},
        {"column": "spc_status", "operator": "==", "value": "OOC"},
    ], "logic": "and"}, df))["data"]
    assert len(both) == 2
    either = (await run(FilterBlockExecutor(), {"conditions": [
        {"column": "step", "operator": "==", "value": "S3"},
        {"column": "toolID", "operator": "==", "value": "EQP-01"},
    ], "logic": "or"}, df))["data"]
    assert len(either) == 3


@pytest.mark.asyncio
async def test_filter_single_condition_backcompat(df):
    out = (await run(FilterBlockExecutor(),
                     {"column": "spc_status", "operator": "==", "value": "OOC"}, df))["data"]
    assert len(out) == 3


# ── block_groupby_agg ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_groupby_multi_aggregations(df):
    out = (await run(GroupByAggBlockExecutor(), {"group_by": "toolID", "aggregations": [
        {"column": "value", "func": "mean"},
        {"column": "value", "func": "count"},
        {"column": "value", "func": "max", "as": "value_top"},
    ]}, df))["data"]
    assert set(out.columns) == {"toolID", "value_mean", "value_count", "value_top"}
    assert out[out.toolID == "EQP-02"]["value_count"].iloc[0] == 3


@pytest.mark.asyncio
async def test_groupby_single_backcompat(df):
    out = (await run(GroupByAggBlockExecutor(),
                     {"group_by": "toolID", "agg_column": "value", "agg_func": "mean"}, df))["data"]
    assert "value_mean" in out.columns


# ── block_streak ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_streak_doc_example():
    # 文件例：值 1,2,3,3,2 → dir flat,up,up,flat,down；len 0,1,2,0,1
    d = pd.DataFrame({"t": [1, 2, 3, 4, 5], "v": [1.0, 2.0, 3.0, 3.0, 2.0]})
    out = (await run(StreakBlockExecutor(), {"value_column": "v", "sort_by": "t"}, d))["data"]
    assert out["v_streak_dir"].tolist() == ["flat", "up", "up", "flat", "down"]
    assert out["v_streak_len"].tolist() == [0, 1, 2, 0, 1]


@pytest.mark.asyncio
async def test_streak_grouped(df):
    out = (await run(StreakBlockExecutor(),
                     {"value_column": "value", "sort_by": "eventTime", "group_by": "toolID"},
                     df))["data"]
    eqp2 = out[out.toolID == "EQP-02"]
    assert eqp2["value_streak_len"].tolist() == [0, 1, 2]  # 20→22→24 連升 2 步


# ── block_correlation ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_correlation_columns_optional_defaults_numeric():
    d = pd.DataFrame({"a": [1, 2, 3, 4, 5], "b": [2, 4, 6, 8, 10],
                      "c": [5, 4, 3, 2, 1], "name": list("vwxyz")})
    out = (await run(CorrelationBlockExecutor(), {}, d))["matrix"]
    assert set(out.col_a.unique()) == {"a", "b", "c"}   # name 非數值不納入


@pytest.mark.asyncio
async def test_correlation_target_ranking():
    d = pd.DataFrame({"a": [1, 2, 3, 4, 5], "b": [2, 4, 6, 8, 10], "c": [5, 1, 4, 2, 3]})
    out = (await run(CorrelationBlockExecutor(), {"target": "a"}, d))["matrix"]
    assert list(out.columns)[:2] == ["column", "correlation"]
    assert out.iloc[0]["column"] == "b" and abs(out.iloc[0]["abs_corr"] - 1.0) < 1e-6


# ── block_linear_regression（既有 — 文件宣稱的 stats port）────────────────

@pytest.mark.asyncio
async def test_linear_regression_stats():
    # 每組至少 3 點（block 規定 n>=3）
    d = pd.DataFrame({
        "toolID": ["A"] * 4 + ["B"] * 4,
        "t": [1, 2, 3, 4] * 2,
        "value": [10.0, 11.0, 12.0, 13.0, 20.0, 19.0, 18.0, 17.0],
    })
    out = await run(LinearRegressionBlockExecutor(),
                    {"x_column": "t", "y_column": "value", "group_by": "toolID"}, d)
    stats = out["stats"]
    assert {"slope", "r_squared", "n"} <= set(stats.columns)
    assert len(stats) == 2  # 兩組各一條
    slopes = dict(zip(stats.iloc[:, 0], stats["slope"]))
    assert slopes["A"] > 0 > slopes["B"]  # A 上升、B 下降


# ── block_line_chart ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_line_chart_sequence_mode(df):
    for params in ({"y": "value"}, {"x": "sequence", "y": "value"}):
        spec = (await run(LineChartBlockExecutor(), params, df))["chart_spec"]
        assert spec["x"] == "__seq"
        assert [r["__seq"] for r in spec["data"]] == [1, 2, 3, 4, 5]


@pytest.mark.asyncio
async def test_line_chart_explicit_x_unchanged(df):
    spec = (await run(LineChartBlockExecutor(), {"x": "step", "y": "value"}, df))["chart_spec"]
    assert spec["x"] == "step"


# ── block_scatter_chart regression ────────────────────────────────────────

@pytest.mark.asyncio
async def test_scatter_regression_line():
    d = pd.DataFrame({"x": [1, 2, 3, 4, 5], "y": [2.1, 4.0, 6.2, 7.9, 10.1]})
    spec = (await run(ScatterChartBlockExecutor(),
                      {"x": "x", "y": "y", "regression": True}, d))["chart_spec"]
    reg = spec["regression"]
    assert abs(reg["slope"] - 2.0) < 0.1 and reg["r2"] > 0.99


@pytest.mark.asyncio
async def test_scatter_regression_failsoft_nonnumeric():
    d = pd.DataFrame({"x": list("abc"), "y": [1, 2, 3]})
    spec = (await run(ScatterChartBlockExecutor(),
                      {"x": "x", "y": "y", "regression": True}, d))["chart_spec"]
    assert "regression" not in spec and "regression_note" in spec


# ── block_data_view highlight_rules ───────────────────────────────────────

@pytest.mark.asyncio
async def test_data_view_highlight_rules_passthrough(df):
    out = await run(DataViewBlockExecutor(), {"highlight_rules": [
        {"column": "spc_status", "operator": "==", "value": "OOC",
         "background": "#FDE8E9", "text_color": "#B4232D"},
        {"no_column": True},  # 壞條目應被略過
    ]}, df)
    spec = out["data_view"]
    assert len(spec["highlight_rules"]) == 1
    assert spec["highlight_rules"][0]["column"] == "spc_status"
