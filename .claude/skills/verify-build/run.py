#!/usr/bin/env python3
"""verify-build runner — run a builder test and produce a structured
3-section report (plan / stuck phase / round-by-round history).

Modes:
  chat     — POST /internal/agent/chat (auto-confirm design_intent_confirm)
  builder  — POST /internal/agent/build (direct stream_graph_build)
  test     — replay a single LLM call from a saved trace under variants
             (wraps tools.trace_replay)

Outputs both human text (stdout) and JSON (--json-out path).

Designed to run from the user's laptop. Test runs against EC2 prod
(http://localhost:8050 inside EC2 via SSH) since:
  (a) sidecar isn't publicly exposed,
  (b) BuildTracer writes traces to EC2's /tmp/builder-traces/.

SSH wrapper picks up SERVICE_TOKEN from /opt/aiops/python_ai_sidecar/.env.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import Any


SSH_KEY = os.environ.get("AIOPS_SSH_KEY", os.path.expanduser("~/Desktop/ai-ops-key.pem"))
SSH_HOST = os.environ.get("AIOPS_SSH_HOST", "ubuntu@aiops-gill.com")
REMOTE_REPO = os.environ.get("AIOPS_REMOTE_REPO", "/opt/aiops")
TRACE_DIR = "/tmp/builder-traces"


def _ssh(cmd: str, *, timeout: int = 600) -> str:
    """Run a remote command via SSH and return stdout."""
    full = ["ssh", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=no", SSH_HOST, cmd]
    res = subprocess.run(full, capture_output=True, text=True, timeout=timeout)
    if res.returncode != 0:
        raise RuntimeError(f"SSH cmd failed (rc={res.returncode}): {res.stderr[:500]}")
    return res.stdout


def _run_harness(mode: str, message: str) -> str:
    """Invoke the right harness script on EC2 and return its stdout."""
    if mode == "chat":
        script = "tools/ui_consistent_verify/chat_walkthrough.py"
    elif mode == "builder":
        script = "tools/ui_consistent_verify/builder_verify.py"
    else:
        raise ValueError(f"unsupported mode={mode!r}")

    quoted_msg = message.replace('"', '\\"')
    bash = (
        f'cd {REMOTE_REPO} && sudo bash -c "source python_ai_sidecar/.env && '
        f'SVC_TOKEN=\\$SERVICE_TOKEN SIDECAR_BASE=http://localhost:8050 '
        f'python3 {script} \\"{quoted_msg}\\""'
    )
    return _ssh(bash, timeout=900)


def _newest_trace_path() -> str | None:
    """Find the most recently modified trace file on EC2."""
    out = _ssh(f"sudo ls -t {TRACE_DIR}/*.json 2>/dev/null | head -1", timeout=30)
    out = out.strip()
    return out or None


def _fetch_trace(path: str) -> dict[str, Any]:
    raw = _ssh(f"sudo cat {path}", timeout=60)
    return json.loads(raw)


# ── Trace parsing ──────────────────────────────────────────────────────


def _extract_plan(trace: dict) -> dict:
    """Pull the goal_plan_node entry (the first one — re-plans yield more)."""
    steps = trace.get("graph_steps") or []
    plan_step = next((s for s in steps if s.get("node") == "goal_plan_node"), None)
    if not plan_step:
        return {"summary": None, "phases": []}
    phases = []
    for p in plan_step.get("phases") or []:
        phases.append({
            "id": p.get("id"),
            "goal": p.get("goal"),
            "expected": p.get("expected"),
            "expected_kind": (p.get("expected_output") or {}).get("kind"),
            "auto_injected": bool(p.get("auto_injected")),
        })
    return {"summary": plan_step.get("summary"), "phases": phases}


def _classify_phase_status(trace: dict) -> dict[str, str]:
    """Per phase id: completed / stuck / not_reached.

    A phase is `completed` if any phase_verifier with status='advanced'
    lists it in phases_advanced. `stuck` if it appears in agentic_phase_loop
    with status in {round_max_hit, revise_failed} or in halt_handover_node
    record. Otherwise `not_reached`.
    """
    plan = _extract_plan(trace)
    status = {p["id"]: "not_reached" for p in plan["phases"]}

    for step in trace.get("graph_steps") or []:
        node = step.get("node", "")
        if node == "phase_verifier" and step.get("status") == "advanced":
            for pid in step.get("phases_advanced") or []:
                if pid in status:
                    status[pid] = "completed"
        elif node == "agentic_phase_loop" and step.get("status") in (
            "round_max_hit", "revise_failed", "revise_budget_exhausted"
        ):
            pid = step.get("phase_id")
            if pid in status and status[pid] != "completed":
                status[pid] = "stuck"
        elif node in ("halt_handover_node", "phase_revise_failed"):
            pid = step.get("phase_id")
            if pid in status and status[pid] != "completed":
                status[pid] = "stuck"
    return status


def _find_stuck_phase(status: dict[str, str]) -> str | None:
    for pid, s in status.items():
        if s == "stuck":
            return pid
    return None


def _verifier_verdicts_for(trace: dict, phase_id: str) -> list[dict]:
    """Join phase_verifier graph_steps with the richer verifier_decisions
    records (added by record_verifier_decision). The latter has the real
    comparison.result + would_have_passed_with — graph_steps only has
    covers/rows/status which can mislead (says 'rows quality gate failed'
    even when the actual cause was the LLM-judge semantic check)."""
    out = []
    # Build lookup of verifier_decisions by phase + block (closest match by ts)
    decisions = [d for d in (trace.get("verifier_decisions") or [])
                 if d.get("phase_id") == phase_id]
    used = set()

    for step in trace.get("graph_steps") or []:
        if step.get("node") != "phase_verifier":
            continue
        if step.get("phase_id") != phase_id:
            continue
        # Find the matching verifier_decision (same block, unused, earliest ts after step)
        match = None
        for i, dec in enumerate(decisions):
            if i in used:
                continue
            if dec.get("candidate_block") == step.get("block_id"):
                match = dec
                used.add(i)
                break
        entry = {
            "expected": step.get("expected"),
            "block_id": step.get("block_id"),
            "covers": step.get("covers"),
            "rows": step.get("rows"),
            "status": step.get("status"),
        }
        if match:
            comp = match.get("comparison") or {}
            entry["comparison_result"] = comp.get("result")
            entry["judge_reject_reason"] = comp.get("judge_reject_reason")
            entry["would_have_passed_with"] = match.get("would_have_passed_with")
        # graph_step also carries judge_reject_reason since v30.17g
        if step.get("judge_reject_reason") and not entry.get("judge_reject_reason"):
            entry["judge_reject_reason"] = step.get("judge_reject_reason")
        out.append(entry)
    return out


def _round_history_for(trace: dict, phase_id: str) -> list[dict]:
    """All agentic_phase_loop entries for the phase (in chrono order)."""
    out = []
    for step in trace.get("graph_steps") or []:
        if step.get("node") != "agentic_phase_loop":
            continue
        if step.get("phase_id") != phase_id:
            continue
        kind = step.get("status")
        if kind == "round_done":
            out.append({
                "kind": "round",
                "round": step.get("round"),
                "tool": step.get("tool"),
                "action_ok": step.get("action_ok"),
                "auto_preview": step.get("auto_preview"),
                "mutated_node": step.get("mutated_node"),
            })
        else:
            out.append({
                "kind": kind,
                "rounds": step.get("rounds"),
            })
    return out


def _revise_history_for(trace: dict, phase_id: str) -> list[dict]:
    out = []
    for step in trace.get("graph_steps") or []:
        if step.get("node") != "phase_revise_node":
            continue
        if step.get("phase_id") != phase_id:
            continue
        out.append({
            "attempt": step.get("attempt"),
            "strategy": (step.get("parsed") or {}).get("strategy") if step.get("parsed") else step.get("strategy"),
            "summary": (step.get("parsed") or {}).get("summary") if step.get("parsed") else None,
        })
    return out


# ── Rendering ──────────────────────────────────────────────────────────


def _render_text(report: dict) -> str:
    out = []
    out.append("=" * 78)
    out.append("BUILD VERIFICATION REPORT")
    out.append("=" * 78)
    out.append(f"mode:      {report['mode']}")
    out.append(f"message:   {report['message'][:120]}")
    if report.get("trace_path"):
        out.append(f"trace:     {report['trace_path']}")
    out.append("")

    plan = report["plan"]
    out.append("─── Plan ─────────────────────────────────────────────────────────────────")
    out.append(f"summary: {plan.get('summary') or '(no plan captured)'}")
    out.append("phases:")
    for p in plan.get("phases") or []:
        mark = {"completed": "[ok]", "stuck": "[NO]", "not_reached": "[ -- ]"}.get(
            report["phase_status"].get(p["id"], "not_reached"), "[?]"
        )
        kind = p.get("expected") or "?"
        out.append(f"  {mark}  {p['id']:<4} [{kind}]  {(p.get('goal') or '')[:60]}")
    out.append("")

    stuck = report["stuck_phase"]
    if not stuck:
        out.append("─── Result ───────────────────────────────────────────────────────────────")
        out.append("ALL PHASES PASSED — no stuck phase.")
        out.append("")
        return "\n".join(out)

    out.append(f"─── Stuck phase: {stuck} ─────────────────────────────────────────────────")
    verdicts = report["stuck_verdicts"]
    if not verdicts:
        out.append("(no phase_verifier entries for this phase — verifier never ran)")
    else:
        out.append(f"{len(verdicts)} verifier verdict(s):")
        for v in verdicts:
            cov = v.get("covers")
            exp = v.get("expected")
            cmp_result = v.get("comparison_result")
            judge_reason = v.get("judge_reject_reason")
            rows = v.get("rows")
            tag = ""
            # Prefer the v30.17g `comparison_result` field — it's already
            # disambiguated. Fall back to inference for older traces.
            if cmp_result == "covers mismatch":
                tag = f"  → COVERS MISMATCH: '{exp}' not in {cov}"
            elif cmp_result == "rows quality gate failed":
                tag = f"  → ROWS GATE: need rows>=1, got {rows}"
            elif cmp_result == "llm_judge_rejected":
                reason_short = (judge_reason or "(no reason)")[:80]
                tag = f"  → LLM-JUDGE REJECTED: {reason_short}"
            elif cmp_result:
                tag = f"  → {cmp_result}"
            else:
                # Old trace fallback — infer from covers + rows
                if isinstance(cov, list) and exp and exp not in cov:
                    tag = f"  → COVERS MISMATCH: '{exp}' not in {cov}"
                elif rows is None or (isinstance(rows, int) and rows < 1):
                    tag = f"  → ROWS GATE (inferred): rows={rows}"
                elif judge_reason:
                    tag = f"  → LLM-JUDGE REJECTED: {judge_reason[:80]}"
            out.append(
                f"  block={(v.get('block_id') or '?'):<28} covers={cov} "
                f"rows={rows} status={v.get('status')}{tag}"
            )
            wp = v.get("would_have_passed_with")
            if wp:
                out.append(f"      would_have_passed_with: {wp[:5]}{'…' if len(wp)>5 else ''}")
    out.append("")

    out.append(f"─── {stuck} round-by-round ────────────────────────────────────────────────")
    for h in report["stuck_rounds"]:
        if h["kind"] == "round":
            preview = h.get("auto_preview") or {}
            row_str = ""
            if isinstance(preview, dict):
                rs = preview.get("rows")
                st = preview.get("status")
                if rs is not None or st:
                    row_str = f" → {st} ({rs} rows)"
            ok = "ok" if h.get("action_ok") else "no"
            out.append(f"  r{h['round']:<2} [{ok}] {h['tool']:<22}{row_str}")
        else:
            out.append(f"  ⤵  {h['kind']} (rounds={h.get('rounds')})")

    revises = report["stuck_revises"]
    if revises:
        out.append("")
        out.append(f"─── {stuck} revise attempts ─────────────────────────────────────────────")
        for r in revises:
            sumtxt = (r.get("summary") or r.get("strategy") or "")[:120]
            out.append(f"  attempt {r.get('attempt')}: {sumtxt}")
    out.append("")
    return "\n".join(out)


def build_report(mode: str, message: str, *, harness_out: str, trace_path: str | None) -> dict:
    trace = _fetch_trace(trace_path) if trace_path else {}
    plan = _extract_plan(trace) if trace else {"summary": None, "phases": []}
    status = _classify_phase_status(trace) if trace else {}
    stuck = _find_stuck_phase(status)
    return {
        "mode": mode,
        "message": message,
        "trace_path": trace_path,
        "plan": plan,
        "phase_status": status,
        "stuck_phase": stuck,
        "stuck_verdicts": _verifier_verdicts_for(trace, stuck) if stuck else [],
        "stuck_rounds": _round_history_for(trace, stuck) if stuck else [],
        "stuck_revises": _revise_history_for(trace, stuck) if stuck else [],
        "harness_stdout_tail": (harness_out or "")[-2000:],
    }


# ── Test mode (trace_replay) ───────────────────────────────────────────


def _run_test_mode(trace: str, target: str | None, variants: list[str], reps: int) -> str:
    """Run a controlled-variant replay over a saved trace's LLM calls.

    Wraps `python -m tools.trace_replay` on EC2 — that's where the trace
    lives. Returns the replay tool's stdout for the caller to surface.
    """
    cmd_parts = [f"python3 -m tools.trace_replay --trace {trace}"]
    if target:
        cmd_parts.append(f"--target '{target}'")
    if variants:
        cmd_parts.append("--variants " + " ".join(variants))
    if reps:
        cmd_parts.append(f"--reps {reps}")
    bash = f'cd {REMOTE_REPO} && sudo bash -c "source python_ai_sidecar/.env && {" ".join(cmd_parts)}"'
    return _ssh(bash, timeout=900)


# ── Main ───────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description="verify-build skill runner")
    ap.add_argument("--mode", choices=("chat", "builder", "test"), default="chat")
    ap.add_argument("--message", help="user message (chat/builder mode)")
    ap.add_argument("--trace", help=(
        "EC2 trace path. In chat/builder mode: skip running the harness "
        "and re-parse this existing trace (faster + lets us examine a "
        "specific past run, e.g. the user's own UI session). In test "
        "mode: trace_replay's --trace argument."
    ))
    ap.add_argument("--target", help="trace_replay target (test mode)")
    ap.add_argument("--variants", nargs="*", default=["identity"],
                    help="trace_replay variants (test mode)")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--json-out", help="path to write structured JSON")
    args = ap.parse_args()

    if args.mode == "test":
        if not args.trace:
            print("ERROR: --trace required in test mode", file=sys.stderr)
            return 2
        out = _run_test_mode(args.trace, args.target, args.variants, args.reps)
        print(out)
        if args.json_out:
            with open(args.json_out, "w") as f:
                json.dump({"mode": "test", "trace": args.trace, "stdout": out}, f, indent=2)
        return 0

    # chat/builder mode — two sub-paths:
    #   (a) --trace PATH given → fetch + parse existing trace, NO harness run
    #   (b) --message MSG given → run harness, then fetch newest trace
    if args.trace:
        print(f"[verify-build] replaying existing trace {args.trace} …", file=sys.stderr)
        trace = _fetch_trace(args.trace)
        # Use the trace's recorded instruction as the message label
        message = args.message or trace.get("instruction", "")[:200]
        report = build_report(args.mode, message,
                              harness_out="", trace_path=args.trace)
        # Replace fetched trace data into the standard pipeline shape
        # (build_report already re-reads the trace from --trace path).
    else:
        if not args.message:
            print("ERROR: --message or --trace required in chat/builder mode",
                  file=sys.stderr)
            return 2

        print(f"[verify-build] running {args.mode} mode on EC2 …", file=sys.stderr)
        try:
            harness_out = _run_harness(args.mode, args.message)
        except subprocess.TimeoutExpired:
            print("ERROR: harness timed out (>15min)", file=sys.stderr)
            return 1

        trace_path = _newest_trace_path()
        if not trace_path:
            print("WARN: no trace file found — printing harness stdout only",
                  file=sys.stderr)
            print(harness_out)
            return 0
        report = build_report(args.mode, args.message,
                              harness_out=harness_out, trace_path=trace_path)

    print(_render_text(report))

    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)
        print(f"\n[verify-build] JSON written to {args.json_out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
