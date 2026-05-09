"""repair_op_node — LLM #3: given a failed op + error msg, return fixed args.

Bounded by MAX_OP_REPAIR (2). After that, escalate to repair_plan
(graph routing decides; we just bump attempts and set status hint).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from python_ai_sidecar.agent_builder.graph_build.state import BuildGraphState
from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client


logger = logging.getLogger(__name__)

MAX_OP_REPAIR = 2


_SYSTEM = """這個 op 執行失敗了。看 error 訊息修正 op 的欄位（不要改 type）。

5 種 type 的欄位:
  add_node:    block_id, block_version, node_id, params (initial)
  set_param:   node_id, params={"key":..., "value":...}
  connect:     src_id, src_port, dst_id, dst_port
  run_preview: node_id
  remove_node: node_id

只輸出 JSON:
{"op": {<整個 op 物件>}}
"""


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.DOTALL)


def _strip_fence(text: str) -> str:
    return _FENCE_RE.sub("", text.strip()).strip()


async def repair_op_node(state: BuildGraphState) -> dict[str, Any]:
    cursor = state.get("cursor", 0)
    plan = state.get("plan") or []
    if cursor >= len(plan):
        return {}

    op = plan[cursor]
    attempts = int(op.get("repair_attempts") or 0) + 1
    err = op.get("error_message") or "(no error msg)"

    if attempts > MAX_OP_REPAIR:
        # Caller (graph routing) will escalate to repair_plan — we just
        # mark the failed_op_idx and let the route handler decide.
        logger.warning("repair_op_node: cursor=%d attempts %d > %d → escalate",
                       cursor, attempts, MAX_OP_REPAIR)
        return {
            "failed_op_idx": cursor,
            "plan_validation_errors": state.get("plan_validation_errors", []) + [
                f"Op#{cursor} failed after {MAX_OP_REPAIR} repair attempts: {err}"
            ],
        }

    user_msg = (
        "failed op:\n"
        + json.dumps(op, ensure_ascii=False, indent=2)
        + f"\n\nerror:\n  {err}"
    )

    client = get_llm_client()
    try:
        resp = await client.create(
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
            max_tokens=1024,
        )
        text = _strip_fence(resp.text or "")
        decision = json.loads(text)
        new_op = decision.get("op") or {}
    except Exception as ex:  # noqa: BLE001
        logger.warning("repair_op_node: LLM/parse failed (%s)", ex)
        new_plan = list(plan)
        new_plan[cursor] = {**op, "repair_attempts": attempts}
        return {
            "plan": new_plan,
            "sse_events": [_event("op_repaired", {
                "cursor": cursor, "attempt": attempts, "ok": False, "fix_summary": str(ex),
            })],
        }

    # Preserve type + bump attempts; clear error/status so dispatch retries
    fixed = {
        **new_op,
        "type": op.get("type"),  # never let LLM change type
        "repair_attempts": attempts,
        "result_status": "pending",
        "error_message": None,
    }
    new_plan = list(plan)
    new_plan[cursor] = fixed
    logger.info("repair_op_node: cursor=%d attempt %d ok", cursor, attempts)

    return {
        "plan": new_plan,
        "sse_events": [_event("op_repaired", {
            "cursor": cursor, "attempt": attempts, "ok": True,
            "fix_summary": f"args revised, retry now",
        })],
    }


def _event(name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"event": name, "data": data}
