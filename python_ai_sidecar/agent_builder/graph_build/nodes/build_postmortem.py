"""build_postmortem_node — Coordinator failure recovery (2026-07-09).

When a build would give up (status=handover_pending — even the phase-local
G2 work orders + M2 plan patch couldn't advance the stuck phase), don't just
hand back to the user. The Coordinator does ONE holistic post-mortem — like
the /verify-build narrative a human does by hand:

  建到哪了  — which phases completed
  卡在哪    — the stuck phase + why (last diagnosis / reject reason)
  少什麼    — what the pipeline is missing to get past it
  修正方向  — a concrete direction for the Planner

…then replans WITH that direction (v30_replan_hint) and lets the Builder try
once more. Capped at 1 (v30_postmortem_count) so it never loops: a second
give-up goes straight to halt_handover, now carrying the post-mortem so the
user sees why it failed, not a blank "failed".

Pure reasoning node: reads state (no tools). The forensic input is what the
build already recorded — completed phase outcomes, the stuck phase, the last
G2 diagnosis, the last verifier reject.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict

from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client
from python_ai_sidecar.observability.episode_recorder import get_current_recorder

logger = logging.getLogger(
    "python_ai_sidecar.agent_builder.graph_build.nodes.build_postmortem")

_SYSTEM = """你是 Coordinator（建置失敗驗屍）。一條 pipeline 建到一半卡住、連自動修正
都救不動。你會拿到：原始需求、計畫的每個 phase、哪些已完成、卡在哪個 phase、
最後的診斷與退件原因。

像資深工程師一樣退一步看全局，輸出 JSON（只輸出 JSON）：
{"progress": "已完成到哪（一句話）",
 "stuck": "卡在哪個 phase、為什麼（一句話）",
 "missing": "要越過這關，pipeline 還缺什麼（一句話，具體：缺哪個聚合/欄位/接線/block）",
 "correction": "給 Planner 重新規劃的修正方向（2-3 句，具體到「這次計畫要包含 X 步驟/用 Y 而不是 Z」，
                讓下一版計畫能繞過這個卡點）"}

原則：
- correction 要可操作、對症下藥（例：「缺一個 count 聚合，計畫在 filter 後要加一個
  groupby_agg(count) 步驟再接 threshold」），不要空泛（不要只說「修好接線」）。
- 若卡點根因是「本來就做不到 / 需求本身有問題」，correction 誠實說明，別硬掰。
只輸出 JSON。"""


def _forensic_input(state: Dict[str, Any]) -> str:
    phases = state.get("v30_phases") or []
    outcomes = state.get("v30_phase_outcomes") or {}
    idx = int(state.get("v30_current_phase_idx") or 0)
    stuck = phases[idx] if 0 <= idx < len(phases) else None
    done = [p for p in phases
            if (outcomes.get(str(p.get("id"))) or {}).get("status") == "completed"]
    diag = state.get("v30_patch_diagnosis") or {}
    reject = state.get("v30_last_verifier_reject") or state.get("v30_last_judge_reject_reason")
    return json.dumps({
        "instruction": str(state.get("instruction") or "")[:400],
        "plan_phases": [{"id": p.get("id"), "expected": p.get("expected"),
                         "text": (p.get("text") or "")[:120]} for p in phases],
        "completed_phase_ids": [p.get("id") for p in done],
        "stuck_phase": ({"id": stuck.get("id"), "expected": stuck.get("expected"),
                         "text": (stuck.get("text") or "")[:150]} if stuck else None),
        "last_diagnosis": {"kind": diag.get("kind"), "detail": str(diag.get("diagnosis") or diag.get("reason") or "")[:250]},
        "last_reject": str(reject or "")[:250],
    }, ensure_ascii=False)


async def build_postmortem_node(state: BuildGraphState) -> dict[str, Any]:  # noqa: F821
    forensic = _forensic_input(state)
    try:
        client = get_llm_client()
        resp = await client.create(
            system=_SYSTEM,
            messages=[{"role": "user", "content": forensic}],
            max_tokens=700,
        )
        raw = (resp.text or "").strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            if raw.rstrip().endswith("```"):
                raw = raw.rstrip()[:-3]
        pm = json.loads(raw)
    except Exception as ex:  # noqa: BLE001 — never block give-up on the LLM
        logger.warning("build_postmortem: failed (%s) — hand over without recovery", ex)
        return {"status": "handover_pending"}

    correction = str((pm or {}).get("correction") or "").strip()
    postmortem = {
        "progress": str((pm or {}).get("progress") or "")[:200],
        "stuck": str((pm or {}).get("stuck") or "")[:200],
        "missing": str((pm or {}).get("missing") or "")[:200],
        "correction": correction[:500],
    }
    count = int(state.get("v30_postmortem_count") or 0) + 1

    rec = get_current_recorder()
    if rec:
        rec.record("build_postmortem", agent="repair", payload={**postmortem, "attempt": count})
        rec.record("llm_usage", agent="repair",
                   input_tokens=getattr(resp, "input_tokens", None),
                   output_tokens=getattr(resp, "output_tokens", None),
                   latency_ms=getattr(resp, "latency_ms", None))

    logger.info("build_postmortem #%d: stuck=%s missing=%s", count,
                postmortem["stuck"][:60], postmortem["missing"][:60])

    if not correction:
        # No actionable direction → don't loop; hand over with the report.
        return {"status": "handover_pending", "v30_postmortem": postmortem,
                "v30_postmortem_count": count}

    # Replan WITH the correction as a hint; reset the stuck-phase cursor so
    # goal_plan produces a fresh plan the Builder retries.
    hint = (f"上一版建置卡住了。診斷：{postmortem['stuck']}。缺的是：{postmortem['missing']}。"
            f"這次規劃請照這個方向修正：{correction}")
    return {
        "v30_replan_hint": hint,
        "v30_postmortem": postmortem,
        "v30_postmortem_count": count,
        # neutral status; the graph edge build_postmortem -> goal_plan is
        # unconditional, and goal_plan will reset the phase machinery.
        "status": "running",
    }
