"""builder_verify.py — POST /internal/agent/build and replay SSE EXACTLY
as AgentBuilderPanelV30.tsx's handleEvent dispatcher would.

Keep BUILDER_UI_HANDLED_EVENTS in sync with:
  aiops-app/src/components/pipeline-builder/AgentBuilderPanelV30.tsx
  handleEvent(...) (around line 144)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import requests


# ── Port from AgentBuilderPanelV30.tsx handleEvent ──────────────────────────
# Source-of-truth: AgentBuilderPanelV30.tsx, handleEvent(), lines 144-302.
# Last verified: 2026-05-17 (commit 94d358f).
BUILDER_UI_HANDLED_EVENTS = frozenset({
    "goal_plan_proposed",          # 149
    "goal_plan_confirmed",         # 161
    "goal_plan_rejected",          # 164
    "goal_plan_refused",           # 164
    "phase_started",               # 167
    "phase_round",                 # 176
    "phase_action",                # 187
    "phase_observation",           # 206 (silent but handled)
    "phase_completed",             # 208
    "phase_fast_forward_report",   # 229
    "phase_verifier_no_match",     # 244 (silent but handled)
    "phase_revise_started",        # 247
    "phase_revise_retry",          # 258
    "handover_pending",            # 269
    "handover_chosen",             # 285
    "build_finalized",             # 288
    "done",                        # 288
    "error",                       # 295
})


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instruction", help="Build instruction")
    ap.add_argument("--sidecar", default=os.environ.get("SIDECAR_BASE", "http://localhost:8050"))
    ap.add_argument("--skill-step-mode", action="store_true", default=False)
    ap.add_argument("--v30-mode", action="store_true", default=True,
                    help="default True since v30.14")
    ap.add_argument("--no-v30-mode", dest="v30_mode", action="store_false")
    ap.add_argument("--auto-confirm-plan", action="store_true", default=True,
                    help="If goal_plan_confirm_required fires, auto-POST /plan-confirm")
    args = ap.parse_args()

    svc = os.environ.get("SVC_TOKEN")
    if not svc:
        print("ERROR: SVC_TOKEN env var required", file=sys.stderr)
        return 2

    body = {
        "instruction": args.instruction,
        "skill_step_mode": args.skill_step_mode,
        "v30_mode": args.v30_mode,
    }
    hdr = {"X-Service-Token": svc, "Content-Type": "application/json",
           "Accept": "text/event-stream"}

    def run_stream(label, url, body):
        nonlocal ui_count, drop_count, by_type, plan_required_sid, build_status
        print(f"[META] {label}: POST {url}  body_keys={list(body.keys())}")
        r = requests.post(url, json=body, headers=hdr, stream=True, timeout=900)
        print(f"[META] HTTP {r.status_code}")
        if r.status_code != 200:
            print("[META] body:", r.text[:300]); return False

        for ev, data in _sse_lines(r):
            by_type[ev] = by_type.get(ev, 0) + 1
            d = data or {}
            if ev == "goal_plan_confirm_required":
                # NOT in handled set by name (Builder uses goal_plan_proposed +
                # waits for user click). But also relayed here so harness can
                # auto-confirm if --auto-confirm-plan
                plan_required_sid = d.get("session_id")
                drop_count += 1
                print(f"[DROP] ev={ev}  session_id={plan_required_sid} (will auto-confirm if enabled)")
                # break out so we can POST /plan-confirm
                return True
            if ev in BUILDER_UI_HANDLED_EVENTS:
                ui_count += 1
                extra = ""
                if ev == "goal_plan_proposed":
                    extra = f"  phases={len(d.get('phases') or [])}"
                elif ev == "goal_plan_confirmed":
                    extra = f"  auto={d.get('auto_confirmed')}"
                elif ev == "phase_action":
                    extra = f"  p={d.get('phase_id')} r={d.get('round')} tool={d.get('tool')}"
                elif ev == "phase_completed":
                    extra = f"  p={d.get('phase_id')} rationale={_short(d.get('rationale') or '', 60)}"
                elif ev == "phase_revise_started":
                    extra = f"  p={d.get('phase_id')} reason={_short(d.get('reason') or '', 60)}"
                elif ev == "handover_pending":
                    extra = f"  failed_at={d.get('failed_phase_id')} reason={_short(d.get('reason') or '', 60)}"
                elif ev == "handover_chosen":
                    extra = f"  choice={d.get('choice')} auto={d.get('auto_chosen')}"
                elif ev == "done":
                    nodes = len((d.get('pipeline_json') or {}).get('nodes') or [])
                    extra = f"  status={d.get('status')} nodes={nodes}"
                    build_status = d.get("status")
                print(f"[UI]   ev={ev}{extra}")
                if ev == "done": return True
            else:
                drop_count += 1
                print(f"[DROP] ev={ev}  data_keys={list(d.keys())[:5]}")
        return True

    ui_count = 0; drop_count = 0; by_type = {}; plan_required_sid = None
    build_status = None
    t0 = time.time()

    cont = run_stream("initial /agent/build",
                       f"{args.sidecar}/internal/agent/build", body)

    # If gate fired and auto-confirm enabled, POST /plan-confirm + drain again
    if plan_required_sid and args.auto_confirm_plan:
        print(f"\n[META] auto-confirming plan for session {plan_required_sid}")
        body2 = {"sessionId": plan_required_sid, "confirmed": True}
        run_stream("/agent/build/plan-confirm",
                    f"{args.sidecar}/internal/agent/build/plan-confirm", body2)

    elapsed = time.time() - t0
    print()
    print(f"[META] elapsed {elapsed:.1f}s — UI seen {ui_count}, dropped {drop_count}")
    print(f"[META] build status: {build_status}")
    print("[META] event counts by type:")
    for t, c in sorted(by_type.items(), key=lambda x: -x[1]):
        flag = "" if t in BUILDER_UI_HANDLED_EVENTS else " [DROP]"
        print(f"  {c:4d}  {t}{flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
