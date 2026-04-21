"""Built-in block executors for Phase 1."""

from app.services.pipeline_builder.blocks.base import BlockExecutor, BlockExecutionError
from app.services.pipeline_builder.blocks.alert import AlertBlockExecutor
from app.services.pipeline_builder.blocks.any_trigger import AnyTriggerBlockExecutor
from app.services.pipeline_builder.blocks.chart import ChartBlockExecutor
from app.services.pipeline_builder.blocks.compute import ComputeBlockExecutor
from app.services.pipeline_builder.blocks.consecutive_rule import ConsecutiveRuleBlockExecutor
from app.services.pipeline_builder.blocks.correlation import CorrelationBlockExecutor
from app.services.pipeline_builder.blocks.count_rows import CountRowsBlockExecutor
from app.services.pipeline_builder.blocks.data_view import DataViewBlockExecutor
from app.services.pipeline_builder.blocks.cpk import CpkBlockExecutor
from app.services.pipeline_builder.blocks.delta import DeltaBlockExecutor
from app.services.pipeline_builder.blocks.ewma import EwmaBlockExecutor
from app.services.pipeline_builder.blocks.filter import FilterBlockExecutor
from app.services.pipeline_builder.blocks.groupby_agg import GroupByAggBlockExecutor
from app.services.pipeline_builder.blocks.histogram import HistogramBlockExecutor
from app.services.pipeline_builder.blocks.hypothesis_test import HypothesisTestBlockExecutor
from app.services.pipeline_builder.blocks.join import JoinBlockExecutor
from app.services.pipeline_builder.blocks.linear_regression import LinearRegressionBlockExecutor
from app.services.pipeline_builder.blocks.mcp_call import McpCallBlockExecutor
from app.services.pipeline_builder.blocks.mcp_foreach import McpForeachBlockExecutor
from app.services.pipeline_builder.blocks.process_history import ProcessHistoryBlockExecutor
from app.services.pipeline_builder.blocks.rolling_window import RollingWindowBlockExecutor
from app.services.pipeline_builder.blocks.shift_lag import ShiftLagBlockExecutor
from app.services.pipeline_builder.blocks.sort import SortBlockExecutor
from app.services.pipeline_builder.blocks.threshold import ThresholdBlockExecutor
from app.services.pipeline_builder.blocks.union import UnionBlockExecutor
from app.services.pipeline_builder.blocks.unpivot import UnpivotBlockExecutor
from app.services.pipeline_builder.blocks.weco_rules import WecoRulesBlockExecutor


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
}

__all__ = [
    "BlockExecutor",
    "BlockExecutionError",
    "BUILTIN_EXECUTORS",
    "AlertBlockExecutor",
    "AnyTriggerBlockExecutor",
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
    "HypothesisTestBlockExecutor",
    "JoinBlockExecutor",
    "LinearRegressionBlockExecutor",
    "McpCallBlockExecutor",
    "McpForeachBlockExecutor",
    "ProcessHistoryBlockExecutor",
    "RollingWindowBlockExecutor",
    "ShiftLagBlockExecutor",
    "SortBlockExecutor",
    "ThresholdBlockExecutor",
    "UnionBlockExecutor",
    "UnpivotBlockExecutor",
    "WecoRulesBlockExecutor",
]
