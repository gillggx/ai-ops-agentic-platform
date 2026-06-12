"""Tests for ENABLE_NO_DUPLICATE_NODE — orphan duplicate add_node guard.

The guard catches KIMI's "echo" behaviour (re-emitting the same add_node a
second time despite the canvas showing the first landed) WITHOUT
false-positives on legitimate parallel-chain DAGs.
"""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock

import pytest

from python_ai_sidecar.agent_builder.session import AgentBuilderSession
from python_ai_sidecar.agent_builder.tools import BuilderToolset, ToolError
from python_ai_sidecar.pipeline_builder.pipeline_schema import PipelineJSON


def _spec(name, *, inputs=None, outputs=None):
    return {
        "name": name, "block_id": name, "block_version": "1.0.0",
        "input_schema": inputs or [],
        "output_schema": outputs or [{"port": "data", "type": "dataframe"}],
    }


def _registry(name_to_spec):
    reg = MagicMock()
    reg.get_spec.side_effect = lambda n, v: name_to_spec.get(n)
    return reg


def _new_session():
    pipeline = PipelineJSON(
        version="1.0", name="test", metadata={"created_by": "test"},
        nodes=[], edges=[],
    )
    return AgentBuilderSession.new(user_prompt="test", base_pipeline=pipeline)


def _reload(monkeypatch, *, enabled: str):
    monkeypatch.setenv("ENABLE_NO_DUPLICATE_NODE", enabled)
    import python_ai_sidecar.config as cfg
    importlib.reload(cfg)
    import python_ai_sidecar.feature_flags as ff
    importlib.reload(ff)


# ── Flag off ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_flag_off_allows_duplicate_orphan(monkeypatch):
    _reload(monkeypatch, enabled="0")
    sess = _new_session()
    reg = _registry({"src": _spec("src")})
    ts = BuilderToolset(sess, reg)
    a = await ts.add_node(block_name="src", params={"x": 1})
    # Second add should NOT raise when flag is off
    b = await ts.add_node(block_name="src", params={"x": 1})
    assert a["node_id"] != b["node_id"]
    assert len(sess.pipeline_json.nodes) == 2


# ── Flag on: positive cases (guard fires) ─────────────────────────────────

@pytest.mark.asyncio
async def test_flag_on_blocks_orphan_duplicate(monkeypatch):
    """The SLASH-13 echo signature: add_node + identical re-emit, no edges."""
    _reload(monkeypatch, enabled="1")
    sess = _new_session()
    reg = _registry({"src": _spec("src")})
    ts = BuilderToolset(sess, reg)
    a = await ts.add_node(block_name="src", params={"x": 1})
    with pytest.raises(ToolError) as ei:
        await ts.add_node(block_name="src", params={"x": 1})
    assert ei.value.code == "DUPLICATE_NODE"
    assert a["node_id"] in ei.value.message
    assert "phase_complete" in ei.value.hint
    assert "inspect_node_output" in ei.value.hint
    # Canvas should still have exactly 1 node (no half-mutation)
    assert len(sess.pipeline_json.nodes) == 1


@pytest.mark.asyncio
async def test_flag_on_blocks_orphan_with_empty_params(monkeypatch):
    """params={} on both — common KIMI shape."""
    _reload(monkeypatch, enabled="1")
    sess = _new_session()
    reg = _registry({"src": _spec("src")})
    ts = BuilderToolset(sess, reg)
    await ts.add_node(block_name="src", params={})
    with pytest.raises(ToolError) as ei:
        await ts.add_node(block_name="src", params={})
    assert ei.value.code == "DUPLICATE_NODE"


@pytest.mark.asyncio
async def test_flag_on_blocks_orphan_with_none_params(monkeypatch):
    """params=None should be treated identically to params={}."""
    _reload(monkeypatch, enabled="1")
    sess = _new_session()
    reg = _registry({"src": _spec("src")})
    ts = BuilderToolset(sess, reg)
    await ts.add_node(block_name="src", params=None)
    with pytest.raises(ToolError):
        await ts.add_node(block_name="src", params={})


# ── Flag on: negative cases (guard does NOT fire) ─────────────────────────

@pytest.mark.asyncio
async def test_flag_on_allows_different_params(monkeypatch):
    """Fan-out pattern: same block, different params."""
    _reload(monkeypatch, enabled="1")
    sess = _new_session()
    reg = _registry({"src": _spec("src")})
    ts = BuilderToolset(sess, reg)
    await ts.add_node(block_name="src", params={"tool_id": "EQP-01"})
    await ts.add_node(block_name="src", params={"tool_id": "EQP-02"})
    await ts.add_node(block_name="src", params={"tool_id": "EQP-03"})
    assert len(sess.pipeline_json.nodes) == 3


@pytest.mark.asyncio
async def test_flag_on_allows_different_block_same_params(monkeypatch):
    _reload(monkeypatch, enabled="1")
    sess = _new_session()
    reg = _registry({"a": _spec("a"), "b": _spec("b")})
    ts = BuilderToolset(sess, reg)
    await ts.add_node(block_name="a", params={"x": 1})
    await ts.add_node(block_name="b", params={"x": 1})
    assert len(sess.pipeline_json.nodes) == 2


@pytest.mark.asyncio
async def test_flag_on_allows_duplicate_when_existing_has_downstream(monkeypatch):
    """Parallel-chain DAG: same block + same params allowed when the existing
    one has a downstream connection (not an orphan).

    Shape:
        n1 (src) → n2 (filter)
        n3 (src, same params as n1, but n1 is NOT orphan)
    """
    _reload(monkeypatch, enabled="1")
    sess = _new_session()
    reg = _registry({
        "src": _spec("src"),
        "filter": _spec(
            "filter",
            inputs=[{"port": "data", "type": "dataframe", "required": True}],
        ),
    })
    ts = BuilderToolset(sess, reg)
    n1 = await ts.add_node(block_name="src", params={"k": "v"})
    n2 = await ts.add_node(block_name="filter", params={"col": "x"})
    await ts.connect(from_node=n1["node_id"], to_node=n2["node_id"])
    # n1 now has a downstream edge → not orphan → second `src` with same
    # params should be allowed.
    n3 = await ts.add_node(block_name="src", params={"k": "v"})
    assert n3["node_id"] != n1["node_id"]
    assert len(sess.pipeline_json.nodes) == 3


@pytest.mark.asyncio
async def test_flag_on_allows_readd_after_remove(monkeypatch):
    """abort_node + remove_node + re-add with same params should work."""
    _reload(monkeypatch, enabled="1")
    sess = _new_session()
    reg = _registry({"src": _spec("src")})
    ts = BuilderToolset(sess, reg)
    n1 = await ts.add_node(block_name="src", params={"k": "v"})
    await ts.remove_node(node_id=n1["node_id"])
    # Canvas is now empty — should be able to re-add with same params (node_id
    # may be reused since _gen_node_id picks the lowest available — what
    # matters is that the guard did not raise).
    n2 = await ts.add_node(block_name="src", params={"k": "v"})
    assert n2["node_id"]  # didn't raise
    assert len(sess.pipeline_json.nodes) == 1


@pytest.mark.asyncio
async def test_flag_on_allows_when_atomic_add_connect_used(monkeypatch):
    """atomic add+connect creates a node WITH a downstream connection from
    the start (because src_node → new_node). The new node is the destination
    of an edge but has no OUTGOING edges yet — still considered orphan when
    a third add_node fires with same params. Make sure this still behaves
    correctly (i.e. the GUARD's outgoing check is about outgoing edges
    FROM the existing node, not incoming TO it)."""
    _reload(monkeypatch, enabled="1")
    sess = _new_session()
    reg = _registry({
        "src": _spec("src"),
        "filter": _spec(
            "filter",
            inputs=[{"port": "data", "type": "dataframe", "required": True}],
        ),
    })
    ts = BuilderToolset(sess, reg)
    n1 = await ts.add_node(block_name="src", params={"k": "v"})
    # n2 is filter with upstream from n1 — n1 gains an OUTGOING edge.
    # The atomic flag isn't relevant here; we're testing the guard's logic.
    # Set atomic on via env override on the existing config.
    monkeypatch.setenv("ENABLE_ATOMIC_ADD_CONNECT", "1")
    import python_ai_sidecar.config as cfg
    importlib.reload(cfg)
    import python_ai_sidecar.feature_flags as ff
    importlib.reload(ff)
    # n1 has outgoing edge after this:
    await ts.add_node(
        block_name="filter", params={"col": "x"},
        upstream=[{"src_node": n1["node_id"]}],
    )
    # Now a third add_node src with same params as n1 — n1 has outgoing edge,
    # so guard should NOT fire even though params match.
    n3 = await ts.add_node(block_name="src", params={"k": "v"})
    assert n3["node_id"] != n1["node_id"]
