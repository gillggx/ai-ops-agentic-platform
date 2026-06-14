"""V58 RAG recall harness — does layer-filtered retrieval surface the RIGHT
knowledge for a given query?

The whole P2/P3 bet is that execute-layer RAG, queried by a phase goal,
surfaces the block-choice knowledge that goal_plan (block-agnostic) can't
carry. This script measures that directly: for each probe (query, layer,
expected knowledge id), it embeds the query, runs the layer-filtered cosine
search, and reports the rank at which the expected entry appears (or MISS).

It also gates P4 — retiring the always-on full dump. If plan-layer RAG recall
of the non-core entries is poor, we keep them always-on; if good, we can shrink.

Run inside the sidecar venv on EC2 (needs the embedding service + Java):

    cd /opt/aiops && python -m tools.knowledge_recall.measure

Exit code 0 if every CRITICAL probe is recalled within its k; 1 otherwise.
"""

from __future__ import annotations

import asyncio
import sys

# (query, layer, expected_id, k, critical)
#   layer='execute' → applies_to ∈ {execute, both}; 'plan' → {plan, both}.
#   critical=True probes gate the exit code (the spc-ooc fix must work).
PROBES: list[tuple[str, str, int, int, bool]] = [
    # ── execute layer: phase goals must surface block-choice knowledge ──
    # spc-ooc p1 — the case that started this. Must surface id 36
    # (全廠聚合 → list_objects + foreach).
    ("取得過去 24 小時各機台的 SPC OOC 統計資料", "execute", 36, 2, True),
    ("全廠所有機台過去七天的 OOC 次數", "execute", 36, 3, True),
    # apc-recipe-compare — must surface id 38 (參數分佈用 flat-mode 別 unnest).
    ("EQP-01 過去 14 天每個 recipe 的 APC etch_time_offset 分佈 box plot", "execute", 38, 3, True),
    # spc trend before/after an event — must surface id 35 (別砍 history).
    ("畫 EQP-01 SPC trend 看某次 OOC event 前後的走勢", "execute", 35, 3, False),
    # multi-tool named — id 37.
    ("比較 EQP-01 EQP-02 EQP-03 三台機台的 xbar chart", "execute", 37, 3, False),
    # ── plan layer: instruction must surface plan-shaping knowledge ──
    ("過去 24 小時哪些機台 SPC OOC 最多 列前 5 名", "plan", 36, 3, False),
    ("顯示 EQP-08 過去 7 天的 SPC 趨勢", "plan", 31, 3, False),
]


async def _run() -> int:
    from python_ai_sidecar.agent_orchestrator_v2.nodes.load_context import (
        _embed_query, _vec_to_pg_literal,
    )
    from python_ai_sidecar.clients.java_client import JavaAPIClient
    from python_ai_sidecar.config import CONFIG

    java = JavaAPIClient(
        CONFIG.java_api_url, CONFIG.java_internal_token,
        timeout_sec=CONFIG.java_timeout_sec,
    )

    print(f"{'layer':8s} {'k':>2s} {'rank':>5s} {'hit':>4s}  query → expect id")
    print("-" * 92)
    failures = 0
    for query, layer, expect_id, k, critical in PROBES:
        vec = await _embed_query(query)
        if vec is None:
            print(f"{layer:8s} {k:>2d}  EMBED-FAIL  {query[:48]!r}")
            if critical:
                failures += 1
            continue
        # fetch a few extra so we can see the rank even past k
        rows = await java.search_knowledge(
            user_id=1, query_vec_literal=_vec_to_pg_literal(vec),
            layer=layer, limit=max(k, 5),
        )
        ids = [int(r.get("id")) for r in rows if r.get("id") is not None]
        rank = (ids.index(expect_id) + 1) if expect_id in ids else None
        hit = rank is not None and rank <= k
        mark = "OK" if hit else ("late" if rank else "MISS")
        crit = " *" if critical else ""
        rank_s = str(rank) if rank else "-"
        print(f"{layer:8s} {k:>2d} {rank_s:>5s} {mark:>4s}{crit}  {query[:46]!r} → {expect_id}")
        if critical and not hit:
            failures += 1

    print("-" * 92)
    if failures:
        print(f"[no] {failures} CRITICAL probe(s) missed — execute-layer RAG not "
              f"reliable yet; keep id 36/38 reachable another way before flipping flags.")
        return 1
    print("[ok] all CRITICAL probes recalled within k — execute-layer retrieval works.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
