"""reflect_op_node — v8 per-op self-correction.

Fires AFTER a single op completes and its preview snapshot exposes a data
problem (rows=0, executor error) — see _detect_op_issue in execute.py.

Why a separate node from reflect_plan:
  - reflect_plan rewrites the ENTIRE plan, often making 1 issue → 4 issues.
  - reflect_op sees only the failing op + 2-3 upstream snapshots, and emits
    a tight patch (params change on a single op, or rollback to earlier op).
  - LLM input ~1.5k tokens (vs reflect_plan's ~60k with catalog) — cheaper,
    faster, smaller delta, less chance to break unrelated ops.

Two output shapes the LLM may produce:
  (a) {"action": "patch_params", "new_params": {...}, "reason": "..."}
      — replaces plan[cursor-1].params with new_params, then cursor-- so
        graph re-runs that op with the patched config.
  (b) {"action": "rollback", "rollback_to_cursor": K, "new_params_for_K":
       {...}, "reason": "..."}
      — when root cause is upstream. Rolls back to op@K with new params,
        clears exec_trace[K:] and result_status of plan[K+1..N], so the
        loop replays K..N. Guarded: K must be >= cursor - 3.

Bounded by MAX_REFLECT_OP per logical id (not per build). If a single op
exhausts its budget, fallthrough — finalize-time inspect_execution +
reflect_plan still serve as safety nets for emergent issues.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from python_ai_sidecar.agent_builder.graph_build.state import BuildGraphState
from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client


logger = logging.getLogger(__name__)


# Per-logical-id budget. 2 tries is enough — if a single op needs more
# than 2 reflect attempts, the root cause is probably elsewhere, and the
# finalize-time reflect_plan is the right tool.
MAX_REFLECT_OP = 2

# Rollback limit — LLM can rollback at most this many ops up from current
# cursor. Keeps the loop bounded and forces the patch to stay local.
MAX_ROLLBACK_DISTANCE = 3


_SYSTEM = """你是 op-level 修正器。你只看到 1 個失敗的 op 跟它前 2-3 個 upstream op 的執行結果。
任務：判斷該怎麼修這個 op，不要動其他 op。

兩個選擇:
  A. patch_params: 改這個 op 的 params（params 是個 dict 跟 add_node 一樣）
  B. rollback: 如果 root cause 在 upstream 第 K 個 op，回到 K 重跑（K 必須 >= current - 3）
     rollback 也要附 new_params_for_K 給 op@K 一個更好的設定

判斷原則:
  - 看 trace 找資料 collapse 點：rows 突然變少？通常是 root cause。
  - 看 ISSUE.expected / .rationale 找約束。
  - 看 Block schema 看每個 param 允許的範圍 / enum。
  - 不要編造 column 名稱，只用 UPSTREAM TRACE 裡實際出現的 cols。
  - 不要把整個 plan 重寫 — 不是你的工作。

輸出規則：只輸出 JSON 一個，不要解釋。

範例 A (改自己):
{"action": "patch_params", "new_params": {"column": "spc_summary.ooc_count", "operator": ">=", "threshold": 2}, "reason": "previous column 'ooc_count' not in upstream cols"}

範例 B (rollback 改上游):
{"action": "rollback", "rollback_to_cursor": 0, "new_params_for_K": {"tool_id": "$equipment_id", "limit": 100, "nested": true}, "reason": "n1 limit=1 collapsed time series; downstream chart can never have >1 distinct eventTime"}
"""


async def reflect_op_node(state: BuildGraphState) -> dict[str, Any]:
    issue = state.get("last_op_issue") or {}
    plan = list(state.get("plan") or [])
    cursor = state.get("cursor", 0)
    exec_trace = dict(state.get("exec_trace") or {})
    attempts_map = dict(state.get("reflect_op_attempts") or {})
    failing_logical_id = issue.get("node_id")

    if not issue or not failing_logical_id or cursor == 0:
        logger.warning("reflect_op_node: invoked without valid issue (cursor=%d, issue=%s)",
                       cursor, bool(issue))
        return {"last_op_issue": None}

    # The op that produced the failing snapshot is plan[cursor-1] (cursor
    # was already advanced by call_tool on success).
    failing_op_idx = cursor - 1
    if failing_op_idx < 0 or failing_op_idx >= len(plan):
        logger.warning("reflect_op_node: failing_op_idx %d out of plan range %d",
                       failing_op_idx, len(plan))
        return {"last_op_issue": None}
    failing_op = plan[failing_op_idx]

    attempts = attempts_map.get(failing_logical_id, 0) + 1
    attempts_map[failing_logical_id] = attempts

    # Defensive — graph router should already check budget, but enforce here too
    if attempts > MAX_REFLECT_OP:
        logger.info("reflect_op_node: %s budget exhausted (%d) — fallthrough",
                    failing_logical_id, attempts)
        return {
            "last_op_issue": None,
            "reflect_op_attempts": attempts_map,
            "sse_events": [_event("reflect_op_skipped", {
                "node_id": failing_logical_id, "attempts": attempts,
                "reason": "budget_exhausted",
            })],
        }

    # Build user message — keep it tight: failing op + small upstream slice
    # of trace + the issue envelope + the block's param_schema.
    user_msg = _build_user_message(
        instruction=state.get("instruction") or "",
        plan=plan,
        failing_op_idx=failing_op_idx,
        exec_trace=exec_trace,
        issue=issue,
    )

    client = get_llm_client()
    from python_ai_sidecar.agent_builder.graph_build.trace import (
        get_current_tracer, trace_event_to_sse,
    )
    tracer = get_current_tracer()
    extra_sse: list[dict[str, Any]] = []
    try:
        resp = await client.create(
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
            max_tokens=2048,
        )
        from python_ai_sidecar.agent_builder.graph_build.nodes.plan import _extract_first_json_object
        decision = _extract_first_json_object(resp.text or "")
        if tracer is not None:
            entry = tracer.record_llm(
                node="reflect_op_node",
                system=_SYSTEM[:300] + "…",  # full system is in source, keep trace small
                user_msg=user_msg,
                raw_response=resp.text or "",
                parsed=decision,
                attempt=attempts,
                target_node_id=failing_logical_id,
            )
            sse = trace_event_to_sse(entry, kind="llm_call")
            if sse: extra_sse.append(sse)
    except Exception as ex:  # noqa: BLE001
        logger.warning("reflect_op_node: LLM/parse failed (%s)", ex)
        return {
            "last_op_issue": None,
            "reflect_op_attempts": attempts_map,
            "sse_events": [_event("reflect_op_failed", {
                "node_id": failing_logical_id, "attempts": attempts,
                "error": str(ex)[:200],
            })],
        }

    action = (decision or {}).get("action")
    reason = (decision or {}).get("reason") or ""
    if action == "patch_params":
        new_params = decision.get("new_params") or {}
        if not isinstance(new_params, dict):
            return _bail(attempts_map, failing_logical_id, attempts,
                         f"patch_params new_params not dict: {type(new_params).__name__}")
        plan[failing_op_idx] = {
            **failing_op,
            "params": {**(failing_op.get("params") or {}), **new_params},
            "result_status": None,  # cleared so it re-runs
        }
        logger.info("reflect_op_node: patch %s (cursor %d → %d), new_params keys=%s, reason=%s",
                    failing_logical_id, cursor, failing_op_idx, list(new_params.keys()), reason[:120])
        # Clear this node's snapshot — about to re-run
        exec_trace.pop(failing_logical_id, None)
        return {
            "plan": plan,
            "cursor": failing_op_idx,         # re-dispatch same op with new params
            "exec_trace": exec_trace,
            "reflect_op_attempts": attempts_map,
            "last_op_issue": None,
            "sse_events": [
                _event("plan_op_reflected", {
                    "action": "patch_params",
                    "node_id": failing_logical_id,
                    "cursor": failing_op_idx,
                    "attempts": attempts,
                    "reason": reason[:200],
                }),
                *extra_sse,
            ],
        }
    if action == "rollback":
        k_raw = decision.get("rollback_to_cursor")
        new_params_k = decision.get("new_params_for_K") or {}
        try:
            k = int(k_raw)
        except (TypeError, ValueError):
            return _bail(attempts_map, failing_logical_id, attempts,
                         f"rollback rollback_to_cursor not int: {k_raw!r}")
        if k < 0 or k >= failing_op_idx:
            return _bail(attempts_map, failing_logical_id, attempts,
                         f"rollback K={k} must be in [0, {failing_op_idx})")
        if failing_op_idx - k > MAX_ROLLBACK_DISTANCE:
            return _bail(attempts_map, failing_logical_id, attempts,
                         f"rollback distance {failing_op_idx-k} > {MAX_ROLLBACK_DISTANCE}")
        if not isinstance(new_params_k, dict):
            return _bail(attempts_map, failing_logical_id, attempts,
                         f"new_params_for_K not dict: {type(new_params_k).__name__}")
        # Apply new params to op@K. K is a logical-id position; we read the
        # op there, replace its params, clear result_status for K..N so they
        # all re-run.
        target_op = plan[k]
        plan[k] = {
            **target_op,
            "params": {**(target_op.get("params") or {}), **new_params_k},
            "result_status": None,
        }
        for i in range(k + 1, len(plan)):
            if plan[i].get("result_status") is not None:
                plan[i] = {**plan[i], "result_status": None}
        # Clear exec_trace entries that depend on K+ (we don't know exact
        # dependencies, so clear all keys whose snapshot was taken after K)
        target_logical_id = _logical_id_of_op_at(plan, k)
        pruned_trace: dict[str, dict] = {}
        for lid, snap in exec_trace.items():
            if isinstance(snap, dict) and snap.get("after_cursor", 9999) < k:
                pruned_trace[lid] = snap
        logger.info("reflect_op_node: rollback %s → cursor=%d (target op#%d, %s), pruned %d trace entries, reason=%s",
                    failing_logical_id, k, k, target_logical_id,
                    len(exec_trace) - len(pruned_trace), reason[:120])
        return {
            "plan": plan,
            "cursor": k,
            "exec_trace": pruned_trace,
            "reflect_op_attempts": attempts_map,
            "last_op_issue": None,
            "sse_events": [
                _event("plan_op_reflected", {
                    "action": "rollback",
                    "node_id": failing_logical_id,
                    "rollback_to_cursor": k,
                    "rollback_target_node_id": target_logical_id,
                    "attempts": attempts,
                    "reason": reason[:200],
                }),
                *extra_sse,
            ],
        }

    return _bail(attempts_map, failing_logical_id, attempts,
                 f"unknown action: {action!r}")


def _bail(attempts_map, lid, attempts, reason):
    logger.warning("reflect_op_node: bailing — %s", reason)
    return {
        "last_op_issue": None,
        "reflect_op_attempts": attempts_map,
        "sse_events": [_event("reflect_op_failed", {
            "node_id": lid, "attempts": attempts, "error": reason,
        })],
    }


def _logical_id_of_op_at(plan: list[dict], k: int) -> str | None:
    """Best-effort lookup for op@k's logical node id (for telemetry only)."""
    if k < 0 or k >= len(plan):
        return None
    op = plan[k]
    return op.get("node_id") or op.get("dst_id") or op.get("src_id")


def _build_user_message(
    *,
    instruction: str,
    plan: list[dict],
    failing_op_idx: int,
    exec_trace: dict[str, dict],
    issue: dict,
) -> str:
    """Compose the user message with USER PROMPT + FAILING OP + upstream
    TRACE slice + ISSUE envelope + block schema for the failing op.

    Trace slice = the failing op's plan window from max(0, idx-3) to idx,
    rendered with trace_serializer for consistency with reflect_plan's
    NODE TRACE format.
    """
    from python_ai_sidecar.agent_builder.graph_build.trace_serializer import build_node_trace
    from python_ai_sidecar.pipeline_builder.seedless_registry import SeedlessBlockRegistry

    failing_op = plan[failing_op_idx]
    start = max(0, failing_op_idx - 3)
    plan_slice = plan[start:failing_op_idx + 1]
    trace_block = build_node_trace(plan_slice, exec_trace)

    # Pull the failing block's param_schema so the LLM sees real constraints.
    registry = SeedlessBlockRegistry()
    registry.load()
    block_id = failing_op.get("block_id") or issue.get("block_id") or ""
    schema_section = "(block_id not resolvable — patch without schema reference)"
    if block_id:
        spec = next(
            (s for (n, _v), s in registry.catalog.items() if n == block_id),
            None,
        )
        if spec:
            try:
                schema_section = json.dumps(
                    spec.get("param_schema") or {}, ensure_ascii=False, indent=2
                )[:2500]
            except (TypeError, ValueError):
                schema_section = "(schema serialization failed)"

    # ErrorEnvelope summary
    issue_lines = [f"  code: {issue.get('code')}", f"  node: {issue.get('node_id')}"]
    for k in ("param", "given", "expected", "rationale", "message", "hint"):
        v = issue.get(k)
        if v is not None:
            issue_lines.append(f"  {k}: {v}")
    issue_block = "\n".join(issue_lines)

    return (
        f"USER PROMPT (intent):\n  {instruction[:400]}\n\n"
        f"FAILING OP at cursor {failing_op_idx}:\n"
        f"{json.dumps(failing_op, ensure_ascii=False, indent=2)}\n\n"
        f"UPSTREAM TRACE (ops {start} to {failing_op_idx}):\n"
        f"{trace_block}\n\n"
        f"ISSUE detected:\n{issue_block}\n\n"
        f"Block schema for {block_id}:\n{schema_section}\n\n"
        "請出修正方案 (JSON only)."
    )


def _event(name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"event": name, "data": data}
