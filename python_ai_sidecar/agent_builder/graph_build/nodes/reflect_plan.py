"""reflect_plan_node — LLM #3: given a plan + post-execution issues,
return a patched plan that fixes the runtime symptoms.

This is the self-correction loop's LLM hop. Unlike repair_plan_node
(which fires on validator structural errors BEFORE execution),
reflect_plan fires when the pipeline executed but produced semantically
broken output (single-point chart, error verdict, etc.).

Bounded by MAX_REFLECT — after that, graph routes to layout with
status="plan_partial_fix" so the user still sees a canvas.

On a successful reflection the node resets cursor / logical_to_real /
final_pipeline / dry_run_results so the loop can re-validate + re-execute
the patched plan from a clean execution state. (canvas_reset will fire
between validate and dispatch via the existing is_from_scratch route.)
"""
from __future__ import annotations

import json
import logging
from typing import Any

from python_ai_sidecar.agent_builder.graph_build.state import BuildGraphState
from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client


logger = logging.getLogger(__name__)

MAX_REFLECT = 2


_SYSTEM = """你之前出的 plan 通過 validator 也成功跑完，但 runtime 結果有問題。下面是 issues 列表，請給我修正版 plan。

規則:
  1. 只修錯，不要新增需求或刪減用戶要求的 output
  2. 同樣的 schema：list[Op]，每個 Op 的 type 是 add_node/set_param/connect/run_preview/remove_node
  3. 邏輯 id 維持 n1, n2, ... 編號
  4. 不要解釋，直接輸出 JSON

常見問題類型 & 修法:
  - single_point_chart: 圖表只有 1 個點。通常因為：
      (a) source block 的 limit=1 太小 → 改成 limit>=50
      (b) source → sort+limit=1 → chart 這種錯誤拓樸 → 把 sort+limit=1 拿掉，
          或讓 chart 只連 source 的另一條支線
      (c) 上游有 aggregate（count/max/etc.）把 time-series 壓縮成 scalar
          → 不要把 aggregate 結果送進 chart
    解法：確保 chart block 的上游路徑上沒有 limit=1 / aggregate-to-scalar。

只輸出 JSON:
{"plan": [...]}
"""


async def reflect_plan_node(state: BuildGraphState) -> dict[str, Any]:
    attempts = state.get("reflect_attempts", 0) + 1
    issues = state.get("inspection_issues") or []
    plan_raw = state.get("plan") or []

    if attempts > MAX_REFLECT:
        # Defensive — graph should route us away before this fires.
        logger.warning("reflect_plan_node: attempts %d exceeded — partial_fix", attempts)
        return {
            "reflect_attempts": attempts,
            "status": "finished",  # canvas still ships; user sees it labeled
            "summary": (state.get("summary") or "")
            + f" ⚠ self-correction gave up after {MAX_REFLECT} cycles",
            "sse_events": [_event("plan_partial_fix", {
                "attempt": attempts,
                "issues_remaining": len(issues),
            })],
        }

    user_msg = (
        "original plan:\n"
        + json.dumps(plan_raw, ensure_ascii=False, indent=2)
        + "\n\nruntime issues:\n"
        + "\n".join(
            f"  - [{i.get('kind')}] node={i.get('node_id')} "
            f"distinct_x={i.get('distinct_x')} n_points={i.get('n_points')} "
            f"hint={i.get('hint')}"
            for i in issues
        )
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
            max_tokens=8192,
        )
        from python_ai_sidecar.agent_builder.graph_build.nodes.plan import _extract_first_json_object
        decision = _extract_first_json_object(resp.text or "")
        new_plan = decision.get("plan") or []
        if tracer is not None:
            entry = tracer.record_llm(
                node="reflect_plan_node",
                system=_SYSTEM,
                user_msg=user_msg,
                raw_response=resp.text or "",
                parsed=decision,
                attempt=attempts,
                input_issues=issues[:5],
            )
            sse = trace_event_to_sse(entry, kind="llm_call")
            if sse: extra_sse.append(sse)
    except Exception as ex:  # noqa: BLE001
        logger.warning("reflect_plan_node: LLM/parse failed (%s)", ex)
        if tracer is not None:
            tracer.record_step("reflect_plan_node", status="failed", attempt=attempts, error=str(ex))
        # Ship what we have — canvas is already built, this is a polish step.
        return {
            "reflect_attempts": attempts,
            "sse_events": [_event("plan_reflected", {
                "attempt": attempts, "ok": False, "error": str(ex)[:200],
            })],
        }

    if not new_plan:
        logger.warning("reflect_plan_node: LLM returned empty plan — skipping loop")
        return {
            "reflect_attempts": attempts,
            "sse_events": [_event("plan_reflected", {
                "attempt": attempts, "ok": False, "reason": "empty plan",
            })],
        }

    logger.info("reflect_plan_node: attempt %d → patched plan has %d ops",
                attempts, len(new_plan))
    if tracer is not None:
        step_entry = tracer.record_step(
            "reflect_plan_node",
            status="ok",
            attempt=attempts,
            n_ops=len(new_plan),
            n_issues_seen=len(issues),
        )
        sse = trace_event_to_sse(step_entry, kind="step")
        if sse: extra_sse.append(sse)

    # Reset execution-stage fields so validate → canvas_reset → dispatch_op
    # re-runs the patched plan from a clean slate. We force skip_confirm=True
    # for the loop: the user already approved this build once; making them
    # click "confirm" again on every self-correction would be terrible UX.
    return {
        "plan": new_plan,
        "reflect_attempts": attempts,
        "inspection_issues": [],
        # Clear stale execution state
        "cursor": 0,
        "logical_to_real": {},
        "failed_op_idx": None,
        "final_pipeline": None,
        "dry_run_results": None,
        # Re-enter validate cleanly (no stale plan errors)
        "plan_validation_errors": [],
        "plan_repair_attempts": 0,
        # Bypass confirm_gate on the loop-back (user already confirmed once)
        "skip_confirm": True,
        "status": "running",
        "sse_events": [
            _event("plan_reflected", {
                "attempt": attempts,
                "fix_summary": f"patched plan now has {len(new_plan)} ops",
                "ok": True,
            }),
            *extra_sse,
        ],
    }


def _event(name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"event": name, "data": data}
