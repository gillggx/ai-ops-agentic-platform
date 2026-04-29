"""AgentState — single source of truth for the LangGraph agent loop.

Replaces the scattered local variables in v1's _run_impl:
  _tools_used, _last_spc_result, _chart_already_rendered,
  _force_synthesis, _plan_extracted, _retrieved_memory_ids, etc.

All nodes read from and write to this state via partial dict updates.
"""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional, Sequence

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class AgentState(dict):
    """LangGraph state for one agent chat turn.

    Using dict subclass so LangGraph can treat it as a TypedDict-like
    while still being mutable for node updates.
    """
    pass


# TypedDict-style annotation for LangGraph — keys and their reducers.
# add_messages merges new messages into the list (handles duplicates by id).
AGENT_STATE_SCHEMA = {
    # ── Input ───────────────────────────────────────────────────────
    "user_id": int,
    "session_id": Optional[str],
    "user_message": str,
    "canvas_overrides": Optional[Dict[str, Any]],
    # Phase E2: "chat" (default) or "builder" — controls system-prompt
    # bias. builder mode lives behind /agent/build (Pipeline Builder
    # canvas-side panel) and tells the LLM to favour build_pipeline_live
    # for any pipeline modification request. chat mode keeps current Q&A
    # / one-shot defaults.
    "mode": str,

    # ── Conversation (LangGraph-managed message list) ───────────────
    "messages": Annotated[Sequence[AnyMessage], add_messages],

    # ── Context (built by load_context node) ────────────────────────
    "system_blocks": List[Dict[str, Any]],       # Anthropic-style content blocks
    "system_text": str,                           # flattened system prompt string
    "retrieved_memory_ids": List[int],
    "context_meta": Dict[str, Any],               # soul_preview, rag_hits, etc.
    "history_turns": int,

    # ── Tool execution tracking ─────────────────────────────────────
    "tools_used": List[Dict[str, Any]],           # [{tool, mcp_name, params, result_text}]
    "current_iteration": int,
    "render_cards": List[Dict[str, Any]],          # accumulated for SSE tool_done events

    # ── Flags (previously scattered local vars) ─────────────────────
    "chart_already_rendered": bool,
    "last_spc_result": Optional[tuple],
    "force_synthesis": bool,
    "plan_extracted": bool,

    # ── Outputs ─────────────────────────────────────────────────────
    "final_text": str,
    "contract": Optional[Dict[str, Any]],
    "reflection_result": Optional[Dict[str, Any]],

    # ── HITL ────────────────────────────────────────────────────────
    "pending_approval_token": Optional[str],
    "pending_approval_tool": Optional[Dict[str, Any]],

    # ── Memory lifecycle ────────────────────────────────────────────
    "cited_memory_ids": List[int],
    "memory_write_scheduled": bool,

    # ── Generative UI (data pipeline) ─────────────────────────────
    "flat_data": Optional[Dict[str, Any]],     # FlattenedResult.to_dict()
    "flat_metadata": Optional[Dict[str, Any]], # metadata for LLM + frontend
    "ui_config": Optional[Dict[str, Any]],     # ChartExplorer configuration

    # ── Plan Panel (v1.4) ─────────────────────────────────────────
    # Live todo list emitted by the agent at the start of each turn.
    # Each item: {id, title, status: "pending"|"in_progress"|"done"|"failed", note?}
    # Frontend renders this as a Claude-Code-style progress checklist.
    "plan_items": List[Dict[str, Any]],
}


# Default values for a fresh state (used by graph invocation)
DEFAULT_STATE: Dict[str, Any] = {
    "messages": [],
    "system_blocks": [],
    "system_text": "",
    "retrieved_memory_ids": [],
    "context_meta": {},
    "history_turns": 0,
    "tools_used": [],
    "current_iteration": 0,
    "render_cards": [],
    "chart_already_rendered": False,
    "last_spc_result": None,
    "force_synthesis": False,
    "plan_extracted": False,
    "final_text": "",
    "contract": None,
    "reflection_result": None,
    "pending_approval_token": None,
    "pending_approval_tool": None,
    "cited_memory_ids": [],
    "memory_write_scheduled": False,
    "canvas_overrides": None,
    "flat_data": None,
    "flat_metadata": None,
    "ui_config": None,
    "plan_items": [],
    "mode": "chat",
}


# Max iterations before force-synthesis (safety cap).
# 2026-04-27: bumped 10 → 25. The original 10 was tuned for direct
# chat / Q&A; once `build_pipeline_live` joined the tool catalog the outer
# loop routinely needs:
#   1× create-plan + 1× invoke-build + N× update_plan(per phase)
#   + a couple of synthesis-prep calls
# which clears 10 easily even when the inner Glass Box ran fine. 25 is the
# new safety cap; if a chat genuinely needs more, SPEC_glassbox_continuation
# v2 should extend the continuation_request UX to the chat path so the user
# decides instead of force_synthesis silently kicking in.
MAX_ITERATIONS = 25
