"""v30.17f — guard against regression of chart-block produces.covers.

Root cause of the p5 chart-phase build failure (2026-05-17):
  All 19 chart blocks in `seed.py` had no `produces.covers` field. The
  verifier's `_resolve_covers(spec, kind='output')` then fell back to
  `_infer_covers_from_block_spec()`, which only returns `['chart']` for
  blocks with `category == 'output'` AND output_schema containing a
  chart-typed port. Several chart blocks (line_chart, xbar_r, etc.) had
  `category='chart'` (not 'output') and thus inferred to `[]`, so the
  verifier rejected even a correctly-built chart node with
  'phase_verifier_no_match: covers mismatch'.

Fix: declare `produces.covers = ['chart']` explicitly on every chart
block. This test locks that in so future block edits can't reintroduce
the regression.
"""
from __future__ import annotations

import pytest

from python_ai_sidecar.pipeline_builder.seed import _blocks
from python_ai_sidecar.agent_builder.graph_build.nodes.phase_verifier import (
    _resolve_covers,
)


CHART_BLOCK_NAMES = frozenset({
    "block_chart",
    "block_line_chart",
    "block_bar_chart",
    "block_scatter_chart",
    "block_box_plot",
    "block_splom",
    "block_histogram_chart",
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
})


@pytest.fixture(scope="module")
def chart_blocks():
    by_name = {b["name"]: b for b in _blocks() if b["name"] in CHART_BLOCK_NAMES}
    missing = CHART_BLOCK_NAMES - set(by_name)
    assert not missing, f"chart blocks missing from seed: {sorted(missing)}"
    return by_name


@pytest.mark.parametrize("block_name", sorted(CHART_BLOCK_NAMES))
def test_chart_block_declares_covers_chart(chart_blocks, block_name):
    spec = chart_blocks[block_name]
    produces = spec.get("produces") or {}
    covers = produces.get("covers") or produces.get("covers_output") or []
    assert "chart" in covers, (
        f"{block_name}: produces.covers must include 'chart' "
        f"(got {covers!r}). Without this, the verifier rejects chart-phase "
        f"builds even when this block is the correct choice."
    )


@pytest.mark.parametrize("block_name", sorted(CHART_BLOCK_NAMES))
def test_resolve_covers_output_returns_chart(chart_blocks, block_name):
    """End-to-end: simulate what the verifier sees."""
    spec = chart_blocks[block_name]
    covers = _resolve_covers(spec, kind="output")
    assert "chart" in covers, (
        f"{block_name}: _resolve_covers(kind='output') returned {covers!r}, "
        f"verifier would reject this block for a chart phase."
    )
