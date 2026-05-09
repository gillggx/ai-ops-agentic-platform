"""repair_plan_node — LLM #2: given a plan + validation errors, return a fixed plan.

Bounded by MAX_PLAN_REPAIR (2). After that, graph routes to END with
status=plan_unfixable.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from python_ai_sidecar.agent_builder.graph_build.state import BuildGraphState
from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client


logger = logging.getLogger(__name__)

MAX_PLAN_REPAIR = 3


_SYSTEM = """你之前出的 plan 有錯誤。下面是錯誤列表，給我修正版 plan。

規則:
  1. 只修錯，不要新增需求或刪減 op
  2. 同樣的 schema：list[Op]，每個 Op 的 type 是 add_node/set_param/connect/run_preview/remove_node
  3. 邏輯 id 維持 n1, n2, ... 編號
  4. 不要解釋，直接輸出 JSON

特別注意 enum 錯誤:
  - 錯誤訊息會列出 allowed enum，例如 "value 'spc_xbar_chart_value' not in
    allowed enum ['', 'SPC', 'APC', 'DC', 'RECIPE', 'FDC', 'EC']"
  - 這代表參數要用「資料類別」(SPC / APC / DC / ...)，不是欄位名稱
  - 'spc_xbar_chart_value' 這種長字串是「欄位名」，應該用在下游 chart block 的
    value_column 之類參數，不是 source block 的 object_name
  - 如果 user 提到「SPC xbar」，object_name 用 'SPC' 即可；空字串 '' 代表全部
  - 不確定就用 enum 第一個值（通常是空字串「全部」或最常用類別）

只輸出 JSON:
{"plan": [...]}
"""


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.DOTALL)


def _strip_fence(text: str) -> str:
    return _FENCE_RE.sub("", text.strip()).strip()


def _extract_json(text: str) -> dict[str, Any]:
    """Tolerant of trailing explanation text — same logic as plan_node."""
    from python_ai_sidecar.agent_builder.graph_build.nodes.plan import _extract_first_json_object
    return _extract_first_json_object(text)


async def repair_plan_node(state: BuildGraphState) -> dict[str, Any]:
    attempts = state.get("plan_repair_attempts", 0) + 1
    errors = state.get("plan_validation_errors") or []
    plan_raw = state.get("plan") or []

    if attempts > MAX_PLAN_REPAIR:
        # Should not be reached — graph routes attempts > MAX away from here.
        logger.warning("repair_plan_node: attempts %d exceeded — abort", attempts)
        return {
            "plan_repair_attempts": attempts,
            "status": "plan_unfixable",
            "summary": f"Plan unfixable after {MAX_PLAN_REPAIR} repair attempts.",
        }

    user_msg = (
        "original plan:\n"
        + json.dumps(plan_raw, ensure_ascii=False, indent=2)
        + "\n\nerrors:\n"
        + "\n".join(f"  - {e}" for e in errors)
    )

    client = get_llm_client()
    try:
        resp = await client.create(
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
            max_tokens=8192,
        )
        decision = _extract_json(resp.text or "")
        new_plan = decision.get("plan") or []
    except Exception as ex:  # noqa: BLE001
        logger.warning("repair_plan_node: LLM/parse failed (%s)", ex)
        return {
            "plan_repair_attempts": attempts,
            "plan_validation_errors": errors + [f"repair_plan failed: {ex}"],
            "sse_events": [_event("plan_repaired", {
                "attempt": attempts, "fix_summary": f"failed: {ex}", "ok": False,
            })],
        }

    logger.info("repair_plan_node: attempt %d → %d ops", attempts, len(new_plan))
    return {
        "plan": new_plan,
        "plan_repair_attempts": attempts,
        "plan_validation_errors": [],  # cleared; re-validated next
        "sse_events": [_event("plan_repaired", {
            "attempt": attempts,
            "fix_summary": f"repaired plan now has {len(new_plan)} ops",
            "ok": True,
        })],
    }


def _event(name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"event": name, "data": data}
