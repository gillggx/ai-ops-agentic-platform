"""Generic Tools Registry (v15.3) — 50 pure analytic + visualization functions.

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
from app.generic_tools.processing.ml import cluster_data, vector_similarity
from app.generic_tools.processing.utility import (
    cross_reference,
    diff_engine,
    logic_evaluator,
    missing_value_impute,
    regex_extractor,
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
)
from app.generic_tools.visualization.special import (
    plot_candlestick,
    plot_network,
    plot_parallel_coords,
    plot_summary_card,
    plot_wordcloud,
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
