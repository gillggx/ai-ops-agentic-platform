#!/usr/bin/env python3
"""verify-build runner — run a builder test and produce a structured
phase / attempt / action report.

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

The canonical trace → model parser lives at
  python_ai_sidecar.agent_builder.graph_build.trace_summary
on EC2. This script SSH-invokes it for a single source of truth (the
same model powers the web BuildTraceDrawer).
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
    full = ["ssh", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=no", SSH_HOST, cmd]
    res = subprocess.run(full, capture_output=True, text=True, timeout=timeout)
    if res.returncode != 0:
        raise RuntimeError(f"SSH cmd failed (rc={res.returncode}): {res.stderr[:500]}")
    return res.stdout


def _run_harness(mode: str, message: str) -> str:
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
    out = _ssh(f"sudo ls -t {TRACE_DIR}/*.json 2>/dev/null | head -1", timeout=30)
    return out.strip() or None


def _fetch_model(trace_path: str) -> dict[str, Any]:
    """Run the sidecar's trace_summary parser on EC2, return its JSON model.

    Uses the sidecar venv python since the module sits inside the
    python_ai_sidecar package whose __init__ chain imports langgraph
    (not available in system python3).
    """
    bash = (
        f'cd {REMOTE_REPO} && sudo bash -c "'
        f'/opt/aiops/venv_sidecar/bin/python3 '
        f'-m python_ai_sidecar.agent_builder.graph_build.trace_summary '
        f'{trace_path}"'
    )
    raw = _ssh(bash, timeout=60)
    raw = raw.strip()
    # Module emits one JSON object on stdout; tolerate stderr noise above.
    for line in reversed(raw.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)
    raise RuntimeError(f"trace_summary returned no JSON: {raw[:300]}")


# ── Rendering ──────────────────────────────────────────────────────────


def _fmt_params(params: Any) -> str:
    """Compact params dict — {k=v, k=v}; truncate long values."""
    if not params:
        return "{}"
    if isinstance(params, str):
        return params[:120]
    parts = []
    for k, v in (params or {}).items():
        vs = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else repr(v)
        if len(vs) > 30:
            vs = vs[:30] + "…"
        parts.append(f"{k}={vs}")
    return "{" + ", ".join(parts) + "}"


def _fmt_verify(v: dict | None) -> tuple[str, list[str]]:
    """Return (one-line summary, list of extra detail lines)."""
    if not v:
        return ("(no verdict — phase ended mid-attempt)", [])
    verdict = v.get("verdict")
    result = v.get("result")
    if verdict == "ADVANCED":
        ff = v.get("fast_forward")
        phs = v.get("phases_advanced") or []
        if ff and len(phs) >= 2:
            return (f"[ADVANCED] (FF: {', '.join(phs)})", [])
        return ("[ADVANCED]", [])
    # REJECTED
    extras: list[str] = []
    rows = v.get("rows")
    covers = v.get("covers") or []
    em = (v.get("error_message") or "")[:200]
    jr = (v.get("judge_reject_reason") or "")[:140]
    wp = v.get("would_pass") or []
    missing = v.get("missing_for_phase") or []

    if result == "covers mismatch":
        head = f"[REJECTED] covers mismatch — block covers={covers}"
    elif result in {"validation_error", "failed", "error"}:
        head = f"[REJECTED] {result}"
        if em:
            extras.append(f"   error: {em}")
    elif "orphan" in (result or ""):
        head = "[REJECTED] orphan (block added but no upstream connected)"
    elif result == "llm_judge_rejected":  # legacy traces
        head = "[REJECTED] llm_judge (legacy)"
        if jr:
            extras.append(f"   judge: {jr}")
    else:
        head = f"[REJECTED] {result or '(unknown)'}"
        if rows is not None:
            head += f", rows={rows}"

    if wp:
        extras.append(f"   would_pass: {wp[:5]}{'…' if len(wp) > 5 else ''}")
    for m in missing[:2]:
        extras.append(f"   missing: {m}")
    return (head, extras)


def _render_text(model: dict, *, mode: str, message: str, trace_path: str) -> str:
    out: list[str] = []
    end = model.get("end") or {}
    status = end.get("status") or "(unknown)"
    sym = {"finished": "[OK]", "handover_pending": "[STUCK]",
           "build_partial": "[PARTIAL]", "failed": "[FAIL]"}.get(status, "[?]")

    out.append("=" * 78)
    out.append("BUILD VERIFICATION REPORT")
    out.append("=" * 78)
    out.append(f"mode:     {mode}")
    out.append(f"status:   {sym} {status}")
    out.append(f"message:  {message[:120]}")
    out.append(f"trace:    {trace_path}")
    dur = model.get("duration_ms")
    if dur:
        out.append(f"duration: {dur/1000:.1f}s")
    out.append("")

    # Plan section
    out.append("── Plan ──")
    plan = model.get("plan") or []
    if not plan:
        out.append("  (no plan captured)")
    else:
        phase_status = {p["id"]: p["outcome"] for p in (model.get("phases") or [])}
        for p in plan:
            mark = {"completed": "[ok]", "stuck": "[NO]", "not_reached": "[--]"}.get(
                phase_status.get(p["id"], "not_reached"), "[?]"
            )
            kind = p.get("expected") or "?"
            out.append(f"  {mark}  {p['id']:<4} [{kind:<9}]  {(p.get('goal') or '')[:60]}")
    out.append("")

    # Per-phase detail
    for ph in model.get("phases") or []:
        head_sym = {"completed": "[ok]", "stuck": "[NO]",
                    "not_reached": "[--]"}.get(ph["outcome"], "[?]")
        out.append(f"── Phase {ph['id']} [{ph['expected'] or '?'}] {head_sym} ──")
        out.append(f"  Goal: {(ph.get('goal') or '(no goal)')[:80]}")
        if ph["outcome"] == "not_reached":
            out.append("  (never reached — earlier phase blocked the build)")
            out.append("")
            continue

        for a in ph.get("attempts") or []:
            if a.get("kind") == "revise":
                out.append("")
                rc = a.get("root_cause") or "(no root cause recorded)"
                out.append(f"  -- REVISE (refine cycle {a['refine_cycle']}) --")
                # Wrap long root cause into 100-char chunks
                for line in _wrap(rc, 100):
                    out.append(f"     {line}")
                alt = a.get("alternative_strategy")
                if alt:
                    out.append(f"     strategy: {str(alt)[:160]}")
                out.append("")
                continue

            block_label = a.get("block_id") or "(unknown block)"
            extra = "" if a.get("from_commit_pick") else " [no-commit-pick]"
            out.append(f"  Attempt {a['n']} — {block_label}{extra}")
            ic = a.get("inspect_count", 0)
            if ic:
                out.append(f"     inspect_block_doc × {ic}")
            for ac in a.get("actions") or []:
                tool = ac.get("tool", "?")
                ok = ac.get("ok")
                tag = "ok" if ok else "no"
                preview = ac.get("preview") or {}
                args = ac.get("args") or {}
                line = f"     [{tag}] {tool:<14}"
                if tool == "add_node":
                    line += f"  {args.get('block_name','?')}"
                    params = args.get("params") or {}
                    if params:
                        line += f"  {_fmt_params(params)}"
                elif tool == "connect":
                    line += (
                        f"  {args.get('from_node','?')}.{args.get('from_port','data')}"
                        f" → {args.get('to_node','?')}.{args.get('to_port','data')}"
                    )
                elif tool == "set_param":
                    line += f"  {args.get('node_id','?')}.{args.get('key','?')}={args.get('value','?')}"
                elif tool == "remove_node":
                    line += f"  {args.get('node_id','?')}"
                else:
                    if args:
                        line += f"  {_fmt_params(args)}"
                if preview:
                    rs = preview.get("rows")
                    st = preview.get("status")
                    line += f"   → {st}"
                    if rs is not None:
                        line += f" ({rs} rows)"
                out.append(line)
            head, extras = _fmt_verify(a.get("verify"))
            out.append(f"     ↳ verify: {head}")
            for ex in extras:
                out.append(f"  {ex}")

        # Phase outcome line
        out.append("")
        if ph["outcome"] == "completed":
            out.append(f"  [ok] Phase goal achieved ({ph['rounds_used']} rounds used)")
        elif ph["outcome"] == "stuck":
            out.append(
                f"  [NO] Phase NOT achieved — "
                f"{ph['rounds_used']} rounds, {ph['max_round_hits']} max-round hit(s)"
            )
        out.append("")

    # End section
    out.append("══════════ END ══════════")
    out.append(f"status: {sym} {status}")
    nodes = end.get("nodes") or []
    edges = end.get("edges") or []
    out.append(f"final canvas: {len(nodes)} nodes, {len(edges)} edges")
    for n in nodes:
        out.append(f"  {n['id']:<4} {n['block_id']:<28} {_fmt_params(n.get('params'))}")
    for e in edges:
        out.append(f"  edge  {e['from']} → {e['to']}")
    out.append("")
    return "\n".join(out)


def _wrap(text: str, width: int) -> list[str]:
    """Naive word-wrap for CJK text (no break-on-space; chunk by char count)."""
    if not text:
        return [""]
    return [text[i:i + width] for i in range(0, len(text), width)]


# ── Test mode (trace_replay) ───────────────────────────────────────────


def _run_test_mode(trace: str, target: str | None, variants: list[str], reps: int) -> str:
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
        "EC2 trace path. In chat/builder mode: skip harness, re-parse "
        "this trace (faster). In test mode: trace_replay --trace arg."
    ))
    ap.add_argument("--target", help="trace_replay target (test mode)")
    ap.add_argument("--variants", nargs="*", default=["identity"])
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--json-out", help="path to write structured JSON model")
    ap.add_argument("--local-trace", help=(
        "Path to a LOCAL trace JSON (skips SSH). For dev when you already "
        "scp'd a trace to /tmp."
    ))
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

    # Decide trace source + harness run
    if args.local_trace:
        # Local fixture — parse via local sidecar module (requires repo on $PYTHONPATH)
        sys.path.insert(0, os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        ))
        from python_ai_sidecar.agent_builder.graph_build.trace_summary import parse
        with open(args.local_trace) as f:
            model = parse(json.load(f))
        trace_path = args.local_trace
        message = args.message or model.get("instruction", "")[:200]
    elif args.trace:
        print(f"[verify-build] replaying existing trace {args.trace} …", file=sys.stderr)
        model = _fetch_model(args.trace)
        trace_path = args.trace
        message = args.message or model.get("instruction", "")[:200]
    else:
        if not args.message:
            print("ERROR: --message or --trace required in chat/builder mode",
                  file=sys.stderr)
            return 2
        print(f"[verify-build] running {args.mode} mode on EC2 …", file=sys.stderr)
        try:
            _ = _run_harness(args.mode, args.message)
        except subprocess.TimeoutExpired:
            print("ERROR: harness timed out (>15min)", file=sys.stderr)
            return 1
        trace_path = _newest_trace_path()
        if not trace_path:
            print("WARN: no trace file found", file=sys.stderr)
            return 0
        model = _fetch_model(trace_path)
        message = args.message

    print(_render_text(model, mode=args.mode, message=message, trace_path=trace_path))

    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump({
                "mode": args.mode,
                "message": message,
                "trace_path": trace_path,
                "model": model,
            }, f, indent=2, ensure_ascii=False, default=str)
        print(f"\n[verify-build] JSON written to {args.json_out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
