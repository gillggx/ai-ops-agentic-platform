"""v30.24 — consecutive empty-response guard in agentic_phase_loop.

Root cause (trace 20260704-200624): GLM returned reasoning-only completions
(finish_reason=stop, empty content, no tool call) for 19 consecutive rounds.
The loop re-prompted with byte-identical context, so the model repeated the
failure deterministically while the chat UI looked frozen.

Guard: nudge (context-changing user message) each empty round; escalate to
phase_revise after MAX_CONSECUTIVE_NO_ACTION consecutive empties.
"""
from __future__ import annotations

from python_ai_sidecar.agent_builder.graph_build.nodes.agentic_phase_loop import (
    MAX_CONSECUTIVE_NO_ACTION,
    NO_ACTION_NUDGE,
    _handle_no_action,
)


def _state(no_action=None, messages=None):
    return {
        "v30_phase_no_action": no_action or {},
        "v30_phase_messages": messages or {},
    }


def test_first_empty_appends_nudge_and_counts():
    msgs = [{"role": "user", "content": "obs"}]
    patch = _handle_no_action(
        _state(), pid="p3", round_n=1,
        phase_messages=msgs, assistant_content=[],
    )
    assert patch["v30_phase_no_action"]["p3"] == 1
    assert "status" not in patch
    out_msgs = patch["v30_phase_messages"]["p3"]
    # assistant placeholder + nudge appended, roles alternate
    assert out_msgs[-2]["role"] == "assistant"
    assert out_msgs[-1] == {"role": "user", "content": NO_ACTION_NUDGE}
    ev = patch["sse_events"][0]
    assert ev["data"]["no_action"] is True
    assert ev["data"]["consecutive_no_action"] == 1


def test_escalates_at_cap():
    patch = _handle_no_action(
        _state(no_action={"p3": MAX_CONSECUTIVE_NO_ACTION - 1}),
        pid="p3", round_n=5,
        phase_messages=[{"role": "user", "content": "obs"}],
        assistant_content=[],
    )
    assert patch["status"] == "phase_revise_pending"
    assert patch["v30_phase_no_action"]["p3"] == MAX_CONSECUTIVE_NO_ACTION
    ev = patch["sse_events"][0]
    assert ev["event"] == "phase_revise_started" or (
        ev.get("data", {}).get("reason") == "empty_llm_responses"
    )


def test_counter_is_per_phase():
    patch = _handle_no_action(
        _state(no_action={"p2": 2}), pid="p3", round_n=0,
        phase_messages=[{"role": "user", "content": "obs"}],
        assistant_content=[],
    )
    # p2's history must not push p3 into escalation
    assert "status" not in patch
    assert patch["v30_phase_no_action"] == {"p2": 2, "p3": 1}


def test_text_only_assistant_content_kept_tool_use_stripped():
    content = [
        {"type": "text", "text": "let me think"},
        {"type": "tool_use", "id": "x", "name": "add_node", "input": {}},
    ]
    patch = _handle_no_action(
        _state(), pid="p1", round_n=0,
        phase_messages=[{"role": "user", "content": "obs"}],
        assistant_content=content,
    )
    assistant = patch["v30_phase_messages"]["p1"][-2]
    kinds = [b["type"] for b in assistant["content"]]
    assert "tool_use" not in kinds
    assert "text" in kinds
