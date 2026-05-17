"""chat_walkthrough.py — like chat_verify but presents plan + each phase
step-by-step (formatted for human review), not just raw event log.

Per user request 2026-05-17: "下次試跑可以先秀它的plan，一步步帶我看".

Phases:
  STEP 1: POST /agent/chat → if design_intent_confirm, auto-confirm
  STEP 2: Show the goal_plan in human-readable card BEFORE phases run
  STEP 3: For each phase_action / phase_completed, print 1-line update
  STEP 4: Final summary — phases status table + nodes count + status
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import requests


HDR_TPL = {"Content-Type": "application/json", "Accept": "text/event-stream"}


def _sse_lines(resp):
    buf = []
    for raw in resp.iter_lines(decode_unicode=True):
        if raw is None:
            continue
        if raw == "":
            if buf:
                ev = next((l[6:].strip() for l in buf if l.startswith("event:")), None)
                data = next((l[5:].strip() for l in buf if l.startswith("data:")), None)
                if ev:
                    try:
                        parsed = json.loads(data) if data else {}
                    except Exception:
                        parsed = {"_raw": data}
                    yield ev, parsed
                buf = []
        else:
            buf.append(raw)


def _short(s, n=80):
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def _print_plan_card(plan_summary, phases):
    print()
    print("┌─" + "─" * 78)
    print("│ 📋 GOAL PLAN")
    print("├─" + "─" * 78)
    if plan_summary:
        print("│ " + _short(plan_summary, 76))
        print("├─" + "─" * 78)
    for p in phases:
        pid = p.get("id", "?")
        exp = (p.get("expected") or "?").strip()
        goal = (p.get("goal") or "").strip()
        why = (p.get("why") or "").strip()
        auto = " [AUTO-INJECTED]" if p.get("auto_injected") else ""
        eo = p.get("expected_output") or {}
        kind = eo.get("kind") or "?"
        vd = (eo.get("value_desc") or "").strip()
        print(f"│ {pid} [{exp}|{kind}]{auto}")
        print(f"│    goal: {_short(goal, 70)}")
        if why:
            print(f"│    why:  {_short(why, 70)}")
        if vd:
            print(f"│    expect: {_short(vd, 70)}")
    print("└─" + "─" * 78)
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("message", help="User message to chat")
    ap.add_argument("--sidecar", default=os.environ.get("SIDECAR_BASE", "http://localhost:8050"))
    ap.add_argument("--mode", default="chat")
    args = ap.parse_args()

    svc = os.environ.get("SVC_TOKEN")
    if not svc:
        print("ERROR: SVC_TOKEN env var required", file=sys.stderr)
        return 2

    hdr = {
        **HDR_TPL,
        "X-Service-Token": svc,
        "X-User-Id": os.environ.get("VERIFY_USER_ID", "2"),
        "X-User-Roles": os.environ.get("VERIFY_USER_ROLES", "IT_ADMIN,PE"),
    }

    print(f"\n=== STEP 1: POST /agent/chat ===")
    print(f"    msg: {_short(args.message, 100)}\n")

    body = {"message": args.message, "session_id": None, "mode": args.mode, "client_context": {}}
    r = requests.post(f"{args.sidecar}/internal/agent/chat", json=body,
                       headers=hdr, stream=True, timeout=900)
    if r.status_code != 200:
        print(f"    HTTP {r.status_code} {r.text[:300]}")
        return 1

    pending_card = None
    chat_session_id = None
    plan_shown = False
    phase_status: dict[str, dict] = {}
    last_status = None
    final_nodes = 0

    def consume(resp_iter, label):
        nonlocal pending_card, chat_session_id, plan_shown, last_status, final_nodes
        synthesis_text = None
        for ev, data in resp_iter:
            d = data or {}
            if d.get("session_id") and not chat_session_id:
                chat_session_id = d["session_id"]

            if ev == "design_intent_confirm":
                pending_card = d.get("card_id")
                print(f"    [intent confirm requested — auto-confirming card {pending_card}]")
                continue

            if ev == "pb_glass_chat":
                content = d.get("content", "")
                if content.startswith("📋 Plan"):
                    # Multi-line plan card — pretty-print
                    print()
                    print("    ┌─" + "─" * 76)
                    for line in content.split("\n"):
                        print(f"    │ {line}")
                    print("    └─" + "─" * 76)
                    print()
                else:
                    print(f"    [chat] {content}")

            elif ev == "pb_glass_op":
                op = d.get("op", "")
                args_obj = d.get("args") or {}
                pid = args_obj.get("phase_id", "?")
                rnd = args_obj.get("round", "?")
                summary = (args_obj.get("args_summary") or "")[:60]
                print(f"    [{pid} r{rnd}] {op:18s} {summary}")

            elif ev == "pb_glass_done":
                status = d.get("status", "?")
                pj = d.get("pipeline_json") or {}
                final_nodes = len(pj.get("nodes") or [])
                last_status = status
                print(f"    [build done] status={status} nodes={final_nodes}")

            elif ev == "synthesis":
                synthesis_text = d.get("text") or ""

            elif ev == "done":
                if synthesis_text:
                    print(f"\n    [agent synthesis]\n    {synthesis_text}")
                return True
        return False

    # Need to ALSO render goal_plan_proposed (which is currently mapped to a
    # pb_glass_chat content but we want a richer card). Hijack: parse raw
    # stream and look for the goal_plan_proposed data BEFORE wrapping.
    # SIMPLER: read pb_glass_chat content starting with "📋 Plan" — it's
    # already a rendering of the plan. Print as-is in a box.
    #
    # For richer card, we'd need server-side to push goal_plan_proposed
    # passthrough — out of scope here. Use the pb_glass_chat content
    # as a fallback render.

    # Run 1
    consume(_sse_lines(r), "round1")

    # Auto-confirm if intent card requested.
    # `design_intent_confirm` (from confirm_pipeline_intent tool) expects a
    # NEW /agent/chat with [intent_confirmed:CARD] prefix — NOT
    # /chat/intent-respond (that's for build_pipeline_live clarifier).
    if pending_card and chat_session_id:
        confirm_msg = f"[intent_confirmed:{pending_card}] {args.message}"
        print(f"\n=== STEP 2: POST /agent/chat with [intent_confirmed:{pending_card}] prefix ===")
        body2 = {"message": confirm_msg, "session_id": chat_session_id,
                  "mode": args.mode, "client_context": {}}
        r2 = requests.post(f"{args.sidecar}/internal/agent/chat", json=body2,
                           headers=hdr, stream=True, timeout=900)
        if r2.status_code == 200:
            consume(_sse_lines(r2), "round2")
        else:
            print(f"    HTTP {r2.status_code} {r2.text[:200]}")

    print(f"\n=== SUMMARY ===")
    print(f"    final build status: {last_status or '(no done event)'}")
    print(f"    final pipeline nodes: {final_nodes}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
