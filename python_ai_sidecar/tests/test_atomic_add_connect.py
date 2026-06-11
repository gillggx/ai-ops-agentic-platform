"""Tests for ENABLE_ATOMIC_ADD_CONNECT — add_node + connect fusion."""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from python_ai_sidecar.agent_builder.session import AgentBuilderSession
from python_ai_sidecar.agent_builder.tools import BuilderToolset, ToolError
from python_ai_sidecar.pipeline_builder.pipeline_schema import PipelineJSON


def _spec(name, *, inputs=None, outputs=None, version="1.0.0"):
    return {
        "name": name,
        "block_id": name,
        "block_version": version,
        "input_schema": inputs or [],
        "output_schema": outputs or [{"port": "data", "type": "dataframe"}],
    }


def _mock_registry(name_to_spec: dict):
    reg = MagicMock()
    reg.get_spec.side_effect = lambda n, v: name_to_spec.get(n)
    return reg


def _new_session():
    pipeline = PipelineJSON(
        version="1.0",
        name="test",
        metadata={"created_by": "test"},
        nodes=[],
        edges=[],
    )
    return AgentBuilderSession.new(user_prompt="test", base_pipeline=pipeline)


# ── add_node executor ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_add_node_without_upstream_legacy_path():
    """upstream=None ⇒ behaviour identical to legacy add_node."""
    sess = _new_session()
    reg = _mock_registry({"block_a": _spec("block_a")})
    ts = BuilderToolset(sess, reg)
    result = await ts.add_node(block_name="block_a", params={})
    assert result["node_id"]
    assert "upstream_connected" not in result
    assert len(sess.pipeline_json.nodes) == 1
    assert len(sess.pipeline_json.edges) == 0


@pytest.mark.asyncio
async def test_add_node_with_upstream_atomic_connect():
    """upstream=[{src_node:n1}] ⇒ adds node + creates one edge in one call."""
    sess = _new_session()
    reg = _mock_registry({
        "block_a": _spec("block_a"),
        "block_b": _spec(
            "block_b",
            inputs=[{"port": "data", "type": "dataframe", "required": True}],
        ),
    })
    ts = BuilderToolset(sess, reg)
    a = await ts.add_node(block_name="block_a", params={})
    b = await ts.add_node(
        block_name="block_b", params={},
        upstream=[{"src_node": a["node_id"]}],
    )
    assert b["node_id"]
    assert b["upstream_connected"][0]["src_node"] == a["node_id"]
    assert b["upstream_connected"][0]["dst_port"] == "data"
    assert len(sess.pipeline_json.edges) == 1
    edge = sess.pipeline_json.edges[0]
    assert edge.from_.node == a["node_id"]
    assert edge.to.node == b["node_id"]


@pytest.mark.asyncio
async def test_add_node_with_upstream_dst_port_auto_detected():
    """When block has named input port (not 'data'), dst_port auto-detected."""
    sess = _new_session()
    reg = _mock_registry({
        "block_a": _spec("block_a"),
        "weco": _spec(
            "weco",
            inputs=[{"port": "rows", "type": "dataframe", "required": True}],
        ),
    })
    ts = BuilderToolset(sess, reg)
    a = await ts.add_node(block_name="block_a", params={})
    b = await ts.add_node(
        block_name="weco", params={},
        upstream=[{"src_node": a["node_id"]}],
    )
    edge = sess.pipeline_json.edges[0]
    assert edge.to.port == "rows"


@pytest.mark.asyncio
async def test_add_node_with_upstream_explicit_dst_port():
    """Explicit dst_port wins over auto-detection."""
    sess = _new_session()
    reg = _mock_registry({
        "block_a": _spec("block_a"),
        "multi_in": _spec(
            "multi_in",
            inputs=[
                {"port": "primary", "type": "dataframe", "required": True},
                {"port": "secondary", "type": "dataframe", "required": False},
            ],
        ),
    })
    ts = BuilderToolset(sess, reg)
    a = await ts.add_node(block_name="block_a", params={})
    b = await ts.add_node(
        block_name="multi_in", params={},
        upstream=[{"src_node": a["node_id"], "dst_port": "secondary"}],
    )
    assert sess.pipeline_json.edges[0].to.port == "secondary"


@pytest.mark.asyncio
async def test_add_node_rolls_back_on_connect_failure():
    """connect failure rolls back the just-added node — canvas unchanged."""
    sess = _new_session()
    reg = _mock_registry({"block_b": _spec(
        "block_b",
        inputs=[{"port": "data", "type": "dataframe", "required": True}],
    )})
    ts = BuilderToolset(sess, reg)
    initial_nodes = len(sess.pipeline_json.nodes)
    initial_edges = len(sess.pipeline_json.edges)
    with pytest.raises(ToolError) as ei:
        await ts.add_node(
            block_name="block_b", params={},
            upstream=[{"src_node": "does_not_exist"}],
        )
    assert "rolled back" in ei.value.message
    assert len(sess.pipeline_json.nodes) == initial_nodes
    assert len(sess.pipeline_json.edges) == initial_edges


@pytest.mark.asyncio
async def test_add_node_with_multiple_upstream():
    """Multi-input block (e.g. union) gets all upstream edges atomically."""
    sess = _new_session()
    reg = _mock_registry({
        "src": _spec("src"),
        "union": _spec(
            "union",
            inputs=[{"port": "data", "type": "dataframe", "required": True}],
        ),
    })
    ts = BuilderToolset(sess, reg)
    a = await ts.add_node(block_name="src", params={})
    b = await ts.add_node(block_name="src", params={})
    u = await ts.add_node(
        block_name="union", params={},
        upstream=[
            {"src_node": a["node_id"]},
            {"src_node": b["node_id"]},
        ],
    )
    assert len(u["upstream_connected"]) == 2
    assert len(sess.pipeline_json.edges) == 2


@pytest.mark.asyncio
async def test_add_node_upstream_invalid_item_raises():
    """Malformed upstream item (missing src_node) ⇒ clear error + rollback."""
    sess = _new_session()
    reg = _mock_registry({"block_b": _spec(
        "block_b",
        inputs=[{"port": "data", "type": "dataframe", "required": True}],
    )})
    ts = BuilderToolset(sess, reg)
    with pytest.raises(ToolError) as ei:
        await ts.add_node(
            block_name="block_b", params={},
            upstream=[{"src_port": "data"}],  # no src_node
        )
    assert ei.value.code == "INVALID_PARAM"
    assert len(sess.pipeline_json.nodes) == 0


# ── _next_subphase shortcut ───────────────────────────────────────────────

def test_next_subphase_legacy_add_node_no_upstream():
    """add_node without upstream → construct (legacy)."""
    from python_ai_sidecar.agent_builder.graph_build.nodes.agentic_phase_loop import (
        _next_subphase,
    )
    assert _next_subphase("construct", "add_node", {}) == "construct"
    assert _next_subphase("construct", "add_node", None) == "construct"


def test_next_subphase_atomic_add_node_jumps_to_tune():
    """add_node with upstream → tune (one round saved)."""
    from python_ai_sidecar.agent_builder.graph_build.nodes.agentic_phase_loop import (
        _next_subphase,
    )
    args = {"block_name": "x", "upstream": [{"src_node": "n1"}]}
    assert _next_subphase("construct", "add_node", args) == "tune"
    assert _next_subphase("pick", "add_node", args) == "tune"
    assert _next_subphase("tune", "add_node", args) == "tune"


def test_next_subphase_atomic_add_node_empty_upstream_still_legacy():
    """upstream=[] (empty list) shouldn't shortcut."""
    from python_ai_sidecar.agent_builder.graph_build.nodes.agentic_phase_loop import (
        _next_subphase,
    )
    args = {"block_name": "x", "upstream": []}
    assert _next_subphase("construct", "add_node", args) == "construct"
