"""trace_summary — canonical trace → phase/attempt/action model.

Single source of truth for trace rendering. Both the verify-build skill
and the web BuildTraceDrawer should consume this JSON model so the user
sees one consistent format whichever surface they look at.

Hierarchy:
    Build
      └─ Plan (list of phases)
      └─ Phases
          └─ Attempts (one per commit_pick → verifier verdict cycle)
              └─ Actions (inspect_count + add_node + connect + set_param)
              └─ Verify result
      └─ End (final status + canvas)

Run as a script for the skill (returns JSON to stdout):
    python3 -m python_ai_sidecar.agent_builder.graph_build.trace_summary <trace_path>
"""
from __future__ import annotations

import json
import sys
from typing import Any


# ─────────────────────────────────────────────────────────────────────
# Trace parsing
# ─────────────────────────────────────────────────────────────────────


def parse(trace: dict) -> dict:
    """Top-level parser. Returns the canonical model dict."""
    plan = _extract_plan(trace)
    phases = _build_phases(trace, plan)
    end = _build_end(trace)
    return {
        "schema_version": 1,
        "build_id": trace.get("build_id"),
        "instruction": trace.get("instruction"),
        "duration_ms": trace.get("duration_ms"),
        "plan": plan,
        "phases": phases,
        "end": end,
    }


def _extract_plan(trace: dict) -> list[dict]:
    """Plan from decision_records[0].user_msg_sections.all_phases_context.

    goal_plan_node doesn't emit a graph_step; its output lives in the
    first decision_record's user_msg_sections.
    """
    for rec in trace.get("decision_records") or []:
        sections = rec.get("user_msg_sections") or {}
        ctx = sections.get("all_phases_context") or []
        if ctx:
            return [
                {
                    "id": p.get("id"),
                    "expected": p.get("expected"),
                    "goal": p.get("goal"),
                }
                for p in ctx
                if p.get("id")
            ]
    # Fallback: dedupe phase_id from graph_steps (loses goal/expected)
    seen: list[str] = []
    for s in trace.get("graph_steps") or []:
        pid = s.get("phase_id")
        if pid and pid not in seen:
            seen.append(pid)
    return [{"id": pid, "expected": None, "goal": None} for pid in seen]


def _build_phases(trace: dict, plan: list[dict]) -> list[dict]:
    """For each planned phase, walk its graph_steps and build attempts."""
    plan_by_id = {p["id"]: p for p in plan}
    steps = trace.get("graph_steps") or []

    # Track which phases were advanced + which had max-round hits
    advanced_phases: set[str] = set()
    for s in steps:
        if s.get("node") == "phase_verifier" and s.get("status") == "advanced":
            for pid in s.get("phases_advanced") or []:
                advanced_phases.add(pid)

    # Group steps by phase_id, preserving order. phase_verifier advanced
    # steps don't carry phase_id (they reference phases_advanced[]
    # instead) — attribute them to the LAST phase in phases_advanced,
    # since that's where the attempt's verdict should attach (the FF
    # chain entries before it are advanced "by association", not by
    # their own attempt).
    by_phase: dict[str, list[dict]] = {}
    for s in steps:
        pid = s.get("phase_id")
        if pid:
            by_phase.setdefault(pid, []).append(s)
            continue
        if s.get("node") == "phase_verifier" and s.get("status") == "advanced":
            adv = s.get("phases_advanced") or []
            if adv:
                # Attach to the FIRST phase in chain — that's the one the
                # agent was trying to satisfy; subsequent FF entries piggy-
                # back on the same block + verifier call.
                by_phase.setdefault(adv[0], []).append(s)

    out: list[dict] = []
    for p in plan:
        pid = p["id"]
        phase_steps = by_phase.get(pid) or []
        attempts = _build_attempts(phase_steps, trace)
        outcome, rounds_used, max_round_hits = _classify_phase_outcome(
            pid, phase_steps, advanced_phases,
        )
        out.append({
            "id": pid,
            "expected": p.get("expected"),
            "goal": p.get("goal"),
            "attempts": attempts,
            "outcome": outcome,
            "rounds_used": rounds_used,
            "max_round_hits": max_round_hits,
        })
    # Any phases that appeared in steps but not in plan (defensive)
    plan_ids = {p["id"] for p in plan}
    for pid in by_phase:
        if pid not in plan_ids:
            out.append({
                "id": pid,
                "expected": None,
                "goal": "(not in original plan)",
                "attempts": _build_attempts(by_phase[pid], trace),
                "outcome": "stuck" if pid not in advanced_phases else "completed",
                "rounds_used": sum(
                    1 for s in by_phase[pid]
                    if s.get("node") == "agentic_phase_loop"
                    and s.get("status") == "round_done"
                ),
                "max_round_hits": 0,
            })
    return out


def _build_attempts(phase_steps: list[dict], trace: dict) -> list[dict]:
    """Slice phase_steps into attempts.

    An attempt is one cycle of (inspect × N → commit_pick → add_node →
    connect → optional set_param → final verify). It starts at a
    commit_pick (or at phase entry for the first one) and ends at the
    NEXT commit_pick / refine marker / end-of-phase.

    The verifier may emit multiple no_match verdicts within one attempt
    (e.g. one after add_node, another after connect). The LAST verdict
    in the attempt window is the decisive one — earlier ones are
    intermediate noise that the agent kept pushing through.

    Refine markers are separate entries with kind="revise" and don't
    occupy an `n` slot; attempt numbering counts only real attempts.
    """
    attempts: list[dict] = []
    pending_inspects = 0
    current: dict | None = None
    refine_cycle = 0
    attempt_n = 0

    def _start_attempt(*, block_id: str | None, from_commit_pick: bool):
        nonlocal current, pending_inspects, attempt_n
        # Flush previous if it had any meaningful content
        if current is not None:
            attempts.append(current)
        attempt_n += 1
        current = {
            "n": attempt_n,
            "refine_cycle": refine_cycle,
            "block_id": block_id,
            "inspect_count": pending_inspects,
            "actions": [],
            "verify": None,
            "from_commit_pick": from_commit_pick,
        }
        pending_inspects = 0

    def _flush_attempt():
        nonlocal current
        if current is not None:
            attempts.append(current)
            current = None

    for s in phase_steps:
        node = s.get("node")
        if node == "agentic_phase_loop":
            status = s.get("status")
            if status != "round_done":
                continue  # round_max_hit etc — phase-level signal, skip
            tool = s.get("tool")
            if tool == "inspect_block_doc":
                pending_inspects += 1
                continue
            if tool == "inspect_node_output":
                # Not counted in inspect_count (it's about upstream, not block)
                continue
            if tool == "commit_pick":
                _start_attempt(
                    block_id=_lookup_commit_pick_block(s, trace),
                    from_commit_pick=True,
                )
                continue
            if tool in {"add_node", "connect", "set_param", "remove_node", "abort_node"}:
                # Lazy attempt if no commit_pick yet (agent went off-script
                # or this is a refine-cycle connect/remove without re-pick).
                if current is None:
                    _start_attempt(block_id=None, from_commit_pick=False)
                action = {
                    "tool": tool,
                    "ok": bool(s.get("action_ok")),
                    "mutated_node": s.get("mutated_node"),
                }
                ap = s.get("auto_preview") or {}
                if ap:
                    action["preview"] = {
                        "rows": ap.get("rows"),
                        "status": ap.get("status"),
                    }
                action["args"] = _lookup_action_args(s, trace, tool)
                # Backfill block_id from add_node args when commit_pick missing
                if (
                    tool == "add_node"
                    and current.get("block_id") is None
                    and (action["args"] or {}).get("block_name")
                ):
                    current["block_id"] = action["args"]["block_name"]
                current["actions"].append(action)
                continue
            if tool in {"phase_complete", "abort_phase", "run_verifier"}:
                if current is not None:
                    current["actions"].append({
                        "tool": tool, "ok": bool(s.get("action_ok")),
                    })
        elif node == "phase_verifier":
            status = s.get("status")
            if status == "advanced":
                if current is None:
                    _start_attempt(
                        block_id=s.get("block_id"), from_commit_pick=False,
                    )
                # Overwrite verify (last verdict wins — should be ADVANCED)
                current["verify"] = {
                    "verdict": "ADVANCED",
                    "result": "advanced",
                    "fast_forward": bool(s.get("fast_forward")),
                    "phases_advanced": s.get("phases_advanced") or [],
                }
                _flush_attempt()
            elif status == "no_match":
                if current is None:
                    _start_attempt(
                        block_id=s.get("block_id"), from_commit_pick=False,
                    )
                result = s.get("result") or "no_match"
                vd = _match_verifier_decision(s, trace)
                would_pass: list[str] = []
                judge_reason = None
                error_message = s.get("error_message")
                if vd:
                    comp = vd.get("comparison") or {}
                    result = comp.get("result") or result
                    judge_reason = comp.get("judge_reject_reason")
                    would_pass = vd.get("would_have_passed_with") or []
                # Always overwrite — last no_match in the attempt wins,
                # unless a subsequent commit_pick / advance fires after.
                current["verify"] = {
                    "verdict": "REJECTED",
                    "result": result,
                    "block_id": s.get("block_id"),
                    "covers": s.get("covers") or [],
                    "rows": s.get("rows"),
                    "error_message": error_message,
                    "judge_reject_reason": judge_reason,  # legacy traces only
                    "would_pass": would_pass[:8],
                    "missing_for_phase": s.get("missing_for_phase") or [],
                }
                # Don't flush yet — agent may try connect / set_param next,
                # producing another verify. We flush on next commit_pick /
                # refine / phase end.
        elif node == "phase_revise_node":
            _flush_attempt()
            refine_cycle += 1
            attempts.append({
                "n": None,
                "kind": "revise",
                "refine_cycle": refine_cycle,
                "root_cause": s.get("root_cause"),
                "alternative_strategy": s.get("alternative_strategy"),
                "missing_capabilities": s.get("missing_capabilities") or [],
                "can_retry": s.get("can_retry"),
            })
    _flush_attempt()
    return attempts


def _lookup_commit_pick_block(step: dict, trace: dict) -> str | None:
    """Find which block_id a commit_pick referred to. graph_step doesn't
    carry it; pull from the matched llm_call by ts."""
    ts = step.get("ts") or ""
    for c in trace.get("llm_calls") or []:
        if abs(_ts_diff(ts, c.get("ts") or "")) > 5.0:
            continue
        parsed = c.get("parsed") or {}
        if parsed.get("name") == "commit_pick":
            return (parsed.get("args") or {}).get("block_id")
    return None


def _lookup_action_args(step: dict, trace: dict, tool: str) -> dict:
    """Pull tool args from the matched llm_call (by ts proximity)."""
    ts = step.get("ts") or ""
    best: tuple[float, dict] = (999.0, {})
    for c in trace.get("llm_calls") or []:
        parsed = c.get("parsed") or {}
        if parsed.get("name") != tool:
            continue
        diff = abs(_ts_diff(ts, c.get("ts") or ""))
        if diff < best[0]:
            best = (diff, parsed.get("args") or {})
    return best[1] if best[0] < 10.0 else {}


def _match_verifier_decision(step: dict, trace: dict) -> dict | None:
    """Find the verifier_decisions entry closest to this phase_verifier step."""
    ts = step.get("ts") or ""
    phase_id = step.get("phase_id")
    best: tuple[float, dict | None] = (999.0, None)
    for d in trace.get("verifier_decisions") or []:
        if d.get("phase_id") != phase_id:
            continue
        diff = abs(_ts_diff(ts, d.get("ts") or ""))
        if diff < best[0]:
            best = (diff, d)
    return best[1] if best[0] < 2.0 else None


def _ts_diff(a: str, b: str) -> float:
    """Return |a - b| in seconds. Treat ISO timestamps; return huge on parse fail."""
    if not a or not b:
        return 999.0
    try:
        from datetime import datetime
        ta = datetime.fromisoformat(a.replace("Z", "+00:00"))
        tb = datetime.fromisoformat(b.replace("Z", "+00:00"))
        return (ta - tb).total_seconds()
    except Exception:
        return 999.0


def _classify_phase_outcome(
    pid: str, phase_steps: list[dict], advanced_phases: set[str],
) -> tuple[str, int, int]:
    """Return (outcome, rounds_used, max_round_hits) for a phase.

    outcome:
      completed   — phase_verifier advanced fired on this pid
      stuck       — round_max_hit appeared and never advanced
      not_reached — no steps for this pid at all
    """
    if not phase_steps:
        return ("not_reached", 0, 0)
    rounds_used = sum(
        1 for s in phase_steps
        if s.get("node") == "agentic_phase_loop"
        and s.get("status") == "round_done"
    )
    max_round_hits = sum(
        1 for s in phase_steps
        if s.get("node") == "agentic_phase_loop"
        and s.get("status") == "round_max_hit"
    )
    if pid in advanced_phases:
        return ("completed", rounds_used, max_round_hits)
    return ("stuck", rounds_used, max_round_hits)


def _build_end(trace: dict) -> dict:
    fp = trace.get("final_pipeline") or {}
    nodes_out: list[dict] = []
    for n in fp.get("nodes") or []:
        nodes_out.append({
            "id": n.get("id"),
            "block_id": n.get("block_id"),
            "params": n.get("params") or {},
        })
    edges_out: list[dict] = []
    for e in fp.get("edges") or []:
        frm = e.get("from") or {}
        to = e.get("to") or {}
        edges_out.append({
            "from": f"{frm.get('node')}.{frm.get('port')}",
            "to": f"{to.get('node')}.{to.get('port')}",
        })
    return {
        "status": trace.get("status"),
        "nodes": nodes_out,
        "edges": edges_out,
    }


# ─────────────────────────────────────────────────────────────────────
# CLI — used by the verify-build skill via SSH.
# ─────────────────────────────────────────────────────────────────────


def _main() -> int:
    if len(sys.argv) < 2:
        print("usage: python -m python_ai_sidecar.agent_builder.graph_build.trace_summary <trace_path>",
              file=sys.stderr)
        return 2
    path = sys.argv[1]
    with open(path) as f:
        trace = json.load(f)
    model = parse(trace)
    json.dump(model, sys.stdout, ensure_ascii=False, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
