"""Built-in block executors for Phase 1."""

from python_ai_sidecar.pipeline_builder.blocks.base import BlockExecutor, BlockExecutionError
from python_ai_sidecar.pipeline_builder.blocks.alert import AlertBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.any_trigger import AnyTriggerBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.apc_long_form import ApcLongFormBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.bar_chart import BarChartBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.box_plot import BoxPlotBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.chart import ChartBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.compute import ComputeBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.consecutive_rule import ConsecutiveRuleBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.correlation import CorrelationBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.count_rows import CountRowsBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.data_view import DataViewBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.cpk import CpkBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.delta import DeltaBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.ewma import EwmaBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.filter import FilterBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.groupby_agg import GroupByAggBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.histogram import HistogramBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.histogram_chart import HistogramChartBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.hypothesis_test import HypothesisTestBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.line_chart import LineChartBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.join import JoinBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.linear_regression import LinearRegressionBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.mcp_call import McpCallBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.mcp_foreach import McpForeachBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.process_history import ProcessHistoryBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.rolling_window import RollingWindowBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.scatter_chart import ScatterChartBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.shift_lag import ShiftLagBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.sort import SortBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.spc_long_form import SpcLongFormBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.splom import SplomBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.threshold import ThresholdBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.union import UnionBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.unpivot import UnpivotBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.weco_rules import WecoRulesBlockExecutor


BUILTIN_EXECUTORS: dict[str, type[BlockExecutor]] = {
    "block_process_history": ProcessHistoryBlockExecutor,
    "block_filter": FilterBlockExecutor,
    "block_join": JoinBlockExecutor,
    "block_groupby_agg": GroupByAggBlockExecutor,
    "block_shift_lag": ShiftLagBlockExecutor,
    "block_rolling_window": RollingWindowBlockExecutor,
    "block_threshold": ThresholdBlockExecutor,
    "block_consecutive_rule": ConsecutiveRuleBlockExecutor,
    "block_delta": DeltaBlockExecutor,
    "block_weco_rules": WecoRulesBlockExecutor,
    "block_linear_regression": LinearRegressionBlockExecutor,
    "block_histogram": HistogramBlockExecutor,
    "block_sort": SortBlockExecutor,
    "block_unpivot": UnpivotBlockExecutor,
    "block_spc_long_form": SpcLongFormBlockExecutor,
    "block_apc_long_form": ApcLongFormBlockExecutor,
    "block_union": UnionBlockExecutor,
    "block_cpk": CpkBlockExecutor,
    "block_any_trigger": AnyTriggerBlockExecutor,
    "block_correlation": CorrelationBlockExecutor,
    "block_hypothesis_test": HypothesisTestBlockExecutor,
    "block_ewma": EwmaBlockExecutor,
    "block_mcp_call": McpCallBlockExecutor,
    "block_mcp_foreach": McpForeachBlockExecutor,
    "block_count_rows": CountRowsBlockExecutor,
    "block_chart": ChartBlockExecutor,
    "block_alert": AlertBlockExecutor,
    "block_data_view": DataViewBlockExecutor,
    "block_compute": ComputeBlockExecutor,
    # PR-G — primitives + EDA chart blocks (Stage 2 part 1/3)
    "block_line_chart": LineChartBlockExecutor,
    "block_bar_chart": BarChartBlockExecutor,
    "block_scatter_chart": ScatterChartBlockExecutor,
    "block_box_plot": BoxPlotBlockExecutor,
    "block_splom": SplomBlockExecutor,
    "block_histogram_chart": HistogramChartBlockExecutor,
}

__all__ = [
    "BlockExecutor",
    "BlockExecutionError",
    "BUILTIN_EXECUTORS",
    "AlertBlockExecutor",
    "AnyTriggerBlockExecutor",
    "ApcLongFormBlockExecutor",
    "BarChartBlockExecutor",
    "BoxPlotBlockExecutor",
    "ChartBlockExecutor",
    "ComputeBlockExecutor",
    "ConsecutiveRuleBlockExecutor",
    "CorrelationBlockExecutor",
    "CountRowsBlockExecutor",
    "DataViewBlockExecutor",
    "CpkBlockExecutor",
    "DeltaBlockExecutor",
    "EwmaBlockExecutor",
    "FilterBlockExecutor",
    "GroupByAggBlockExecutor",
    "HistogramBlockExecutor",
    "HistogramChartBlockExecutor",
    "HypothesisTestBlockExecutor",
    "JoinBlockExecutor",
    "LinearRegressionBlockExecutor",
    "LineChartBlockExecutor",
    "McpCallBlockExecutor",
    "McpForeachBlockExecutor",
    "ProcessHistoryBlockExecutor",
    "RollingWindowBlockExecutor",
    "ScatterChartBlockExecutor",
    "ShiftLagBlockExecutor",
    "SortBlockExecutor",
    "SpcLongFormBlockExecutor",
    "SplomBlockExecutor",
    "ThresholdBlockExecutor",
    "UnionBlockExecutor",
    "UnpivotBlockExecutor",
    "WecoRulesBlockExecutor",
]
