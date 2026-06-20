"""2026-06-20 — goal_plan bounded retry + provider-error classification.

Root cause (SLASH-17 2026-06-20): a SINGLE transient OpenRouter blip
(finish_reason='error' → empty/truncated JSON) at goal_plan killed the whole
build (0 nodes), and the failure trace mislabelled it as a JSON-parse error.

These tests cover:
  - _attempt_plan_parse: classification (provider_error / empty / unparseable)
    and that valid JSON always wins even when the provider flagged an error.
  - goal_plan_node retry loop: one transient blip recovers on retry; a
    persistent failure fails fast after _MAX_PLAN_ATTEMPTS with the true
    error_kind recorded.
"""
from __future__ import annotations

import json

import pytest

from python_ai_sidecar.agent_builder.graph_build.nodes import goal_plan as gp
from python_ai_sidecar.agent_builder.graph_build.nodes.goal_plan import (
    _MAX_PLAN_ATTEMPTS,
    _attempt_plan_parse,
    goal_plan_node,
)


# ── Fakes ───────────────────────────────────────────────────────────

class FakeResp:
    def __init__(self, text="", stop_reason="end_turn", finish_reason="stop",
                 output_tokens=0):
        self.text = text
        self.stop_reason = stop_reason
        self.finish_reason = finish_reason
        self.output_tokens = output_tokens
        self.reasoning_content = ""


class FakeClient:
    """Yields a scripted sequence of responses; records call count."""
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    async def create(self, **_kwargs):
        self.calls += 1
        # repeat the last scripted response once the queue is exhausted
        idx = min(self.calls - 1, len(self._responses) - 1)
        return self._responses[idx]


def _extract(text):
    # mirror plan._extract_first_json_object's contract: raise on no/unbalanced
    s = text.strip()
    if "{" not in s:
        raise ValueError("no JSON object found in LLM output")
    return json.loads(s)  # may raise — caller treats any raise as unparseable


_VALID_PLAN = json.dumps({
    "plan_summary": "ok",
    "phases": [
        {"id": "p1", "goal": "fetch", "expected": "raw_data",
         "expected_output": {"kind": "raw_rows", "value_desc": "rows"}},
        {"id": "p2", "goal": "chart", "expected": "chart",
         "expected_output": {"kind": "chart_spec", "value_desc": "trend"}},
    ],
    "alarm": None,
})


# ── _attempt_plan_parse classification ──────────────────────────────

def test_valid_json_parses_ok():
    decision, kind = _attempt_plan_parse(FakeResp(text=_VALID_PLAN), _extract)
    assert kind is None
    assert decision["phases"][0]["id"] == "p1"


def test_fenced_json_parses_ok():
    fenced = f"```json\n{_VALID_PLAN}\n```"
    decision, kind = _attempt_plan_parse(FakeResp(text=fenced), _extract)
    assert kind is None
    assert decision["plan_summary"] == "ok"


def test_provider_error_empty_classified():
    # finish_reason='error' with empty content (spc-multi-step signature)
    resp = FakeResp(text="", stop_reason="error", finish_reason="error")
    decision, kind = _attempt_plan_parse(resp, _extract)
    assert decision is None
    assert kind == "provider_error"


def test_provider_error_truncated_classified():
    # finish_reason='error' with truncated JSON (apc-drift signature)
    truncated = '{\n  "plan_summary": "x",\n  "phases": [\n    {\n      "id": "p1"'
    resp = FakeResp(text=truncated, stop_reason="error", finish_reason="error")
    decision, kind = _attempt_plan_parse(resp, _extract)
    assert decision is None
    assert kind == "provider_error"


def test_empty_output_without_error_flag():
    resp = FakeResp(text="   ", stop_reason="end_turn")
    decision, kind = _attempt_plan_parse(resp, _extract)
    assert decision is None
    assert kind == "empty_output"


def test_unparseable_non_json_text():
    resp = FakeResp(text="Sure! Here is the plan in prose, no JSON here.",
                    stop_reason="end_turn")
    decision, kind = _attempt_plan_parse(resp, _extract)
    assert decision is None
    assert kind == "unparseable"


def test_valid_json_wins_even_if_error_flag():
    # Never discard a usable plan just because the provider flagged an error.
    resp = FakeResp(text=_VALID_PLAN, stop_reason="error", finish_reason="error")
    decision, kind = _attempt_plan_parse(resp, _extract)
    assert kind is None
    assert decision["phases"][0]["id"] == "p1"


# ── goal_plan_node retry loop ───────────────────────────────────────

@pytest.mark.asyncio
async def test_retry_recovers_after_one_provider_error(monkeypatch):
    """Transient error then a valid plan → create() called twice, no failure."""
    fake = FakeClient([
        FakeResp(text="", stop_reason="error", finish_reason="error"),
        FakeResp(text=_VALID_PLAN, output_tokens=120),
    ])
    monkeypatch.setattr(gp, "get_llm_client", lambda: fake)

    out = await goal_plan_node({"instruction": "EQP-01 xbar trend chart", "user_id": 1})

    assert fake.calls == 2  # retried exactly once
    assert out.get("status") != "failed"
    assert out.get("v30_phases")  # produced phases


@pytest.mark.asyncio
async def test_persistent_provider_error_fails_fast_with_kind(monkeypatch):
    """Always error → fail after _MAX_PLAN_ATTEMPTS with error_kind recorded."""
    fake = FakeClient([FakeResp(text="", stop_reason="error", finish_reason="error")])
    monkeypatch.setattr(gp, "get_llm_client", lambda: fake)

    out = await goal_plan_node({"instruction": "EQP-01 xbar trend chart", "user_id": 1})

    assert fake.calls == _MAX_PLAN_ATTEMPTS  # bounded, no infinite retry
    assert out.get("status") == "failed"
    assert "provider_error" in (out.get("summary") or "")
    # SSE event carries the structured kind for the UI / driver
    evs = out.get("sse_events") or []
    assert any((e.get("data") or {}).get("kind") == "provider_error"
               or "provider_error" in json.dumps(e) for e in evs)
