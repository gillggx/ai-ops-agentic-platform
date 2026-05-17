"""v30.17h — wrap_build_event_for_chat must emit pb_glass_op events
in the v27-compatible shape so the Lite Canvas can paint live.

Regression: v30.17c flattened phase_action events into text summaries
(`op="v30:add_node"`, `args={args_summary: "..."}`) which made
applyGlassOp silent no-op → canvas stayed empty for the entire build.

Contract this test locks in:
  - op == raw tool name (no "v30:" prefix), so OP_LABEL_MAP matches
  - args contains the raw tool args (block_name, params, from_node, ...)
    PLUS underscore-prefixed metadata (_phase_id, _round, _args_summary)
  - result contains the raw action_result (node_id, edge_id, ...)
    PLUS _summary text
"""
from __future__ import annotations

from python_ai_sidecar.agent_builder.event_wrapper import wrap_build_event_for_chat
from python_ai_sidecar.agent_builder.session import StreamEvent


def _make_phase_action(tool: str, tool_args: dict, action_result: dict,
                       *, pid: str = "p1", rnd: int = 2,
                       args_summary: str = "", result_summary: str = "") -> StreamEvent:
    return StreamEvent(
        type="phase_action",
        data={
            "phase_id": pid,
            "round": rnd,
            "tool": tool,
            "args_summary": args_summary,
            "result_summary": result_summary,
            "tool_args_raw": tool_args,
            "action_result_raw": action_result,
        },
    )


# ── Core canvas-mutating ops ──────────────────────────────────────────


def test_add_node_emits_v27_shape():
    evt = _make_phase_action(
        tool="add_node",
        tool_args={"block_name": "block_process_history",
                   "block_version": "1.0.0",
                   "params": {"lot_id": "LOT-0001"}},
        action_result={"node_id": "n1", "position": {"x": 100, "y": 100}},
        args_summary="block_name=block_process_history, params={lot_id:LOT-0001}",
        result_summary="success: n1",
    )
    out = wrap_build_event_for_chat(evt, "sess-abc")
    assert out is not None
    assert out["type"] == "pb_glass_op"
    # op must NOT carry the v30: prefix — OP_LABEL_MAP keys are raw tool names
    assert out["op"] == "add_node"
    # args must carry the raw structured fields for applyGlassOp
    assert out["args"]["block_name"] == "block_process_history"
    assert out["args"]["block_version"] == "1.0.0"
    assert out["args"]["params"] == {"lot_id": "LOT-0001"}
    # plus phase metadata under underscore-prefixed keys for chat log
    assert out["args"]["_phase_id"] == "p1"
    assert out["args"]["_round"] == 2
    assert "_args_summary" in out["args"]
    # result must carry node_id (applyGlassOp uses it as the canvas node id)
    assert out["result"]["node_id"] == "n1"
    assert out["result"]["position"] == {"x": 100, "y": 100}
    assert "_summary" in out["result"]


def test_connect_emits_v27_shape():
    evt = _make_phase_action(
        tool="connect",
        tool_args={"from_node": "n1", "from_port": "out",
                   "to_node": "n2", "to_port": "in"},
        action_result={"edge_id": "e_xyz", "status": "success"},
    )
    out = wrap_build_event_for_chat(evt, "sess-abc")
    assert out["op"] == "connect"
    assert out["args"]["from_node"] == "n1"
    assert out["args"]["from_port"] == "out"
    assert out["args"]["to_node"] == "n2"
    assert out["args"]["to_port"] == "in"
    assert out["result"]["edge_id"] == "e_xyz"


def test_set_param_emits_v27_shape():
    evt = _make_phase_action(
        tool="set_param",
        tool_args={"node_id": "n1", "key": "lot_id", "value": "LOT-0001"},
        action_result={"status": "success"},
    )
    out = wrap_build_event_for_chat(evt, "sess-abc")
    assert out["op"] == "set_param"
    assert out["args"]["node_id"] == "n1"
    assert out["args"]["key"] == "lot_id"
    assert out["args"]["value"] == "LOT-0001"


def test_remove_node_emits_v27_shape():
    evt = _make_phase_action(
        tool="remove_node",
        tool_args={"node_id": "n3"},
        action_result={"status": "success"},
    )
    out = wrap_build_event_for_chat(evt, "sess-abc")
    assert out["op"] == "remove_node"
    assert out["args"]["node_id"] == "n3"


# ── Non-mutating ops (no canvas effect but still surface in chat log) ──


def test_inspect_block_doc_emits_pb_glass_op():
    evt = _make_phase_action(
        tool="inspect_block_doc",
        tool_args={"block_id": "block_line_chart"},
        action_result={"description": "...", "param_schema": {}},
    )
    out = wrap_build_event_for_chat(evt, "sess-abc")
    assert out["op"] == "inspect_block_doc"
    assert out["args"]["block_id"] == "block_line_chart"
    # applyGlassOp falls through for non-canvas ops — safe by design


def test_phase_complete_emits_pb_glass_op():
    evt = _make_phase_action(
        tool="phase_complete",
        tool_args={"rationale": "phase p2 done"},
        action_result={"status": "completed"},
        pid="p2", rnd=4,
    )
    out = wrap_build_event_for_chat(evt, "sess-abc")
    assert out["op"] == "phase_complete"
    assert out["args"]["rationale"] == "phase p2 done"
    assert out["args"]["_phase_id"] == "p2"


# ── Defensive: missing raw fields shouldn't crash (old sidecar fallback) ──


def test_missing_raw_args_still_wraps():
    """If an old sidecar didn't include tool_args_raw, wrap shouldn't crash
    — just emit a pb_glass_op with empty args (canvas no-op, same as broken
    v30.17c behaviour — no regression beyond what was already there)."""
    evt = StreamEvent(
        type="phase_action",
        data={
            "phase_id": "p1", "round": 1, "tool": "add_node",
            "args_summary": "block_name=...", "result_summary": "ok",
            # NO tool_args_raw / action_result_raw
        },
    )
    out = wrap_build_event_for_chat(evt, "sess-abc")
    assert out["type"] == "pb_glass_op"
    assert out["op"] == "add_node"
    assert out["args"]["_phase_id"] == "p1"
    # raw fields default to {} so applyGlassOp returns ok with no canvas effect
    assert "block_name" not in out["args"]
    assert out["result"]["_summary"] == "ok"


def test_session_id_propagates():
    evt = _make_phase_action("add_node", {"block_name": "x"}, {})
    out = wrap_build_event_for_chat(evt, "sess-xyz")
    assert out["session_id"] == "sess-xyz"
