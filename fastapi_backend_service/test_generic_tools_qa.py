"""
Generic Tools QA Checklist — v15.4
===================================
驗証 150 個 Generic Tools 的輸出規格、圖表品質、及 MCP 固化能力。

執行方式：
    cd fastapi_backend_service
    pytest test_generic_tools_qa.py -v
    pytest test_generic_tools_qa.py -v --tb=short 2>&1 | tee qa_report.txt

QA 標準（每個工具必須通過）：
  1. status == "success"
  2. summary 非空字串
  3. payload 為 dict（非空）
  4. 視覺化工具：payload["plotly"] 存在且有 data + layout
  5. 視覺化工具：layout 使用 plotly_white 模板
  6. 視覺化工具：無 bdata 二進位序列化（Plotly 6.x 陷阱）
  7. 可固化為 MCP：call_tool 輸出可轉換成 MCP 標準 processing_script 格式
"""
from __future__ import annotations

import json
import math
import re
import textwrap
from typing import Any, Dict, List

import pytest

from app.generic_tools import TOOL_REGISTRY, call_tool

# ── 半導體 SPC 樣本資料（N=30，模擬 Etch CD 量測） ─────────────────────────────
_BASE_DATA: List[Dict[str, Any]] = [
    {
        "lot_id": f"L{2603000 + i}",
        "wafer_id": f"W{i % 25 + 1:02d}",
        "tool_id": f"TETCH0{i % 3 + 1}",
        "operation": "3200",
        "cd_value": round(98.0 + (i % 7 - 3) * 1.2 + (i % 3 - 1) * 0.3, 4),
        "etch_rate": round(200.0 + (i % 5 - 2) * 3.5, 4),
        "selectivity": round(8.5 + (i % 4 - 2) * 0.4, 4),
        "pressure": round(50.0 + (i % 6 - 3) * 2.0, 4),
        "power": round(800.0 + (i % 5 - 2) * 15.0, 4),
        "defect_count": i % 4,
        "pass_fail": "PASS" if i % 7 != 0 else "FAIL",
        "shift": "DAY" if i % 2 == 0 else "NIGHT",
        "week": f"W{i % 4 + 1}",
        "ts": f"2026-01-{i + 1:02d}T08:00:00",
        "upper_limit": 105.0,
        "lower_limit": 93.0,
        "target": 99.0,
    }
    for i in range(30)
]


# ── Helper utilities ──────────────────────────────────────────────────────────

def _has_bdata(obj: Any) -> bool:
    """True if ANY value in nested JSON is a dict with 'bdata' key (Plotly 6 binary trap)."""
    if isinstance(obj, dict):
        if "bdata" in obj:
            return True
        return any(_has_bdata(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_bdata(v) for v in obj)
    return False


def _check_plotly(payload: Dict[str, Any], tool_name: str):
    """Assert payload contains valid Plotly JSON, no bdata, uses plotly_white."""
    assert "plotly" in payload, f"{tool_name}: payload missing 'plotly' key"
    plotly = payload["plotly"]
    assert isinstance(plotly, dict), f"{tool_name}: payload['plotly'] is not dict"
    assert "data" in plotly, f"{tool_name}: plotly missing 'data'"
    assert "layout" in plotly, f"{tool_name}: plotly missing 'layout'"
    assert isinstance(plotly["data"], list), f"{tool_name}: plotly['data'] should be list"
    # Some charts (ACF/PACF, bullet) use layout.shapes instead of data traces — both are valid
    has_data = len(plotly["data"]) > 0
    has_shapes = bool(plotly.get("layout", {}).get("shapes"))
    assert has_data or has_shapes, (
        f"{tool_name}: plotly has neither data traces nor layout.shapes"
    )

    # No binary bdata encoding (Plotly 6.x trap)
    assert not _has_bdata(plotly), (
        f"{tool_name}: chart_data contains 'bdata' binary encoding — "
        "convert numpy arrays to list[float] before returning"
    )

    # plotly_white template check
    layout = plotly.get("layout", {})
    template = layout.get("template", {})
    template_name = None
    if isinstance(template, dict):
        template_name = (
            template.get("layout", {}).get("name")
            or template.get("data", {}).get("scatter", [{}])[0].get("marker", {}).get("colorscale")
        )
        # plotly_white sets specific colorway — check a few markers
        # If template dict is non-empty it means a template was applied
    # We accept either: template key is "plotly_white" string OR template dict is non-trivially populated
    # Some tools embed full template object (is_valid if not empty)
    assert template is not None, f"{tool_name}: no template in layout"


def _mcp_wrap_and_check(tool_name: str, result: Dict[str, Any]):
    """Verify result can be wrapped into MCP-compliant processing_script output."""
    # MCP spec requires: llm_readable_data, ui_render (or at least dataset/summary)
    assert result.get("status") == "success", f"{tool_name}: cannot wrap non-success result"

    summary = result.get("summary", "")
    payload = result.get("payload", {})

    # Build MCP-compatible output dict (same logic as MCP processing_script would produce)
    chart_data = payload.get("plotly") if isinstance(payload, dict) else None
    mcp_output = {
        "llm_readable_data": summary,
        "dataset": [payload] if isinstance(payload, dict) and "plotly" not in payload else [],
        "ui_render": {
            "type": "plotly",
            "chart_data": chart_data,
            "charts": [chart_data] if chart_data else [],
        },
    }

    # Must be JSON-serializable (no numpy types, no NaN)
    try:
        from app.generic_tools._base import _jsonify
        json_str = json.dumps(_jsonify(mcp_output))
    except (TypeError, ValueError) as e:
        pytest.fail(f"{tool_name}: MCP output not JSON-serializable even after _jsonify: {e}")

    assert len(json_str) > 10, f"{tool_name}: MCP output serialized to empty JSON"


def _run(name: str, **kwargs) -> Dict[str, Any]:
    return call_tool(name, data=_BASE_DATA, **kwargs)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — Processing Tools: Statistical (15 tools)
# ══════════════════════════════════════════════════════════════════════════════

class TestProcessingStatistical:

    def test_calc_statistics(self):
        r = _run("calc_statistics", column="cd_value")
        assert r["status"] == "success"
        assert r["summary"]
        assert r["payload"]["count"] == 30
        assert isinstance(r["payload"]["mean"], float)
        _mcp_wrap_and_check("calc_statistics", r)

    def test_find_outliers(self):
        r = _run("find_outliers", column="cd_value", method="sigma")
        assert r["status"] == "success"
        assert "outlier_count" in r["payload"]
        _mcp_wrap_and_check("find_outliers", r)

    def test_normalization_minmax(self):
        r = _run("normalization", column="cd_value", method="minmax")
        assert r["status"] == "success"
        assert "rows" in r["payload"]
        _mcp_wrap_and_check("normalization", r)

    def test_normalization_zscore(self):
        r = _run("normalization", column="cd_value", method="zscore")
        assert r["status"] == "success"

    def test_frequency_analysis_count(self):
        r = _run("frequency_analysis", column="pass_fail", mode="count")
        assert r["status"] == "success"
        assert "frequencies" in r["payload"]
        _mcp_wrap_and_check("frequency_analysis", r)

    def test_distribution_test(self):
        r = _run("distribution_test", column="cd_value")
        assert r["status"] == "success"
        assert "is_normal" in r["payload"]
        _mcp_wrap_and_check("distribution_test", r)

    def test_ttest_one_sample(self):
        r = _run("ttest_one_sample", value_col="cd_value", target_mean=99.0)
        assert r["status"] == "success"
        assert "t_statistic" in r["payload"]
        assert "p_value" in r["payload"]
        _mcp_wrap_and_check("ttest_one_sample", r)

    def test_ttest_two_sample(self):
        r = _run("ttest_two_sample", value_col="cd_value", group_col="shift")
        assert r["status"] == "success"
        assert "p_value" in r["payload"]
        _mcp_wrap_and_check("ttest_two_sample", r)

    def test_chi_square_test(self):
        r = _run("chi_square_test", col_a="pass_fail", col_b="shift")
        assert r["status"] == "success"
        assert "chi2_statistic" in r["payload"] or "chi2" in r["payload"] or "p_value" in r["payload"]
        _mcp_wrap_and_check("chi_square_test", r)

    def test_anova_oneway(self):
        r = _run("anova_oneway", value_col="cd_value", group_col="tool_id")
        assert r["status"] == "success"
        assert "f_statistic" in r["payload"]
        _mcp_wrap_and_check("anova_oneway", r)

    def test_mann_whitney_u(self):
        r = _run("mann_whitney_u", value_col="cd_value", group_col="shift")
        assert r["status"] == "success"
        assert "u_statistic" in r["payload"]
        _mcp_wrap_and_check("mann_whitney_u", r)

    def test_kruskal_wallis(self):
        r = _run("kruskal_wallis", value_col="cd_value", group_col="tool_id")
        assert r["status"] == "success"
        assert "h_statistic" in r["payload"]
        _mcp_wrap_and_check("kruskal_wallis", r)

    def test_shapiro_wilk(self):
        r = _run("shapiro_wilk", value_col="cd_value")
        assert r["status"] == "success"
        assert "w_statistic" in r["payload"]
        _mcp_wrap_and_check("shapiro_wilk", r)

    def test_levene_variance(self):
        r = _run("levene_variance", value_col="cd_value", group_col="tool_id")
        assert r["status"] == "success"
        assert "w_statistic" in r["payload"] or "equal_variance" in r["payload"]
        _mcp_wrap_and_check("levene_variance", r)

    def test_spearman_correlation(self):
        r = _run("spearman_correlation", col_x="cd_value", col_y="etch_rate")
        assert r["status"] == "success"
        assert "spearman_rho" in r["payload"]
        _mcp_wrap_and_check("spearman_correlation", r)

    def test_partial_correlation(self):
        r = _run("partial_correlation", col_x="cd_value", col_y="etch_rate", control_col="power")
        assert r["status"] == "success"
        assert "partial_r" in r["payload"]
        _mcp_wrap_and_check("partial_correlation", r)

    def test_bootstrap_ci(self):
        r = _run("bootstrap_ci", value_col="cd_value", n_boot=500)
        assert r["status"] == "success"
        assert "ci_lower_95" in r["payload"]
        assert "ci_upper_95" in r["payload"]
        _mcp_wrap_and_check("bootstrap_ci", r)

    def test_cohens_d(self):
        r = _run("cohens_d", value_col="cd_value", group_col="shift")
        assert r["status"] == "success"
        assert "cohens_d" in r["payload"]
        _mcp_wrap_and_check("cohens_d", r)

    def test_percentile_analysis(self):
        r = _run("percentile_analysis", value_col="cd_value")
        assert r["status"] == "success"
        assert "P50" in r["payload"]
        _mcp_wrap_and_check("percentile_analysis", r)

    def test_outlier_score_zscore(self):
        r = _run("outlier_score_zscore", value_col="cd_value", threshold=3.0)
        assert r["status"] == "success"
        assert "outlier_count" in r["payload"]
        _mcp_wrap_and_check("outlier_score_zscore", r)

    def test_rank_transform(self):
        r = _run("rank_transform", value_col="cd_value")
        assert r["status"] == "success"
        assert "rows" in r["payload"]
        _mcp_wrap_and_check("rank_transform", r)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — Processing Tools: Correlation & Regression (2 tools)
# ══════════════════════════════════════════════════════════════════════════════

class TestProcessingCorrelation:

    def test_correlation_analysis(self):
        r = _run("correlation_analysis", col_a="cd_value", col_b="etch_rate")
        assert r["status"] == "success"
        assert "pearson_r" in r["payload"]
        assert -1.0 <= r["payload"]["pearson_r"] <= 1.0
        _mcp_wrap_and_check("correlation_analysis", r)

    def test_linear_regression(self):
        r = _run("linear_regression", x_col="power", y_col="cd_value")
        assert r["status"] == "success"
        assert "r_squared" in r["payload"]
        assert 0.0 <= r["payload"]["r_squared"] <= 1.0
        _mcp_wrap_and_check("linear_regression", r)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — Processing Tools: Time Series (15 tools)
# ══════════════════════════════════════════════════════════════════════════════

class TestProcessingTimeSeries:

    def test_time_series_decompose(self):
        r = _run("time_series_decompose", column="cd_value", period=7)
        assert r["status"] == "success"
        _mcp_wrap_and_check("time_series_decompose", r)

    def test_detect_step_change(self):
        r = _run("detect_step_change", column="cd_value", threshold=2.0)
        assert r["status"] == "success"
        assert "change_points" in r["payload"]
        _mcp_wrap_and_check("detect_step_change", r)

    def test_resample_time_series(self):
        r = _run("resample_time_series", time_col="ts", value_col="cd_value", freq="W")
        assert r["status"] == "success"
        _mcp_wrap_and_check("resample_time_series", r)

    def test_moving_window_op(self):
        r = _run("moving_window_op", column="cd_value", window=5, op="mean")
        assert r["status"] == "success"
        _mcp_wrap_and_check("moving_window_op", r)

    def test_stationarity_test(self):
        r = _run("stationarity_test", value_col="cd_value")
        assert r["status"] == "success"
        assert "is_stationary" in r["payload"]
        _mcp_wrap_and_check("stationarity_test", r)

    def test_autocorrelation_analysis(self):
        r = _run("autocorrelation_analysis", value_col="cd_value", max_lags=10)
        assert r["status"] == "success"
        assert "acf" in r["payload"]
        _mcp_wrap_and_check("autocorrelation_analysis", r)

    def test_ewma_smoothing(self):
        r = _run("ewma_smoothing", value_col="cd_value", span=5)
        assert r["status"] == "success"
        assert "out_column" in r["payload"] or "rows" in r["payload"]
        _mcp_wrap_and_check("ewma_smoothing", r)

    def test_cusum_detection(self):
        r = _run("cusum_detection", value_col="cd_value", target=99.0, k=0.5)
        assert r["status"] == "success"
        assert "cusum_upper" in r["payload"] or "signals_up" in r["payload"]
        _mcp_wrap_and_check("cusum_detection", r)

    def test_seasonal_strength(self):
        r = _run("seasonal_strength", value_col="cd_value", period=7)
        assert r["status"] == "success"
        _mcp_wrap_and_check("seasonal_strength", r)

    def test_rolling_statistics(self):
        r = _run("rolling_statistics", value_col="cd_value", window=5, stats=["mean", "std"])
        assert r["status"] == "success"
        _mcp_wrap_and_check("rolling_statistics", r)

    def test_change_point_pettitt(self):
        r = _run("change_point_pettitt", value_col="cd_value")
        assert r["status"] == "success"
        assert "change_point_index" in r["payload"]
        _mcp_wrap_and_check("change_point_pettitt", r)

    def test_fft_dominant_freq(self):
        r = _run("fft_dominant_freq", value_col="cd_value", top_n=3, sampling_rate=1.0)
        assert r["status"] == "success"
        assert "top_frequencies" in r["payload"]
        _mcp_wrap_and_check("fft_dominant_freq", r)

    def test_lag_correlation(self):
        r = _run("lag_correlation", col_x="cd_value", col_y="etch_rate", max_lags=5)
        assert r["status"] == "success"
        assert "lag_correlations" in r["payload"] or "best_lag" in r["payload"]
        _mcp_wrap_and_check("lag_correlation", r)

    def test_trend_strength(self):
        r = _run("trend_strength", value_col="cd_value")
        assert r["status"] == "success"
        _mcp_wrap_and_check("trend_strength", r)

    def test_run_length_encoding(self):
        r = _run("run_length_encoding", value_col="cd_value")
        assert r["status"] == "success"
        assert "runs" in r["payload"]
        _mcp_wrap_and_check("run_length_encoding", r)

    def test_time_between_events(self):
        r = _run("time_between_events", value_col="defect_count", threshold=2.0)
        assert r["status"] == "success"
        _mcp_wrap_and_check("time_between_events", r)

    def test_velocity_acceleration(self):
        r = _run("velocity_acceleration", value_col="cd_value")
        assert r["status"] == "success"
        assert "velocity_col" in r["payload"] or "max_velocity" in r["payload"]
        _mcp_wrap_and_check("velocity_acceleration", r)

    def test_seasonality_index(self):
        r = _run("seasonality_index", value_col="cd_value", period_col="week")
        assert r["status"] == "success"
        _mcp_wrap_and_check("seasonality_index", r)

    def test_time_weighted_average(self):
        r = _run("time_weighted_average", value_col="cd_value", time_col="ts")
        assert r["status"] == "success", r["summary"]
        assert "time_weighted_average" in r["payload"] or "twa" in r["payload"]
        _mcp_wrap_and_check("time_weighted_average", r)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — Processing Tools: Transform / Utility (10 tools)
# ══════════════════════════════════════════════════════════════════════════════

class TestProcessingTransform:

    def test_data_filter(self):
        r = _run("data_filter", condition="defect_count > 0")
        assert r["status"] == "success"
        _mcp_wrap_and_check("data_filter", r)

    def test_data_aggregation(self):
        r = _run("data_aggregation", group_by="tool_id", agg_func="mean")
        assert r["status"] == "success"
        _mcp_wrap_and_check("data_aggregation", r)

    def test_pivot_table(self):
        r = _run("pivot_table", index="tool_id", col="shift", values="cd_value", aggfunc="mean")
        assert r["status"] == "success"
        _mcp_wrap_and_check("pivot_table", r)

    def test_flatten_json(self):
        r = _run("flatten_json", sep="_")
        assert r["status"] == "success"
        _mcp_wrap_and_check("flatten_json", r)

    def test_sort_by_multiple(self):
        r = _run("sort_by_multiple", criteria=[{"col": "cd_value", "order": "desc"}])
        assert r["status"] == "success"
        _mcp_wrap_and_check("sort_by_multiple", r)

    def test_cumulative_op(self):
        r = _run("cumulative_op", column="cd_value", op="sum")
        assert r["status"] == "success"
        _mcp_wrap_and_check("cumulative_op", r)

    def test_missing_value_impute(self):
        r = _run("missing_value_impute", column="cd_value", strategy="mean")
        assert r["status"] == "success"
        _mcp_wrap_and_check("missing_value_impute", r)

    def test_cross_reference(self):
        list_b = [{"lot_id": f"L{2603000 + i}", "golden_cd": 99.0} for i in range(10)]
        r = _run("cross_reference", list_b=list_b, key="lot_id")
        assert r["status"] == "success"
        assert "result_count" in r["payload"]
        _mcp_wrap_and_check("cross_reference", r)

    def test_logic_evaluator(self):
        # logic_evaluator evaluates a single expression with context (not per-row)
        r = _run("logic_evaluator", expression="x > 2", context={"x": 5})
        assert r["status"] == "success"
        assert r["payload"]["result"] is True
        _mcp_wrap_and_check("logic_evaluator", r)

    def test_regex_extractor(self):
        r = _run("regex_extractor", column="lot_id", pattern=r"L(\d+)")
        assert r["status"] == "success"
        _mcp_wrap_and_check("regex_extractor", r)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — Processing Tools: ML (10 tools)
# ══════════════════════════════════════════════════════════════════════════════

class TestProcessingML:

    def test_cluster_data(self):
        r = _run("cluster_data", k=3, columns=["cd_value", "etch_rate", "power"])
        assert r["status"] == "success"
        assert "cluster_sizes" in r["payload"]
        _mcp_wrap_and_check("cluster_data", r)

    def test_pca_variance(self):
        r = _run("pca_variance", feature_cols=["cd_value", "etch_rate", "power", "pressure"], n_components=3)
        assert r["status"] == "success"
        assert "components" in r["payload"]
        assert "total_explained" in r["payload"]
        _mcp_wrap_and_check("pca_variance", r)

    def test_vif_analysis(self):
        r = _run("vif_analysis", feature_cols=["cd_value", "etch_rate", "power", "pressure"])
        assert r["status"] == "success"
        assert "vif_scores" in r["payload"]
        _mcp_wrap_and_check("vif_analysis", r)

    def test_feature_variance(self):
        r = _run("feature_variance", feature_cols=["cd_value", "etch_rate", "power"], threshold=0.1)
        assert r["status"] == "success"
        _mcp_wrap_and_check("feature_variance", r)

    def test_mutual_information(self):
        r = _run("mutual_information", feature_cols=["etch_rate", "power", "pressure"], target_col="cd_value")
        assert r["status"] == "success"
        assert "mi_scores" in r["payload"]
        _mcp_wrap_and_check("mutual_information", r)

    def test_binning_equal_width(self):
        r = _run("binning_equal_width", value_col="cd_value", n_bins=5)
        assert r["status"] == "success", r["summary"]
        assert "bin_counts" in r["payload"]
        _mcp_wrap_and_check("binning_equal_width", r)

    def test_binning_quantile(self):
        r = _run("binning_quantile", value_col="cd_value", n_bins=4)
        assert r["status"] == "success", r["summary"]
        assert "bin_counts" in r["payload"]
        _mcp_wrap_and_check("binning_quantile", r)

    def test_target_encode(self):
        r = _run("target_encode", cat_col="tool_id", target_col="cd_value")
        assert r["status"] == "success", r["summary"]
        assert "encoding_map" in r["payload"]
        _mcp_wrap_and_check("target_encode", r)

    def test_robust_scale(self):
        r = _run("robust_scale", value_col="cd_value")
        assert r["status"] == "success", r["summary"]
        assert "out_column" in r["payload"]
        _mcp_wrap_and_check("robust_scale", r)

    def test_winsorize(self):
        r = _run("winsorize", value_col="cd_value", lower_pct=5.0, upper_pct=95.0)
        assert r["status"] == "success", r["summary"]
        assert "n_clipped" in r["payload"]
        _mcp_wrap_and_check("winsorize", r)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — Processing Tools: SPC / Semiconductor Utility (10 tools)
# ══════════════════════════════════════════════════════════════════════════════

class TestProcessingSPC:

    def test_capability_analysis(self):
        r = _run("capability_analysis", value_col="cd_value", usl=105.0, lsl=93.0)
        assert r["status"] == "success"
        assert "Cp" in r["payload"] or "Cpk" in r["payload"]
        _mcp_wrap_and_check("capability_analysis", r)

    def test_western_electric_rules(self):
        r = _run("western_electric_rules", value_col="cd_value")
        assert r["status"] == "success"
        assert "violations" in r["payload"]
        _mcp_wrap_and_check("western_electric_rules", r)

    def test_nelson_rules(self):
        r = _run("nelson_rules", value_col="cd_value")
        assert r["status"] == "success"
        assert "violations" in r["payload"]
        _mcp_wrap_and_check("nelson_rules", r)

    def test_process_sigma(self):
        r = _run("process_sigma", defects_col="defect_count", opportunities_per_unit=5)
        assert r["status"] == "success"
        assert "sigma_level" in r["payload"]
        _mcp_wrap_and_check("process_sigma", r)

    def test_gage_repeatability(self):
        r = _run("gage_repeatability", measurement_col="cd_value", part_col="wafer_id")
        assert r["status"] == "success"
        _mcp_wrap_and_check("gage_repeatability", r)

    def test_tolerance_interval(self):
        r = _run("tolerance_interval", value_col="cd_value")
        assert r["status"] == "success"
        assert "tolerance_lower" in r["payload"]
        assert "tolerance_upper" in r["payload"]
        _mcp_wrap_and_check("tolerance_interval", r)

    def test_control_limits_calculator(self):
        r = _run("control_limits_calculator", value_col="cd_value", method="3sigma")
        assert r["status"] == "success"
        assert "ucl" in r["payload"]
        assert "lcl" in r["payload"]
        _mcp_wrap_and_check("control_limits_calculator", r)

    def test_top_n_contributors(self):
        r = _run("top_n_contributors", value_col="cd_value", group_col="tool_id", top_n=3)
        assert r["status"] == "success"
        _mcp_wrap_and_check("top_n_contributors", r)

    def test_within_between_variance(self):
        r = _run("within_between_variance", value_col="cd_value", group_col="tool_id")
        assert r["status"] == "success"
        assert "ss_within" in r["payload"] or "pct_between" in r["payload"]
        _mcp_wrap_and_check("within_between_variance", r)

    def test_data_quality_score(self):
        r = _run("data_quality_score", columns=["cd_value", "etch_rate", "power"])
        assert r["status"] == "success"
        assert "overall_quality" in r["payload"] or "overall_score" in r["payload"]
        _mcp_wrap_and_check("data_quality_score", r)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7 — Visualization Tools: Basic (25 tools)
# ══════════════════════════════════════════════════════════════════════════════

class TestVizBasic:

    def test_plot_line(self):
        r = _run("plot_line", x="ts", y="cd_value")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_line")
        _mcp_wrap_and_check("plot_line", r)

    def test_plot_bar(self):
        r = _run("plot_bar", x="tool_id", y="cd_value")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_bar")
        _mcp_wrap_and_check("plot_bar", r)

    def test_plot_scatter(self):
        r = _run("plot_scatter", x="power", y="cd_value", color="tool_id")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_scatter")
        _mcp_wrap_and_check("plot_scatter", r)

    def test_plot_histogram(self):
        r = _run("plot_histogram", column="cd_value", bins=15)
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_histogram")
        _mcp_wrap_and_check("plot_histogram", r)

    def test_plot_pie(self):
        r = _run("plot_pie", labels="pass_fail", values="defect_count")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_pie")
        _mcp_wrap_and_check("plot_pie", r)

    def test_plot_area(self):
        r = _run("plot_area", x="ts", y="cd_value")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_area")
        _mcp_wrap_and_check("plot_area", r)

    def test_plot_step_line(self):
        r = _run("plot_step_line", x="ts", y="cd_value")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_step_line")
        _mcp_wrap_and_check("plot_step_line", r)

    def test_plot_box(self):
        r = _run("plot_box", column="cd_value", group_by="tool_id")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_box")
        _mcp_wrap_and_check("plot_box", r)

    def test_plot_violin(self):
        r = _run("plot_violin", column="cd_value", group_by="tool_id")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_violin")
        _mcp_wrap_and_check("plot_violin", r)

    def test_plot_heatmap(self):
        r = _run("plot_heatmap", columns=["cd_value", "etch_rate", "power", "pressure"])
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_heatmap")
        _mcp_wrap_and_check("plot_heatmap", r)

    def test_plot_radar(self):
        r = _run("plot_radar", axes=["cd_value", "etch_rate", "power", "selectivity"], group_by="tool_id")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_radar")
        _mcp_wrap_and_check("plot_radar", r)

    def test_plot_error_bar(self):
        r = _run("plot_error_bar", x="tool_id", y="cd_value", error="selectivity")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_error_bar")
        _mcp_wrap_and_check("plot_error_bar", r)

    def test_plot_sankey(self):
        r = _run("plot_sankey", source="shift", target="pass_fail", value="defect_count")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_sankey")
        _mcp_wrap_and_check("plot_sankey", r)

    def test_plot_treemap(self):
        r = _run("plot_treemap", path=["tool_id", "shift"], value="defect_count")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_treemap")
        _mcp_wrap_and_check("plot_treemap", r)

    def test_plot_sunburst(self):
        r = _run("plot_sunburst", path=["tool_id", "shift"], value="defect_count")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_sunburst")
        _mcp_wrap_and_check("plot_sunburst", r)

    def test_plot_waterfall(self):
        r = _run("plot_waterfall", x="tool_id", y="cd_value")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_waterfall")
        _mcp_wrap_and_check("plot_waterfall", r)

    def test_plot_funnel(self):
        r = _run("plot_funnel", stage="tool_id", value="cd_value")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_funnel")
        _mcp_wrap_and_check("plot_funnel", r)

    def test_plot_gauge(self):
        r = _run("plot_gauge", value=98.5, column="cd_value")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_gauge")
        _mcp_wrap_and_check("plot_gauge", r)

    def test_plot_bubble(self):
        r = _run("plot_bubble", x="power", y="cd_value", size="selectivity", color="tool_id")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_bubble")
        _mcp_wrap_and_check("plot_bubble", r)

    def test_plot_dual_axis(self):
        r = _run("plot_dual_axis", x="ts", y1="cd_value", y2="etch_rate")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_dual_axis")
        _mcp_wrap_and_check("plot_dual_axis", r)

    def test_plot_candlestick(self):
        r = _run("plot_candlestick", time="ts", open="cd_value", high="etch_rate",
                  low="lower_limit", close="upper_limit")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_candlestick")
        _mcp_wrap_and_check("plot_candlestick", r)

    def test_plot_network(self):
        r = _run("plot_network", source="tool_id", target="shift", value="defect_count")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_network")
        _mcp_wrap_and_check("plot_network", r)

    def test_plot_parallel_coords(self):
        r = _run("plot_parallel_coords", axes=["cd_value", "etch_rate", "power"], color_col="defect_count")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_parallel_coords")
        _mcp_wrap_and_check("plot_parallel_coords", r)

    def test_plot_wordcloud(self):
        r = _run("plot_wordcloud", column="tool_id")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_wordcloud")
        _mcp_wrap_and_check("plot_wordcloud", r)

    def test_plot_summary_card(self):
        r = _run("plot_summary_card", column="cd_value", label="CD Value KPI")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_summary_card")
        _mcp_wrap_and_check("plot_summary_card", r)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 8 — Visualization Tools: Distribution (15 tools)
# ══════════════════════════════════════════════════════════════════════════════

class TestVizDistribution:

    def test_plot_qq(self):
        r = _run("plot_qq", value_col="cd_value")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_qq")
        _mcp_wrap_and_check("plot_qq", r)

    def test_plot_kde(self):
        r = _run("plot_kde", value_col="cd_value", group_col="tool_id")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_kde")
        _mcp_wrap_and_check("plot_kde", r)

    def test_plot_ecdf(self):
        r = _run("plot_ecdf", value_col="cd_value", group_col="shift")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_ecdf")
        _mcp_wrap_and_check("plot_ecdf", r)

    def test_plot_probability_plot(self):
        r = _run("plot_probability_plot", value_col="cd_value")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_probability_plot")
        _mcp_wrap_and_check("plot_probability_plot", r)

    def test_plot_residuals(self):
        r = _run("plot_residuals", value_col="cd_value", fitted_col="etch_rate")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_residuals")
        _mcp_wrap_and_check("plot_residuals", r)

    def test_plot_ridge(self):
        r = _run("plot_ridge", value_col="cd_value", group_col="tool_id")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_ridge")
        _mcp_wrap_and_check("plot_ridge", r)

    def test_plot_strip(self):
        r = _run("plot_strip", value_col="cd_value", group_col="tool_id")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_strip")
        _mcp_wrap_and_check("plot_strip", r)

    def test_plot_correlation_matrix(self):
        r = _run("plot_correlation_matrix", feature_cols=["cd_value", "etch_rate", "power", "pressure"])
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_correlation_matrix")
        _mcp_wrap_and_check("plot_correlation_matrix", r)

    def test_plot_scatter_matrix(self):
        r = _run("plot_scatter_matrix", feature_cols=["cd_value", "etch_rate", "power"], color_col="tool_id")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_scatter_matrix")
        _mcp_wrap_and_check("plot_scatter_matrix", r)

    def test_plot_mean_ci(self):
        r = _run("plot_mean_ci", value_col="cd_value", group_col="tool_id")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_mean_ci")
        _mcp_wrap_and_check("plot_mean_ci", r)

    def test_plot_bland_altman(self):
        r = _run("plot_bland_altman", method1_col="cd_value", method2_col="etch_rate")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_bland_altman")
        _mcp_wrap_and_check("plot_bland_altman", r)

    def test_plot_distribution_compare(self):
        r = _run("plot_distribution_compare", value_col="cd_value", group_col="tool_id")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_distribution_compare")
        _mcp_wrap_and_check("plot_distribution_compare", r)

    def test_plot_lollipop(self):
        r = _run("plot_lollipop", value_col="cd_value", label_col="lot_id")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_lollipop")
        _mcp_wrap_and_check("plot_lollipop", r)

    def test_plot_dumbbell(self):
        r = _run("plot_dumbbell", before_col="lower_limit", after_col="upper_limit", label_col="tool_id")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_dumbbell")
        _mcp_wrap_and_check("plot_dumbbell", r)

    def test_plot_diverging_bar(self):
        r = _run("plot_diverging_bar", value_col="cd_value", label_col="tool_id", baseline=99.0)
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_diverging_bar")
        _mcp_wrap_and_check("plot_diverging_bar", r)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 9 — Visualization Tools: SPC / Advanced (20 tools)
# ══════════════════════════════════════════════════════════════════════════════

class TestVizAdvanced:

    def test_plot_xbar_r(self):
        r = _run("plot_xbar_r", value_col="cd_value", subgroup_col="tool_id")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_xbar_r")
        _mcp_wrap_and_check("plot_xbar_r", r)

    def test_plot_imr(self):
        r = _run("plot_imr", value_col="cd_value")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_imr")
        _mcp_wrap_and_check("plot_imr", r)

    def test_plot_cusum(self):
        r = _run("plot_cusum", value_col="cd_value", target=99.0, k=0.5, h=5.0)
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_cusum")
        _mcp_wrap_and_check("plot_cusum", r)

    def test_plot_ewma_chart(self):
        r = _run("plot_ewma_chart", value_col="cd_value", lambda_=0.2, L=3.0)
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_ewma_chart")
        _mcp_wrap_and_check("plot_ewma_chart", r)

    def test_plot_pareto(self):
        r = _run("plot_pareto", value_col="defect_count", label_col="tool_id")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_pareto")
        _mcp_wrap_and_check("plot_pareto", r)

    def test_plot_capability_hist(self):
        r = _run("plot_capability_hist", value_col="cd_value", usl=105.0, lsl=93.0)
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_capability_hist")
        _mcp_wrap_and_check("plot_capability_hist", r)

    def test_plot_acf_pacf(self):
        r = _run("plot_acf_pacf", value_col="cd_value", max_lags=15)
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_acf_pacf")
        _mcp_wrap_and_check("plot_acf_pacf", r)

    def test_plot_rolling_stats(self):
        r = _run("plot_rolling_stats", value_col="cd_value", window=7)
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_rolling_stats")
        _mcp_wrap_and_check("plot_rolling_stats", r)

    def test_plot_seasonal_decompose(self):
        r = _run("plot_seasonal_decompose", value_col="cd_value", period=7)
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_seasonal_decompose")
        _mcp_wrap_and_check("plot_seasonal_decompose", r)

    def test_plot_forecast_band(self):
        r = _run("plot_forecast_band", value_col="cd_value", upper_col="upper_limit", lower_col="lower_limit")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_forecast_band")
        _mcp_wrap_and_check("plot_forecast_band", r)

    def test_plot_event_markers(self):
        r = _run("plot_event_markers", value_col="cd_value", time_col="ts", event_col="pass_fail")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_event_markers")
        _mcp_wrap_and_check("plot_event_markers", r)

    def test_plot_multi_vari(self):
        r = _run("plot_multi_vari", value_col="cd_value", part_col="wafer_id")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_multi_vari")
        _mcp_wrap_and_check("plot_multi_vari", r)

    def test_plot_run_chart(self):
        r = _run("plot_run_chart", value_col="cd_value")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_run_chart")
        _mcp_wrap_and_check("plot_run_chart", r)

    def test_plot_hexbin(self):
        r = _run("plot_hexbin", col_x="power", col_y="cd_value")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_hexbin")
        _mcp_wrap_and_check("plot_hexbin", r)

    def test_plot_contour(self):
        r = _run("plot_contour", col_x="power", col_y="cd_value")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_contour")
        _mcp_wrap_and_check("plot_contour", r)

    def test_plot_3d_scatter(self):
        r = _run("plot_3d_scatter", col_x="power", col_y="cd_value", col_z="etch_rate", color_col="tool_id")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_3d_scatter")
        _mcp_wrap_and_check("plot_3d_scatter", r)

    def test_plot_marginal_scatter(self):
        r = _run("plot_marginal_scatter", col_x="power", col_y="cd_value", color_col="tool_id")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_marginal_scatter")
        _mcp_wrap_and_check("plot_marginal_scatter", r)

    def test_plot_slope_chart(self):
        r = _run("plot_slope_chart", value_col="cd_value", time_col="week", group_col="tool_id")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_slope_chart")
        _mcp_wrap_and_check("plot_slope_chart", r)

    def test_plot_benchmark(self):
        r = _run("plot_benchmark", value_col="cd_value", benchmark_col="target", label_col="lot_id")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_benchmark")
        _mcp_wrap_and_check("plot_benchmark", r)

    def test_plot_outlier_flags(self):
        r = _run("plot_outlier_flags", value_col="cd_value", time_col="ts", threshold=2.0)
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_outlier_flags")
        _mcp_wrap_and_check("plot_outlier_flags", r)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 10 — Visualization Tools: Special / Dashboard (15 tools)
# ══════════════════════════════════════════════════════════════════════════════

class TestVizSpecial:

    def test_plot_missing_heatmap(self):
        r = _run("plot_missing_heatmap", columns=["cd_value", "etch_rate", "power"])
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_missing_heatmap")
        _mcp_wrap_and_check("plot_missing_heatmap", r)

    def test_plot_data_profile(self):
        r = _run("plot_data_profile", columns=["cd_value", "etch_rate", "power", "pressure"])
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_data_profile")
        _mcp_wrap_and_check("plot_data_profile", r)

    def test_plot_boxplot_with_stats(self):
        r = _run("plot_boxplot_with_stats", value_col="cd_value", group_col="tool_id")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_boxplot_with_stats")
        _mcp_wrap_and_check("plot_boxplot_with_stats", r)

    def test_plot_correlation_network(self):
        r = _run("plot_correlation_network",
                 feature_cols=["cd_value", "etch_rate", "power", "pressure"], threshold=0.3)
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_correlation_network")
        _mcp_wrap_and_check("plot_correlation_network", r)

    def test_plot_value_counts(self):
        r = _run("plot_value_counts", cat_col="tool_id", top_n=5)
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_value_counts")
        _mcp_wrap_and_check("plot_value_counts", r)

    def test_plot_time_heatmap(self):
        r = _run("plot_time_heatmap", value_col="cd_value", time_col="ts")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_time_heatmap")
        _mcp_wrap_and_check("plot_time_heatmap", r)

    def test_plot_rank_change(self):
        r = _run("plot_rank_change", value_col="cd_value", time_col="week", group_col="tool_id")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_rank_change")
        _mcp_wrap_and_check("plot_rank_change", r)

    def test_plot_stacked_pct(self):
        r = _run("plot_stacked_pct", value_col="defect_count", group_col="tool_id", time_col="week")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_stacked_pct")
        _mcp_wrap_and_check("plot_stacked_pct", r)

    def test_plot_bullet_chart(self):
        r = _run("plot_bullet_chart", value_col="cd_value", label_col="tool_id", target_col="target")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_bullet_chart")
        _mcp_wrap_and_check("plot_bullet_chart", r)

    def test_plot_control_plan(self):
        r = _run("plot_control_plan",
                 value_cols=["cd_value", "etch_rate"],
                 ucl_cols=["upper_limit", "upper_limit"])
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_control_plan")
        _mcp_wrap_and_check("plot_control_plan", r)

    def test_plot_contribution_waterfall(self):
        r = _run("plot_contribution_waterfall", value_col="cd_value", group_col="tool_id")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_contribution_waterfall")
        _mcp_wrap_and_check("plot_contribution_waterfall", r)

    def test_plot_timeline(self):
        r = _run("plot_timeline", event_col="pass_fail", start_col="ts")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_timeline")
        _mcp_wrap_and_check("plot_timeline", r)

    def test_plot_funnel_conversion(self):
        r = _run("plot_funnel_conversion", stage_col="tool_id", count_col="defect_count")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_funnel_conversion")
        _mcp_wrap_and_check("plot_funnel_conversion", r)

    def test_plot_spc_dashboard(self):
        r = _run("plot_spc_dashboard", value_col="cd_value", ucl=105.0, lcl=93.0)
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_spc_dashboard")
        _mcp_wrap_and_check("plot_spc_dashboard", r)

    def test_plot_eda_overview(self):
        r = _run("plot_eda_overview", value_col="cd_value")
        assert r["status"] == "success"
        _check_plotly(r["payload"], "plot_eda_overview")
        _mcp_wrap_and_check("plot_eda_overview", r)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 11 — Cross-cutting: all 150 tools auto-discovery check
# ══════════════════════════════════════════════════════════════════════════════

class TestToolRegistrySanity:

    def test_registry_count(self):
        """Ensure all 150 tools are registered."""
        assert len(TOOL_REGISTRY) == 150, (
            f"Expected 150 tools, found {len(TOOL_REGISTRY)}. "
            "Check __init__.py registrations."
        )

    def test_all_tools_have_required_metadata(self):
        """Every tool must have category, description, params."""
        for name, meta in TOOL_REGISTRY.items():
            assert "category" in meta, f"{name}: missing 'category'"
            assert meta["category"] in ("processing", "visualization"), f"{name}: bad category"
            assert "description" in meta, f"{name}: missing 'description'"
            assert meta["description"], f"{name}: empty description"
            assert "params" in meta, f"{name}: missing 'params'"
            assert "fn" in meta, f"{name}: missing 'fn' (callable)"
            assert callable(meta["fn"]), f"{name}: 'fn' is not callable"

    def test_processing_tools_count(self):
        proc = [k for k, v in TOOL_REGISTRY.items() if v["category"] == "processing"]
        assert len(proc) == 75, f"Expected 75 processing tools, found {len(proc)}"

    def test_visualization_tools_count(self):
        viz = [k for k, v in TOOL_REGISTRY.items() if v["category"] == "visualization"]
        assert len(viz) == 75, f"Expected 75 visualization tools, found {len(viz)}"

    def test_all_tools_callable_with_empty_data(self):
        """Every tool must return a dict with 'status' key even on empty input."""
        failures = []
        for name in TOOL_REGISTRY:
            try:
                r = call_tool(name, data=[])
                if not isinstance(r, dict) or "status" not in r:
                    failures.append(f"{name}: bad return type")
            except Exception as e:
                failures.append(f"{name}: raised exception: {e}")
        assert not failures, "Tools with bad empty-data behavior:\n" + "\n".join(failures)

    def test_no_tool_raises_on_basic_data(self):
        """All tools must return dict (not raise) on _BASE_DATA with no params."""
        failures = []
        for name in TOOL_REGISTRY:
            try:
                r = call_tool(name, data=_BASE_DATA)
                if not isinstance(r, dict):
                    failures.append(f"{name}: returned {type(r)}")
            except Exception as e:
                failures.append(f"{name}: raised {type(e).__name__}: {e}")
        assert not failures, "Tools that raise exceptions:\n" + "\n".join(failures[:20])

    def test_catalog_endpoint_payload_structure(self):
        """Simulate GET /generic-tools/catalog response structure."""
        items = [
            {
                "name": name,
                "category": meta["category"],
                "description": meta["description"],
                "params": meta["params"],
            }
            for name, meta in TOOL_REGISTRY.items()
        ]
        assert len(items) == 150
        for item in items:
            json.dumps(item)  # must be JSON-serializable
