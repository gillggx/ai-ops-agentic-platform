"""chat_verify.py — POST /internal/agent/chat and replay SSE EXACTLY as
ChatPanel.tsx's switch statement would. Drops everything the UI drops.

Lesson 2026-05-17 v30.17a: a "PASS" verification at sidecar log level
turned out to be invisible to the chat UI because wrap_build_event_for_chat
returned None for v30 event types. Always verify through this harness.

Keep CHAT_UI_HANDLED_EVENTS in sync with:
  aiops-app/src/components/chat/ChatPanel.tsx  switch (type) { ... }
  (around line 171; cases listed line 172-370)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import requests


# ── Port from ChatPanel.tsx ─────────────────────────────────────────────────
# Source-of-truth: aiops-app/src/components/chat/ChatPanel.tsx
# Last verified: 2026-05-17 (commit 94d358f), lines 172-373.
#
# If you add/rename a `case "..."` branch in ChatPanel, also update this set.
# Any event NOT in this set will be DROPPED by the UI (rendered as nothing).
CHAT_UI_HANDLED_EVENTS = frozenset({
    # Lifecycle / observability ---
    "stage_update",        # 172
    "context_load",        # 186
    "thinking",            # 194
    "llm_usage",           # 198
    "tool_start",          # 207
    "tool_done",           # 221
    "memory_write",        # 247
    "reflection_running",  # 260
    "reflection_pass",     # 264
    "reflection_amendment",# 268
    "approval_required",   # 283
    "synthesis",           # 294
    "done",                # 311
    "error",               # 315
    "plan",                # 320

    # Pipeline-Builder Glass Box events (chat-mode build_pipeline_live tool)
    "pb_glass_start",      # 333
    "pb_glass_chat",       # 339
    "pb_glass_op",         # 350
    "pb_glass_done",       # 358

    # v18 intent confirmation
    "pb_intent_confirm",   # 370
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
    ap.add_argument("message", help="User message to chat (use [intent_confirmed:id] prefix to force build path)")
    ap.add_argument("--sidecar", default=os.environ.get("SIDECAR_BASE", "http://localhost:8050"))
    ap.add_argument("--session-id", default=None)
    ap.add_argument("--mode", default="chat")
    args = ap.parse_args()

    svc = os.environ.get("SVC_TOKEN")
    if not svc:
        print("ERROR: SVC_TOKEN env var required", file=sys.stderr)
        return 2

    body = {
        "message": args.message,
        "session_id": args.session_id,
        "mode": args.mode,
        "client_context": {},
    }
    hdr = {"X-Service-Token": svc, "Content-Type": "application/json",
           "Accept": "text/event-stream"}

    t0 = time.time()
    print(f"[META] POST {args.sidecar}/internal/agent/chat  msg={_short(args.message, 80)}")
    r = requests.post(f"{args.sidecar}/internal/agent/chat", json=body,
                       headers=hdr, stream=True, timeout=600)
    print(f"[META] HTTP {r.status_code}")
    if r.status_code != 200:
        print("[META] body:", r.text[:300])
        return 1

    ui_count = 0
    drop_count = 0
    by_type = {}
    last_synthesis_text = None
    pb_glass_ops = 0
    pb_glass_chats = 0

    for ev, data in _sse_lines(r):
        by_type[ev] = by_type.get(ev, 0) + 1
        d = data or {}
        if ev in CHAT_UI_HANDLED_EVENTS:
            ui_count += 1
            extra = ""
            if ev == "synthesis":
                last_synthesis_text = d.get("text") or ""
                extra = f"  text={_short(last_synthesis_text, 80)}"
            elif ev == "pb_glass_chat":
                pb_glass_chats += 1
                extra = f"  content={_short(d.get('content') or '', 80)}"
            elif ev == "pb_glass_op":
                pb_glass_ops += 1
                extra = f"  op={d.get('op')} desc={_short(d.get('description') or '', 60)}"
            elif ev == "pb_glass_done":
                extra = f"  status={d.get('status')} nodes={len((d.get('pipeline_json') or {}).get('nodes', []))}"
            elif ev == "tool_start":
                extra = f"  tool={d.get('tool')}"
            elif ev == "pb_intent_confirm":
                extra = f"  bullets={len(d.get('bullets') or [])}"
            print(f"[UI]   ev={ev}{extra}")
            if ev == "done":
                break
        else:
            drop_count += 1
            print(f"[DROP] ev={ev}  data_keys={list(d.keys())[:5]}")

    elapsed = time.time() - t0
    print()
    print(f"[META] elapsed {elapsed:.1f}s — UI seen {ui_count}, dropped {drop_count}")
    print("[META] event counts by type:")
    for t, c in sorted(by_type.items(), key=lambda x: -x[1]):
        flag = "  " if t in CHAT_UI_HANDLED_EVENTS else "  [DROP]"
        print(f"  {c:4d}  {t}{flag}")

    print()
    print("[META] Summary for user-facing experience:")
    if pb_glass_chats == 0 and pb_glass_ops == 0:
        print("  [no] no pb_glass_chat or pb_glass_op events — chat UI shows NO build progress to user")
    else:
        print(f"  [ok] {pb_glass_chats} pb_glass_chat + {pb_glass_ops} pb_glass_op events — user sees build progress")
    if last_synthesis_text:
        print(f"  synthesis text: {_short(last_synthesis_text, 200)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
