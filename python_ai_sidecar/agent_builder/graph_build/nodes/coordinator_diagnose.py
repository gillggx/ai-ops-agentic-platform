"""coordinator_diagnose_node — G2 失敗診斷 + 修理工單 (成本結構修正 波2).

Before: a stuck phase went to phase_revise, which produced a narrative
"alternative strategy" and re-entered the FULL agent loop with fresh
budget — a second planner in practice, expensive and prone to leaving
dead nodes behind.

Now (per the agreed two-agent behavior spec): the Coordinator diagnoses
the failure ONCE (narrow LLM classification) and emits a MINIMAL work
order that the Builder toolset executes MECHANICALLY — no LLM rounds:

    {"kind": "param_error|wiring_error|wrong_block|data_empty|plan_error",
     "diagnosis": "...",
     "ops": [{"op": "set_param",  "node": "n3", "key": "column", "value": "name"},
             {"op": "connect",    "from": "n2", "to": "n3"},
             {"op": "remove_node","node": "n4"}]}

Hard rules (deterministic, after the LLM):
  - ops ≤ 5, only set_param / connect / remove_node (v1);
  - referenced nodes must exist on the canvas;
  - kind=plan_error (or 2 spent work orders) escalates to plan_patch (M2)
    with the diagnosis envelope — the Planner never re-diagnoses.

After a successfully applied order the graph goes STRAIGHT to
phase_verifier (the order carried its own preview refresh) — no extra
agent round to "confirm" what a deterministic gate can check.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from python_ai_sidecar.agent_builder.graph_build.state import BuildGraphState
from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client

logger = logging.getLogger(
    "python_ai_sidecar.agent_builder.graph_build.nodes.coordinator_diagnose")

MAX_WORK_ORDERS_PER_PHASE = 2
_ALLOWED = {"set_param", "connect", "remove_node"}

_SYSTEM = """你是 Coordinator（調度員）。一個建置 phase 卡住了，你要做的是「診斷 + 開最小修理工單」，
不是重新規劃。輸出 JSON：

{"kind": "param_error" | "wiring_error" | "wrong_block" | "data_empty" | "plan_error",
 "diagnosis": "一句話根因",
 "ops": [{"op": "set_param", "node": "<node id>", "key": "<param>", "value": <值>},
         {"op": "connect", "from": "<node id>", "to": "<node id>"},
         {"op": "remove_node", "node": "<node id>"}]}

規則：
- 工單是最小修理動作（≤5 個 ops），只能用 set_param / connect / remove_node。
- 參數值必須來自「畫布狀態 / 執行快照」裡看得到的真實欄位與值 — 不要發明。
- 選錯 block 的情境：開 remove_node 把錯的節點拆掉即可（建造員會重選）。
- 若根因是「計畫本身的做法錯了」（不是操作層能修的）→ kind=plan_error、ops=[]，
  diagnosis 寫清楚為什麼，交給 Planner 修訂計畫。
只輸出 JSON。"""


def validate_work_order(
    ops: list[dict[str, Any]],
    node_ids: set[str],
) -> tuple[list[dict[str, Any]] | None, str]:
    """Deterministic order validation — LLM output is never trusted."""
    if not isinstance(ops, list) or not ops:
        return None, "empty ops"
    if len(ops) > 5:
        return None, f"too many ops ({len(ops)} > 5)"
    clean: list[dict[str, Any]] = []
    for op in ops:
        if not isinstance(op, dict):
            return None, "op is not an object"
        kind = op.get("op")
        if kind not in _ALLOWED:
            return None, f"op '{kind}' not allowed"
        if kind == "set_param":
            node, key = str(op.get("node") or ""), str(op.get("key") or "")
            if node not in node_ids:
                return None, f"set_param: unknown node '{node}'"
            if not key:
                return None, "set_param: missing key"
            clean.append({"op": "set_param", "node": node, "key": key,
                          "value": op.get("value")})
        elif kind == "connect":
            f, t = str(op.get("from") or ""), str(op.get("to") or "")
            if f not in node_ids or t not in node_ids:
                return None, f"connect: unknown node '{f}'->'{t}'"
            clean.append({"op": "connect", "from": f, "to": t})
        else:  # remove_node
            node = str(op.get("node") or "")
            if node not in node_ids:
                return None, f"remove_node: unknown node '{node}'"
            clean.append({"op": "remove_node", "node": node})
    return clean, ""


async def coordinator_diagnose_node(state: BuildGraphState) -> dict[str, Any]:
    from python_ai_sidecar.agent_builder.graph_build.nodes.plan import (
        _extract_first_json_object,
    )
    from python_ai_sidecar.agent_builder.graph_build.trace import get_current_tracer
    from python_ai_sidecar.agent_builder.session import AgentBuilderSession
    from python_ai_sidecar.agent_builder.tools import BuilderToolset, ToolError
    from python_ai_sidecar.pipeline_builder.pipeline_schema import PipelineJSON
    from python_ai_sidecar.pipeline_builder.seedless_registry import SeedlessBlockRegistry
    from python_ai_sidecar.pipeline_builder.source_cache import get_session_cache

    phases = state.get("v30_phases") or []
    idx = state.get("v30_current_phase_idx", 0)
    if not phases or idx >= len(phases):
        return {"status": "phase_in_progress"}
    phase = phases[idx]
    pid = str(phase.get("id"))
    tracer = get_current_tracer()

    counts = dict(state.get("v30_work_order_counts") or {})
    used = int(counts.get(pid) or 0)

    def _escalate(reason: str, tried: str) -> dict[str, Any]:
        """→ plan_patch (M2) with the diagnosis envelope."""
        logger.info("coordinator: escalate to plan_patch (%s)", reason)
        return {
            "status": "plan_patch_pending",
            "v30_work_order_counts": counts,
            "v30_patch_diagnosis": {
                "failed_phase_id": pid,
                "reason": reason[:300],
                "tried_summary": tried[:400],
            },
            "sse_events": [_sse("plan_patch_started", {
                "failed_phase_id": pid, "reason": reason[:200],
            })],
        }

    prior_orders = state.get("v30_last_work_order") or {}
    tried_summary = str(prior_orders.get("digest") or "")

    if used >= MAX_WORK_ORDERS_PER_PHASE:
        return _escalate(f"{used} 張工單皆未修復 — 判定計畫層問題", tried_summary)

    # ── Diagnosis context ────────────────────────────────────────────
    pj_dict = state.get("final_pipeline") or state.get("base_pipeline") or {}
    nodes = pj_dict.get("nodes") or []
    node_ids = {str(n.get("id")) for n in nodes if n.get("id")}
    exec_trace = state.get("exec_trace") or {}
    reject = state.get("v30_last_verifier_reject") or {}
    recent = (state.get("v30_phase_recent_actions") or {}).get(pid, [])

    # deterministic hint: empty upstreams (rows==0)
    empty_ups = [f"{nid}({(snap or {}).get('block_id')})"
                 for nid, snap in exec_trace.items()
                 if isinstance(snap, dict) and snap.get("rows") == 0]

    user_msg = (
        f"== PHASE ==\nid: {pid}\ngoal: {phase.get('goal')}\nexpected: {phase.get('expected')}\n"
        + f"\n== 畫布節點 ==\n"
        + json.dumps([{"id": n.get("id"), "block": n.get("block_id"),
                       "params": n.get("params")} for n in nodes],
                     ensure_ascii=False, default=str)[:2200]
        + f"\n\n== 連線 ==\n"
        + json.dumps([{"from": (e.get('from') or {}).get('node'),
                       "to": (e.get('to') or {}).get('node')}
                      for e in (pj_dict.get("edges") or [])], ensure_ascii=False)[:600]
        + f"\n\n== 最後驗收拒絕 ==\n" + json.dumps(reject, ensure_ascii=False, default=str)[:700]
        + f"\n\n== 執行快照（節點→rows/error）==\n"
        + json.dumps({nid: {"rows": (s or {}).get("rows"), "error": str((s or {}).get("error") or "")[:120],
                            "cols": ((s or {}).get("cols") or [])[:12]}
                      for nid, s in exec_trace.items() if isinstance(s, dict)},
                     ensure_ascii=False, default=str)[:1500]
        + (f"\n\n== 確定性提示 ==\n上游 0 筆節點: {', '.join(empty_ups)}" if empty_ups else "")
        + f"\n\n== 近期動作 ==\n"
        + "\n".join(f"- {a.get('tool')} {str(a.get('args_summary') or '')[:80]}" for a in recent[-8:])
        + (f"\n\n== 前一張工單（已失敗，換角度）==\n{tried_summary}" if used else "")
    )

    client = get_llm_client()
    raw = ""
    decision: dict[str, Any] = {}
    try:
        resp = await client.create(
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
            max_tokens=1000,
        )
        raw = resp.text or ""
        try:
            decision = json.loads(_strip_fence(raw))
        except json.JSONDecodeError:
            decision = _extract_first_json_object(raw or "") or {}
    except Exception as ex:  # noqa: BLE001
        logger.warning("coordinator: LLM failed: %s", ex)

    decision = decision if isinstance(decision, dict) else {}
    kind = str(decision.get("kind") or "")
    diagnosis = str(decision.get("diagnosis") or "")[:300]
    ops = decision.get("ops") if isinstance(decision.get("ops"), list) else []

    if tracer is not None:
        tracer.record_llm("coordinator_diagnose", system=_SYSTEM, user_msg=user_msg,
                          raw_response=raw, parsed=decision,
                          resp=resp if "resp" in dir() else None)

    if kind == "plan_error":
        return _escalate(diagnosis or "coordinator 判定計畫層問題", tried_summary)

    clean, reject_why = (None, "LLM 未產出可用診斷") if not decision else \
        validate_work_order(ops, node_ids)
    counts[pid] = used + 1
    if clean is None:
        # A bad order is an attempt; second failure escalates to M2.
        if counts[pid] >= MAX_WORK_ORDERS_PER_PHASE:
            return _escalate(f"工單無法成立（{reject_why}）", tried_summary)
        return {
            "v30_work_order_counts": counts,
            "status": "phase_revise_pending",  # loops back here via router
            "sse_events": [_sse("work_order_rejected", {
                "phase_id": pid, "reason": reject_why, "attempt": counts[pid],
            })],
        }

    # ── Mechanical execution (zero LLM) ──────────────────────────────
    registry = SeedlessBlockRegistry()
    registry.load()
    pipeline = PipelineJSON.model_validate(pj_dict)
    transient = AgentBuilderSession.new(
        user_prompt=state.get("instruction", ""), base_pipeline=pipeline)
    toolset = BuilderToolset(
        transient, registry,
        source_cache=get_session_cache(str(state.get("session_id") or "anon")))

    applied: list[str] = []
    failed_op: str | None = None
    last_touched: str | None = None
    for op in clean:
        try:
            if op["op"] == "set_param":
                await toolset.dispatch("set_param", {
                    "node_id": op["node"], "key": op["key"], "value": op["value"]})
                last_touched = op["node"]
                applied.append(f"set_param {op['node']}.{op['key']}")
            elif op["op"] == "connect":
                await toolset.dispatch("connect", {
                    "from_node": op["from"], "to_node": op["to"]})
                last_touched = op["to"]
                applied.append(f"connect {op['from']}->{op['to']}")
            else:
                await toolset.dispatch("remove_node", {"node_id": op["node"]})
                applied.append(f"remove {op['node']}")
        except ToolError as ex:
            failed_op = f"{op['op']}: {ex.message[:120]}"
            break

    new_pipeline = transient.pipeline_json.model_dump(by_alias=True)
    digest = "; ".join(applied) + (f" | FAILED at {failed_op}" if failed_op else "")

    try:
        from python_ai_sidecar.observability import get_current_recorder
        rec = get_current_recorder()
        if rec is not None:
            rec.record("work_order", agent="repair", phase_id=pid, payload={
                "kind": kind or "unknown", "diagnosis": diagnosis,
                "ops": applied, "failed_op": failed_op,
            })
    except Exception:  # noqa: BLE001
        pass
    if tracer is not None:
        tracer.record_step("work_order", status="applied" if not failed_op else "partial",
                           phase_id=pid, kind=kind, ops=applied, failed_op=failed_op)
    logger.info("coordinator: work order #%d on %s — %s", counts[pid], pid, digest)

    out: dict[str, Any] = {
        "final_pipeline": new_pipeline,
        "v30_work_order_counts": counts,
        "v30_last_work_order": {"digest": f"[{kind}] {diagnosis} → {digest}"},
        "sse_events": [_sse("work_order_applied", {
            "phase_id": pid, "kind": kind, "diagnosis": diagnosis,
            "ops": applied, "failed_op": failed_op,
        })],
    }
    if failed_op or last_touched is None:
        # Order couldn't fully apply — treat as spent attempt, loop for the
        # next diagnosis (or escalate if budget gone via top-of-node check).
        out["status"] = "phase_revise_pending"
        return out

    # Refresh the touched node's snapshot so phase_verifier has current
    # status/rows (source cache makes this cheap), then go straight to verify.
    try:
        pv = await toolset.preview(node_id=last_touched, sample_size=5)
        exec_trace2 = dict(state.get("exec_trace") or {})
        exec_trace2[last_touched] = {
            "logical_id": last_touched, "real_id": last_touched,
            "block_id": next((n.get("block_id") for n in new_pipeline.get("nodes", [])
                              if n.get("id") == last_touched), None),
            "rows": pv.get("rows"), "status": pv.get("status"),
            "error": pv.get("error"),
            "cols": list(((pv.get("preview") or {}).get("data") or {}).get("columns") or [])[:20]
            if isinstance(pv.get("preview"), dict) else [],
        }
        out["exec_trace"] = exec_trace2
        out["v30_last_mutated_logical_id"] = last_touched
        out["v30_verify_now"] = True
        out["status"] = "phase_in_progress"
    except Exception as ex:  # noqa: BLE001
        logger.warning("coordinator: post-order preview failed: %s", ex)
        out["status"] = "phase_revise_pending"
    return out


def _strip_fence(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


def _sse(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"event": event_type, "data": data}
