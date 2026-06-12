"""Tests for ENABLE_RICH_CANVAS_SNAPSHOT — context-aware per-sub-phase prompt.

Covers the three helpers (_flatten_sample_one_level, _build_flow_tree_md,
_build_node_data_md) and the _build_subphase_context_md router.
"""

from __future__ import annotations

from python_ai_sidecar.pipeline_builder.pipeline_schema import (
    PipelineJSON, PipelineNode, PipelineEdge, EdgeEndpoint, NodePosition,
)
from python_ai_sidecar.agent_builder.graph_build.nodes.agentic_phase_loop import (
    _flatten_sample_one_level,
    _build_flow_tree_md,
    _build_node_data_md,
    _build_subphase_context_md,
    _fmt_cols_inline,
)


def _node(nid, block_id, params=None):
    return PipelineNode(
        id=nid, block_id=block_id, block_version="1.0.0",
        position=NodePosition(x=0, y=0), params=params or {},
    )


def _edge(eid, src, dst, sport="data", dport="data"):
    return PipelineEdge(
        id=eid,
        **{"from": EdgeEndpoint(node=src, port=sport)},
        to=EdgeEndpoint(node=dst, port=dport),
    )


def _pipe(nodes, edges):
    return PipelineJSON(
        version="1.0", name="t", metadata={"created_by": "t"},
        nodes=nodes, edges=edges,
    )


# ── _flatten_sample_one_level ─────────────────────────────────────────────

def test_flatten_scalar_values():
    out = _flatten_sample_one_level({"a": 1, "b": "x", "c": 3.5}, 200)
    assert out == "{a: 1, b: 'x', c: 3.5}"


def test_flatten_collapses_nested():
    out = _flatten_sample_one_level(
        {"k": {"deep": 1}, "arr": [1, 2, 3], "s": "v"}, 200)
    assert "{...}" in out
    assert "[...]" in out
    assert "s: 'v'" in out


def test_flatten_caps_length():
    big = {f"col{i}": "x" * 20 for i in range(50)}
    out = _flatten_sample_one_level(big, 100)
    assert len(out) <= 100
    assert out.endswith("…")


def test_flatten_non_dict_returns_empty():
    assert _flatten_sample_one_level([1, 2], 100) == ""
    assert _flatten_sample_one_level(None, 100) == ""
    assert _flatten_sample_one_level({}, 100) == ""


def test_flatten_truncates_long_strings():
    out = _flatten_sample_one_level({"x": "a" * 50}, 200)
    assert "…" in out  # long string value truncated


# ── _fmt_cols_inline ──────────────────────────────────────────────────────

def test_fmt_cols_under_limit():
    assert _fmt_cols_inline(["a", "b", "c"]) == "[a, b, c]"


def test_fmt_cols_over_limit():
    cols = [f"c{i}" for i in range(40)]
    out = _fmt_cols_inline(cols)
    assert "(+10 more)" in out


def test_fmt_cols_empty():
    assert _fmt_cols_inline([]) == ""


# ── _build_node_data_md ───────────────────────────────────────────────────

def test_node_data_with_cols_and_sample():
    exec_trace = {"n1": {"cols": ["a", "b"], "sample": {"a": 1, "b": 2}}}
    lines = _build_node_data_md(exec_trace, "n1", "block_x", sample_cap=200)
    joined = "\n".join(lines)
    assert "n1 [block_x]" in joined
    assert "output cols: [a, b]" in joined
    assert "sample: {a: 1, b: 2}" in joined


def test_node_data_not_previewed():
    lines = _build_node_data_md({}, "n1", "block_x", sample_cap=200)
    assert "not yet previewed" in "\n".join(lines)


# ── _build_flow_tree_md ───────────────────────────────────────────────────

def test_flow_tree_empty():
    out = _build_flow_tree_md(_pipe([], []), {})
    assert "empty canvas" in out


def test_flow_tree_linear_marks_terminal_and_cols():
    pipe = _pipe(
        [_node("n1", "block_process_history", {"tool_id": "EQP-01"}),
         _node("n2", "block_unnest", {"column": "APC.parameters"})],
        [_edge("e1", "n1", "n2")],
    )
    exec_trace = {
        "n2": {"cols": ["step", "etch_time_offset"], "sample": {"step": "S1"}},
    }
    out = _build_flow_tree_md(pipe, exec_trace)
    assert "[source] n1 block_process_history" in out
    assert "n2 block_unnest" in out
    assert "<- canvas terminal" in out
    assert "terminal cols: [step, etch_time_offset]" in out


# ── _build_subphase_context_md router ─────────────────────────────────────

def test_router_pick_emits_flow_and_guidance():
    pipe = _pipe(
        [_node("n1", "block_process_history"), _node("n2", "block_unnest")],
        [_edge("e1", "n1", "n2")],
    )
    state = {"exec_trace": {"n2": {"cols": ["step", "etch_time_offset"]}}}
    out = _build_subphase_context_md("pick", pipe, {"expected": "chart"}, state)
    assert "SUB-PHASE: pick_block" in out
    assert "FLOW SO FAR" in out
    assert "choosing the NEXT block" in out


def test_router_construct_surfaces_upstream_cols():
    """The SLASH-13 fix: construct context must show n2's columns so agent
    sees `etch_time_offset` exists but `recipe_id` does NOT."""
    pipe = _pipe(
        [_node("n1", "block_process_history"), _node("n2", "block_unnest")],
        [_edge("e1", "n1", "n2")],
    )
    state = {
        "v30_pending_block": "block_box_plot",
        "exec_trace": {
            "n2": {"cols": ["step", "etch_time_offset", "chamber_temp"],
                   "sample": {"step": "STEP_004", "etch_time_offset": 3.2}},
        },
    }
    out = _build_subphase_context_md("construct", pipe, {"expected": "chart"}, state)
    assert "SUB-PHASE: construct_node" in out
    assert "committed to block_box_plot" in out
    assert "UPSTREAM OUTPUT" in out
    assert "etch_time_offset" in out
    assert "recipe_id" not in out  # the column the agent wrongly guessed
    assert "ONLY columns listed above" in out


def test_router_tune_shows_current_params_and_upstream():
    pipe = _pipe(
        [_node("n2", "block_unnest"),
         _node("n3", "block_box_plot", {"x": "step", "y": "etch_time_offset"})],
        [_edge("e1", "n2", "n3")],
    )
    state = {
        "v30_pending_node_id": "n3",
        "exec_trace": {"n2": {"cols": ["step", "etch_time_offset"]}},
    }
    out = _build_subphase_context_md("tune", pipe, {"expected": "chart"}, state)
    assert "SUB-PHASE: tune" in out
    assert "n3 [block_box_plot] CURRENT params" in out
    assert "x='step'" in out
    assert "UPSTREAM cols" in out


def test_router_unknown_subphase_returns_empty():
    pipe = _pipe([_node("n1", "block_x")], [])
    assert _build_subphase_context_md("refine", pipe, {}, {}) == ""
    assert _build_subphase_context_md(None, pipe, {}, {}) == ""


def test_router_construct_marks_unpreviewed_terminal():
    pipe = _pipe([_node("n1", "block_process_history")], [])
    state = {"v30_pending_block": "block_filter", "exec_trace": {}}
    out = _build_subphase_context_md("construct", pipe, {"expected": "transform"}, state)
    assert "not yet previewed" in out
