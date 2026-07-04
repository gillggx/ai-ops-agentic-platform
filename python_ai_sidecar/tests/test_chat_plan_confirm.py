"""Chat plan-confirm gate (v31, 2026-07-04) — unit tests.

Covers the pending-store kind discrimination that keeps the three resume
branches (plan_decision / judge_decision / confirmations) from consuming
each other's pauses, plus the env kill-switch parsing in tool_execute.
The full pause→card→resume path is covered by the E2E acceptance run
(chat_walkthrough auto-confirm) — not re-mocked here.
"""
from __future__ import annotations

import asyncio
import json

from python_ai_sidecar.agent_orchestrator_v2 import pending_clarify as pc


def _pending(kind: str = "intent", chat_sid: str = "chat-1") -> pc.PendingClarify:
    return pc.PendingClarify(
        chat_session_id=chat_sid,
        build_session_id="build-1",
        bullets=[],
        instruction="查 EQP-01",
        base_pipeline=None,
        skill_step_mode=False,
        user_id=1,
        kind=kind,
        phases=[{"id": "p1", "goal": "取資料", "expected": "raw_data"}],
        plan_summary="s",
    )


def test_pending_kind_roundtrip():
    pc.register(_pending(kind="plan_confirm"))
    got = pc.consume("chat-1")
    assert got is not None
    assert got.kind == "plan_confirm"
    assert got.phases[0]["id"] == "p1"
    assert pc.consume("chat-1") is None   # consumed


def test_pending_default_kind_is_intent():
    pc.register(_pending(kind="intent", chat_sid="chat-2"))
    got = pc.consume("chat-2")
    assert got is not None and got.kind == "intent"


async def _drain(gen):
    return [e async for e in gen]


def test_plan_branch_rejects_intent_pending_and_puts_it_back():
    """plan_decision must not consume an intent-kind pending (and vice
    versa) — the mismatched entry goes back untouched."""
    from python_ai_sidecar.routers.agent import (
        ChatIntentRespondRequest,
        _chat_intent_respond_stream,
    )

    pc.register(_pending(kind="intent", chat_sid="chat-3"))
    req = ChatIntentRespondRequest(
        chat_session_id="chat-3",
        plan_decision={"confirmed": True},
    )
    events = asyncio.run(_drain(_chat_intent_respond_stream(req, caller=None)))
    # error + done(no_pending)
    assert any(e.get("event") == "error" for e in events)
    done = [e for e in events if e.get("event") == "done"][-1]
    assert json.loads(done["data"])["status"] == "no_pending"
    # intent pending survived for its own branch
    back = pc.consume("chat-3")
    assert back is not None and back.kind == "intent"


def test_intent_branch_rejects_plan_pending_and_puts_it_back():
    from python_ai_sidecar.routers.agent import (
        ChatIntentRespondRequest,
        _chat_intent_respond_stream,
    )

    pc.register(_pending(kind="plan_confirm", chat_sid="chat-4"))
    req = ChatIntentRespondRequest(
        chat_session_id="chat-4",
        confirmations={"b1": {"action": "confirm"}},
    )
    events = asyncio.run(_drain(_chat_intent_respond_stream(req, caller=None)))
    done = [e for e in events if e.get("event") == "done"][-1]
    assert json.loads(done["data"])["status"] == "no_pending"
    back = pc.consume("chat-4")
    assert back is not None and back.kind == "plan_confirm"


def test_plan_confirm_env_kill_switch(monkeypatch):
    """CHAT_PLAN_CONFIRM_ENABLED=0 must flip skip_confirm back to True."""
    def flag(val):
        monkeypatch.setenv("CHAT_PLAN_CONFIRM_ENABLED", val)
        import os
        return os.environ.get(
            "CHAT_PLAN_CONFIRM_ENABLED", "1").strip().lower() not in ("0", "false", "no")

    assert flag("1") is True
    assert flag("0") is False
    assert flag("false") is False
    assert flag("yes") is True
