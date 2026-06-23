"""Chat-mode regression driver (W1). Runs a batch of operations questions through
the chat orchestrator (/internal/agent/chat) and captures behaviour-agnostic
signals per case so we can SEE what chat does before fixing anything.

Captures per case:
  - tools_called : ordered tool names from `tool_start` events
  - iterations   : max llm_usage.iteration (efficiency proxy)
  - synthesis    : final answer text from the `synthesis` event(s)
  - behavior     : classified terminal behaviour — answer / build_confirm /
                   clarify / error / empty
  - status       : the `done` payload status (if any)

Env: SVC_TOKEN (required), SIDECAR_BASE (default http://localhost:8050),
     OUT_FILE (default /tmp/chat_eval_results.json).
Run on the EC2 host (sidecar not publicly exposed).
"""
from __future__ import annotations

import json
import os
import time

import requests

SIDECAR = os.environ.get("SIDECAR_BASE", "http://localhost:8050")
SVC = os.environ["SVC_TOKEN"]
OUT_FILE = os.environ.get("OUT_FILE", "/tmp/chat_eval_results.json")
HDR = {"X-Service-Token": SVC, "Content-Type": "application/json",
       "Accept": "text/event-stream"}

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


def run_one(key, message):
    acc = {"key": key, "tools_called": [], "iterations": 0,
           "synthesis": "", "behavior": None, "status": None, "n_events": 0}
    clarified = errored = False
    t0 = time.time()
    try:
        r = requests.post(f"{SIDECAR}/internal/agent/chat",
                          json={"message": message, "mode": "chat"},
                          headers=HDR, stream=True, timeout=400)
        if r.status_code != 200:
            acc["behavior"] = "error"
            acc["status"] = f"HTTP {r.status_code}"
            acc["sec"] = round(time.time() - t0, 1)
            return acc
        synth_seen = False
        pings_after_synth = 0
        for ev, d in _sse(r):
            # Hard cap — covers any non-terminating stream.
            if time.time() - t0 > MAX_WALL_SEC:
                acc["status"] = acc["status"] or "wall_clock_cap"
                break
            if ev == "ping":
                # A confirm pivot delivers its synthesis card then pauses (only
                # pings flow). Two pings after a synthesis = terminal pause.
                if synth_seen:
                    pings_after_synth += 1
                    if pings_after_synth >= 2:
                        break
                continue
            acc["n_events"] += 1
            if ev == "tool_start":
                acc["tools_called"].append(d.get("tool"))
            elif ev == "llm_usage":
                try:
                    acc["iterations"] = max(acc["iterations"], int(d.get("iteration") or 0))
                except (TypeError, ValueError):
                    pass
            elif ev == "synthesis":
                acc["synthesis"] += (d.get("text") or "")
                synth_seen = True
                pings_after_synth = 0
            elif ev in ("clarify", "design_intent_confirm", "pb_intent_confirm"):
                if ev == "clarify":
                    clarified = True
            elif ev in ("error", "pb_run_error", "pb_glass_error"):
                errored = True
            elif ev == "done":
                acc["status"] = d.get("status")
                break
    except Exception as e:
        acc["exc"] = f"{type(e).__name__}: {str(e)[:160]}"
        errored = True
    acc["behavior"] = _classify(acc["tools_called"], acc["synthesis"], clarified, errored)
    acc["sec"] = round(time.time() - t0, 1)
    return acc


def main():
    results = []
    for i, (key, msg) in enumerate(CASES, 1):
        r = run_one(key, msg)
        results.append(r)
        print(f"[{i:2d}/{len(CASES)}] {key:14s} behavior={r['behavior']:13s} "
              f"iters={r['iterations']} tools={len(r['tools_called'])} "
              f"{r['sec']}s :: {(r['synthesis'] or '').strip()[:60]!r}", flush=True)
    json.dump(results, open(OUT_FILE, "w"), ensure_ascii=False, indent=2)
    print(f"  results -> {OUT_FILE}", flush=True)


if __name__ == "__main__":
    main()
