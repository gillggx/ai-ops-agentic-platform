"""StateGraph assembly + checkpointer + run/resume helpers.

Topology (matches docs/PHASE_10_BUILDER_GRAPH_V2.html):

  START → plan → validate
                  ├─ has errors  → repair_plan → validate (loop, max 2)
                  └─ ok → route_after_validate
                          ├─ FROM_SCRATCH    → confirm_gate → dispatch_op
                          └─ INCREMENTAL     → dispatch_op
                                                    │
                                                    ▼
                                              call_tool
                                                    ├─ ok    → route_after_call
                                                    └─ error → repair_op → call_tool (loop, max 2)
                                                              ├─ ok → route_after_call
                                                              └─ escalate → repair_plan
                                              route_after_call:
                                                    ├─ cursor < len → dispatch_op
                                                    └─ done         → finalize → END
"""
from __future__ import annotations

import logging
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from python_ai_sidecar.agent_builder.graph_build.state import BuildGraphState
from python_ai_sidecar.agent_builder.graph_build.nodes.plan import plan_node
from python_ai_sidecar.agent_builder.graph_build.nodes.validate import validate_plan_node
from python_ai_sidecar.agent_builder.graph_build.nodes.repair_plan import (
    MAX_PLAN_REPAIR,
    repair_plan_node,
)
from python_ai_sidecar.agent_builder.graph_build.nodes.confirm import confirm_gate_node
from python_ai_sidecar.agent_builder.graph_build.nodes.dispatch import dispatch_op_node
from python_ai_sidecar.agent_builder.graph_build.nodes.execute import call_tool_node
from python_ai_sidecar.agent_builder.graph_build.nodes.repair_op import (
    MAX_OP_REPAIR,
    repair_op_node,
)
from python_ai_sidecar.agent_builder.graph_build.nodes.finalize import finalize_node
from python_ai_sidecar.agent_builder.graph_build.nodes.layout import layout_node


logger = logging.getLogger(__name__)


# ── Routing functions ──────────────────────────────────────────────────────

def _route_after_validate(state: BuildGraphState) -> str:
    """Plan good? → confirm_gate (or skip to dispatch). Errors? → repair_plan.

    skip_confirm=True (Chat Mode) bypasses confirm_gate even on FROM_SCRATCH:
    the chat conversation IS the confirmation; pausing the chat orchestrator
    mid-tool to wait for a UI click would break the conversational flow.
    """
    errors = state.get("plan_validation_errors") or []
    if errors:
        attempts = state.get("plan_repair_attempts", 0)
        if attempts >= MAX_PLAN_REPAIR:
            logger.warning("route_after_validate: plan_unfixable (attempts=%d)", attempts)
            return "finalize"  # finalize will mark status=failed since no pipeline produced
        return "repair_plan"
    if state.get("skip_confirm"):
        return "dispatch_op"
    if state.get("is_from_scratch"):
        return "confirm_gate"
    return "dispatch_op"


def _route_after_confirm(state: BuildGraphState) -> str:
    """User confirmed? → start executing. Rejected? → END (finalize w/ no-op)."""
    if state.get("user_confirmed") is True:
        return "dispatch_op"
    return "finalize"


def _route_after_call(state: BuildGraphState) -> str:
    """Per-op routing after call_tool ran:
       - last op errored → repair_op
       - last op ok and more ops → dispatch_op
       - last op ok and no more → finalize
    """
    cursor = state.get("cursor", 0)
    plan = state.get("plan") or []

    # cursor was advanced on success in call_tool_node → look at cursor-1 to
    # see what just ran. On error, cursor was NOT advanced.
    if cursor < len(plan):
        last = plan[cursor]  # current cursor still points to the failing op
        if last.get("result_status") == "error":
            attempts = int(last.get("repair_attempts") or 0)
            if attempts >= MAX_OP_REPAIR:
                logger.warning("route_after_call: cursor=%d escalating to repair_plan", cursor)
                return "repair_plan"
            return "repair_op"

    # All ops done?
    if cursor >= len(plan):
        return "finalize"
    return "dispatch_op"


# ── Build the graph (cached) ───────────────────────────────────────────────

_compiled = None


def build_graph():
    """Compile the StateGraph once and cache it. Checkpointer = MemorySaver
    (in-process). Sidecar restart drops paused sessions — same as the v1
    behaviour, see _PAUSED_SESSIONS in orchestrator.py.
    """
    global _compiled
    if _compiled is not None:
        return _compiled

    g: StateGraph = StateGraph(BuildGraphState)
    g.add_node("plan", plan_node)
    g.add_node("validate", validate_plan_node)
    g.add_node("repair_plan", repair_plan_node)
    g.add_node("confirm_gate", confirm_gate_node)
    g.add_node("dispatch_op", dispatch_op_node)
    g.add_node("call_tool", call_tool_node)
    g.add_node("repair_op", repair_op_node)
    g.add_node("finalize", finalize_node)
    g.add_node("layout", layout_node)

    g.add_edge(START, "plan")
    g.add_edge("plan", "validate")
    g.add_conditional_edges(
        "validate",
        _route_after_validate,
        {
            "repair_plan": "repair_plan",
            "confirm_gate": "confirm_gate",
            "dispatch_op": "dispatch_op",
            "finalize": "finalize",
        },
    )
    g.add_edge("repair_plan", "validate")
    g.add_conditional_edges(
        "confirm_gate",
        _route_after_confirm,
        {"dispatch_op": "dispatch_op", "finalize": "finalize"},
    )
    g.add_edge("dispatch_op", "call_tool")
    g.add_conditional_edges(
        "call_tool",
        _route_after_call,
        {
            "dispatch_op": "dispatch_op",
            "repair_op": "repair_op",
            "repair_plan": "repair_plan",
            "finalize": "finalize",
        },
    )
    g.add_edge("repair_op", "call_tool")
    g.add_edge("finalize", "layout")
    g.add_edge("layout", END)

    checkpointer = MemorySaver()
    _compiled = g.compile(checkpointer=checkpointer)
    return _compiled
