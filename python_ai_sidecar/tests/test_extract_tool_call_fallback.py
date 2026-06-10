"""Cover the phase_complete synthesis fallback in _extract_tool_call.

KIMI K2.5 on OpenRouter (and likely other non-Anthropic providers) replies
in plain text when it wants to end a phase, instead of calling the
phase_complete tool. Without the fallback, the graph replays the same
prompt and KIMI then re-adds the previous node (verified in
/tmp/builder-traces/20260610-142738-d2ebd8ecf2c5.json).

The fallback synthesizes a phase_complete tool_use when (and only when)
the text clearly signals "phase done" intent. Generic agent chatter must
NOT trigger.
"""
from __future__ import annotations

from types import SimpleNamespace

from python_ai_sidecar.agent_builder.graph_build.nodes.agentic_phase_loop import (
    _extract_tool_call,
)


def _resp_with_blocks(blocks):
    return SimpleNamespace(content=blocks)


def _text(t: str) -> dict:
    return {"type": "text", "text": t}


def _tool_use(name: str, inp: dict, tid: str = "tu_x") -> dict:
    return {"type": "tool_use", "name": name, "input": inp, "id": tid}


# ── Happy path: real tool_use wins, no synth ──────────────────────────────

def test_real_tool_use_returned():
    resp = _resp_with_blocks([_tool_use("add_node", {"block_name": "block_x"})])
    out = _extract_tool_call(resp)
    assert out is not None
    assert out["name"] == "add_node"
    assert out["id"] == "tu_x"


def test_tool_use_with_extra_text_still_wins_over_synth():
    # If both text "phase complete..." AND a real tool_use are present,
    # the real tool_use must win (synth is fallback only).
    resp = _resp_with_blocks([
        _text("Phase p1 complete; running verifier"),
        _tool_use("run_verifier", {}, "tu_v"),
    ])
    out = _extract_tool_call(resp)
    assert out is not None
    assert out["name"] == "run_verifier"


# ── Fallback triggers ─────────────────────────────────────────────────────

def test_text_phase_complete_synthesizes_phase_complete():
    text = "Phase p1 complete. block_process_history fetched 100 rows."
    resp = _resp_with_blocks([_text(text)])
    out = _extract_tool_call(resp)
    assert out is not None
    assert out["name"] == "phase_complete"
    assert out["id"] == "synth_phase_complete"
    assert text in out["args"]["rationale"]


def test_text_phase_goal_achieved_synthesizes_phase_complete():
    resp = _resp_with_blocks([_text("Phase goal achieved — moving on.")])
    out = _extract_tool_call(resp)
    assert out is not None
    assert out["name"] == "phase_complete"


def test_text_phase_done_synthesizes_phase_complete():
    # Tight pattern: phase immediately followed by done/complete/finished
    # (with optional pN between). "This phase IS done" doesn't fire —
    # avoids false positives on conditional / future tense like
    # "this phase is done only after X" or "the phase will be done".
    resp = _resp_with_blocks([_text("Phase done.")])
    out = _extract_tool_call(resp)
    assert out is not None
    assert out["name"] == "phase_complete"


def test_text_phase_pN_finished_synthesizes_phase_complete():
    resp = _resp_with_blocks([_text("Phase p2 finished successfully.")])
    out = _extract_tool_call(resp)
    assert out is not None
    assert out["name"] == "phase_complete"


# ── Fallback DOES NOT trigger on generic chatter ──────────────────────────

def test_generic_text_does_not_synthesize():
    resp = _resp_with_blocks([_text("I think we're done with this step.")])
    assert _extract_tool_call(resp) is None


def test_thinking_text_does_not_synthesize():
    resp = _resp_with_blocks([_text(
        "Let me check the upstream output before deciding what block to add."
    )])
    assert _extract_tool_call(resp) is None


def test_text_mentioning_phase_without_done_keyword_does_not_synthesize():
    resp = _resp_with_blocks([_text(
        "Phase p1 needs a source block for SPC history data."
    )])
    assert _extract_tool_call(resp) is None


# ── Edge cases ────────────────────────────────────────────────────────────

def test_empty_content_returns_none():
    resp = _resp_with_blocks([])
    assert _extract_tool_call(resp) is None


def test_non_list_content_returns_none():
    resp = SimpleNamespace(content="phase complete")
    assert _extract_tool_call(resp) is None


def test_long_rationale_truncated_to_500_chars():
    long_text = "Phase p1 complete. " + ("blah " * 200)
    resp = _resp_with_blocks([_text(long_text)])
    out = _extract_tool_call(resp)
    assert out is not None
    assert len(out["args"]["rationale"]) <= 500
