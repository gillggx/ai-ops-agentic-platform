"""v30.17j judge_clarify_pause_node — interrupt and wait for user
decision when the LLM-judge detects a data-source deficit case
(rows >= 1 but significantly below user's count quantifier).

Triggered by phase_verifier_node setting state.v30_judge_pause; routed
here by _route_after_phase_verifier. Pauses graph via LangGraph
interrupt(); the wrapper (build_pipeline_live in tool_execute.py)
catches the pause, registers a pending_judge record, and emits
pb_judge_clarify SSE. User picks an action via /chat/intent-respond
which resumes this node with the choice.

User choices:
  - continue: accept current data, advance phase. The verifier's
    deficit gate reads v30_judge_decisions next round and skips the
    pause.
  - replan: re-run goal_plan_node with a relaxed instruction so
    value_desc no longer demands the unattainable N.
  - cancel: route to halt_handover with abort.
"""
from __future__ import annotations

import logging
from typing import Any

from langgraph.types import interrupt

from python_ai_sidecar.agent_builder.graph_build.state import BuildGraphState


logger = logging.getLogger(__name__)


VALID_JUDGE_ACTIONS = {"continue", "replan", "cancel"}

# Cap replans so a stubborn LLM can't loop forever (same plan → same
# deficit → ask again → replan → same plan → ...). After this many
# replans, force-treat next action as 'continue'.
MAX_JUDGE_REPLAN = 1


def _event(name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"type": name, **data}


async def judge_clarify_pause_node(state: BuildGraphState) -> dict[str, Any]:
    pause = state.get("v30_judge_pause") or {}
    pid = pause.get("phase_id") or "?"

    logger.info(
        "judge_clarify_pause_node: pausing for user decision on phase %s "
        "(deficit %s/%s)",
        pid, pause.get("actual_rows"), pause.get("requested_n"),
    )

    user_response = interrupt({
        "kind": "judge_clarify_pending",
        "session_id": state.get("session_id"),
        **pause,
    })

    if not isinstance(user_response, dict):
        action = "cancel"
    else:
        action = str(user_response.get("action") or "cancel").lower()
    if action not in VALID_JUDGE_ACTIONS:
        logger.warning(
            "judge_clarify_pause: invalid action %r — default to cancel",
            action,
        )
        action = "cancel"

    # Persist decision so the verifier knows what to do next round
    decisions = dict(state.get("v30_judge_decisions") or {})
    decisions[pid] = action

    base_update: dict[str, Any] = {
        "v30_judge_decisions": decisions,
        # Clear the pause flag so router doesn't re-enter this node
        "v30_judge_pause": None,
        "sse_events": [_event("judge_clarify_resolved", {
            "phase_id": pid, "action": action,
            "auto_resolved": False,
        })],
    }

    if action == "cancel":
        # Set v30_handover so halt_handover_node fires with abort
        base_update["v30_handover"] = {
            "failed_phase_id": pid,
            "reason": "user_cancelled_judge_clarify",
            "user_choice": "abort",
            "auto_chosen": True,
        }
        base_update["status"] = "cancelled"
        return base_update

    if action == "replan":
        # Cap replan retries — if LLM keeps emitting the same plan after
        # replan_hint, fall back to 'continue' so we don't loop forever
        # (each iteration costs a Haiku call + user click).
        prior_count = int(state.get("v30_judge_replan_count") or 0)
        if prior_count >= MAX_JUDGE_REPLAN:
            logger.warning(
                "judge_clarify_pause: replan budget exhausted (count=%d >= max=%d), "
                "falling back to 'continue' for phase %s",
                prior_count, MAX_JUDGE_REPLAN, pid,
            )
            decisions[pid] = "continue"
            base_update["v30_judge_decisions"] = decisions
            base_update["status"] = "phase_in_progress"
            base_update["sse_events"] = [_event("judge_clarify_resolved", {
                "phase_id": pid, "action": "continue",
                "auto_resolved": True,
                "reason": "replan budget exhausted — proceeding with available data",
            })]
            return base_update
        # Wipe phases + bump replan counter + add modifier hint for goal_plan
        relax_hint = (
            f"前次規劃要求 '{pause.get('value_desc', '')}' 但資料源僅 "
            f"{pause.get('actual_rows')} 筆 (要求 {pause.get('requested_n')} 筆)。"
            f"請改寫 phase {pid} 的 value_desc 移除『N 筆』量詞，改成「可取得的最大量」"
            f"或類似不限定數量的描述。**重要**：不可再寫『{pause.get('requested_n')} 筆』。"
        )
        base_update["v30_phases"] = []
        base_update["v30_current_phase_idx"] = 0
        base_update["v30_replan_hint"] = relax_hint
        base_update["v30_judge_replan_count"] = prior_count + 1
        base_update["status"] = "replan_pending"
        return base_update

    # action == "continue" — verifier will re-run, detect prior decision,
    # treat deficit as accepted, advance the phase.
    base_update["status"] = "phase_in_progress"
    return base_update
