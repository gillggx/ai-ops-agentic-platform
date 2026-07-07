"""plan_patch_node — Planner M2「計畫修訂」(成本結構修正 波2, 2026-07-07).

Before: when a phase exhausted its revise budget the ONLY exits were
handover (stop and ask the user) or a full replan that regenerated the
whole plan — completed phases' work was thrown away and their data
refetched. Planner could only「砍掉重練」.

Now: the escalation first tries a PLAN PATCH — the Planner receives the
failure diagnosis and outputs minimal ops against the CURRENT plan:

    {"ops": [{"op": "update_phase", "id": "p4", "phase": {...}},
             {"op": "remove_phase", "id": "p5"}],
     "reason": "..."}

Hard rules (deterministically enforced AFTER the LLM, never trusted):
  - the immutable prefix: phases already completed (advanced/success
    outcome) can never be touched — their ids, outcomes and source-cache
    keys stay valid, so nothing re-runs and nothing re-fetches;
  - only update_phase / remove_phase in v1 (insert escalates to the old
    handover path — adding scope mid-repair needs the human);
  - the failed phase must be addressed by at least one op;
  - patched phases keep the {id, goal, expected} shape.

Budget: 2 patches per build session; the 3rd escalation goes to handover
exactly as before (fallback unchanged). Division of labor per the agreed
behavior spec: the diagnosis (why) comes IN from the escalation; the
Planner only decides what-instead.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from python_ai_sidecar.agent_builder.graph_build.state import BuildGraphState
from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client

logger = logging.getLogger(
    "python_ai_sidecar.agent_builder.graph_build.nodes.plan_patch")

MAX_PLAN_PATCHES = 2
_ALLOWED_OPS = {"update_phase", "remove_phase"}
_VALID_EXPECTED = {"raw_data", "transform", "chart", "verdict", "alarm", "scalar", "chart_list", "table"}

_SYSTEM = """你是 Planner。某個建置 phase 反覆失敗，診斷已經完成 — 你不需要重新診斷，
只要決定「計畫改成怎樣」。輸出對現行計畫的最小修訂（JSON）：

{"ops": [{"op": "update_phase", "id": "<phase id>", "phase": {"id": "<同 id>", "goal": "...", "expected": "..."}}
        , {"op": "remove_phase", "id": "<phase id>"}],
 "reason": "一句話說明修訂邏輯"}

規則：
- 只能動「尚未完成」的 phases（會列給你）。已完成的 phases 是不可變的。
- 失敗的 phase 必須被處理（改寫它、或移除它並讓後續 phase 涵蓋）。
- 修訂是手段不是重寫：能少動就少動。goal 寫意圖不寫 block 名（計畫層原則）。
- 若你判斷整份計畫的方向就是錯的、小修救不了 → 輸出 {"ops": [], "reason": "why"}。
只輸出 JSON。"""


def apply_plan_patch(
    phases: list[dict[str, Any]],
    completed_ids: set[str],
    failed_pid: str,
    ops: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]] | None, str]:
    """Pure patch application with hard-rule validation.

    Returns (new_phases, "") on success or (None, reason) on rejection —
    the caller treats rejection as「這張補丁不能用」, not as a crash.
    """
    if not ops:
        return None, "empty ops"
    by_id = {p.get("id"): p for p in phases}
    touched: set[str] = set()
    out = [dict(p) for p in phases]
    for op in ops:
        if not isinstance(op, dict):
            return None, "op is not an object"
        kind = op.get("op")
        pid = str(op.get("id") or "")
        if kind not in _ALLOWED_OPS:
            return None, f"op '{kind}' not allowed (v1: update/remove only)"
        if pid not in by_id:
            return None, f"unknown phase id '{pid}'"
        if pid in completed_ids:
            return None, f"phase '{pid}' is completed — immutable prefix"
        touched.add(pid)
        if kind == "update_phase":
            new_phase = op.get("phase")
            if not isinstance(new_phase, dict):
                return None, f"update_phase '{pid}' missing phase object"
            goal = str(new_phase.get("goal") or "").strip()
            expected = str(new_phase.get("expected") or "").strip()
            if not goal or not expected:
                return None, f"phase '{pid}' patch needs goal + expected"
            if expected not in _VALID_EXPECTED:
                return None, f"phase '{pid}' expected '{expected}' invalid"
            for i, p in enumerate(out):
                if p.get("id") == pid:
                    out[i] = {**p, "goal": goal[:400], "expected": expected}
        else:  # remove_phase
            out = [p for p in out if p.get("id") != pid]
    if failed_pid not in touched:
        return None, f"failed phase '{failed_pid}' not addressed by any op"
    if not out:
        return None, "patch removed every phase"
    return out, ""


async def plan_patch_node(state: BuildGraphState) -> dict[str, Any]:
    from python_ai_sidecar.agent_builder.graph_build.nodes.plan import (
        _extract_first_json_object,
    )
    from python_ai_sidecar.agent_builder.graph_build.trace import get_current_tracer

    phases = state.get("v30_phases") or []
    idx = state.get("v30_current_phase_idx", 0)
    outcomes = dict(state.get("v30_phase_outcomes") or {})
    diagnosis = state.get("v30_patch_diagnosis") or {}
    failed_pid = str(diagnosis.get("failed_phase_id") or (phases[idx]["id"] if idx < len(phases) else ""))
    patch_count = int(state.get("v30_plan_patch_count") or 0)
    tracer = get_current_tracer()

    def _handover(reason: str) -> dict[str, Any]:
        """Fallback = the exact pre-M2 handover shape (behavior unchanged)."""
        logger.info("plan_patch: falling back to handover (%s)", reason)
        return {
            "status": "handover_pending",
            "v30_handover": {
                "failed_phase_id": failed_pid,
                "reason": diagnosis.get("reason") or reason,
                "tried_summary": diagnosis.get("tried_summary") or "",
                "missing_capabilities": diagnosis.get("missing_capabilities") or [],
                "options_offered": ["edit_goal", "take_over", "backlog", "abort"],
                "user_choice": None,
            },
            "sse_events": [_sse("handover_pending", {
                "failed_phase_id": failed_pid,
                "reason": diagnosis.get("reason") or reason,
                "options": ["edit_goal", "take_over", "backlog", "abort"],
            })],
        }

    if patch_count >= MAX_PLAN_PATCHES:
        return _handover(f"plan patch budget exhausted ({patch_count})")
    if not phases or idx >= len(phases):
        return _handover("no active phase")

    completed_ids = {
        pid for pid, o in outcomes.items()
        if isinstance(o, dict) and str(o.get("status") or "") in ("advanced", "success", "finished")
    }
    editable = [p for p in phases if p.get("id") not in completed_ids]
    kept = [p.get("id") for p in phases if p.get("id") in completed_ids]

    user_msg = (
        "== 原始指令 ==\n" + str(state.get("instruction") or "")[:400]
        + "\n\n== 現行計畫 ==\n"
        + json.dumps([{k: p.get(k) for k in ("id", "goal", "expected")} for p in phases],
                     ensure_ascii=False)
        + "\n\n== 已完成（不可變）==\n" + json.dumps(kept, ensure_ascii=False)
        + "\n\n== 可修訂 ==\n"
        + json.dumps([p.get("id") for p in editable], ensure_ascii=False)
        + f"\n\n== 失敗診斷（phase {failed_pid}）==\n"
        + json.dumps({
            "root_cause": diagnosis.get("reason") or "",
            "tried": diagnosis.get("tried_summary") or "",
        }, ensure_ascii=False)
    )

    client = get_llm_client()
    raw = ""
    try:
        resp = await client.create(
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
            max_tokens=1200,
        )
        raw = resp.text or ""
        try:
            decision = json.loads(_strip_fence(raw))
        except json.JSONDecodeError:
            decision = _extract_first_json_object(raw or "")
    except Exception as ex:  # noqa: BLE001
        logger.warning("plan_patch: LLM failed: %s", ex)
        decision = {}

    decision = decision if isinstance(decision, dict) else {}
    ops = decision.get("ops") if isinstance(decision.get("ops"), list) else []
    reason = str(decision.get("reason") or "")[:300]

    if tracer is not None:
        tracer.record_llm("plan_patch_node", system=_SYSTEM, user_msg=user_msg,
                          raw_response=raw, parsed=decision,
                          resp=resp if "resp" in dir() else None)

    new_phases, reject = apply_plan_patch(phases, completed_ids, failed_pid, ops)
    if new_phases is None:
        # One rejected patch consumes budget too (a bad patch IS an attempt) —
        # count it and hand over if this was the last allowed try.
        nxt = patch_count + 1
        if nxt >= MAX_PLAN_PATCHES:
            return {**_handover(f"plan patch rejected: {reject}"),
                    "v30_plan_patch_count": nxt}
        logger.info("plan_patch: rejected (%s) — %d attempt(s) left",
                    reject, MAX_PLAN_PATCHES - nxt)
        return {
            "v30_plan_patch_count": nxt,
            "status": "plan_patch_pending",  # router loops back here once
            "sse_events": [_sse("plan_patch_rejected", {
                "reason": reject, "attempt": nxt,
            })],
        }

    # Patch accepted — reset the failed phase's loop state and resume.
    new_msgs = dict(state.get("v30_phase_messages") or {})
    new_recent = dict(state.get("v30_phase_recent_actions") or {})
    touched_ids = {str(o.get("id")) for o in ops if isinstance(o, dict)}
    for pid in touched_ids:
        new_msgs.pop(pid, None)
        new_recent.pop(pid, None)
        if pid in outcomes:
            outcomes.pop(pid)

    # Recompute current idx: first phase (in new order) that isn't completed.
    new_idx = 0
    for i, p in enumerate(new_phases):
        if p.get("id") not in completed_ids:
            new_idx = i
            break

    try:
        from python_ai_sidecar.observability import get_current_recorder
        rec = get_current_recorder()
        if rec is not None:
            rec.record("plan_patch", agent="planner", phase_id=failed_pid, payload={
                "ops": [{"op": o.get("op"), "id": o.get("id")} for o in ops][:6],
                "preserved": kept,
                "reason": reason[:150],
            })
    except Exception:  # noqa: BLE001
        pass
    if tracer is not None:
        tracer.record_step("plan_patch", status="applied", phase_id=failed_pid,
                           ops=[{"op": o.get("op"), "id": o.get("id")} for o in ops][:6],
                           preserved=kept, reason=reason[:150])
    logger.info("plan_patch: applied %d op(s) on %s (preserved %s)",
                len(ops), sorted(touched_ids), kept)

    return {
        "v30_phases": new_phases,
        "v30_current_phase_idx": new_idx,
        "v30_phase_outcomes": outcomes,
        "v30_phase_messages": new_msgs,
        "v30_phase_recent_actions": new_recent,
        "v30_phase_round": 0,
        "v30_subphase": None,
        "v30_plan_patch_count": patch_count + 1,
        "v30_patch_diagnosis": None,
        "status": "phase_in_progress",
        "sse_events": [_sse("plan_patched", {
            "ops": [{"op": o.get("op"), "id": o.get("id")} for o in ops][:6],
            "preserved": kept,
            "reason": reason,
            "n_phases": len(new_phases),
        })],
    }


def _strip_fence(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


def _sse(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"event": event_type, "data": data}
