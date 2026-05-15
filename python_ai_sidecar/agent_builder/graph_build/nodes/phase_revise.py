"""v30 phase_revise_node — self-reflect when a phase exhausts rounds.

Triggered when agentic_phase_loop hits MAX_REACT_ROUNDS or stuck detector
fires. The LLM gets the full action history of the phase + canvas state
and is asked to (a) explain why it stuck, (b) propose 1 alternative
strategy, (c) reset round counter and try once more.

If revise also fails (next round still stuck), halt_handover_node takes
over.

We give phase_revise ONE attempt — if it produces a workable alternative,
clear stuck history and decrement round counter to give the new strategy
a fresh ~half budget. If it can't, escalate.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from python_ai_sidecar.agent_builder.graph_build.state import BuildGraphState
from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client


logger = logging.getLogger(__name__)


# Cap revise attempts per phase. >1 here would let LLM loop between revise +
# round; better to escalate to user once self-reflection fails.
MAX_REVISE_ATTEMPTS_PER_PHASE = 1


_SYSTEM = """你之前在一個 ReAct loop 試 build 一個 pipeline phase，跑了 N round 沒達成目標。

你會收到:
  - CURRENT PHASE goal + expected
  - 完整 action history (你試過什麼 tool + 結果)
  - 當前 canvas state

你的任務:
  1. 用 1-2 句說明 root cause — 為什麼前面 round 沒進展
  2. 提出 1 個明確的 alternative 策略 (e.g. 「改用 X block 而非 Y」、「先 inspect_node_output 看上游再決定」)
  3. 列出 1-3 個 capability gap (若是系統本身缺什麼能力導致做不到)

輸出 JSON (no markdown fence):
{
  "root_cause": "...",
  "alternative_strategy": "...",
  "missing_capabilities": ["...", "..."],
  "can_retry": true | false  // false 表示連你都覺得做不到 -> 直接 halt
}
"""

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.DOTALL)


def _strip_fence(text: str) -> str:
    return _FENCE_RE.sub("", text.strip()).strip()


async def phase_revise_node(state: BuildGraphState) -> dict[str, Any]:
    """One self-reflection pass for the active phase."""
    from python_ai_sidecar.agent_builder.graph_build.nodes.plan import (
        _extract_first_json_object,
    )
    from python_ai_sidecar.agent_builder.graph_build.trace import get_current_tracer

    phases = state.get("v30_phases") or []
    idx = state.get("v30_current_phase_idx", 0)
    if idx >= len(phases):
        return {}
    phase = phases[idx]
    pid = phase["id"]
    tracer = get_current_tracer()

    # Track revise attempts in outcomes
    outcomes = dict(state.get("v30_phase_outcomes") or {})
    prev_outcome = outcomes.get(pid) or {}
    revise_attempts = int(prev_outcome.get("revise_attempts", 0)) + 1

    if revise_attempts > MAX_REVISE_ATTEMPTS_PER_PHASE:
        logger.warning(
            "phase_revise: phase %s revise budget exhausted — escalate to handover",
            pid,
        )
        outcomes[pid] = {
            **prev_outcome,
            "revise_attempts": revise_attempts,
            "status": "failed",
            "fail_reason": "revise_budget_exhausted",
        }
        return {
            "v30_phase_outcomes": outcomes,
            "status": "handover_pending",
            "v30_handover": {
                "failed_phase_id": pid,
                "reason": prev_outcome.get("fail_reason") or "revise budget exhausted",
                "tried_summary": _summarize_actions(state, pid),
                "missing_capabilities": prev_outcome.get("missing_capabilities") or [],
                "options_offered": ["edit_goal", "take_over", "backlog", "abort"],
                "user_choice": None,
            },
            "sse_events": [_event("handover_pending", {
                "failed_phase_id": pid,
                "reason": prev_outcome.get("fail_reason") or "revise budget exhausted",
                "options": ["edit_goal", "take_over", "backlog", "abort"],
            })],
        }

    # Build LLM context — full action history this phase
    recent_actions = (state.get("v30_phase_recent_actions") or {}).get(pid, [])
    action_hist_lines = [f"  - {a.get('tool')}" for a in recent_actions]
    user_msg = (
        f"== CURRENT PHASE ==\n"
        f"id: {pid}\ngoal: {phase['goal']}\nexpected: {phase['expected']}\n\n"
        f"== ACTION HISTORY ({len(recent_actions)} actions) ==\n"
        + ("\n".join(action_hist_lines) if action_hist_lines else "(none)")
        + "\n\n== CANVAS STATE ==\n"
        + json.dumps(
            (state.get("final_pipeline") or {}).get("nodes") or [], default=str,
        )[:1500]
    )

    client = get_llm_client()
    try:
        resp = await client.create(
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
            max_tokens=1024,
        )
        raw = resp.text or ""
        text = _strip_fence(raw)
        try:
            decision = json.loads(text)
        except json.JSONDecodeError:
            decision = _extract_first_json_object(text or "")
    except Exception as ex:  # noqa: BLE001
        logger.warning("phase_revise: LLM failed: %s", ex)
        decision = {"can_retry": False, "root_cause": f"LLM error: {ex}"}

    decision = decision if isinstance(decision, dict) else {}
    can_retry = bool(decision.get("can_retry"))
    root_cause = str(decision.get("root_cause") or "")[:300]
    alt_strategy = str(decision.get("alternative_strategy") or "")[:300]
    missing_caps = decision.get("missing_capabilities") or []
    if not isinstance(missing_caps, list):
        missing_caps = []
    missing_caps = [str(x)[:200] for x in missing_caps[:5]]

    logger.info(
        "phase_revise: phase %s can_retry=%s root_cause=%r",
        pid, can_retry, root_cause[:80],
    )

    if tracer is not None:
        tracer.record_llm(
            "phase_revise_node", system=_SYSTEM, user_msg=user_msg,
            raw_response=raw if 'raw' in locals() else "",
            parsed=decision, resp=resp if 'resp' in locals() else None,
        )
        tracer.record_step(
            "phase_revise_node",
            status="retry" if can_retry else "escalate",
            phase_id=pid, root_cause=root_cause,
            alternative=alt_strategy, missing=missing_caps,
            revise_attempts=revise_attempts,
        )

    outcomes[pid] = {
        **prev_outcome,
        "revise_attempts": revise_attempts,
        "last_revise_root_cause": root_cause,
        "last_revise_alternative": alt_strategy,
        "missing_capabilities": missing_caps,
    }

    if can_retry:
        # Reset stuck history + half-fresh round budget. Clear status back to
        # phase_in_progress so router sends us to agentic_phase_loop.
        new_recent = dict(state.get("v30_phase_recent_actions") or {})
        new_recent[pid] = []  # clear stuck detector window
        # Give 4 fresh rounds (half of MAX_REACT_ROUNDS) by setting round=4
        from python_ai_sidecar.agent_builder.graph_build.nodes.agentic_phase_loop import (
            MAX_REACT_ROUNDS,
        )
        new_round = max(0, MAX_REACT_ROUNDS // 2)
        return {
            "v30_phase_outcomes": outcomes,
            "v30_phase_recent_actions": new_recent,
            "v30_phase_round": new_round,
            "status": "phase_in_progress",
            "sse_events": [_event("phase_revise_retry", {
                "phase_id": pid,
                "root_cause": root_cause,
                "alternative": alt_strategy,
                "fresh_round_budget": MAX_REACT_ROUNDS - new_round,
            })],
        }

    # LLM said can_retry=false — go straight to handover
    outcomes[pid] = {
        **outcomes[pid],
        "status": "failed",
        "fail_reason": "revise_self_rejected",
    }
    return {
        "v30_phase_outcomes": outcomes,
        "status": "handover_pending",
        "v30_handover": {
            "failed_phase_id": pid,
            "reason": root_cause or "phase_revise self-rejected",
            "alternative_tried": alt_strategy,
            "tried_summary": _summarize_actions(state, pid),
            "missing_capabilities": missing_caps,
            "options_offered": ["edit_goal", "take_over", "backlog", "abort"],
            "user_choice": None,
        },
        "sse_events": [_event("handover_pending", {
            "failed_phase_id": pid,
            "reason": root_cause,
            "missing_capabilities": missing_caps,
            "options": ["edit_goal", "take_over", "backlog", "abort"],
        })],
    }


def _summarize_actions(state: BuildGraphState, pid: str) -> list[str]:
    """Compact action history for handover trace."""
    recent = (state.get("v30_phase_recent_actions") or {}).get(pid, [])
    return [str(a.get("tool")) for a in recent[-10:]]


def _event(name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"event": name, "data": data}
