#!/usr/bin/env python3
"""Supervisor v1 report renderer (spec §5, G3: manual + weekly cron).

Pulls the aggregates from Java's internal report endpoint and renders a
markdown report. REPORT + DRAFT SUGGESTIONS ONLY — writes nothing back.

Usage (on EC2):
    JAVA_INTERNAL_TOKEN=$(grep ^JAVA_INTERNAL_TOKEN= /opt/aiops/python_ai_sidecar/.env | cut -d= -f2-) \
        python3 tools/supervisor_report/run.py --days 30 --out /tmp/supervisor_report.md

Weekly cron (documented, not auto-installed):
    0 8 * * 1  cd /opt/aiops && JAVA_INTERNAL_TOKEN=... python3 tools/supervisor_report/run.py \
               --days 7 --out /tmp/supervisor_report_$(date +%%Y%%m%%d).md
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone


def fetch(base: str, token: str, days: int) -> dict:
    req = urllib.request.Request(
        f"{base}/internal/agent-episodes/report?days={days}",
        headers={"X-Internal-Token": token},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.load(resp)
    return body.get("data") or body


def render(r: dict) -> str:
    ep = r.get("episodes") or {}
    lines: list[str] = []
    lines.append(f"# Supervisor 週期報告（過去 {r.get('window_days')} 天）")
    lines.append(f"\n> 產生時間:{datetime.now(timezone.utc).isoformat()}Z · "
                 f"read-only 報告與草案,未自動修改任何東西。\n")

    lines.append("## 1. Episode 總覽")
    total = ep.get("total", 0)
    fin = ep.get("finished", 0)
    lines.append(f"- 總 build:{total};finished:{fin}"
                 f"（{(100 * fin / total):.0f}%）" if total else "- 無資料")
    lines.append(f"- divergence（自認 OK 但 user 否決）:{ep.get('divergent', 0)}")
    lines.append(f"- 平均事件數/episode:{ep.get('avg_steps', 0)}\n")

    lines.append("## 2. Doc-gap Top-N（verifier 拒絕最多的 block）")
    gaps = r.get("doc_gaps") or []
    if gaps:
        lines.append("| block | rejects | builds |")
        lines.append("|---|---|---|")
        for g in gaps:
            lines.append(f"| {g.get('block')} | {g.get('rejects')} | {g.get('builds')} |")
        lines.append("\n**草案建議**:上表 rejects 最高的 block,優先檢視其 "
                      "description / param_schema 是否寫清楚(依 spec 這是 doc 不齊的第一訊號)。\n")
    else:
        lines.append("(窗口內無 verifier reject — 無 doc-gap 訊號)\n")

    lines.append("## 3. Plan 被 user 修改(重複 pattern 原料)")
    edits = r.get("plan_edits") or []
    if edits:
        for e in edits[:10]:
            lines.append(f"- `{e.get('episode_key', '')[:12]}…` {e.get('ts', '')}: "
                         f"{str(e.get('edit_payload', ''))[:180]}")
        lines.append("\n**草案建議**:若同類修改反覆出現(如時間窗/呈現形式),"
                      "應提為 preference/presentation 記憶草案(Phase 4)。\n")
    else:
        lines.append("(窗口內無 plan 編輯)\n")

    lines.append("## 4. 成本歸因(per-agent)")
    costs = r.get("cost_by_agent") or []
    if costs:
        lines.append("| agent | calls | input | output | cache_read | cache% |")
        lines.append("|---|---|---|---|---|---|")
        for c in costs:
            inp = int(c.get("input") or 0)
            cr = int(c.get("cache_read") or 0)
            tot = inp + cr
            pct = f"{100 * cr / tot:.1f}%" if tot else "-"
            lines.append(f"| {c.get('agent')} | {c.get('calls')} | {inp} | "
                         f"{c.get('output')} | {cr} | {pct} |")
        lines.append("")
    else:
        lines.append("(無 llm_usage 資料)\n")

    lines.append("## 5. Divergence 清單(金礦 — 逐案人工檢討)")
    div = r.get("divergences") or []
    if div:
        for d in div:
            lines.append(f"- `{d.get('episode_key', '')[:12]}…` "
                         f"instr: {d.get('instruction')} | feedback: {d.get('user_feedback')}")
        lines.append("")
    else:
        lines.append("(無 divergence — 或 feedback 三鍵使用量still低)\n")

    lines.append("## 6. Repair 結果分佈")
    rep = r.get("repair_outcomes") or []
    if rep:
        for x in rep:
            lines.append(f"- {x.get('result')}: {x.get('count')}")
        lines.append("")
    else:
        lines.append("(窗口內無 repair 事件)\n")

    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--base", default=os.environ.get("JAVA_API_URL", "http://localhost:8002"))
    ap.add_argument("--out", default=None, help="write markdown here (default stdout)")
    args = ap.parse_args()

    token = os.environ.get("JAVA_INTERNAL_TOKEN", "").strip()
    if not token:
        print("ERROR: set JAVA_INTERNAL_TOKEN (see python_ai_sidecar/.env)", file=sys.stderr)
        return 2

    md = render(fetch(args.base.rstrip("/"), token, args.days))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"report -> {args.out}")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
