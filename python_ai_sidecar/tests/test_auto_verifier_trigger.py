"""Unit tests for ENABLE_AUTO_VERIFIER trigger logic in agentic_phase_loop."""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def _reload(monkeypatch, *, auto_verifier: str):
    monkeypatch.setenv("ENABLE_AUTO_VERIFIER", auto_verifier)
    import python_ai_sidecar.config as cfg
    importlib.reload(cfg)
    import python_ai_sidecar.feature_flags as ff
    importlib.reload(ff)


def _make_pipeline(node_ids_with_blocks, edges=None):
    """Build a minimal pipeline-like object for _terminal_block_matches_expected.

    node_ids_with_blocks: list of (logical_id, block_id) tuples.
    edges: list of (from_node, to_node) tuples (port defaults to 'data').
    """
    nodes = [
        SimpleNamespace(id=nid, block_id=bid, block_version="1.0.0")
        for nid, bid in node_ids_with_blocks
    ]
    edges_list = []
    for fr, to in edges or []:
        edges_list.append(SimpleNamespace(
            from_=SimpleNamespace(node=fr, port="data"),
            to=SimpleNamespace(node=to, port="data"),
        ))
    return SimpleNamespace(nodes=nodes, edges=edges_list)


def _registry_with(block_to_covers: dict[str, list[str]]):
    """Mock registry whose get_spec returns a dict whose `_resolve_covers`
    output matches block_to_covers[block_id]."""
    reg = MagicMock()
    def get_spec(block_id, _ver):
        # phase_verifier._resolve_covers reads produces.covers_output (or
        # the legacy produces.covers); be explicit about the new field.
        covers = block_to_covers.get(block_id, [])
        return {"produces": {"covers_output": covers}}
    reg.get_spec.side_effect = get_spec
    return reg


def test_off_flag_returns_false(monkeypatch):
    _reload(monkeypatch, auto_verifier="0")
    from python_ai_sidecar.agent_builder.graph_build.nodes.agentic_phase_loop import (
        _should_auto_verify,
    )
    state = {}
    phase = {"id": "p1", "expected": "chart"}
    pipeline = _make_pipeline([("n1", "block_line_chart")])
    reg = _registry_with({"block_line_chart": ["chart"]})
    assert _should_auto_verify(
        state, phase, "add_node", {}, [], pipeline, reg
    ) is False


def test_on_terminal_match_decisive(monkeypatch):
    _reload(monkeypatch, auto_verifier="1")
    from python_ai_sidecar.agent_builder.graph_build.nodes.agentic_phase_loop import (
        _should_auto_verify,
    )
    phase = {"id": "p1", "expected": "chart"}
    pipeline = _make_pipeline(
        [("n1", "block_process_history"), ("n2", "block_line_chart")],
        edges=[("n1", "n2")],
    )
    reg = _registry_with({
        "block_process_history": ["raw_data"],
        "block_line_chart": ["chart"],
    })
    # Recent actions: connect, add_node — no inspect
    recent = [{"tool": "connect"}, {"tool": "add_node"}]
    assert _should_auto_verify(
        {}, phase, "connect", {}, recent, pipeline, reg
    ) is True


def test_on_terminal_match_but_recently_inspected(monkeypatch):
    """Agent still exploring (inspect_block_doc in last 2) → don't auto-verify."""
    _reload(monkeypatch, auto_verifier="1")
    from python_ai_sidecar.agent_builder.graph_build.nodes.agentic_phase_loop import (
        _should_auto_verify,
    )
    phase = {"id": "p1", "expected": "chart"}
    pipeline = _make_pipeline(
        [("n1", "block_process_history"), ("n2", "block_line_chart")],
        edges=[("n1", "n2")],
    )
    reg = _registry_with({
        "block_process_history": ["raw_data"],
        "block_line_chart": ["chart"],
    })
    recent = [{"tool": "inspect_block_doc"}, {"tool": "add_node"}]
    assert _should_auto_verify(
        {}, phase, "add_node", {}, recent, pipeline, reg
    ) is False


def test_on_but_terminal_does_not_match(monkeypatch):
    """Multi-block phase mid-build: terminal block is filter, not chart."""
    _reload(monkeypatch, auto_verifier="1")
    from python_ai_sidecar.agent_builder.graph_build.nodes.agentic_phase_loop import (
        _should_auto_verify,
    )
    phase = {"id": "p1", "expected": "chart"}
    pipeline = _make_pipeline(
        [("n1", "block_process_history"), ("n2", "block_filter")],
        edges=[("n1", "n2")],
    )
    reg = _registry_with({
        "block_process_history": ["raw_data"],
        "block_filter": ["transform"],
    })
    recent = [{"tool": "add_node"}, {"tool": "connect"}]
    # filter is terminal but doesn't cover 'chart' — should not auto-verify
    assert _should_auto_verify(
        {}, phase, "connect", {}, recent, pipeline, reg
    ) is False


def test_on_but_tool_was_not_mutating(monkeypatch):
    _reload(monkeypatch, auto_verifier="1")
    from python_ai_sidecar.agent_builder.graph_build.nodes.agentic_phase_loop import (
        _should_auto_verify,
    )
    phase = {"id": "p1", "expected": "chart"}
    pipeline = _make_pipeline([("n1", "block_line_chart")])
    reg = _registry_with({"block_line_chart": ["chart"]})
    assert _should_auto_verify(
        {}, phase, "inspect_block_doc", {}, [], pipeline, reg
    ) is False


def test_on_but_action_errored(monkeypatch):
    _reload(monkeypatch, auto_verifier="1")
    from python_ai_sidecar.agent_builder.graph_build.nodes.agentic_phase_loop import (
        _should_auto_verify,
    )
    phase = {"id": "p1", "expected": "chart"}
    pipeline = _make_pipeline([("n1", "block_line_chart")])
    reg = _registry_with({"block_line_chart": ["chart"]})
    assert _should_auto_verify(
        {}, phase, "add_node", {"error": "INVALID_PARAM"}, [], pipeline, reg
    ) is False


def test_on_empty_canvas(monkeypatch):
    _reload(monkeypatch, auto_verifier="1")
    from python_ai_sidecar.agent_builder.graph_build.nodes.agentic_phase_loop import (
        _should_auto_verify,
    )
    phase = {"id": "p1", "expected": "chart"}
    pipeline = _make_pipeline([])
    reg = _registry_with({})
    assert _should_auto_verify(
        {}, phase, "add_node", {}, [], pipeline, reg
    ) is False


def test_on_phase_expected_empty_string(monkeypatch):
    """Defensive: phases without an `expected` kind should not auto-verify."""
    _reload(monkeypatch, auto_verifier="1")
    from python_ai_sidecar.agent_builder.graph_build.nodes.agentic_phase_loop import (
        _should_auto_verify,
    )
    phase = {"id": "p1", "expected": ""}
    pipeline = _make_pipeline([("n1", "block_line_chart")])
    reg = _registry_with({"block_line_chart": ["chart"]})
    assert _should_auto_verify(
        {}, phase, "add_node", {}, [], pipeline, reg
    ) is False
