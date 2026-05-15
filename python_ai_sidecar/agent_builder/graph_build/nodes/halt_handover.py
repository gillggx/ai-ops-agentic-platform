"""v30 halt_handover_node — interrupt and wait for user choice.

Triggered when a phase fails even after phase_revise. Pauses the graph,
emits handover_pending SSE with 4 options, waits for user decision via
/agent/build/handover endpoint.

User choices:
  - edit_goal — user rewrites the phase goal; resume from agentic_phase_loop
  - take_over — accept partial build, route to finalize with build_partial status
  - backlog — log missing_capabilities to a TODO list, then take_over
  - abort — clear pipeline, route to finalize with status=failed
"""
from __future__ import annotations

import logging
from typing import Any

from langgraph.types import interrupt

from python_ai_sidecar.agent_builder.graph_build.state import BuildGraphState


logger = logging.getLogger(__name__)


VALID_CHOICES = {"edit_goal", "take_over", "backlog", "abort"}


async def halt_handover_node(state: BuildGraphState) -> dict[str, Any]:
    handover = state.get("v30_handover") or {}
    pid = handover.get("failed_phase_id")
    logger.info("halt_handover_node: pausing for user choice on phase %s", pid)

    user_response = interrupt({
        "kind": "handover_pending",
        "session_id": state.get("session_id"),
        "failed_phase_id": pid,
        "reason": handover.get("reason"),
        "tried_summary": handover.get("tried_summary"),
        "missing_capabilities": handover.get("missing_capabilities", []),
        "options": list(VALID_CHOICES),
    })

    if not isinstance(user_response, dict):
        choice = "abort"
    else:
        choice = str(user_response.get("choice") or "abort").lower()
    if choice not in VALID_CHOICES:
        logger.warning("halt_handover: invalid choice %r — default to abort", choice)
        choice = "abort"

    new_handover = {**handover, "user_choice": choice}
    base = {
        "v30_handover": new_handover,
        "sse_events": [_event("handover_chosen", {
            "failed_phase_id": pid, "choice": choice,
        })],
    }

    if choice == "edit_goal":
        new_goal = str(user_response.get("new_goal") or "").strip()
        if new_goal:
            phases = list(state.get("v30_phases") or [])
            idx = state.get("v30_current_phase_idx", 0)
            if idx < len(phases):
                old_goal = phases[idx].get("goal", "")
                phases[idx] = {
                    **phases[idx],
                    "goal": new_goal,
                    "user_edited": True,
                }
                edit_hist = dict(state.get("v30_phase_edit_history") or {})
                edit_hist.setdefault(pid, []).append({"from": old_goal, "to": new_goal})
                # Reset phase round + recent actions for fresh try
                new_recent = dict(state.get("v30_phase_recent_actions") or {})
                new_recent[pid] = []
                return {
                    **base,
                    "v30_phases": phases,
                    "v30_phase_edit_history": edit_hist,
                    "v30_phase_round": 0,
                    "v30_phase_recent_actions": new_recent,
                    "status": "phase_in_progress",
                    "v30_handover": None,  # clear handover so loop re-enters
                }
        # No new_goal supplied; fall through to take_over
        logger.info("halt_handover: edit_goal chosen but no new_goal — treating as take_over")
        choice = "take_over"

    if choice == "take_over":
        return {
            **base,
            "status": "build_partial",
            "summary": "User chose to take over manually; canvas preserved.",
        }

    if choice == "backlog":
        # Log capability gap to a JSON file then proceed as take_over
        _persist_backlog(handover)
        return {
            **base,
            "status": "build_partial",
            "summary": "Capability gap logged to backlog; canvas preserved for manual continuation.",
        }

    # abort
    return {
        **base,
        "status": "failed",
        "final_pipeline": None,
        "summary": "User aborted the build.",
    }


def _persist_backlog(handover: dict) -> None:
    """Append capability gap to /tmp/v30_backlog.jsonl (POC simple impl)."""
    import json, os, time
    try:
        line = {
            "ts": time.time(),
            "failed_phase_id": handover.get("failed_phase_id"),
            "reason": handover.get("reason"),
            "missing_capabilities": handover.get("missing_capabilities", []),
            "tried_summary": handover.get("tried_summary"),
        }
        path = os.environ.get("V30_BACKLOG_PATH", "/tmp/v30_backlog.jsonl")
        with open(path, "a") as f:
            f.write(json.dumps(line, default=str) + "\n")
    except Exception as ex:  # noqa: BLE001
        logger.warning("halt_handover: backlog persist failed: %s", ex)


def _event(name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"event": name, "data": data}
