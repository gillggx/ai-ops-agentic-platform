"""Generic Tools Registry (v15.4) — 100 pure analytic + visualization functions.

Usage:
    from app.generic_tools import TOOL_REGISTRY, call_tool

    result = call_tool("calc_statistics", data=[...], column="value")
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List

# ── Processing tools ──────────────────────────────────────────────────────────
from app.generic_tools.processing.statistical import (
    calc_statistics,
    distribution_test,
    find_outliers,
    frequency_analysis,
    normalization,
    # NEW v15.4
    ttest_one_sample,
    ttest_two_sample,
    chi_square_test,
    anova_oneway,
    mann_whitney_u,
    kruskal_wallis,
    shapiro_wilk,
    levene_variance,
    spearman_correlation,
    partial_correlation,
    bootstrap_ci,
    cohens_d,
    percentile_analysis,
    outlier_score_zscore,
    rank_transform,
)
from app.generic_tools.processing.correlation import (
    correlation_analysis,
    linear_regression,
)
from app.generic_tools.processing.time_series import (
    detect_step_change,
    moving_window_op,
    resample_time_series,
    time_series_decompose,
    # NEW v15.4
    stationarity_test,
    autocorrelation_analysis,
    ewma_smoothing,
    cusum_detection,
    seasonal_strength,
    rolling_statistics,
    change_point_pettitt,
    fft_dominant_freq,
    lag_correlation,
    trend_strength,
    run_length_encoding,
    time_between_events,
    velocity_acceleration,
    seasonality_index,
    time_weighted_average,
)
from app.generic_tools.processing.transform import (
    cumulative_op,
    data_aggregation,
    data_filter,
    flatten_json,
    pivot_table,
    set_operation,
    sort_by_multiple,
)
from app.generic_tools.processing.ml import (
    cluster_data,
    vector_similarity,
    # NEW v15.4
    pca_variance,
    vif_analysis,
    feature_variance,
    mutual_information,
    binning_equal_width,
    binning_quantile,
    target_encode,
    polynomial_interaction,
    robust_scale,
    winsorize,
)
from app.generic_tools.processing.utility import (
    cross_reference,
    diff_engine,
    logic_evaluator,
    missing_value_impute,
    regex_extractor,
    # NEW v15.4
    capability_analysis,
    western_electric_rules,
    nelson_rules,
    process_sigma,
    gage_repeatability,
    tolerance_interval,
    control_limits_calculator,
    top_n_contributors,
    within_between_variance,
    data_quality_score,
)

# ── Visualization tools ───────────────────────────────────────────────────────
from app.generic_tools.visualization.basic import (
    plot_area,
    plot_bar,
    plot_histogram,
    plot_line,
    plot_pie,
    plot_scatter,
    plot_step_line,
)
from app.generic_tools.visualization.distribution import (
    plot_box,
    plot_error_bar,
    plot_heatmap,
    plot_radar,
    plot_violin,
    # NEW v15.4
    plot_qq,
    plot_kde,
    plot_ecdf,
    plot_probability_plot,
    plot_residuals,
    plot_ridge,
    plot_strip,
    plot_correlation_matrix,
    plot_scatter_matrix,
    plot_mean_ci,
    plot_bland_altman,
    plot_distribution_compare,
    plot_lollipop,
    plot_dumbbell,
    plot_diverging_bar,
)
from app.generic_tools.visualization.advanced import (
    plot_bubble,
    plot_dual_axis,
    plot_funnel,
    plot_gauge,
    plot_sankey,
    plot_sunburst,
    plot_treemap,
    plot_waterfall,
    # NEW v15.4
    plot_xbar_r,
    plot_imr,
    plot_cusum,
    plot_ewma_chart,
    plot_pareto,
    plot_capability_hist,
    plot_acf_pacf,
    plot_rolling_stats,
    plot_seasonal_decompose,
    plot_forecast_band,
    plot_event_markers,
    plot_multi_vari,
    plot_run_chart,
    plot_hexbin,
    plot_contour,
    plot_3d_scatter,
    plot_marginal_scatter,
    plot_slope_chart,
    plot_benchmark,
    plot_outlier_flags,
)
from app.generic_tools.visualization.special import (
    plot_candlestick,
    plot_network,
    plot_parallel_coords,
    plot_summary_card,
    plot_wordcloud,
    # NEW v15.4
    plot_missing_heatmap,
    plot_data_profile,
    plot_boxplot_with_stats,
    plot_correlation_network,
    plot_value_counts,
    plot_time_heatmap,
    plot_rank_change,
    plot_stacked_pct,
    plot_bullet_chart,
    plot_control_plan,
    plot_contribution_waterfall,
    plot_timeline,
    plot_funnel_conversion,
    plot_spc_dashboard,
    plot_eda_overview,
)

# ── Registry ──────────────────────────────────────────────────────────────────

TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {
    # ── Statistical / Processing ──────────────────────────────────────────────
    "calc_statistics": {
        "fn": calc_statistics,
        "category": "processing",
        "description": "Return mean, std, median, variance, skewness, kurtosis for one or more numeric columns.",
        "params": {
            "column": "str — target column (optional; auto-detects first numeric if omitted)",
            "columns": "list[str] — multiple columns (optional)",
        },
    },
    "find_outliers": {
        "fn": find_outliers,
        "category": "processing",
        "description": "Detect outliers using Z-score (sigma) or IQR method.",
        "params": {
            "column": "str — numeric column to analyse",
            "method": "'sigma' (default) or 'iqr'",
            "threshold": "float — sigma threshold (default 3.0) or IQR multiplier (default 1.5)",
        },
    },
    "normalization": {
        "fn": normalization,
        "category": "processing",
        "description": "Min-max or Z-score normalization of a numeric column.",
        "params": {
            "column": "str — column to normalize",
            "method": "'minmax' (default) or 'zscore'",
        },
    },
    "frequency_analysis": {
        "fn": frequency_analysis,
        "category": "processing",
        "description": "FFT frequency spectrum or value-count distribution for a column.",
        "params": {
            "column": "str — target column",
            "mode": "'fft' (default) or 'count'",
        },
    },
    "distribution_test": {
        "fn": distribution_test,
        "category": "processing",
        "description": "Jarque-Bera normality test (pure numpy, no scipy).",
        "params": {
            "column": "str — numeric column to test",
        },
    },
    "correlation_analysis": {
        "fn": correlation_analysis,
        "category": "processing",
        "description": "Pearson + Spearman correlation with p-value approximation.",
        "params": {
            "col_a": "str — first column (auto-detects if omitted)",
            "col_b": "str — second column (auto-detects if omitted)",
        },
    },
    "linear_regression": {
        "fn": linear_regression,
        "category": "processing",
        "description": "OLS linear regression: slope, intercept, R², RMSE, residuals.",
        "params": {
            "x_col": "str — independent variable column",
            "y_col": "str — dependent variable column",
        },
    },
    "time_series_decompose": {
        "fn": time_series_decompose,
        "category": "processing",
        "description": "Decompose time series into trend, seasonal, residual via moving average.",
        "params": {
            "column": "str — numeric series column",
            "period": "int — seasonality period (default 7)",
        },
    },
    "detect_step_change": {
        "fn": detect_step_change,
        "category": "processing",
        "description": "Detect mean shifts using CUSUM algorithm.",
        "params": {
            "column": "str — numeric column",
            "threshold": "float — sensitivity in sigma units (default 1.0)",
        },
    },
    "resample_time_series": {
        "fn": resample_time_series,
        "category": "processing",
        "description": "Resample time series to a different interval (e.g. '1min', '1H', '1D').",
        "params": {
            "time_col": "str — datetime column",
            "value_col": "str — value column (optional; all numeric if omitted)",
            "interval": "str — pandas offset alias (default '1min')",
            "agg_func": "str — 'mean'|'sum'|'min'|'max' (default 'mean')",
        },
    },
    "moving_window_op": {
        "fn": moving_window_op,
        "category": "processing",
        "description": "Rolling window mean/std/min/max/sum on a numeric column.",
        "params": {
            "column": "str — target column",
            "window": "int — window size (default 5)",
            "op": "str — 'mean'|'std'|'min'|'max'|'sum' (default 'mean')",
        },
    },
    "data_filter": {
        "fn": data_filter,
        "category": "processing",
        "description": "Filter rows using a pandas query string (e.g. 'value > 45 and status == \"OOC\"').",
        "params": {
            "condition": "str — pandas query expression (required)",
        },
    },
    "data_aggregation": {
        "fn": data_aggregation,
        "category": "processing",
        "description": "Group-by aggregation (sum/mean/count/min/max/std).",
        "params": {
            "group_by": "str | list[str] — column(s) to group by (required)",
            "agg_func": "str — aggregation function (default 'mean')",
            "column": "str — value column (optional; all numeric if omitted)",
        },
    },
    "pivot_table": {
        "fn": pivot_table,
        "category": "processing",
        "description": "Pivot long table to wide format.",
        "params": {
            "index": "str — row index column (required)",
            "col": "str — column pivot field (required)",
            "val": "str — value field (required)",
            "agg_func": "str — aggregation (default 'mean')",
        },
    },
    "flatten_json": {
        "fn": flatten_json,
        "category": "processing",
        "description": "Flatten nested JSON/dict structures to single-level using pd.json_normalize.",
        "params": {
            "sep": "str — separator for nested keys (default '_')",
        },
    },
    "sort_by_multiple": {
        "fn": sort_by_multiple,
        "category": "processing",
        "description": "Sort rows by multiple columns with per-column asc/desc order.",
        "params": {
            "criteria": "list[{col: str, order: 'asc'|'desc'}] — sort criteria (required)",
        },
    },
    "cumulative_op": {
        "fn": cumulative_op,
        "category": "processing",
        "description": "Cumulative sum/product/min/max on a numeric column.",
        "params": {
            "column": "str — numeric column",
            "op": "str — 'sum'|'prod'|'min'|'max' (default 'sum')",
        },
    },
    "set_operation": {
        "fn": set_operation,
        "category": "processing",
        "description": "Set operations (intersection/union/difference/symmetric_difference) between two lists.",
        "params": {
            "list_a": "list — first set (or use 'column' to extract from data)",
            "list_b": "list — second set (required)",
            "op": "str — operation name (default 'intersection')",
        },
    },
    "cluster_data": {
        "fn": cluster_data,
        "category": "processing",
        "description": "K-means clustering (pure numpy, no sklearn). Returns cluster labels + centroids.",
        "params": {
            "k": "int — number of clusters (default 3)",
            "columns": "list[str] — numeric columns to cluster on (optional; all numeric if omitted)",
            "max_iter": "int — max iterations (default 100)",
        },
    },
    "vector_similarity": {
        "fn": vector_similarity,
        "category": "processing",
        "description": "Cosine, Euclidean, and Manhattan distances between two numeric vectors.",
        "params": {
            "vec_a": "list[float] — first vector (or use col_a to extract from data)",
            "vec_b": "list[float] — second vector",
            "col_a": "str — column for vec_a (alternative to vec_a)",
            "col_b": "str — column for vec_b (alternative to vec_b)",
        },
    },
    "missing_value_impute": {
        "fn": missing_value_impute,
        "category": "processing",
        "description": "Fill missing values using mean/median/previous/constant strategy.",
        "params": {
            "column": "str — column to impute (optional; all columns if omitted)",
            "strategy": "str — 'mean'|'median'|'prev'|'constant' (default 'mean')",
            "constant": "any — fill value when strategy='constant'",
        },
    },
    "regex_extractor": {
        "fn": regex_extractor,
        "category": "processing",
        "description": "Extract capture groups from a text column using a regex pattern.",
        "params": {
            "column": "str — text column (required)",
            "pattern": "str — regex pattern with optional named groups (required)",
            "out_column": "str — output column name (default '{column}_extracted')",
        },
    },
    "diff_engine": {
        "fn": diff_engine,
        "category": "processing",
        "description": "Deep diff between two dicts/objects, or row-by-row diff between two data lists.",
        "params": {
            "old": "dict — baseline dict (or use data as list of before/after pairs)",
            "new": "dict — new dict to compare against",
        },
    },
    "cross_reference": {
        "fn": cross_reference,
        "category": "processing",
        "description": "Join two datasets on a key column (inner/left/right/outer merge).",
        "params": {
            "other": "list[dict] — second dataset to join (required)",
            "on": "str — join key column (required)",
            "how": "str — 'inner'|'left'|'right'|'outer' (default 'inner')",
        },
    },
    "logic_evaluator": {
        "fn": logic_evaluator,
        "category": "processing",
        "description": "Evaluate a Python expression against each row, adding a boolean result column.",
        "params": {
            "expression": "str — Python expression using row fields (required)",
            "out_column": "str — output boolean column name (default 'eval_result')",
        },
    },
    # ── Basic Visualization ───────────────────────────────────────────────────
    "plot_line": {
        "fn": plot_line,
        "category": "visualization",
        "description": "Line chart with optional multi-series support.",
        "params": {
            "x": "str — X-axis column",
            "y": "str | list[str] — Y column(s)",
            "title": "str — chart title",
        },
    },
    "plot_bar": {
        "fn": plot_bar,
        "category": "visualization",
        "description": "Bar chart (grouped or stacked).",
        "params": {
            "x": "str — category column",
            "y": "str | list[str] — value column(s)",
            "barmode": "'group' (default) | 'stack'",
            "title": "str — chart title",
        },
    },
    "plot_scatter": {
        "fn": plot_scatter,
        "category": "visualization",
        "description": "Scatter plot with optional color/size encoding.",
        "params": {
            "x": "str — X column",
            "y": "str — Y column",
            "color": "str — color-encode by this column (optional)",
            "size": "str — size-encode by this column (optional)",
            "title": "str — chart title",
        },
    },
    "plot_histogram": {
        "fn": plot_histogram,
        "category": "visualization",
        "description": "Histogram with configurable bin count.",
        "params": {
            "column": "str — numeric column",
            "bins": "int — number of bins (default 20)",
            "title": "str — chart title",
        },
    },
    "plot_pie": {
        "fn": plot_pie,
        "category": "visualization",
        "description": "Pie / donut chart.",
        "params": {
            "labels": "str — labels column",
            "values": "str — values column",
            "hole": "float — donut hole 0–1 (default 0 = pie)",
            "title": "str — chart title",
        },
    },
    "plot_area": {
        "fn": plot_area,
        "category": "visualization",
        "description": "Stacked or overlaid area chart.",
        "params": {
            "x": "str — X column",
            "y": "str | list[str] — Y column(s)",
            "title": "str — chart title",
        },
    },
    "plot_step_line": {
        "fn": plot_step_line,
        "category": "visualization",
        "description": "Step-line chart (hv, vh, or hvh shape).",
        "params": {
            "x": "str — X column",
            "y": "str — Y column",
            "shape": "'hv' (default) | 'vh' | 'hvh'",
            "title": "str — chart title",
        },
    },
    # ── Distribution Visualization ────────────────────────────────────────────
    "plot_box": {
        "fn": plot_box,
        "category": "visualization",
        "description": "Box plot (with optional grouping).",
        "params": {
            "column": "str — numeric column",
            "group_by": "str — group column (optional)",
            "title": "str — chart title",
        },
    },
    "plot_violin": {
        "fn": plot_violin,
        "category": "visualization",
        "description": "Violin plot showing distribution shape.",
        "params": {
            "column": "str — numeric column",
            "group_by": "str — group column (optional)",
            "title": "str — chart title",
        },
    },
    "plot_heatmap": {
        "fn": plot_heatmap,
        "category": "visualization",
        "description": "Correlation heatmap or custom Z-value heatmap.",
        "params": {
            "columns": "list[str] — columns for correlation matrix (optional; all numeric if omitted)",
            "x": "str — X column for custom heatmap",
            "y": "str — Y column for custom heatmap",
            "z": "str — Z (value) column for custom heatmap",
            "title": "str — chart title",
        },
    },
    "plot_radar": {
        "fn": plot_radar,
        "category": "visualization",
        "description": "Radar (spider) chart for multi-dimensional comparison.",
        "params": {
            "axes": "list[str] — numeric columns to use as axes",
            "group_by": "str — group column (optional)",
            "title": "str — chart title",
        },
    },
    "plot_error_bar": {
        "fn": plot_error_bar,
        "category": "visualization",
        "description": "Error bar chart showing mean ± std (or custom error column).",
        "params": {
            "x": "str — X column",
            "y": "str — mean value column",
            "error": "str — error column (optional; computes std if omitted)",
            "title": "str — chart title",
        },
    },
    # ── Advanced Visualization ────────────────────────────────────────────────
    "plot_sankey": {
        "fn": plot_sankey,
        "category": "visualization",
        "description": "Sankey flow diagram from source/target/value columns.",
        "params": {
            "source": "str — source column (default 'source')",
            "target": "str — target column (default 'target')",
            "value": "str — flow value column (default 'value')",
            "title": "str — chart title",
        },
    },
    "plot_treemap": {
        "fn": plot_treemap,
        "category": "visualization",
        "description": "Treemap with hierarchical path columns.",
        "params": {
            "path": "list[str] — hierarchy columns from root to leaf",
            "value": "str — size value column",
            "title": "str — chart title",
        },
    },
    "plot_sunburst": {
        "fn": plot_sunburst,
        "category": "visualization",
        "description": "Sunburst hierarchical chart.",
        "params": {
            "path": "list[str] — hierarchy columns from root to leaf",
            "value": "str — size value column",
            "title": "str — chart title",
        },
    },
    "plot_waterfall": {
        "fn": plot_waterfall,
        "category": "visualization",
        "description": "Waterfall chart showing incremental changes.",
        "params": {
            "x": "str — category column (default 'category')",
            "y": "str — value change column (default 'value')",
            "title": "str — chart title",
        },
    },
    "plot_funnel": {
        "fn": plot_funnel,
        "category": "visualization",
        "description": "Funnel chart for conversion / pipeline stages.",
        "params": {
            "stage": "str — stage/label column (default 'stage')",
            "value": "str — count/value column (default 'value')",
            "title": "str — chart title",
        },
    },
    "plot_gauge": {
        "fn": plot_gauge,
        "category": "visualization",
        "description": "Gauge / speedometer for a single KPI value.",
        "params": {
            "value": "float — current value (or pass column to read from data)",
            "column": "str — column to read value from (alternative to value)",
            "max_val": "float — gauge maximum (default 100)",
            "title": "str — chart title",
        },
    },
    "plot_bubble": {
        "fn": plot_bubble,
        "category": "visualization",
        "description": "Bubble chart (scatter + size encoding).",
        "params": {
            "x": "str — X column",
            "y": "str — Y column",
            "size": "str — bubble size column",
            "color": "str — color column (optional)",
            "title": "str — chart title",
        },
    },
    "plot_dual_axis": {
        "fn": plot_dual_axis,
        "category": "visualization",
        "description": "Dual Y-axis chart combining line + bar traces.",
        "params": {
            "x": "str — X column",
            "y1": "str — left-axis column (bar)",
            "y2": "str — right-axis column (line)",
            "title": "str — chart title",
        },
    },
    # ── Special Visualization ─────────────────────────────────────────────────
    "plot_candlestick": {
        "fn": plot_candlestick,
        "category": "visualization",
        "description": "OHLC candlestick chart for financial / time-series price data.",
        "params": {
            "time": "str — datetime column (auto-detects if omitted)",
            "open": "str — open price column (default 'open')",
            "high": "str — high price column (default 'high')",
            "low": "str — low price column (default 'low')",
            "close": "str — close price column (default 'close')",
            "title": "str — chart title",
        },
    },
    "plot_network": {
        "fn": plot_network,
        "category": "visualization",
        "description": "Network graph with circular node layout (no networkx required).",
        "params": {
            "source": "str — source node column (default 'source')",
            "target": "str — target node column (default 'target')",
            "nodes": "list[{id, label}] — explicit node list (optional)",
            "edges": "list[{source, target}] — explicit edge list (optional)",
            "title": "str — chart title",
        },
    },
    "plot_parallel_coords": {
        "fn": plot_parallel_coords,
        "category": "visualization",
        "description": "Parallel coordinates plot for multi-dimensional comparison.",
        "params": {
            "axes": "list[str] — numeric columns to include as axes (optional; auto-detects up to 6)",
            "color": "str — color-encode by this column (optional)",
            "title": "str — chart title",
        },
    },
    "plot_wordcloud": {
        "fn": plot_wordcloud,
        "category": "visualization",
        "description": "Simulated word cloud using Scatter text (no wordcloud library required).",
        "params": {
            "words": "dict[str, int] — {word: frequency} mapping (or use 'column')",
            "column": "str — text column to auto-generate word frequencies",
            "title": "str — chart title",
        },
    },
    "plot_summary_card": {
        "fn": plot_summary_card,
        "category": "visualization",
        "description": "Big-number KPI card with optional delta indicator.",
        "params": {
            "value": "float — KPI value (or use 'column')",
            "column": "str — column to compute mean from",
            "delta": "float — change amount for delta indicator (optional)",
            "title": "str — card title",
        },
    },

    # ── NEW STATISTICAL PROCESSING (v15.4) ──────────────────────────────────
    "ttest_one_sample": {
        "fn": ttest_one_sample,
        "category": "processing",
        "description": "One-sample t-test: test if column mean equals a target value.",
        "params": {"value_col": "str", "target_mean": "float (default 0.0)"},
    },
    "ttest_two_sample": {
        "fn": ttest_two_sample,
        "category": "processing",
        "description": "Two independent-sample t-test comparing group means.",
        "params": {"value_col": "str", "group_col": "str"},
    },
    "chi_square_test": {
        "fn": chi_square_test,
        "category": "processing",
        "description": "Chi-square goodness-of-fit (1 col) or independence test (2 cols).",
        "params": {"col_a": "str", "col_b": "str (optional for independence test)"},
    },
    "anova_oneway": {
        "fn": anova_oneway,
        "category": "processing",
        "description": "One-way ANOVA across groups.",
        "params": {"value_col": "str", "group_col": "str"},
    },
    "mann_whitney_u": {
        "fn": mann_whitney_u,
        "category": "processing",
        "description": "Mann-Whitney U non-parametric rank test for two groups.",
        "params": {"value_col": "str", "group_col": "str"},
    },
    "kruskal_wallis": {
        "fn": kruskal_wallis,
        "category": "processing",
        "description": "Kruskal-Wallis non-parametric multi-group test.",
        "params": {"value_col": "str", "group_col": "str"},
    },
    "shapiro_wilk": {
        "fn": shapiro_wilk,
        "category": "processing",
        "description": "Shapiro-Wilk normality test (n ≤ 5000).",
        "params": {"value_col": "str"},
    },
    "levene_variance": {
        "fn": levene_variance,
        "category": "processing",
        "description": "Levene's test for equality of variances across groups.",
        "params": {"value_col": "str", "group_col": "str"},
    },
    "spearman_correlation": {
        "fn": spearman_correlation,
        "category": "processing",
        "description": "Spearman rank correlation between two columns.",
        "params": {"col_x": "str", "col_y": "str"},
    },
    "partial_correlation": {
        "fn": partial_correlation,
        "category": "processing",
        "description": "Partial correlation controlling for a third variable.",
        "params": {"col_x": "str", "col_y": "str", "control_col": "str"},
    },
    "bootstrap_ci": {
        "fn": bootstrap_ci,
        "category": "processing",
        "description": "Bootstrap 95% confidence interval for the mean.",
        "params": {"value_col": "str", "n_boot": "int (default 1000)"},
    },
    "cohens_d": {
        "fn": cohens_d,
        "category": "processing",
        "description": "Cohen's d effect size between two groups.",
        "params": {"value_col": "str", "group_col": "str"},
    },
    "percentile_analysis": {
        "fn": percentile_analysis,
        "category": "processing",
        "description": "Compute P5, P25, P50, P75, P95, P99 percentiles.",
        "params": {"value_col": "str", "group_col": "str (optional)"},
    },
    "outlier_score_zscore": {
        "fn": outlier_score_zscore,
        "category": "processing",
        "description": "Z-score per row with outlier flag column added.",
        "params": {"value_col": "str", "threshold": "float (default 3.0)"},
    },
    "rank_transform": {
        "fn": rank_transform,
        "category": "processing",
        "description": "Rank-transform values for non-parametric pre-processing.",
        "params": {"value_col": "str", "method": "str (default 'average')", "group_col": "str (optional)"},
    },

    # ── NEW TIME SERIES PROCESSING (v15.4) ───────────────────────────────────
    "stationarity_test": {
        "fn": stationarity_test,
        "category": "processing",
        "description": "Augmented Dickey-Fuller test for unit root / non-stationarity.",
        "params": {"value_col": "str"},
    },
    "autocorrelation_analysis": {
        "fn": autocorrelation_analysis,
        "category": "processing",
        "description": "ACF and PACF values up to max_lags.",
        "params": {"value_col": "str", "max_lags": "int (default 20)"},
    },
    "ewma_smoothing": {
        "fn": ewma_smoothing,
        "category": "processing",
        "description": "Exponential weighted moving average smoothing.",
        "params": {"value_col": "str", "span": "float (default 10)"},
    },
    "cusum_detection": {
        "fn": cusum_detection,
        "category": "processing",
        "description": "CUSUM cumulative sum for mean shift detection.",
        "params": {"value_col": "str", "target": "float (optional)", "k": "float (default 0.5)"},
    },
    "seasonal_strength": {
        "fn": seasonal_strength,
        "category": "processing",
        "description": "Measure seasonal strength vs trend via variance decomposition.",
        "params": {"value_col": "str", "period": "int (default 7)"},
    },
    "rolling_statistics": {
        "fn": rolling_statistics,
        "category": "processing",
        "description": "Rolling mean/std/min/max with configurable stats list.",
        "params": {"value_col": "str", "window": "int", "stats": "list (default ['mean','std'])"},
    },
    "change_point_pettitt": {
        "fn": change_point_pettitt,
        "category": "processing",
        "description": "Pettitt test for detecting a single change point in a series.",
        "params": {"value_col": "str"},
    },
    "fft_dominant_freq": {
        "fn": fft_dominant_freq,
        "category": "processing",
        "description": "FFT top-N dominant frequencies with amplitudes.",
        "params": {"value_col": "str", "top_n": "int (default 5)", "sampling_rate": "float (default 1.0)"},
    },
    "lag_correlation": {
        "fn": lag_correlation,
        "category": "processing",
        "description": "Cross-correlation between two columns at multiple lags.",
        "params": {"col_x": "str", "col_y": "str", "max_lags": "int (default 10)"},
    },
    "trend_strength": {
        "fn": trend_strength,
        "category": "processing",
        "description": "Ratio of trend variance to total variance.",
        "params": {"value_col": "str", "time_col": "str (optional)"},
    },
    "run_length_encoding": {
        "fn": run_length_encoding,
        "category": "processing",
        "description": "Detect consecutive run lengths above/below threshold.",
        "params": {"value_col": "str", "threshold": "float (optional, default mean)"},
    },
    "time_between_events": {
        "fn": time_between_events,
        "category": "processing",
        "description": "Mean/std/max time between threshold crossings.",
        "params": {"value_col": "str", "threshold": "float"},
    },
    "velocity_acceleration": {
        "fn": velocity_acceleration,
        "category": "processing",
        "description": "First (velocity) and second (acceleration) derivative of a column.",
        "params": {"value_col": "str"},
    },
    "seasonality_index": {
        "fn": seasonality_index,
        "category": "processing",
        "description": "Seasonality index: ratio of each period's mean to overall mean.",
        "params": {"value_col": "str", "period_col": "str"},
    },
    "time_weighted_average": {
        "fn": time_weighted_average,
        "category": "processing",
        "description": "Time-weighted average (area under curve / time span).",
        "params": {"value_col": "str", "time_col": "str (optional)"},
    },

    # ── NEW ML PROCESSING (v15.4) ────────────────────────────────────────────
    "pca_variance": {
        "fn": pca_variance,
        "category": "processing",
        "description": "PCA explained variance ratio for feature columns.",
        "params": {"feature_cols": "list[str]", "n_components": "int (default 3)"},
    },
    "vif_analysis": {
        "fn": vif_analysis,
        "category": "processing",
        "description": "Variance Inflation Factor for multicollinearity detection.",
        "params": {"feature_cols": "list[str]"},
    },
    "feature_variance": {
        "fn": feature_variance,
        "category": "processing",
        "description": "Filter features by variance threshold.",
        "params": {"feature_cols": "list[str]", "threshold": "float (default 0.0)"},
    },
    "mutual_information": {
        "fn": mutual_information,
        "category": "processing",
        "description": "Mutual information between features and target column.",
        "params": {"feature_cols": "list[str]", "target_col": "str"},
    },
    "binning_equal_width": {
        "fn": binning_equal_width,
        "category": "processing",
        "description": "Equal-width discretization of a numeric column.",
        "params": {"value_col": "str", "n_bins": "int (default 5)"},
    },
    "binning_quantile": {
        "fn": binning_quantile,
        "category": "processing",
        "description": "Quantile-based discretization of a numeric column.",
        "params": {"value_col": "str", "n_bins": "int (default 4)"},
    },
    "target_encode": {
        "fn": target_encode,
        "category": "processing",
        "description": "Replace category with mean of target (target encoding).",
        "params": {"cat_col": "str", "target_col": "str"},
    },
    "polynomial_interaction": {
        "fn": polynomial_interaction,
        "category": "processing",
        "description": "Generate polynomial and interaction features for two columns.",
        "params": {"col_a": "str", "col_b": "str"},
    },
    "robust_scale": {
        "fn": robust_scale,
        "category": "processing",
        "description": "Median/IQR robust scaling (outlier-resistant normalization).",
        "params": {"value_col": "str"},
    },
    "winsorize": {
        "fn": winsorize,
        "category": "processing",
        "description": "Clip values at percentile bounds (Winsorization).",
        "params": {"value_col": "str", "lower_pct": "float (default 1.0)", "upper_pct": "float (default 99.0)"},
    },

    # ── NEW UTILITY / SPC PROCESSING (v15.4) ────────────────────────────────
    "capability_analysis": {
        "fn": capability_analysis,
        "category": "processing",
        "description": "Process capability: Cp, Cpk, Pp, Ppk with out-of-spec count.",
        "params": {"value_col": "str", "usl": "float", "lsl": "float"},
    },
    "western_electric_rules": {
        "fn": western_electric_rules,
        "category": "processing",
        "description": "Check all 8 Western Electric SPC rules for violations.",
        "params": {"value_col": "str", "ucl": "float (optional)", "lcl": "float (optional)", "cl": "float (optional)"},
    },
    "nelson_rules": {
        "fn": nelson_rules,
        "category": "processing",
        "description": "Nelson SPC rules 1-8 violation detection.",
        "params": {"value_col": "str", "mean": "float (optional)", "std": "float (optional)"},
    },
    "process_sigma": {
        "fn": process_sigma,
        "category": "processing",
        "description": "DPMO and Six Sigma level calculation.",
        "params": {"defects_col": "str", "opportunities_per_unit": "int (default 1)"},
    },
    "gage_repeatability": {
        "fn": gage_repeatability,
        "category": "processing",
        "description": "Measurement repeatability using range method (Gage R&R).",
        "params": {"measurement_col": "str", "part_col": "str", "operator_col": "str (optional)"},
    },
    "tolerance_interval": {
        "fn": tolerance_interval,
        "category": "processing",
        "description": "Two-sided 95%/95% tolerance interval (normal assumption).",
        "params": {"value_col": "str"},
    },
    "control_limits_calculator": {
        "fn": control_limits_calculator,
        "category": "processing",
        "description": "Compute UCL/LCL from data (3-sigma or custom method).",
        "params": {"value_col": "str", "method": "str (default '3sigma')", "n_subgroups": "int (optional)"},
    },
    "top_n_contributors": {
        "fn": top_n_contributors,
        "category": "processing",
        "description": "Rank groups by their contribution to total value.",
        "params": {"value_col": "str", "group_col": "str", "top_n": "int (default 10)"},
    },
    "within_between_variance": {
        "fn": within_between_variance,
        "category": "processing",
        "description": "Decompose total variance into within-group and between-group components.",
        "params": {"value_col": "str", "group_col": "str"},
    },
    "data_quality_score": {
        "fn": data_quality_score,
        "category": "processing",
        "description": "Score columns by completeness, uniqueness, and range checks.",
        "params": {"columns": "list[str] (optional, default all)"},
    },

    # ── NEW DISTRIBUTION VISUALIZATION (v15.4) ───────────────────────────────
    "plot_qq": {
        "fn": plot_qq,
        "category": "visualization",
        "description": "Q-Q normality plot for assessing distributional fit.",
        "params": {"value_col": "str", "title": "str"},
    },
    "plot_kde": {
        "fn": plot_kde,
        "category": "visualization",
        "description": "Kernel density estimate with rug ticks (optional grouping).",
        "params": {"value_col": "str", "group_col": "str (optional)", "title": "str"},
    },
    "plot_ecdf": {
        "fn": plot_ecdf,
        "category": "visualization",
        "description": "Empirical CDF plot with optional group comparison.",
        "params": {"value_col": "str", "group_col": "str (optional)", "title": "str"},
    },
    "plot_probability_plot": {
        "fn": plot_probability_plot,
        "category": "visualization",
        "description": "Normal probability plot (similar to Q-Q but shows probability scale).",
        "params": {"value_col": "str", "title": "str"},
    },
    "plot_residuals": {
        "fn": plot_residuals,
        "category": "visualization",
        "description": "Residuals vs fitted scatter + residual histogram.",
        "params": {"value_col": "str", "fitted_col": "str", "title": "str"},
    },
    "plot_ridge": {
        "fn": plot_ridge,
        "category": "visualization",
        "description": "Ridge/joy plot for visualizing distributions across multiple groups.",
        "params": {"value_col": "str", "group_col": "str", "title": "str"},
    },
    "plot_strip": {
        "fn": plot_strip,
        "category": "visualization",
        "description": "Strip/jitter plot with group mean line markers.",
        "params": {"value_col": "str", "group_col": "str (optional)", "title": "str"},
    },
    "plot_correlation_matrix": {
        "fn": plot_correlation_matrix,
        "category": "visualization",
        "description": "Annotated correlation heatmap for feature columns.",
        "params": {"feature_cols": "list[str]", "title": "str"},
    },
    "plot_scatter_matrix": {
        "fn": plot_scatter_matrix,
        "category": "visualization",
        "description": "Pair plot scatter matrix for multi-feature exploration.",
        "params": {"feature_cols": "list[str]", "color_col": "str (optional)", "title": "str"},
    },
    "plot_mean_ci": {
        "fn": plot_mean_ci,
        "category": "visualization",
        "description": "Mean + 95% CI comparison bar chart across groups.",
        "params": {"value_col": "str", "group_col": "str", "title": "str"},
    },
    "plot_bland_altman": {
        "fn": plot_bland_altman,
        "category": "visualization",
        "description": "Bland-Altman agreement plot for method comparison.",
        "params": {"method1_col": "str", "method2_col": "str", "title": "str"},
    },
    "plot_distribution_compare": {
        "fn": plot_distribution_compare,
        "category": "visualization",
        "description": "Overlay multiple group distributions as histograms.",
        "params": {"value_col": "str", "group_col": "str (optional)", "title": "str"},
    },
    "plot_lollipop": {
        "fn": plot_lollipop,
        "category": "visualization",
        "description": "Sorted lollipop ranking chart.",
        "params": {"value_col": "str", "label_col": "str", "title": "str"},
    },
    "plot_dumbbell": {
        "fn": plot_dumbbell,
        "category": "visualization",
        "description": "Before-after dumbbell chart for change comparison.",
        "params": {"before_col": "str", "after_col": "str", "label_col": "str", "title": "str"},
    },
    "plot_diverging_bar": {
        "fn": plot_diverging_bar,
        "category": "visualization",
        "description": "Diverging bar chart from a baseline value (positive/negative).",
        "params": {"value_col": "str", "label_col": "str", "baseline": "float (default 0)", "title": "str"},
    },

    # ── NEW ADVANCED VISUALIZATION (v15.4) ───────────────────────────────────
    "plot_xbar_r": {
        "fn": plot_xbar_r,
        "category": "visualization",
        "description": "X-bar and R control chart for subgroup data.",
        "params": {"value_col": "str", "subgroup_col": "str (optional)", "title": "str"},
    },
    "plot_imr": {
        "fn": plot_imr,
        "category": "visualization",
        "description": "Individuals (I) and Moving Range (MR) control chart.",
        "params": {"value_col": "str", "title": "str"},
    },
    "plot_cusum": {
        "fn": plot_cusum,
        "category": "visualization",
        "description": "CUSUM control chart with upper/lower decision intervals.",
        "params": {"value_col": "str", "target": "float (optional)", "k": "float (default 0.5)", "h": "float (default 5)", "title": "str"},
    },
    "plot_ewma_chart": {
        "fn": plot_ewma_chart,
        "category": "visualization",
        "description": "EWMA control chart with dynamic control limits.",
        "params": {"value_col": "str", "lambda_": "float (default 0.2)", "L": "float (default 3.0)", "title": "str"},
    },
    "plot_pareto": {
        "fn": plot_pareto,
        "category": "visualization",
        "description": "Pareto chart with bars and cumulative percentage line.",
        "params": {"value_col": "str", "label_col": "str", "title": "str"},
    },
    "plot_capability_hist": {
        "fn": plot_capability_hist,
        "category": "visualization",
        "description": "Process capability histogram with spec limits and Cp/Cpk.",
        "params": {"value_col": "str", "usl": "float", "lsl": "float", "title": "str"},
    },
    "plot_acf_pacf": {
        "fn": plot_acf_pacf,
        "category": "visualization",
        "description": "ACF and PACF side-by-side for time series model identification.",
        "params": {"value_col": "str", "max_lags": "int (default 20)", "title": "str"},
    },
    "plot_rolling_stats": {
        "fn": plot_rolling_stats,
        "category": "visualization",
        "description": "Rolling mean + std band chart.",
        "params": {"value_col": "str", "window": "int", "title": "str"},
    },
    "plot_seasonal_decompose": {
        "fn": plot_seasonal_decompose,
        "category": "visualization",
        "description": "Trend/seasonal/residual decomposition 4-panel chart.",
        "params": {"value_col": "str", "period": "int (default 7)", "title": "str"},
    },
    "plot_forecast_band": {
        "fn": plot_forecast_band,
        "category": "visualization",
        "description": "Line chart with upper/lower forecast confidence band.",
        "params": {"value_col": "str", "upper_col": "str", "lower_col": "str", "title": "str"},
    },
    "plot_event_markers": {
        "fn": plot_event_markers,
        "category": "visualization",
        "description": "Time series with vertical event marker lines.",
        "params": {"value_col": "str", "time_col": "str", "event_col": "str", "title": "str"},
    },
    "plot_multi_vari": {
        "fn": plot_multi_vari,
        "category": "visualization",
        "description": "Multi-vari chart showing within/between variation (Gage R&R style).",
        "params": {"value_col": "str", "part_col": "str", "operator_col": "str (optional)", "title": "str"},
    },
    "plot_run_chart": {
        "fn": plot_run_chart,
        "category": "visualization",
        "description": "Run chart with mean line and run count annotations.",
        "params": {"value_col": "str", "title": "str"},
    },
    "plot_hexbin": {
        "fn": plot_hexbin,
        "category": "visualization",
        "description": "Hexagonal 2D density histogram (hexbin chart).",
        "params": {"col_x": "str", "col_y": "str", "title": "str"},
    },
    "plot_contour": {
        "fn": plot_contour,
        "category": "visualization",
        "description": "Filled contour density chart with scatter overlay.",
        "params": {"col_x": "str", "col_y": "str", "title": "str"},
    },
    "plot_3d_scatter": {
        "fn": plot_3d_scatter,
        "category": "visualization",
        "description": "3D scatter plot with optional color encoding.",
        "params": {"col_x": "str", "col_y": "str", "col_z": "str", "color_col": "str (optional)", "title": "str"},
    },
    "plot_marginal_scatter": {
        "fn": plot_marginal_scatter,
        "category": "visualization",
        "description": "Scatter with marginal histograms on X and Y axes.",
        "params": {"col_x": "str", "col_y": "str", "color_col": "str (optional)", "title": "str"},
    },
    "plot_slope_chart": {
        "fn": plot_slope_chart,
        "category": "visualization",
        "description": "Slope/bump chart for before-after rank changes over time.",
        "params": {"value_col": "str", "time_col": "str", "group_col": "str", "title": "str"},
    },
    "plot_benchmark": {
        "fn": plot_benchmark,
        "category": "visualization",
        "description": "Actual vs benchmark/target comparison bar+line chart.",
        "params": {"value_col": "str", "benchmark_col": "str", "label_col": "str", "title": "str"},
    },
    "plot_outlier_flags": {
        "fn": plot_outlier_flags,
        "category": "visualization",
        "description": "Line chart with outlier points highlighted in red.",
        "params": {"value_col": "str", "time_col": "str (optional)", "threshold": "float (default 3.0)", "title": "str"},
    },

    # ── NEW SPECIAL / EDA PROFILING VISUALIZATION (v15.4) ───────────────────
    "plot_missing_heatmap": {
        "fn": plot_missing_heatmap,
        "category": "visualization",
        "description": "Missing value matrix heatmap showing null patterns across columns.",
        "params": {"columns": "list[str] (optional)", "title": "str"},
    },
    "plot_data_profile": {
        "fn": plot_data_profile,
        "category": "visualization",
        "description": "Multi-stat card grid: histogram or bar chart per column.",
        "params": {"columns": "list[str] (optional, max 12)", "title": "str"},
    },
    "plot_boxplot_with_stats": {
        "fn": plot_boxplot_with_stats,
        "category": "visualization",
        "description": "Box + jitter + mean diamond + outlier labels.",
        "params": {"value_col": "str", "group_col": "str (optional)", "title": "str"},
    },
    "plot_correlation_network": {
        "fn": plot_correlation_network,
        "category": "visualization",
        "description": "Network graph of high correlations between features.",
        "params": {"feature_cols": "list[str]", "threshold": "float (default 0.5)", "title": "str"},
    },
    "plot_value_counts": {
        "fn": plot_value_counts,
        "category": "visualization",
        "description": "Horizontal bar chart of top-N value counts for a categorical column.",
        "params": {"cat_col": "str", "top_n": "int (default 15)", "title": "str"},
    },
    "plot_time_heatmap": {
        "fn": plot_time_heatmap,
        "category": "visualization",
        "description": "Calendar/time-of-day heatmap (day-of-week × hour).",
        "params": {"value_col": "str", "time_col": "str", "title": "str"},
    },
    "plot_rank_change": {
        "fn": plot_rank_change,
        "category": "visualization",
        "description": "Rank change over time for multiple groups (bump chart).",
        "params": {"value_col": "str", "time_col": "str", "group_col": "str", "title": "str"},
    },
    "plot_stacked_pct": {
        "fn": plot_stacked_pct,
        "category": "visualization",
        "description": "100% stacked bar chart.",
        "params": {"value_col": "str", "group_col": "str", "time_col": "str", "title": "str"},
    },
    "plot_bullet_chart": {
        "fn": plot_bullet_chart,
        "category": "visualization",
        "description": "Bullet chart: actual vs target vs range.",
        "params": {"value_col": "str", "target_col": "str (optional)", "label_col": "str", "title": "str"},
    },
    "plot_control_plan": {
        "fn": plot_control_plan,
        "category": "visualization",
        "description": "Control chart matrix for multiple metrics (subplots).",
        "params": {"value_cols": "list[str]", "ucl_cols": "list[str] (optional)", "title": "str"},
    },
    "plot_contribution_waterfall": {
        "fn": plot_contribution_waterfall,
        "category": "visualization",
        "description": "Waterfall chart showing each group's contribution to total.",
        "params": {"value_col": "str", "group_col": "str", "title": "str"},
    },
    "plot_timeline": {
        "fn": plot_timeline,
        "category": "visualization",
        "description": "Horizontal timeline with events and optional end dates.",
        "params": {"event_col": "str", "start_col": "str", "end_col": "str (optional)", "title": "str"},
    },
    "plot_funnel_conversion": {
        "fn": plot_funnel_conversion,
        "category": "visualization",
        "description": "Funnel conversion chart with % drop labels.",
        "params": {"stage_col": "str", "count_col": "str", "title": "str"},
    },
    "plot_spc_dashboard": {
        "fn": plot_spc_dashboard,
        "category": "visualization",
        "description": "4-panel SPC dashboard: run chart / histogram / box / stats table.",
        "params": {"value_col": "str", "ucl": "float (optional)", "lcl": "float (optional)", "title": "str"},
    },
    "plot_eda_overview": {
        "fn": plot_eda_overview,
        "category": "visualization",
        "description": "Full EDA overview: distribution + box + Q-Q + stats in one figure.",
        "params": {"value_col": "str", "title": "str"},
    },
}


def call_tool(tool_name: str, data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Dispatch a generic tool call by name.

    Args:
        tool_name: Key in TOOL_REGISTRY.
        data: List of row dicts passed to the tool.
        **params: Tool-specific keyword arguments.

    Returns:
        Standard {status, summary, payload} dict from ToolResult.
    """
    entry = TOOL_REGISTRY.get(tool_name)
    if not entry:
        from app.generic_tools._base import ToolResult
        return ToolResult.err(f"Unknown tool '{tool_name}'. Available: {', '.join(TOOL_REGISTRY)}")
    return entry["fn"](data, **params)


__all__ = ["TOOL_REGISTRY", "call_tool"]
