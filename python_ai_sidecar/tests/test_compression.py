"""Compression of Glass Box conversation history.

Replaces older (assistant, tool_result) pairs with one synthetic assistant
message holding a deterministic op synopsis, plus truncates verbose tool
results retained in the recent window. Cuts per-turn input token count
without an extra LLM call.
"""

from __future__ import annotations

import json

from python_ai_sidecar.agent_builder.compression import (
    COMPRESSION_TRIGGER_TURNS,
    _render_op_synopsis,
    _truncate_tool_result,
    compress_messages,
)
from python_ai_sidecar.agent_builder.session import AgentBuilderSession, Operation
from python_ai_sidecar.pipeline_builder.pipeline_schema import (
    PipelineJSON, PipelineNode, PipelineInput, NodePosition,
)


def _mk_op(op: str, args: dict, result: dict | None = None) -> Operation:
    return Operation(op=op, args=args, result=result or {}, elapsed_ms=1.0)


# ---------------------------------------------------------------------------
# Synopsis renderer
# ---------------------------------------------------------------------------


def test_synopsis_includes_canvas_state_and_mutations():
    pipeline = {
        "version": "1.0",
        "name": "Test",
        "metadata": {},
        "inputs": [{"name": "tool_id", "type": "string", "example": "EQP-01"}],
        "nodes": [
            {"id": "n1", "block_id": "block_process_history", "block_version": "1.0.0",
             "position": {"x": 0, "y": 0},
             "params": {"tool_id": "$tool_id", "time_range": "24h"}},
            {"id": "n2", "block_id": "block_filter", "block_version": "1.0.0",
             "position": {"x": 200, "y": 0},
             "params": {"column": "spc_status", "operator": "==", "value": "OOC"}},
        ],
        "edges": [{"id": "e1", "from": {"node": "n1", "port": "data"},
                   "to": {"node": "n2", "port": "data"}}],
    }
    ops = [
        _mk_op("add_node", {"block_name": "block_process_history"}, {"node_id": "n1"}),
        _mk_op("set_param", {"node_id": "n1", "key": "tool_id", "value": "$tool_id"}),
        _mk_op("set_param", {"node_id": "n1", "key": "time_range", "value": "24h"}),
        _mk_op("add_node", {"block_name": "block_filter"}, {"node_id": "n2"}),
        _mk_op("connect", {"from_node": "n1", "to_node": "n2",
                           "from_port": "data", "to_port": "data"}),
    ]
    text = _render_op_synopsis(ops, pipeline, read_only_op_count=2)

    assert "n1 added (block_process_history)" in text
    assert "n2 added (block_filter)" in text
    assert "n1.tool_id set to" in text
    assert "edge n1.data → n2.data" in text
    assert "2 read-only check" in text
    assert "Current canvas state:" in text
    assert "nodes:   2" in text
    assert "tool_id (string, example='EQP-01')" in text


def test_synopsis_empty_when_nothing_done():
    text = _render_op_synopsis([], {"nodes": [], "edges": [], "inputs": []})
    assert text == ""


def test_synopsis_skips_read_only_ops_in_bullets():
    """list_blocks / explain_block / get_state etc. only count, don't list
    each individually as canvas mutations."""
    ops = [
        _mk_op("list_blocks", {}, {"blocks": []}),
        _mk_op("explain_block", {"block_name": "block_filter"}, {}),
        _mk_op("get_state", {}, {}),
    ]
    text = _render_op_synopsis(
        ops, {"nodes": [], "edges": [], "inputs": []}, read_only_op_count=3,
    )
    # No per-op bullet — they're aggregated into the read-only count.
    assert "list_blocks(" not in text  # no individual call rendering
    assert "explain_block(" not in text
    assert "3 read-only check" in text
    assert "(no canvas-mutating ops yet)" in text


# ---------------------------------------------------------------------------
# Tool result truncation
# ---------------------------------------------------------------------------


def test_truncate_validate_keeps_first_3_errors():
    body = json.dumps({"valid": False, "errors": [{"i": i} for i in range(10)]})
    out = _truncate_tool_result("validate", body)
    obj = json.loads(out)
    assert len(obj["errors"]) == 4  # 3 + 1 truncation marker
    assert obj["errors"][3]["_truncated"] == "7 more error(s)"


def test_truncate_run_preview_keeps_first_5_rows():
    body = json.dumps({"rows": [{"i": i} for i in range(20)], "total": 20})
    out = _truncate_tool_result("run_preview", body)
    obj = json.loads(out)
    assert len(obj["rows"]) == 6  # 5 + truncation marker
    assert obj["rows"][5]["_truncated"] == "15 more row(s)"


def test_truncate_unknown_tool_passes_through():
    body = json.dumps({"rows": [{"i": i} for i in range(20)]})
    out = _truncate_tool_result("set_param", body)
    assert out == body  # unchanged — set_param isn't in verbose set


def test_truncate_explain_block_caps_examples():
    body = json.dumps({
        "name": "block_filter",
        "description": "...",
        "examples": [{"name": f"ex{i}"} for i in range(10)],
    })
    out = _truncate_tool_result("explain_block", body)
    obj = json.loads(out)
    assert len(obj["examples"]) == 3


# ---------------------------------------------------------------------------
# Full compress_messages flow
# ---------------------------------------------------------------------------


def _sess_with_ops(n_ops: int) -> AgentBuilderSession:
    """Build a fake session with N add_node operations."""
    sess = AgentBuilderSession.new(user_prompt="build me a thing")
    for i in range(n_ops):
        nid = f"n{i+1}"
        sess.pipeline_json.nodes.append(PipelineNode(
            id=nid, block_id="block_filter", block_version="1.0.0",
            position=NodePosition(x=200.0 * i, y=0.0),
            params={"column": "x", "operator": "==", "value": str(i)},
        ))
        sess.operations.append(_mk_op(
            "add_node", {"block_name": "block_filter"}, {"node_id": nid},
        ))
    return sess


def _msg_pair(tool_name: str, payload: dict) -> list[dict]:
    """One assistant tool_use → one user tool_result pair."""
    tu_id = f"toolu_{tool_name}_{id(payload)}"
    return [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": tu_id, "name": tool_name, "input": {}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tu_id,
             "content": json.dumps(payload, ensure_ascii=False)},
        ]},
    ]


def test_compress_skips_short_history():
    """Below trigger threshold → no compression, return as-is (modulo
    in-place tool_result truncation which is a no-op for short payloads)."""
    sess = _sess_with_ops(2)
    msgs = [{"role": "user", "content": "go"}]
    for _ in range(3):
        msgs += _msg_pair("add_node", {"node_id": "n1"})
    out = compress_messages(msgs, sess, trigger_turns=COMPRESSION_TRIGGER_TURNS)
    # 3 turn pairs ≪ trigger 8 → unchanged length
    assert len(out) == len(msgs)


def test_compress_long_history_collapses_old_pairs():
    """12 turns of history (≫ trigger) → keep messages[0] + 1 synopsis +
    last (window×2)=10 messages = 12 total. Original was 1 + 12*2 = 25."""
    sess = _sess_with_ops(12)
    msgs: list[dict] = [{"role": "user", "content": "go"}]
    for i in range(12):
        # interleave verbose validate results so we see compression hit
        if i == 5:
            msgs += _msg_pair("validate", {"valid": False,
                                           "errors": [{"i": k} for k in range(8)]})
        elif i == 7:
            msgs += _msg_pair("run_preview", {"rows": [{"i": k} for k in range(50)]})
        else:
            msgs += _msg_pair("add_node", {"node_id": f"n{i+1}"})

    out = compress_messages(msgs, sess, window=5, trigger_turns=8)

    # Structure: [user_prompt, synopsis, ...last 10 msgs]
    assert len(out) == 1 + 1 + 10
    assert out[0] == msgs[0]
    assert out[1]["role"] == "assistant"
    text = out[1]["content"][0]["text"]
    assert "Earlier in this build" in text
    assert "Current canvas state:" in text
    # Last 10 messages preserved verbatim by index
    assert out[-1] == _truncate_recent_msg_inline(msgs[-1])


def test_compress_falls_back_on_internal_error(monkeypatch):
    sess = _sess_with_ops(12)
    msgs = [{"role": "user", "content": "go"}] + (_msg_pair("add_node", {"node_id": "n1"}) * 12)

    def boom(*_a, **_k):
        raise RuntimeError("synthetic")

    # Force the impl to crash and assert we still get the original messages back
    import python_ai_sidecar.agent_builder.compression as comp
    monkeypatch.setattr(comp, "_compress_messages_impl", boom)
    out = compress_messages(msgs, sess)
    assert out is msgs  # exact pass-through on error


def test_compress_preserves_first_user_prompt():
    sess = _sess_with_ops(15)
    user = {"role": "user", "content": "build pipeline X"}
    msgs = [user] + (_msg_pair("add_node", {"node_id": "n1"}) * 15)
    out = compress_messages(msgs, sess, window=5, trigger_turns=8)
    assert out[0] is user


# Helper: inline call to module-private truncator so structural compare
# above doesn't fail on the verbose-result rewriting that happens during
# compression to retained recent messages.
def _truncate_recent_msg_inline(m):
    from python_ai_sidecar.agent_builder.compression import _truncate_recent_msg
    return _truncate_recent_msg(m)
