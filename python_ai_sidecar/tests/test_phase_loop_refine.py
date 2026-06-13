"""Tests for the 2026-06-13 phase-loop refine bundle:
  - Item 1 ENABLE_NEXT_MEMO       — mutation tools carry `next`, surfaced next round
  - Item 2 ENABLE_STRICT_PHASE_VERIFY — verifier REJECTs missing-kind terminal
  - Item 3 ENABLE_CONSTRUCT_PARAM_DOC — pending block's param doc at construct
"""

from __future__ import annotations

import importlib

import pytest


# ── flag round-trips ──────────────────────────────────────────────────────

@pytest.mark.parametrize("flag,env,helper", [
    ("construct_param_doc", "ENABLE_CONSTRUCT_PARAM_DOC", "is_construct_param_doc_enabled"),
    ("strict_phase_verify", "ENABLE_STRICT_PHASE_VERIFY", "is_strict_phase_verify_enabled"),
    ("next_memo", "ENABLE_NEXT_MEMO", "is_next_memo_enabled"),
])
def test_flag_round_trip(monkeypatch, flag, env, helper):
    from python_ai_sidecar.feature_flags import parse_feature_flags_header
    assert parse_feature_flags_header(f"{flag}:on") == {flag: True}

    monkeypatch.setenv(env, "0")
    import python_ai_sidecar.config as cfg
    importlib.reload(cfg)
    import python_ai_sidecar.feature_flags as ff
    importlib.reload(ff)
    fn = getattr(ff, helper)
    assert fn() is False
    tok = ff.set_request_overrides({flag: True})
    try:
        assert fn() is True
    finally:
        ff.reset_request_overrides(tok)
    assert fn() is False


# ── Item 3: construct param doc ───────────────────────────────────────────

def test_param_doc_extracts_params_section_for_process_history():
    """process_history params live in description '== Params =='; the doc must
    carry the object_name '留空' guidance (the SLASH-13 root cause)."""
    from python_ai_sidecar.agent_builder.graph_build.nodes.agentic_phase_loop import (
        _build_pending_param_doc_md,
    )
    out = _build_pending_param_doc_md("block_process_history")
    assert "PARAM DOC: block_process_history" in out
    assert "object_name" in out
    assert "留空" in out  # the steering guidance reaches construct


def test_param_doc_renders_param_schema_for_filter():
    from python_ai_sidecar.agent_builder.graph_build.nodes.agentic_phase_loop import (
        _build_pending_param_doc_md,
    )
    out = _build_pending_param_doc_md("block_filter")
    assert "block_filter" in out
    assert "column" in out and "operator" in out


def test_param_doc_empty_for_unknown_block():
    from python_ai_sidecar.agent_builder.graph_build.nodes.agentic_phase_loop import (
        _build_pending_param_doc_md,
    )
    assert _build_pending_param_doc_md("block_does_not_exist") == ""


def test_construct_branch_injects_param_doc_only_when_flag_on(monkeypatch):
    """The construct sub-phase context includes the committed block's param doc
    iff ENABLE_CONSTRUCT_PARAM_DOC is on."""
    monkeypatch.setenv("ENABLE_CONSTRUCT_PARAM_DOC", "0")
    import python_ai_sidecar.config as cfg
    importlib.reload(cfg)
    import python_ai_sidecar.feature_flags as ff
    importlib.reload(ff)
    from python_ai_sidecar.agent_builder.graph_build.nodes import agentic_phase_loop as apl
    importlib.reload(apl)
    from python_ai_sidecar.pipeline_builder.pipeline_schema import PipelineJSON

    pipe = PipelineJSON.model_validate({"name": "t", "nodes": [], "edges": []})
    state = {"v30_pending_block": "block_filter", "exec_trace": {}}
    off = apl._build_subphase_context_md("construct", pipe, {"expected": "transform"}, state)
    assert "PARAM DOC" not in off

    tok = ff.set_request_overrides({"construct_param_doc": True})
    try:
        on = apl._build_subphase_context_md("construct", pipe, {"expected": "transform"}, state)
    finally:
        ff.reset_request_overrides(tok)
    assert "PARAM DOC: block_filter" in on


# ── Item 1: next memo ─────────────────────────────────────────────────────

def test_next_memo_injected_into_mutation_tools_when_on(monkeypatch):
    import python_ai_sidecar.feature_flags as ff
    from python_ai_sidecar.agent_builder.graph_build.nodes.agentic_phase_loop import (
        _build_tool_specs,
    )
    tok = ff.set_request_overrides({"next_memo": True})
    try:
        specs = {s["name"]: s for s in _build_tool_specs()}
    finally:
        ff.reset_request_overrides(tok)
    for t in ("add_node", "set_param", "connect", "remove_node"):
        sch = specs[t]["input_schema"]
        assert "next" in sch["properties"]
        assert "next" in sch["required"]
    # non-mutation tools untouched
    assert "next" not in specs["inspect_node_output"]["input_schema"]["properties"]
    assert "next" not in specs["run_verifier"]["input_schema"]["properties"]


def test_next_memo_absent_when_flag_off():
    from python_ai_sidecar.agent_builder.graph_build.nodes.agentic_phase_loop import (
        _build_tool_specs,
    )
    specs = {s["name"]: s for s in _build_tool_specs()}
    assert "next" not in specs["add_node"]["input_schema"]["properties"]


def test_canvas_diff_renders_memo_when_on(monkeypatch):
    import python_ai_sidecar.feature_flags as ff
    from python_ai_sidecar.agent_builder.graph_build.nodes.agentic_phase_loop import (
        _build_canvas_diff_md,
    )
    from python_ai_sidecar.pipeline_builder.pipeline_schema import PipelineJSON
    pipe = PipelineJSON.model_validate({"name": "t", "nodes": [], "edges": []})
    state = {"v30_next_memo": "add block_line_chart from n3, x=eventTime y=value"}

    tok = ff.set_request_overrides({"next_memo": True})
    try:
        out = _build_canvas_diff_md(pipe, {"expected": "chart", "goal": "g"}, state)
    finally:
        ff.reset_request_overrides(tok)
    assert "YOUR PLAN" in out
    assert "block_line_chart" in out

    # flag off → not rendered even if state carries a memo
    out_off = _build_canvas_diff_md(pipe, {"expected": "chart", "goal": "g"}, state)
    assert "YOUR PLAN" not in out_off


# ── Item 2: strict verify kinds ───────────────────────────────────────────

def test_strict_verify_kinds_are_presentation_only():
    """raw_data / transform stay loose; chart/table/scalar/alarm gated."""
    from python_ai_sidecar.agent_builder.graph_build.nodes.phase_verifier import (
        _STRICT_VERIFY_KINDS,
    )
    assert "chart" in _STRICT_VERIFY_KINDS
    assert "table" in _STRICT_VERIFY_KINDS
    assert "transform" not in _STRICT_VERIFY_KINDS
    assert "raw_data" not in _STRICT_VERIFY_KINDS
