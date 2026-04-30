"""state.py — defaults + constants for the LangGraph agent loop.

⚠️ The **schema** (TypedDict + reducers) lives in
[graph.py:GraphState](graph.py). LangGraph uses *that* as the
authoritative shape; anything not declared in GraphState is silently
dropped from initial_state. Don't add a new state field here without
also adding it to GraphState.

This module exposes only:
  - DEFAULT_STATE  — initial values spread into orchestrator.run()'s
                     initial_state dict
  - MAX_ITERATIONS — outer-loop safety cap

The previous AGENT_STATE_SCHEMA dict and AgentState dict-subclass were
deleted in 2026-04-30 after they masked a real bug — they looked
authoritative but graph.py:GraphState was actually canonical, so adding
`mode` / `pipeline_snapshot` to AGENT_STATE_SCHEMA gave false confidence
that the wiring was complete when in fact LangGraph still saw nothing.
"""

from __future__ import annotations

from typing import Any, Dict


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
    "pipeline_snapshot": None,
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
