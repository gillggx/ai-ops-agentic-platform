"""macro_plan_node — v16 (2026-05-14) Phase 1 of the macro+chunk architecture.

Replaces the 1-shot plan_node. Instead of asking the LLM to produce 21
ops + structured outputs + node_contracts in a single call (which scaled
poorly past ~8 nodes — validator caught errors, repair looped, finalize
eventually plan_unfixable), this node produces a small natural-language
"macro plan" with 5-10 steps.

Per CLAUDE.md description-driven principle: this node reads the full block
catalog ONLY to format candidate brief lines (block_id + 1-line desc) —
LLM doesn't need full param schemas here. Choosing exact block params
is deferred to compile_chunk_node, which sees the upstream context for
each individual chunk.

Output shape:
  {"plan_summary": "<sentence>",
   "macro_plan": [
     {"step_idx": 1, "text": "撈 EQP-01 過去 7d Process History",
      "expected_kind": "transform",
      "expected_cols": [],
      "candidate_block": "block_process_history"},
     {"step_idx": 2, "text": "過濾 spc_status=='OOC'",
      "expected_kind": "transform",
      "candidate_block": "block_filter"},
     ...
     {"step_idx": 7, "text": "列出 OOC charts snapshot table",
      "expected_kind": "table",
      "expected_cols": ["name","value","ucl","lcl"],
      "candidate_block": "block_data_view"}
   ]
  }

Validator runs on this minimal macro shape (no ops yet). compile_chunk_node
then walks each step.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from python_ai_sidecar.agent_builder.graph_build.state import BuildGraphState
from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client


logger = logging.getLogger(__name__)


# Max macro steps a build can have. Above this means the build is too
# complex to attempt in one pass — surface back to user to break into
# smaller skills.
MAX_MACRO_STEPS = 12


_SYSTEM = """你是 pipeline architect。User 給你需求，你把它**拆成 5-10 個高階步驟**，每步驟用一句中文描述要做什麼。

不要寫 JSON ops / 不要選 block 細項 / 不要寫 params — 那是下一個 worker 的工作。

你只要決定:
  1. 每個 step 做什麼資料動作 (撈/過濾/排序/聚合/篩選/列出/視覺化/判定)
  2. 每個 step 預期輸出的「形狀」(transform/table/chart/scalar)
  3. 終端 step (table/chart/scalar) 的預期欄位 (若 user 有明說)
  4. 大概用哪個 block (e.g. process_history / filter / sort / unnest / step_check / data_view) — **只是建議候選**，最終 block 選擇交給下一階段

整個 macro plan 必須:
  - 起點是 source block (block_process_history / block_mcp_call 之類)
  - 終點包含 1 個 verdict (block_step_check) — skill_step_mode=true 時必須
  - 必要時可以有 side branch (verdict 一條，視覺化另一條)

如果 user 的需求過於模糊或不適合 build pipeline，回 {"too_vague": true, "reason": "..."}。

只輸出 JSON，無 markdown fence:

{
  "plan_summary": "<一句話描述要建什麼>",
  "macro_plan": [
    {
      "step_idx": 1,
      "text": "<這 step 做什麼，1 句中文>",
      "expected_kind": "transform" | "table" | "chart" | "scalar",
      "expected_cols": ["col1", "col2"] (terminal step 才寫；transform/中間 step 留空 []),
      "candidate_block": "block_xxx" (建議候選 block_id)
    }
  ]
}

注意:
  - 每 step 1 句話即可，不要寫很長
  - 步驟順序是執行順序 (含 source → terminal)
  - candidate_block 用上面列出的 block 名稱命名格式 (block_xxx)
  - **5-10 步**是合理範圍；超過 10 步代表你拆得太細，請合併
"""


_BLOCK_BRIEF_CACHE: str | None = None


def _format_block_briefs(catalog: dict) -> str:
    """One-line briefs only — block_id + first sentence of description.
    Caller is encouraged to cache (catalog is constant per process)."""
    global _BLOCK_BRIEF_CACHE
    if _BLOCK_BRIEF_CACHE is not None:
        return _BLOCK_BRIEF_CACHE
    lines: list[str] = []
    seen: set[str] = set()
    for (name, _version), spec in catalog.items():
        if name in seen:
            continue
        seen.add(name)
        desc = (spec.get("description") or "").strip()
        first_line = desc.split("\n", 1)[0][:120]
        category = spec.get("category", "")
        lines.append(f"- {name} ({category}): {first_line}")
    lines.sort()
    _BLOCK_BRIEF_CACHE = "\n".join(lines)
    return _BLOCK_BRIEF_CACHE


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.DOTALL)


def _strip_fence(text: str) -> str:
    return _FENCE_RE.sub("", text.strip()).strip()


async def macro_plan_node(state: BuildGraphState) -> dict[str, Any]:
    """Emits a 5-10 step natural-language macro plan."""
    from python_ai_sidecar.pipeline_builder.seedless_registry import SeedlessBlockRegistry
    from python_ai_sidecar.agent_builder.graph_build.nodes.plan import (
        _extract_first_json_object,
    )

    registry = SeedlessBlockRegistry()
    registry.load()
    briefs = _format_block_briefs(registry.catalog)

    instruction = state.get("instruction") or ""
    skill_step_mode = bool(state.get("skill_step_mode"))
    base_pipeline = state.get("base_pipeline") or {}

    declared_inputs = base_pipeline.get("inputs") or []
    inputs_section = ""
    if declared_inputs:
        names = [inp.get("name") for inp in declared_inputs if isinstance(inp, dict)]
        if names:
            inputs_section = (
                f"\n\nPipeline 已宣告 inputs (用 $name 引用): {', '.join('$' + n for n in names if n)}"
            )

    skill_section = (
        "\n\n⚠ SKILL STEP MODE — pipeline 必須以 block_step_check 收尾作為 verdict gate。"
        if skill_step_mode else ""
    )

    user_msg = (
        f"USER NEED:\n{instruction[:2000]}"
        f"{inputs_section}"
        f"{skill_section}"
        f"\n\n候選 blocks (你可以選):\n{briefs}"
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
        text = _strip_fence(resp.text or "")
        try:
            decision = json.loads(text)
        except json.JSONDecodeError:
            decision = _extract_first_json_object(text or "")
    except Exception as ex:  # noqa: BLE001
        logger.warning("macro_plan_node: LLM/parse failed (%s)", ex)
        return {
            "macro_plan": [],
            "plan_validation_errors": [f"macro_plan failed: {ex}"],
            "sse_events": [_event("macro_plan_failed", {"error": str(ex)[:200]})],
        }

    if isinstance(decision, dict) and decision.get("too_vague"):
        reason = str(decision.get("reason") or "instruction too vague to build a pipeline")
        logger.info("macro_plan_node: too_vague — %s", reason[:120])
        return {
            "macro_plan": [],
            "plan_validation_errors": [f"too vague: {reason}"],
            "summary": "Instruction too vague.",
            "status": "failed",
            "sse_events": [_event("macro_plan_too_vague", {"reason": reason[:300]})],
        }

    raw_macro = (decision or {}).get("macro_plan") or []
    macro_plan: list[dict[str, Any]] = []
    if isinstance(raw_macro, list):
        for i, item in enumerate(raw_macro[:MAX_MACRO_STEPS], 1):
            if not isinstance(item, dict):
                continue
            step_idx = item.get("step_idx", i)
            text_val = str(item.get("text") or "").strip()
            if not text_val:
                continue
            macro_plan.append({
                "step_idx": int(step_idx),
                "text": text_val,
                "expected_kind": str(item.get("expected_kind") or "transform"),
                "expected_cols": list(item.get("expected_cols") or []),
                "candidate_block": str(item.get("candidate_block") or ""),
                "completed": False,
                "ops_appended": 0,
            })

    if not macro_plan:
        return {
            "macro_plan": [],
            "plan_validation_errors": ["macro_plan empty after parsing"],
            "summary": "(macro plan generation failed)",
            "sse_events": [_event("macro_plan_failed", {"reason": "no valid steps"})],
        }

    summary = str(decision.get("plan_summary") or "(no summary)").strip() or "(no summary)"

    logger.info(
        "macro_plan_node: produced %d steps (max=%d), summary=%r",
        len(macro_plan), MAX_MACRO_STEPS, summary[:80],
    )

    if tracer is not None:
        step_entry = tracer.record_step(
            "macro_plan_node", status="ok",
            n_steps=len(macro_plan), summary=summary[:200],
        )
        sse = trace_event_to_sse(step_entry, kind="step")
        if sse: extra_sse.append(sse)
        llm_entry = tracer.record_llm(
            node="macro_plan_node",
            system=_SYSTEM[:300] + "…",
            user_msg=user_msg[:1500],
            raw_response=resp.text or "",
            parsed=decision,
        )
        sse2 = trace_event_to_sse(llm_entry, kind="llm_call")
        if sse2: extra_sse.append(sse2)

    return {
        "macro_plan": macro_plan,
        "current_macro_step": 0,
        "compile_attempts": {},
        "summary": summary,
        "is_from_scratch": True,  # v16 always treats macro+chunk as from-scratch
        "plan_validation_errors": [],
        "sse_events": [
            _event("macro_plan_proposed", {
                "summary": summary,
                "macro_plan": [
                    {k: v for k, v in s.items() if k not in {"completed", "ops_appended"}}
                    for s in macro_plan
                ],
                "n_steps": len(macro_plan),
            }),
            *extra_sse,
        ],
    }


def _event(name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"event": name, "data": data}
