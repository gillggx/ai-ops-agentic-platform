"""Chat-mode regression driver (W1). Runs operations questions through the chat
orchestrator (/internal/agent/chat) and verifies the REAL deliverable.

Two-leg flow per case:
  leg 1 (ask): POST the question. Chat routes a data question to a build-intent
    card (design_intent_confirm). We capture card_id + session_id.
  leg 2 (auto-confirm): re-POST [intent_confirmed:CARD] + the same session_id —
    the same thing the frontend does when the user clicks "開始建". This drives
    the Glass Box build to completion so we can grade what actually gets built.

Captures per case:
  - behavior        : answer / build_confirm / clarify / error
  - synthesis       : leg-1 answer / confirm-card text
  - confirmed_*     : the post-confirm deliverable — blocks (from pb_glass_done
                      .pipeline_json), ran (pb_run_done), answer, result_summary

Role: ON_DUTY (empty roles, fail-closed) is BLOCKED from build_pipeline_live, so
a data question dead-ends at "值班帳號無法建立 Pipeline". The eval runs as PE
(X-User-Roles, override via EVAL_ROLES) to exercise + verify the full build path.

Env: SVC_TOKEN (required), SIDECAR_BASE (default http://localhost:8050),
     OUT_FILE, EVAL_ROLES (default PE). Run on the EC2 host (sidecar not public).
"""
from __future__ import annotations

import json
import os
import time

import requests

SIDECAR = os.environ.get("SIDECAR_BASE", "http://localhost:8050")
SVC = os.environ["SVC_TOKEN"]
OUT_FILE = os.environ.get("OUT_FILE", "/tmp/chat_eval_results.json")
# Caller role gates the tool catalog: ON_DUTY (empty roles, fail-closed) is
# BLOCKED from build_pipeline_live, so a data question that routes to "build a
# pipeline" dead-ends with "你的帳號無法建立 Pipeline". To exercise + verify the
# full build path the eval runs as PE by default (override via EVAL_ROLES).
ROLES = os.environ.get("EVAL_ROLES", "PE")
HDR = {"X-Service-Token": SVC, "Content-Type": "application/json",
       "Accept": "text/event-stream", "X-User-Roles": ROLES}

# First batch — operations questions a duty engineer would actually ask. Kept
# behaviour-agnostic: the driver records what chat DOES; expected behaviour is
# set once (in grade_chat.py) after the product owner confirms whether a data
# question should be answered directly or answered-by-building-a-pipeline.
CASES = [
    ("status-one",   "EQP-01 現在狀態如何？"),
    ("status-fleet", "現在所有機台的狀態，標示異常的"),
    ("ooc-rank",     "列出最近 7 天 OOC 最多的 3 台機台"),
    ("ooc-count",    "EQP-08 過去 7 天有幾次 OOC？"),
    ("spc-trend",    "EQP-01 STEP_001 最近 100 筆 xbar 趨勢"),
    ("compare",      "比較 EQP-01 跟 EQP-02 過去 7 天的 OOC 次數"),
    ("knowledge",    "什麼是 WECO 規則？"),
    ("vague",        "幫我看一下機台"),
]


# Per-case wall-clock cap. The chat stream never goes idle (a keepalive `ping`
# fires every ~10s), so a build-confirm pivot — where the graph pauses waiting
# for the user to confirm a proposed pipeline — would otherwise hang the driver
# forever. We surface pings to the caller so it can break on (a) a confirm
# pause (synthesis delivered, then only pings) or (b) this hard cap.
MAX_WALL_SEC = 150


def _sse(resp):
    """Yield (event, data). Pings ARE surfaced (as ('ping', {})) so the caller's
    loop ticks ~every 10s even while the graph is paused on a confirm card."""
    buf = []
    for raw in resp.iter_lines(decode_unicode=True):
        if raw is None:
            continue
        if raw == "":
            if buf:
                ev = next((l[6:].strip() for l in buf if l.startswith("event:")), None)
                d = next((l[5:].strip() for l in buf if l.startswith("data:")), None)
                buf = []
                if not ev:
                    continue
                if ev == "ping":
                    yield "ping", {}
                    continue
                try:
                    yield ev, (json.loads(d) if d else {})
                except Exception:
                    yield ev, {"_raw": d}
        else:
            buf.append(raw)


def _classify(tools, synthesis, clarified, errored):
    if errored:
        return "error"
    # build-confirm: the agent proposed a pipeline and asked to confirm
    if any(t in tools for t in ("confirm_pipeline_intent", "build_pipeline_live")) \
       or ("確認要建" in synthesis or "開始建" in synthesis):
        return "build_confirm"
    if clarified:
        return "clarify"
    if synthesis.strip():
        return "answer"
    return "empty"


def _consume_leg(body, t0, max_wall):
    """POST one chat leg + drain the SSE stream. Returns captured signals.
    Breaks on done, on a confirm pause (2 pings after a synthesis), or the cap."""
    leg = {"synthesis": "", "tools": [], "iters": 0, "card_id": None,
           "session_id": None, "blocks": [], "ran": False, "result_summary": None,
           "clarified": False, "errored": False, "status": None, "n_events": 0}
    r = requests.post(f"{SIDECAR}/internal/agent/chat", json=body,
                      headers=HDR, stream=True, timeout=400)
    if r.status_code != 200:
        leg["errored"] = True
        leg["status"] = f"HTTP {r.status_code}"
        return leg
    synth_seen = False
    pings_after_synth = 0
    for ev, d in _sse(r):
        if time.time() - t0 > max_wall:
            leg["status"] = leg["status"] or "wall_clock_cap"
            break
        if ev == "ping":
            if synth_seen:
                pings_after_synth += 1
                if pings_after_synth >= 2:
                    break
            continue
        leg["n_events"] += 1
        if d.get("session_id"):
            leg["session_id"] = d["session_id"]
        if ev == "tool_start":
            leg["tools"].append(d.get("tool"))
        elif ev == "llm_usage":
            try:
                leg["iters"] = max(leg["iters"], int(d.get("iteration") or 0))
            except (TypeError, ValueError):
                pass
        elif ev == "synthesis":
            leg["synthesis"] += (d.get("text") or "")
            synth_seen = True
            pings_after_synth = 0
        elif ev == "design_intent_confirm":
            leg["card_id"] = d.get("card_id")
        elif ev == "pb_glass_done":
            # chat-mode Glass Box build finished — pipeline_json carries the nodes.
            nodes = (d.get("pipeline_json") or {}).get("nodes") or []
            if nodes:
                leg["blocks"] = [n.get("block_id") for n in nodes]
        elif ev == "pb_run_done":
            leg["ran"] = True
            leg["result_summary"] = d.get("result_summary")
        elif ev == "clarify":
            leg["clarified"] = True
        elif ev in ("error", "pb_run_error", "pb_glass_error"):
            leg["errored"] = True
        elif ev == "done":
            leg["status"] = d.get("status")
            break
    return leg


def run_one(key, message):
    acc = {"key": key, "tools_called": [], "iterations": 0, "synthesis": "",
           "behavior": None, "status": None, "n_events": 0,
           # leg-2 (post-confirm) — the REAL deliverable the agent builds + runs
           "confirmed": False, "confirmed_blocks": [], "confirmed_ran": False,
           "confirmed_answer": "", "confirmed_result": None}
    t0 = time.time()
    try:
        leg1 = _consume_leg({"message": message, "mode": "chat"}, t0, MAX_WALL_SEC)
        acc.update(tools_called=leg1["tools"], iterations=leg1["iters"],
                   synthesis=leg1["synthesis"], status=leg1["status"],
                   n_events=leg1["n_events"])
        clarified, errored = leg1["clarified"], leg1["errored"]

        # ── Intervention: auto-confirm the build-intent card so we can verify
        # the REAL pipeline + result, not just "a card appeared". Mirrors the
        # frontend confirm: re-POST /agent/chat with [intent_confirmed:CARD] +
        # the same session_id (the design_intent_confirm path, per chat
        # _walkthrough.py — NOT /chat/intent-respond).
        if leg1["card_id"] and leg1["session_id"]:
            confirm_msg = f"[intent_confirmed:{leg1['card_id']}] {message}"
            leg2 = _consume_leg({"message": confirm_msg, "mode": "chat",
                                 "session_id": leg1["session_id"]}, t0, MAX_WALL_SEC + 500)
            acc["confirmed"] = True
            acc["confirmed_blocks"] = leg2["blocks"]
            acc["confirmed_ran"] = leg2["ran"]
            acc["confirmed_answer"] = leg2["synthesis"]
            acc["confirmed_result"] = leg2["result_summary"]
            acc["status"] = leg2["status"] or acc["status"]
            errored = errored or leg2["errored"]
    except Exception as e:
        acc["exc"] = f"{type(e).__name__}: {str(e)[:160]}"
        errored = True
    acc["behavior"] = _classify(acc["tools_called"], acc["synthesis"], clarified, errored)
    acc["sec"] = round(time.time() - t0, 1)
    return acc


def main():
    import sys
    only = sys.argv[1] if len(sys.argv) > 1 else None
    cases = [(k, m) for k, m in CASES if (only is None or k == only)]
    results = []
    for i, (key, msg) in enumerate(cases, 1):
        r = run_one(key, msg)
        results.append(r)
        cf = (f" | confirmed: blocks={len(r['confirmed_blocks'])} ran={r['confirmed_ran']} "
              f"ans={(r['confirmed_answer'] or '').strip()[:40]!r}") if r["confirmed"] else ""
        print(f"[{i:2d}/{len(cases)}] {key:14s} behavior={r['behavior']:13s} "
              f"iters={r['iterations']} tools={len(r['tools_called'])} "
              f"{r['sec']}s :: {(r['synthesis'] or '').strip()[:50]!r}{cf}", flush=True)
    json.dump(results, open(OUT_FILE, "w"), ensure_ascii=False, indent=2)
    print(f"  results -> {OUT_FILE}", flush=True)


if __name__ == "__main__":
    main()
