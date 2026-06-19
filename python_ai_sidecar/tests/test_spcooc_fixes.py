"""Unit tests for the two spc-ooc follow-up fixes (2026-06-18):
  - goal-aware MATCHING BLOCKS re-ranking (Fix B)
  - isolated-orphan detection for orphan_resolve (Fix A)
"""
from __future__ import annotations

import pytest

from python_ai_sidecar.feature_flags import set_request_overrides, reset_request_overrides
from python_ai_sidecar.agent_builder.graph_build.nodes.agentic_phase_loop import (
    _char_bigrams, _goal_relevance, _build_matching_blocks_section,
)
from python_ai_sidecar.agent_builder.graph_build.nodes.orphan_resolve import (
    _isolated_nodes, maybe_resolve_orphans,
)


# ── Fix B: goal-aware matching ──────────────────────────────────────────────


def test_char_bigrams():
    assert _char_bigrams("機台清單") == {"機台", "台清", "清單"}
    assert _char_bigrams(" a b ") == {"ab"}  # whitespace stripped


def test_goal_relevance_ranks_list_over_history():
    goal_bg = _char_bigrams("取得全廠機台清單")
    list_score = _goal_relevance(goal_bg, "block_list_objects", "列出 ontology 物件清單（機台 / 批次）")
    hist_score = _goal_relevance(goal_bg, "block_process_history", "拉指定條件的 process events")
    assert list_score > hist_score  # list_objects more relevant to "list machines" goal


def test_matching_section_marks_best_fit():
    tok = set_request_overrides({"goal_aware_matching": True})
    try:
        out = _build_matching_blocks_section("raw_data", "取得全廠機台清單")
    finally:
        reset_request_overrides(tok)
    # list_objects should be tagged best fit and appear before process_history
    assert "block_list_objects" in out and "[best fit for this phase]" in out
    li = out.find("block_list_objects")
    ph = out.find("block_process_history")
    assert li != -1 and (ph == -1 or li < ph)  # list_objects ranked above history
    # the best-fit tag is on the list_objects line
    bf_line = [l for l in out.splitlines() if "block_list_objects" in l][0]
    assert "best fit" in bf_line


def test_matching_section_flag_off_is_kind_sorted():
    tok = set_request_overrides({"goal_aware_matching": False})
    try:
        out = _build_matching_blocks_section("raw_data", "取得全廠機台清單")
    finally:
        reset_request_overrides(tok)
    assert "[best fit" not in out  # no goal ranking when flag off


# ── Fix A: isolated-orphan detection ────────────────────────────────────────


def test_isolated_detects_stray_node():
    pipe = {
        "nodes": [{"id": "n1"}, {"id": "n2"}, {"id": "n3"}],
        "edges": [{"from": {"node": "n1"}, "to": {"node": "n2"}}],
    }
    iso = _isolated_nodes(pipe)
    assert [n["id"] for n in iso] == ["n3"]  # n3 has no in+out; n1 (source) & n2 (terminal) ok


def test_isolated_none_when_all_connected():
    pipe = {
        "nodes": [{"id": "n1"}, {"id": "n2"}],
        "edges": [{"from": {"node": "n1"}, "to": {"node": "n2"}}],
    }
    assert _isolated_nodes(pipe) == []


def test_isolated_ignores_single_node_pipeline():
    # 1 node = whole pipeline (source=terminal), not an orphan
    assert _isolated_nodes({"nodes": [{"id": "n1"}], "edges": []}) == []


@pytest.mark.asyncio
async def test_maybe_resolve_orphans_noop_when_flag_off():
    pipe = {"nodes": [{"id": "n1"}, {"id": "n2"}], "edges": []}
    tok = set_request_overrides({"orphan_resolve": False})
    try:
        out = await maybe_resolve_orphans({"final_pipeline": pipe})
    finally:
        reset_request_overrides(tok)
    assert out == {}
