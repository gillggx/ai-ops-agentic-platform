"""Agent Console SSE mirror (2026-07-04).

Covers:
- EpisodeRecorder mirrors CONSOLE_MIRROR_TYPES into drain_console_events()
  and nothing else; drain empties the buffer.
- event_wrapper passes `agent_console` events through with raw structured
  fields intact (chat surface parity with builder surface).
- _extract_how_apply pulls the How-to-apply sentence for cited-memory chips.
"""
from __future__ import annotations

from python_ai_sidecar.agent_builder.event_wrapper import wrap_build_event_for_chat
from python_ai_sidecar.agent_builder.session import StreamEvent
from python_ai_sidecar.agent_orchestrator_v2.nodes.load_context import _extract_how_apply
from python_ai_sidecar.observability.episode_recorder import (
    CONSOLE_MIRROR_TYPES,
    EpisodeRecorder,
)


def _make_rec() -> EpisodeRecorder:
    return EpisodeRecorder(session_id="s1", instruction="i", user_id=1)


class TestRecorderConsoleMirror:
    def test_whitelisted_types_are_mirrored(self):
        rec = _make_rec()
        for et in sorted(CONSOLE_MIRROR_TYPES):
            rec.record(et, agent="builder", phase_id="p1", payload={"x": 1})
        out = rec.drain_console_events()
        assert [e["kind"] for e in out] == sorted(CONSOLE_MIRROR_TYPES)
        first = out[0]
        assert first["agent"] == "builder"
        assert first["phase_id"] == "p1"
        assert first["payload"] == {"x": 1}
        assert first["ts"]  # stamped

    def test_non_whitelisted_types_not_mirrored(self):
        rec = _make_rec()
        rec.record("plan_proposed", agent="planner", payload={})
        rec.record("phase_done", agent="builder", phase_id="p1", payload={})
        assert rec.drain_console_events() == []
        # still recorded to the episode buffer
        assert rec.pending() == 2

    def test_llm_usage_mirrors_tokens(self):
        rec = _make_rec()
        rec.record("llm_usage", agent="builder", input_tokens=100,
                   output_tokens=50, cache_read=80)
        out = rec.drain_console_events()
        assert out[0]["kind"] == "llm_usage"
        assert out[0]["input_tokens"] == 100
        assert out[0]["output_tokens"] == 50
        assert out[0]["cache_read"] == 80

    def test_drain_empties(self):
        rec = _make_rec()
        rec.record("memory_recall", agent="planner", payload={"recalled": []})
        assert len(rec.drain_console_events()) == 1
        assert rec.drain_console_events() == []

    def test_mirror_independent_of_network_death(self):
        rec = _make_rec()
        rec._dead = True  # flush failed earlier — mirror must keep working
        rec.record("repair_triggered", agent="repair", phase_id="p2", payload={})
        assert len(rec.drain_console_events()) == 1


class TestEventWrapperPassthrough:
    def test_agent_console_passes_raw_fields(self):
        data = {
            "kind": "verifier_reject",
            "agent": "builder",
            "phase_id": "p2",
            "payload": {"block_id": "block_unnest", "reason": "PARAM_TYPE_WRONG"},
            "ts": "2026-07-04T00:00:00+00:00",
        }
        out = wrap_build_event_for_chat(StreamEvent(type="agent_console", data=data), "sid")
        assert out is not None
        assert out["type"] == "agent_console"
        assert out["kind"] == "verifier_reject"
        assert out["agent"] == "builder"
        assert out["phase_id"] == "p2"
        # raw structured payload preserved verbatim (no text flattening)
        assert out["payload"] == data["payload"]

    def test_memory_write_shape(self):
        data = {"kind": "memory_write", "agent": "planner", "phase_id": None,
                "payload": {"code": "W1", "memo_class": "preference",
                            "title": "t", "status": "active"},
                "ts": "2026-07-04T00:00:00+00:00"}
        out = wrap_build_event_for_chat(StreamEvent(type="agent_console", data=data), "sid")
        assert out is not None and out["payload"]["code"] == "W1"


class TestExtractHowApply:
    def test_extracts_sentence(self):
        body = ("user 改了 phase。\n**Why:** 明確修改。\n"
                "**How to apply:** 同類需求規劃時，預設採用修改後的表述。")
        assert _extract_how_apply(body) == "同類需求規劃時，預設採用修改後的表述。"

    def test_absent_marker_returns_empty(self):
        assert _extract_how_apply("no marker here") == ""

    def test_truncates_long_sentence(self):
        body = "**How to apply:** " + "a" * 500
        assert len(_extract_how_apply(body)) == 160
