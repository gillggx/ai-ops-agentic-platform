"""graph.py — assemble the LangGraph StateGraph for the v2 agent orchestrator.

Phase 2-B: happy path only (no HITL, no self-critique, no memory lifecycle).
These will be added in Phase 2-C as additional nodes + conditional edges.

Graph topology:
    load_context → llm_call ←─┐
                       │       │
              ┌────────┴───┐   │
              │            │   │
         (tool_calls)  (end_turn)
              │            │
              ▼            ▼
        tool_execute   synthesis
              │            │
              └──► llm_call│
                   (loop)  ▼
                          END
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Literal

from langgraph.graph import END, StateGraph

from typing import Annotated, Any, Dict, List, Optional, Sequence

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from python_ai_sidecar.agent_orchestrator_v2.state import MAX_ITERATIONS
from python_ai_sidecar.agent_orchestrator_v2.nodes.load_context import load_context_node
from python_ai_sidecar.agent_orchestrator_v2.nodes.intent_classifier import intent_classifier_node
from python_ai_sidecar.agent_orchestrator_v2.nodes.intent_completeness import intent_completeness_node
from python_ai_sidecar.agent_orchestrator_v2.nodes.llm_call import llm_call_node
from python_ai_sidecar.agent_orchestrator_v2.nodes.tool_execute import tool_execute_node
from python_ai_sidecar.agent_orchestrator_v2.nodes.synthesis import synthesis_node
from python_ai_sidecar.agent_orchestrator_v2.nodes.self_critique import self_critique_node
from python_ai_sidecar.agent_orchestrator_v2.nodes.memory_lifecycle import memory_lifecycle_node


# ── Reducer helpers ──────────────────────────────────────────────────
def _replace(existing, new):
    """Simple replace reducer — last write wins."""
    return new


def _extend_list(existing, new):
    """Append-only list reducer."""
    if existing is None:
        return new or []
    return (existing or []) + (new or [])


# ── Typed state for key-level merging ────────────────────────────────
# LangGraph merges node outputs key-by-key using these reducers.
# Keys not returned by a node keep their previous value (not deleted).
from typing import TypedDict


class GraphState(TypedDict, total=False):
    # Input (set once, never overwritten by nodes)
    user_id: int
    session_id: Optional[str]
    user_message: Annotated[str, _replace]
    canvas_overrides: Optional[Dict[str, Any]]
    client_context: Optional[Dict[str, Any]]
    # Phase E2: "chat" (default) or "builder" — controls system-prompt bias.
    # Only present in TypedDict so LangGraph propagates it through nodes;
    # without this key the run() kwarg is silently dropped from initial_state
    # and load_context.py always sees state.get("mode") == None → "chat".
    mode: Annotated[str, _replace]
    # Phase E3 follow-up: snapshot of the canvas the user is on (with declared
    # inputs / nodes). load_context surfaces it to the user-facing system prompt
    # AND tool_execute injects it as _state_pipeline_snapshot for build_pipeline_live
    # so Glass Box sub-agent reuses $name references instead of writing literals.
    pipeline_snapshot: Annotated[Optional[Dict[str, Any]], _replace]
    # Part A — intent classifier output. "clear_chart" / "clear_rca" /
    # "clear_status" / "vague" / "clarified" (re-submit). Read by llm_call to
    # tweak guidance; read by graph routing to short-circuit on vague.
    intent: Annotated[str, _replace]
    intent_hint: Annotated[Optional[str], _replace]

    # Messages — merge via add_messages (handles dedup by id)
    messages: Annotated[Sequence[AnyMessage], add_messages]

    # Context (set by load_context, read by llm_call/synthesis)
    system_blocks: Annotated[List[Dict[str, Any]], _replace]
    system_text: Annotated[str, _replace]
    retrieved_memory_ids: Annotated[List[int], _replace]
    context_meta: Annotated[Dict[str, Any], _replace]
    history_turns: Annotated[int, _replace]

    # Tool tracking (accumulated across iterations)
    tools_used: Annotated[List[Dict[str, Any]], _extend_list]
    render_cards: Annotated[List[Dict[str, Any]], _extend_list]
    current_iteration: Annotated[int, _replace]

    # Flags
    chart_already_rendered: Annotated[bool, _replace]
    last_spc_result: Annotated[Optional[tuple], _replace]
    force_synthesis: Annotated[bool, _replace]

    # Outputs
    final_text: Annotated[str, _replace]
    contract: Annotated[Optional[Dict[str, Any]], _replace]

    # Self-critique
    reflection_result: Annotated[Optional[Dict[str, Any]], _replace]

    # Memory lifecycle
    cited_memory_ids: Annotated[List[int], _replace]
    memory_write_scheduled: Annotated[bool, _replace]

    # Generative UI (data pipeline)
    flat_data: Annotated[Optional[Dict[str, Any]], _replace]
    flat_metadata: Annotated[Optional[Dict[str, Any]], _replace]
    ui_config: Annotated[Optional[Dict[str, Any]], _replace]


# Module-level invariant: every key passed by orchestrator.run() into
# initial_state MUST be declared in GraphState above, otherwise LangGraph
# silently drops it and downstream nodes read None. Fails import on drift.
from python_ai_sidecar._boot_invariants import assert_graph_state_covers_run_kwargs
assert_graph_state_covers_run_kwargs(GraphState.__annotations__.keys())


logger = logging.getLogger(__name__)


def _route_after_intent(state: Dict[str, Any]) -> Literal["synthesis", "intent_completeness", "llm_call"]:
    """Route after intent_classifier:
      - vague (or any other force_synthesis): straight to synthesis (clarify card already emitted).
      - clear_chart / clear_rca / clear_status: through completeness gate first.
      - clarified (re-submit from clarify card): skip gate, go to llm_call.
    """
    if state.get("force_synthesis") or state.get("intent") == "vague":
        return "synthesis"
    intent = (state.get("intent") or "").lower()
    if intent.startswith("clear_"):
        return "intent_completeness"
    return "llm_call"


def _route_after_completeness(state: Dict[str, Any]) -> Literal["synthesis", "llm_call"]:
    """Route after intent_completeness:
      - incomplete (force_synthesis): synthesis renders the design-intent card.
      - complete (no flag set): proceed to llm_call as normal.
    """
    if state.get("force_synthesis"):
        return "synthesis"
    return "llm_call"


def _should_continue(state: Dict[str, Any]) -> Literal["tool_execute", "synthesis"]:
    """Route after llm_call: tool_calls → execute; end_turn → synthesis."""
    # Force synthesis takes priority (unrecoverable error, max iterations, etc.)
    if state.get("force_synthesis"):
        return "synthesis"

    if state.get("current_iteration", 0) >= MAX_ITERATIONS:
        logger.warning("Max iterations (%d) reached — forcing synthesis", MAX_ITERATIONS)
        return "synthesis"

    # Check last message for tool_calls
    messages = state.get("messages", [])
    if messages:
        last = messages[-1]
        if hasattr(last, "tool_calls") and last.tool_calls:
            return "tool_execute"

    return "synthesis"


def _after_tools(state: Dict[str, Any]) -> Literal["llm_call", "synthesis"]:
    """Route after tool_execute: loop back for more LLM thinking or finish."""
    if state.get("force_synthesis"):
        return "synthesis"
    if state.get("current_iteration", 0) >= MAX_ITERATIONS:
        return "synthesis"
    return "llm_call"


def build_graph() -> StateGraph:
    """Build and return the compiled LangGraph StateGraph.

    Returns an uncompiled graph — the caller compiles it with a checkpointer.
    """
    # TypedDict-based state — LangGraph does key-level merging with reducers.
    # Nodes only need to return the keys they change; other keys are preserved.
    graph = StateGraph(GraphState)

    # ── Nodes ────────────────────────────────────────────────────────
    graph.add_node("load_context", load_context_node)
    graph.add_node("intent_classifier", intent_classifier_node)
    graph.add_node("intent_completeness", intent_completeness_node)
    graph.add_node("llm_call", llm_call_node)
    graph.add_node("tool_execute", tool_execute_node)
    graph.add_node("synthesis", synthesis_node)
    graph.add_node("self_critique", self_critique_node)
    graph.add_node("memory_lifecycle", memory_lifecycle_node)

    # ── Edges ────────────────────────────────────────────────────────
    # load_context → intent_classifier
    #   ├─ vague                    → synthesis (clarify card already emitted)
    #   ├─ clear_*                  → intent_completeness
    #   │     ├─ incomplete         → synthesis (design-intent card emitted)
    #   │     └─ complete           → llm_call
    #   └─ clarified / fallback     → llm_call
    graph.set_entry_point("load_context")
    graph.add_edge("load_context", "intent_classifier")
    graph.add_conditional_edges(
        "intent_classifier",
        _route_after_intent,
        {
            "synthesis": "synthesis",
            "intent_completeness": "intent_completeness",
            "llm_call": "llm_call",
        },
    )
    graph.add_conditional_edges(
        "intent_completeness",
        _route_after_completeness,
        {"synthesis": "synthesis", "llm_call": "llm_call"},
    )

    # llm_call → tool_execute (if tool_calls) or → synthesis (if end_turn)
    graph.add_conditional_edges(
        "llm_call",
        _should_continue,
        {"tool_execute": "tool_execute", "synthesis": "synthesis"},
    )

    # tool_execute → llm_call (loop) or → synthesis (force/max iterations)
    graph.add_conditional_edges(
        "tool_execute",
        _after_tools,
        {"llm_call": "llm_call", "synthesis": "synthesis"},
    )

    # synthesis → self_critique → memory_lifecycle → END
    graph.add_edge("synthesis", "self_critique")
    graph.add_edge("self_critique", "memory_lifecycle")
    graph.add_edge("memory_lifecycle", END)

    return graph
