"""Unit tests for presentation-contract look-ahead (2026-06-17).

Covers the pure pieces of resolve_presentation_contracts_node + the async node
with LLM/markdown mocked, and the observation injection gate.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from python_ai_sidecar.agent_builder.graph_build.nodes import presentation_contract as pc


_PHASES = [
    {"id": "p1", "goal": "取得 EQP-01 過去 7 天的歷史資料", "expected": "raw_data"},
    {"id": "p2", "goal": "整理出 xbar 的時序量測", "expected": "transform"},
    {"id": "p3", "goal": "繪製 xbar 趨勢圖", "expected": "chart"},
]

_DOC = """---
name: block_line_chart
description: line chart
---

# block_line_chart

## When to invoke
- trend over time

## Inputs

### port: data
- type: dataframe
- 必要欄位: x (time col), y (numeric col)
- 期望狀態: long-format, one row per (time, series)

## Outputs
chart_spec
"""


# ── pure helpers ────────────────────────────────────────────────────────────


def test_present_phase_indices():
    assert pc._present_phase_indices(_PHASES) == [2]  # only p3 (chart)


def test_present_phase_indices_multi_kinds():
    phases = [
        {"id": "p1", "expected": "raw_data"},
        {"id": "p2", "expected": "verdict"},
        {"id": "p3", "expected": "scalar"},
    ]
    assert pc._present_phase_indices(phases) == [1, 2]


def test_contract_target_includes_upstream_transform_and_self():
    # p3 (chart) at idx 2 → nearest upstream transform p2 + p3 itself
    assert pc._contract_target_phase_ids(_PHASES, 2) == ["p2", "p3"]


def test_contract_target_no_transform_falls_back_to_self():
    phases = [
        {"id": "p1", "expected": "raw_data"},
        {"id": "p2", "expected": "chart"},  # chart directly off raw
    ]
    assert pc._contract_target_phase_ids(phases, 1) == ["p2"]


def test_extract_inputs_section():
    out = pc._extract_inputs_section(_DOC)
    assert out.startswith("## Inputs")
    assert "必要欄位: x (time col), y (numeric col)" in out
    assert "long-format" in out
    assert "## Outputs" not in out  # stops at next header


def test_extract_inputs_section_absent():
    assert pc._extract_inputs_section("# block\n## Outputs\nx") == ""


def test_render_contract_shape():
    md = pc._render_contract("block_line_chart", "## Inputs\n必要欄位: x, y", "繪製趨勢")
    assert "DOWNSTREAM CONTRACT" in md
    assert "block_line_chart" in md
    assert "必要欄位: x, y" in md
    assert "hint" in md  # explicitly soft, not a hard constraint


# ── async node (LLM + markdown mocked) ──────────────────────────────────────


@pytest.mark.asyncio
async def test_node_noop_when_flag_off():
    with patch.object(pc, "is_presentation_lookahead_enabled", return_value=False):
        out = await pc.resolve_presentation_contracts_node({"v30_phases": _PHASES})
    assert out == {}


@pytest.mark.asyncio
async def test_node_stamps_contract_on_upstream_and_present():
    with patch.object(pc, "is_presentation_lookahead_enabled", return_value=True), \
         patch.object(pc, "_candidate_present_blocks",
                      return_value=[("block_line_chart", "trend"), ("block_bar_chart", "bars")]), \
         patch.object(pc, "_resolve_present_block",
                      new=AsyncMock(return_value="block_line_chart")), \
         patch("python_ai_sidecar.agent_builder.tools._fetch_block_doc_markdown",
               new=AsyncMock(return_value=_DOC)):
        out = await pc.resolve_presentation_contracts_node({"v30_phases": _PHASES})
    contracts = out["v30_phase_contracts"]
    # stamped on the upstream transform (p2) AND the present phase (p3)
    assert set(contracts.keys()) == {"p2", "p3"}
    assert "block_line_chart" in contracts["p2"]
    assert "必要欄位: x (time col), y (numeric col)" in contracts["p2"]


@pytest.mark.asyncio
async def test_resolve_single_candidate_skips_llm():
    # one candidate → no LLM call, returns it directly
    out = await pc._resolve_present_block("goal", [("block_data_view", "table")])
    assert out == "block_data_view"
