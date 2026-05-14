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


_SYSTEM = """你是 pipeline architect。User 給你需求，你把它**拆成 3-6 個高階步驟**，每步驟用一句中文描述要做什麼。

不要寫 JSON ops / 不要選 block 細項 / 不要寫 params — 那是下一個 worker 的工作。

你只要決定:
  1. 每個 step 做什麼資料動作 (依資料形狀決定：撈/解 nested/過濾/排序/聚合/視覺化/判定)
  2. 每個 step 預期輸出的「形狀」(transform/table/chart/scalar)
  3. 終端 step (table/chart/scalar) 的預期欄位 (若 user 有明說)
  4. 大概用哪個 block — **只是建議候選**，從下方候選 blocks 清單挑

==選 block 的根本原則==
**你只能讀候選 blocks 清單裡每個 block 的「What」+「Output」brief 來判斷**。如果某 block 的
Output 說它回的是 nested 結構（list / dict），下游就必須先有解 nested 的步驟才能接後續轉換。
**不要憑想像 / 訓練資料中的常識**填寫 step text 或 candidate_block — 一切看下方 brief。

== 規則 ==
  - 起點是 source block (從清單裡 category=source 的挑)
  - 終點必須是 user 要看的形狀（chart / table / scalar）— 看 user 需求字面要求什麼
  - 中間 step 只放 user 真的需要的轉換；別加 user 沒提的聚合 / 排序 / 篩欄
  - 3-6 步合理；超過 6 表示拆太細

⚠ 每個 step 必須是「**單一原子動作**」 — 不要把多動作塞同一 step：
  - ❌ 「撈 process_history 並解開 spc_charts 並篩 xbar」(三件事擠一句)
  - ✅ step_1: 撈 process_history → step_2: 解開 spc_charts → step_3: 篩 xbar
  - ❌ 「撈資料 + 計算 mean + 畫線」 → 三個 steps
  - ✅ 看到「並 / 加上 / 同時 / + / 然後」這種連接詞，**拆**

理由：每 step 編譯成 1 add_node，下一個 step 編譯時才看得到上一個 step 的實際輸出欄位
驗證 column ref。同 step 塞多動作 → 後面動作的 col 沒人驗 → runtime 才爆。

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
      "candidate_block": "block_xxx" (從候選 blocks 清單挑)
    }
  ]
}
"""


_BLOCK_BRIEF_CACHE: str | None = None


def _format_block_briefs(catalog: dict) -> str:
    """Compact brief per block — block_id + What section + Output shape.

    macro_plan needs to know output shape to plan unnest / flatten steps
    correctly. Just the first line of description (`== What ==`) skips
    over the critical Output section that says "this block returns
    nested data — downstream needs unnest" for sources like
    block_process_history. Without it, macro_plan plans
    `groupby_agg → sort by eventTime` over data that has no eventTime
    column post-groupby.

    Strategy: pull `== What ==` section (1-3 lines) AND `== Output ==`
    section (capped to ~200 chars) per block. Cache the result; the
    catalog is constant per process.
    """
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
        category = spec.get("category", "")
        what = _extract_section(desc, "What")
        output = _extract_section(desc, "Output")
        brief_parts: list[str] = []
        if what:
            brief_parts.append(what[:240])
        if output:
            brief_parts.append("output: " + output[:240])
        if not brief_parts:
            # Fallback: legacy desc without sections — take first 200 chars
            brief_parts.append(desc.split("\n\n", 1)[0][:200])
        brief = " | ".join(brief_parts)
        lines.append(f"- {name} ({category}): {brief}")
    lines.sort()
    _BLOCK_BRIEF_CACHE = "\n".join(lines)
    return _BLOCK_BRIEF_CACHE


def _extract_section(desc: str, header: str) -> str:
    """Pull a `== Header ==` section from a description, return its body
    (lines until the next `== Other ==` header), trimmed and joined as
    one line.  Empty string if section not found.
    """
    marker = f"== {header} =="
    idx = desc.find(marker)
    if idx < 0:
        return ""
    body_start = idx + len(marker)
    rest = desc[body_start:]
    # Find next "== ... ==" header to stop at
    next_marker = re.search(r"\n==\s+\S+\s+==", rest)
    section = rest[:next_marker.start()] if next_marker else rest
    # Collapse newlines + extra whitespace into single spaces
    return " ".join(section.split())


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

    # In skill mode, the terminal must be a verdict-shaped block (output
    # carries a pass/fail signal) so SkillRunner can read pass/fail. We
    # don't name the specific block here — let the LLM pick from the
    # candidate list using each block's Output brief. Deterministic
    # post-checks below enforce the shape.
    skill_section = (
        "\n\n⚠ SKILL STEP MODE — 終點必須是 verdict 形狀的 block（看 brief 的 output 是 bool/verdict 那種，"
        "讓 runner 讀 pass/fail）。"
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

    raw_text = ""
    try:
        resp = await client.create(
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
            max_tokens=2048,
        )
        raw_text = resp.text or ""
        text = _strip_fence(raw_text)
        try:
            decision = json.loads(text)
        except json.JSONDecodeError:
            decision = _extract_first_json_object(text or "")
    except Exception as ex:  # noqa: BLE001
        logger.warning("macro_plan_node: LLM/parse failed (%s)", ex)
        if tracer is not None:
            tracer.record_llm(
                "macro_plan_node", system=_SYSTEM, user_msg=user_msg,
                raw_response=raw_text, parsed=None, error=str(ex)[:300],
            )
            tracer.record_step("macro_plan_node", status="failed", error=str(ex)[:300])
        return {
            "macro_plan": [],
            "plan_validation_errors": [f"macro_plan failed: {ex}"],
            "status": "failed",
            "summary": f"macro_plan failed: {ex}",
            "sse_events": [_event("macro_plan_failed", {"error": str(ex)[:200]})],
        }

    if isinstance(decision, dict) and decision.get("too_vague"):
        reason = str(decision.get("reason") or "instruction too vague to build a pipeline")
        logger.info("macro_plan_node: too_vague — %s", reason[:120])
        if tracer is not None:
            tracer.record_llm(
                "macro_plan_node", system=_SYSTEM, user_msg=user_msg,
                raw_response=raw_text, parsed=decision, verdict="too_vague",
            )
            tracer.record_step(
                "macro_plan_node", status="too_vague", reason=reason[:300],
            )
        return {
            "macro_plan": [],
            "plan_validation_errors": [f"too vague: {reason}"],
            "summary": f"Instruction too vague — {reason[:200]}",
            "status": "failed",
            "sse_events": [_event("macro_plan_too_vague", {"reason": reason[:300]})],
        }

    raw_macro = (decision or {}).get("macro_plan") or []
    # Catalog lookup: block_id → output port types. Used by the chat-mode
    # filter below — drop any step whose candidate_block emits a non-data
    # type (bool / verdict), since chat terminals must be chart/table/scalar.
    # Looked up from registry instead of hard-coding block names.
    bool_output_blocks: set[str] = set()
    for (name, _v), spec in registry.catalog.items():
        ports = spec.get("output_schema") or []
        if any(isinstance(p, dict) and p.get("type") in {"bool", "verdict"} for p in ports):
            bool_output_blocks.add(name)

    macro_plan: list[dict[str, Any]] = []
    if isinstance(raw_macro, list):
        for i, item in enumerate(raw_macro[:MAX_MACRO_STEPS], 1):
            if not isinstance(item, dict):
                continue
            step_idx = item.get("step_idx", i)
            text_val = str(item.get("text") or "").strip()
            if not text_val:
                continue
            candidate_block = str(item.get("candidate_block") or "")
            # Chat mode terminals must carry data (chart/table/scalar); drop
            # any LLM-suggested step whose candidate_block emits bool/verdict.
            if not skill_step_mode and candidate_block in bool_output_blocks:
                logger.info(
                    "macro_plan_node: dropped step_idx=%s candidate=%s (verdict-shaped block forbidden in chat mode)",
                    step_idx, candidate_block,
                )
                continue
            macro_plan.append({
                "step_idx": int(step_idx),
                "text": text_val,
                "expected_kind": str(item.get("expected_kind") or "transform"),
                "expected_cols": list(item.get("expected_cols") or []),
                "candidate_block": candidate_block,
                "completed": False,
                "ops_appended": 0,
            })
    # Renumber step_idx after any drops so compile_chunk doesn't see gaps.
    for new_i, step in enumerate(macro_plan, 1):
        step["step_idx"] = new_i

    if not macro_plan:
        if tracer is not None:
            tracer.record_llm(
                "macro_plan_node", system=_SYSTEM, user_msg=user_msg,
                raw_response=raw_text, parsed=decision, verdict="empty_after_parse",
            )
            tracer.record_step(
                "macro_plan_node", status="failed",
                reason="macro_plan empty after parsing (no valid steps)",
            )
        return {
            "macro_plan": [],
            "plan_validation_errors": ["macro_plan empty after parsing"],
            "summary": "(macro plan generation failed — model returned no valid steps)",
            "status": "failed",
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
