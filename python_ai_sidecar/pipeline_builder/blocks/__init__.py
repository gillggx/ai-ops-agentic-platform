"""Built-in block executors for Phase 1."""

from python_ai_sidecar.pipeline_builder.blocks.base import BlockExecutor, BlockExecutionError
from python_ai_sidecar.pipeline_builder.blocks.alert import AlertBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.any_trigger import AnyTriggerBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.apc_long_form import ApcLongFormBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.apc_panel import ApcPanelBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.bar_chart import BarChartBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.box_plot import BoxPlotBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.chart import ChartBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.compute import ComputeBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.consecutive_rule import ConsecutiveRuleBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.correlation import CorrelationBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.count_rows import CountRowsBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.data_view import DataViewBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.cpk import CpkBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.defect_stack import DefectStackBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.delta import DeltaBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.ewma import EwmaBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.ewma_cusum import EwmaCusumBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.filter import FilterBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.find import FindBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.groupby_agg import GroupByAggBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.heatmap_dendro import HeatmapDendroBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.histogram import HistogramBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.histogram_chart import HistogramChartBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.hypothesis_test import HypothesisTestBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.imr import IMRBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.line_chart import LineChartBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.join import JoinBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.linear_regression import LinearRegressionBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.list_objects import ListObjectsBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.mcp_call import McpCallBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.mcp_foreach import McpForeachBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.parallel_coords import ParallelCoordsBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.pareto import ParetoBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.pluck import PluckBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.probability_plot import ProbabilityPlotBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.process_history import ProcessHistoryBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.rolling_window import RollingWindowBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.scatter_chart import ScatterChartBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.select import SelectBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.shift_lag import ShiftLagBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.sort import SortBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.spatial_pareto import SpatialParetoBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.spc_long_form import SpcLongFormBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.spc_panel import SpcPanelBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.splom import SplomBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.step_check import StepCheckBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.threshold import ThresholdBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.trend_wafer_maps import TrendWaferMapsBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.union import UnionBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.unnest import UnnestBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.unpivot import UnpivotBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.variability_gauge import VariabilityGaugeBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.wafer_heatmap import WaferHeatmapBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.weco_rules import WecoRulesBlockExecutor
from python_ai_sidecar.pipeline_builder.blocks.xbar_r import XbarRBlockExecutor


BUILTIN_EXECUTORS: dict[str, type[BlockExecutor]] = {
    "block_process_history": ProcessHistoryBlockExecutor,
    "block_filter": FilterBlockExecutor,
    "block_find": FindBlockExecutor,
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
    "block_list_objects": ListObjectsBlockExecutor,
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
    # PR-H + PR-I — SPC + Diagnostic + Wafer chart blocks (Stage 2 parts 2/3 + 3/3)
    "block_xbar_r": XbarRBlockExecutor,
    "block_imr": IMRBlockExecutor,
    "block_ewma_cusum": EwmaCusumBlockExecutor,
    "block_pareto": ParetoBlockExecutor,
    "block_variability_gauge": VariabilityGaugeBlockExecutor,
    "block_parallel_coords": ParallelCoordsBlockExecutor,
    "block_probability_plot": ProbabilityPlotBlockExecutor,
    "block_heatmap_dendro": HeatmapDendroBlockExecutor,
    "block_wafer_heatmap": WaferHeatmapBlockExecutor,
    "block_defect_stack": DefectStackBlockExecutor,
    "block_spatial_pareto": SpatialParetoBlockExecutor,
    "block_trend_wafer_maps": TrendWaferMapsBlockExecutor,
    # Phase 11 — Skill terminal block (skill-step pipelines must end here)
    "block_step_check": StepCheckBlockExecutor,
    # 2026-05-13 (Phase 1 object-native) — path navigation blocks
    "block_pluck": PluckBlockExecutor,
    "block_unnest": UnnestBlockExecutor,
    "block_select": SelectBlockExecutor,
    # 2026-05-14 (v18) — domain-composite panel blocks
    "block_spc_panel": SpcPanelBlockExecutor,
    "block_apc_panel": ApcPanelBlockExecutor,
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
    "DefectStackBlockExecutor",
    "DeltaBlockExecutor",
    "EwmaBlockExecutor",
    "EwmaCusumBlockExecutor",
    "StepCheckBlockExecutor",
    "FilterBlockExecutor",
    "FindBlockExecutor",
    "GroupByAggBlockExecutor",
    "HeatmapDendroBlockExecutor",
    "HistogramBlockExecutor",
    "HistogramChartBlockExecutor",
    "HypothesisTestBlockExecutor",
    "IMRBlockExecutor",
    "JoinBlockExecutor",
    "LinearRegressionBlockExecutor",
    "LineChartBlockExecutor",
    "ListObjectsBlockExecutor",
    "McpCallBlockExecutor",
    "McpForeachBlockExecutor",
    "ParallelCoordsBlockExecutor",
    "ParetoBlockExecutor",
    "ProbabilityPlotBlockExecutor",
    "ProcessHistoryBlockExecutor",
    "RollingWindowBlockExecutor",
    "ScatterChartBlockExecutor",
    "ShiftLagBlockExecutor",
    "SortBlockExecutor",
    "SpatialParetoBlockExecutor",
    "SpcLongFormBlockExecutor",
    "SplomBlockExecutor",
    "ThresholdBlockExecutor",
    "TrendWaferMapsBlockExecutor",
    "PluckBlockExecutor",
    "SelectBlockExecutor",
    "UnionBlockExecutor",
    "UnnestBlockExecutor",
    "UnpivotBlockExecutor",
    "VariabilityGaugeBlockExecutor",
    "WaferHeatmapBlockExecutor",
    "WecoRulesBlockExecutor",
    "XbarRBlockExecutor",
]
