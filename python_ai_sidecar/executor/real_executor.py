"""Sidecar native PipelineExecutor wrapper.

Phase 8-B entrypoint: uses the ported ``pipeline_builder.executor.PipelineExecutor``
with a seed-loaded block catalog instead of a DB-backed registry. Call
``get_real_executor()`` — the first call loads the registry and caches it.

The sidecar's router decides whether to delegate to this real executor or
fall back to ``:8001`` based on :data:`SIDECAR_NATIVE_BLOCKS` — only
pure-in-memory blocks (no DB/internal-MCP lookups) are in the whitelist
until those few remaining data-source blocks are rewired to call Java's
``/internal/mcp/*`` endpoints.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from python_ai_sidecar.pipeline_builder.executor import PipelineExecutor
from python_ai_sidecar.pipeline_builder.pipeline_schema import PipelineJSON
from python_ai_sidecar.pipeline_builder.seedless_registry import SeedlessBlockRegistry

log = logging.getLogger("python_ai_sidecar.executor.real")


# Blocks that are 100% pandas + httpx (no DB session, no internal repos).
# Verified safe to run inside the sidecar today.
#
# Excluded: block_mcp_call, block_mcp_foreach — both look up mcp_definitions
# via an SQLAlchemy session which the sidecar doesn't have. They'll fall back
# to :8001 until ported to call Java's /internal/mcp/* endpoints.
SIDECAR_NATIVE_BLOCKS: frozenset[str] = frozenset({
    "block_process_history",   # httpx → OntologySim only
    "block_filter",
    "block_threshold",
    "block_count_rows",
    "block_consecutive_rule",
    "block_delta",
    "block_join",
    "block_groupby_agg",
    "block_chart",
    "block_shift_lag",
    "block_rolling_window",
    "block_weco_rules",
    "block_unpivot",
    "block_spc_long_form",
    "block_apc_long_form",
    "block_union",
    "block_cpk",
    "block_any_trigger",
    "block_correlation",
    "block_hypothesis_test",
    "block_ewma",
    "block_linear_regression",
    "block_histogram",
    "block_sort",
    "block_alert",
    "block_data_view",
    "block_compute",
    # PR-G — primitives + EDA chart blocks (Stage 2 part 1/3)
    "block_line_chart",
    "block_bar_chart",
    "block_scatter_chart",
    "block_box_plot",
    "block_splom",
    "block_histogram_chart",
    # PR-H + PR-I — SPC + Diagnostic + Wafer chart blocks (Stage 2 parts 2/3 + 3/3)
    "block_xbar_r",
    "block_imr",
    "block_ewma_cusum",
    "block_pareto",
    "block_variability_gauge",
    "block_parallel_coords",
    "block_probability_plot",
    "block_heatmap_dendro",
    "block_wafer_heatmap",
    "block_defect_stack",
    "block_spatial_pareto",
    "block_trend_wafer_maps",
    # Phase 8-B final: rewired to call Java /internal/mcp-definitions
    # (instead of opening a DB session) in commit below.
    "block_mcp_call",
    "block_mcp_foreach",
})


_registry: SeedlessBlockRegistry | None = None
_executor: PipelineExecutor | None = None


def get_real_executor() -> PipelineExecutor:
    """Lazily construct + return the cached executor. First call loads the
    seedless catalog (~1ms)."""
    global _registry, _executor
    if _executor is None:
        _registry = SeedlessBlockRegistry()
        _registry.load()
        _executor = PipelineExecutor(_registry)
        log.info(
            "real executor ready — %d native blocks whitelisted",
            len(SIDECAR_NATIVE_BLOCKS),
        )
    return _executor


def all_blocks_native(pipeline_json: dict | None) -> bool:
    """Return True iff every node in the pipeline is in the sidecar whitelist.
    Unknown block names (not in catalog) are treated as non-native.
    """
    if not isinstance(pipeline_json, dict):
        return False
    nodes = pipeline_json.get("nodes") or []
    for n in nodes:
        block_id = n.get("block_id") or n.get("block") or n.get("type")
        if block_id not in SIDECAR_NATIVE_BLOCKS:
            return False
    return True


def _parse_pipeline(pipeline_json: dict) -> PipelineJSON | None:
    """Validate the raw dict against the pydantic model. Returns None on
    parse failure so callers can fall back instead of 500-ing."""
    try:
        return PipelineJSON.model_validate(pipeline_json)
    except Exception as e:  # noqa: BLE001
        log.warning("pipeline_json failed pydantic validation: %s", e)
        return None


async def execute_native(
    pipeline_json: dict,
    inputs: dict[str, Any] | None = None,
    *,
    run_id: int | None = None,
) -> dict[str, Any]:
    """Execute via the ported executor. Returns the executor's full result
    dict (status / node_results / result_summary / duration_ms / ...).

    Caller should have already gated on `all_blocks_native(pipeline_json)`.
    If the pipeline fails pydantic parsing, we raise — caller fallback.
    """
    pipeline = _parse_pipeline(pipeline_json)
    if pipeline is None:
        raise ValueError("pipeline_json failed schema validation")
    executor = get_real_executor()
    result = await executor.execute(pipeline, inputs=inputs, run_id=run_id)
    return result


def _json_safe(value: Any) -> Any:
    """Recursive fallback coercion for execution-log persistence."""
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)[:500]
