"""v30.17a — goal_plan_confirm_gate_node skip_confirm bypass.

Bug: chat orchestrator's build_pipeline_live tool passes skip_confirm=True
("chat conversation IS the confirmation"), but v30 goal_plan_confirm_gate
unconditionally called interrupt() → graph paused → chat tool_execute saw
empty SSE → chat LLM wrote a generic reply → user stuck.

Fix: when state.skip_confirm is True, return phase_in_progress + emit
goal_plan_confirmed SSE, do NOT interrupt.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest


@pytest.fixture
def goal_plan_module():
    from python_ai_sidecar.agent_builder.graph_build.nodes import goal_plan
    return goal_plan


def test_skip_confirm_true_bypasses_interrupt(goal_plan_module):
    """skip_confirm=True → auto-confirm, no interrupt() call."""
    state = {
        "skip_confirm": True,
        "v30_phases": [
            {"id": "p1", "goal": "fetch data", "expected": "raw_data"},
            {"id": "p2", "goal": "transform", "expected": "transform"},
        ],
        "summary": "test plan summary",
        "session_id": "test-session-1",
    }

    # If interrupt() is called, we want the test to fail loudly
    with patch.object(goal_plan_module, "interrupt",
                       side_effect=AssertionError("interrupt() should not be called when skip_confirm=True")):
        result = asyncio.run(goal_plan_module.goal_plan_confirm_gate_node(state))

    assert result["status"] == "phase_in_progress"
    assert result["v30_current_phase_idx"] == 0
    assert result["v30_phase_round"] == 0

    events = result["sse_events"]
    assert len(events) == 1
    # _event returns {"event": name, "data": {...}}
    ev = events[0]
    assert ev["event"] == "goal_plan_confirmed"
    assert ev["data"]["auto_confirmed"] is True
    assert ev["data"]["n_edits"] == 0
    assert len(ev["data"]["phases"]) == 2


def test_skip_confirm_missing_falls_through_to_interrupt(goal_plan_module):
    """No skip_confirm key in state → interrupt() IS called (original behaviour)."""
    state = {
        "v30_phases": [{"id": "p1", "goal": "x", "expected": "raw_data"}],
        "summary": "test",
        "session_id": "test-session-2",
        # no skip_confirm key
    }

    # interrupt() raises a special LangGraph exception in real graph; for
    # this unit test we just verify it IS reached. Use a sentinel exception.
    class _InterruptCalled(Exception):
        pass

    with patch.object(goal_plan_module, "interrupt",
                       side_effect=_InterruptCalled("interrupt was called")):
        with pytest.raises(_InterruptCalled):
            asyncio.run(goal_plan_module.goal_plan_confirm_gate_node(state))


def test_skip_confirm_false_falls_through_to_interrupt(goal_plan_module):
    """skip_confirm=False explicitly → interrupt() IS called."""
    state = {
        "skip_confirm": False,
        "v30_phases": [{"id": "p1", "goal": "x", "expected": "raw_data"}],
        "summary": "t",
        "session_id": "s",
    }

    class _InterruptCalled(Exception):
        pass

    with patch.object(goal_plan_module, "interrupt",
                       side_effect=_InterruptCalled("interrupt")):
        with pytest.raises(_InterruptCalled):
            asyncio.run(goal_plan_module.goal_plan_confirm_gate_node(state))


def test_skip_confirm_with_empty_phases_still_auto_confirms(goal_plan_module):
    """Edge: phases empty + skip_confirm=True → still auto-confirm (downstream
    agentic_phase_loop handles empty-phases case)."""
    state = {
        "skip_confirm": True,
        "v30_phases": [],
        "summary": "",
        "session_id": "s",
    }
    with patch.object(goal_plan_module, "interrupt",
                       side_effect=AssertionError("should not interrupt")):
        result = asyncio.run(goal_plan_module.goal_plan_confirm_gate_node(state))

    assert result["status"] == "phase_in_progress"
    assert result["sse_events"][0]["event"] == "goal_plan_confirmed"
    assert result["sse_events"][0]["data"]["phases"] == []
