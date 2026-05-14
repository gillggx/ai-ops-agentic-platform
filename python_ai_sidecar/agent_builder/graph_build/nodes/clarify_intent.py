"""clarify_intent_node — G1 pre-plan clarification gate (v15, 2026-05-13).

Catches high-ambiguity terms in the user instruction BEFORE plan_node
burns Opus tokens guessing. Emits 0-3 multiple-choice questions; user's
answers come back via /agent/build/clarify-respond and get woven into
state.instruction so plan_node sees a disambiguated prompt.

Why Haiku not Opus: this is a classification task ("which buckets does
this prompt fall into?"), not a generation task. Cheap and fast.

Trigger types we look for:
  - display verb ambiguity: "顯示/看/展示/列出" → snapshot table vs trend chart
  - time scope missing: "最近/最後/過去" without N → 24h vs 7d vs 30d
  - subject ambiguity: "機台/批次" without ID → declare $input vs literal
  - comparison target unclear: "比較" without explicit pairs
  - severity threshold unclear: ">2" vs ">=2" vs ">1.5σ"

If the prompt is already precise (rare on real user input), emit
proceed_directly=true and bypass the gate.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from langgraph.types import interrupt

from python_ai_sidecar.agent_builder.graph_build.state import BuildGraphState
from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client


logger = logging.getLogger(__name__)


_SYSTEM = """你是 builder 前置的「意圖釐清器」。
你不負責產出 pipeline，只負責看 user 的 instruction，找 0-3 個歧義點。

抓的歧義類型（**只抓 user 真的沒講清楚**的，不要過度問）：
  1. 「顯示 / 看 / 展示 / 列出」這類動詞 — 該回 snapshot table 還是 trend chart?
  2. 時間範圍沒給 N — 「最近」是 24h? 7d? 30d?
  3. 「機台 / 批次 / 站點」沒指明 ID — 該是宣告 $input 還是寫死?
  4. 「比較」沒明說對象 — A vs B vs C?
  5. 「異常」沒指明分類 — SPC OOC? APC drift? FDC fault?

寫選項規則:
  - 每題 2-4 個 options
  - 每個 option 有 value (machine readable, ascii_snake_case) + label (user friendly Chinese)
  - 給一個 default (最常見的選擇)
  - 不要超過 3 題

如果 instruction 已經夠精確（罕見），直接回 proceed_directly=true。

僅輸出 JSON，無 markdown fence：

{
  "proceed_directly": false,
  "clarifications": [
    {
      "id": "q1",
      "question": "「顯示該 SPC charts」你想看哪種?",
      "options": [
        {"value": "snapshot_table", "label": "當下那一刻的數值表 (name/value/ucl/lcl)"},
        {"value": "trend_chart", "label": "過去 N 天的趨勢線圖"},
        {"value": "delta_around_event", "label": "事件前後變化對照"}
      ],
      "default": "snapshot_table"
    }
  ]
}

如果完全 proceed:

{
  "proceed_directly": true,
  "clarifications": []
}
"""


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.DOTALL)


def _strip_fence(text: str) -> str:
    return _FENCE_RE.sub("", text.strip()).strip()


async def clarify_intent_node(state: BuildGraphState) -> dict[str, Any]:
    # Skip if already passed once (resume after user picks answers comes
    # back here, but with clarify_attempts=1; only fire LLM call when 0).
    attempts = state.get("clarify_attempts", 0)
    if attempts >= 1:
        logger.info("clarify_intent: skipped (already done, attempts=%d)", attempts)
        return {}

    # Chat mode (skip_confirm=True) has no UI to surface clarification
    # questions — the chat orchestrator already asked the user before
    # calling build_pipeline_live, and there is no /agent/build/clarify-
    # respond path from the chat panel. If we interrupt() here the graph
    # pauses forever and the user sees an empty canvas. Skip the gate;
    # macro_plan will handle whatever residual ambiguity remains by
    # picking sensible defaults from block descriptions.
    if state.get("skip_confirm"):
        logger.info("clarify_intent: skipped (skip_confirm=True, chat mode)")
        return {
            "clarify_attempts": 1,
            "clarifications": {},
            "sse_events": [_event("clarify_skipped", {"reason": "skip_confirm"})],
        }

    instruction = state.get("instruction") or ""
    if not instruction.strip():
        return {"clarify_attempts": 1, "clarifications": {}}

    from python_ai_sidecar.agent_builder.graph_build.trace import get_current_tracer
    tracer = get_current_tracer()

    client = get_llm_client()
    user_msg = f"USER INSTRUCTION:\n{instruction[:1000]}"

    decision: dict[str, Any] = {"proceed_directly": True, "clarifications": []}
    raw_text = ""
    try:
        # Spec said "use Haiku" but BaseLLMClient.create doesn't accept a
        # per-call model override. Using default model — this is a small
        # JSON-output classification call (~1k system + 500 user), cost
        # is negligible compared to plan_node's ~60k catalog payload.
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
            from python_ai_sidecar.agent_builder.graph_build.nodes.plan import (
                _extract_first_json_object,
            )
            decision = _extract_first_json_object(text or "")
    except Exception as ex:  # noqa: BLE001
        logger.warning("clarify_intent: LLM/parse failed (%s) — proceeding without clarification", ex)
        if tracer is not None:
            tracer.record_llm(
                "clarify_intent_node", system=_SYSTEM, user_msg=user_msg,
                raw_response=raw_text, parsed=None, error=str(ex)[:300],
            )
            tracer.record_step("clarify_intent_node", status="failed", error=str(ex)[:300])
        return {
            "clarify_attempts": 1,
            "clarifications": {},
            "sse_events": [_event("clarify_skipped", {"reason": str(ex)[:200]})],
        }

    # Record the successful LLM call regardless of decision branch below.
    if tracer is not None:
        tracer.record_llm(
            "clarify_intent_node", system=_SYSTEM, user_msg=user_msg,
            raw_response=raw_text, parsed=decision,
        )

    questions = decision.get("clarifications") if isinstance(decision, dict) else None
    proceed = bool(decision.get("proceed_directly")) if isinstance(decision, dict) else True

    if proceed or not questions:
        logger.info("clarify_intent: prompt clear, proceeding without gate")
        if tracer is not None:
            tracer.record_step(
                "clarify_intent_node", status="ok",
                verdict="proceed_directly", n_questions=0,
            )
        return {
            "clarify_attempts": 1,
            "clarifications": {},
            "sse_events": [_event("clarify_skipped", {"reason": "proceed_directly"})],
        }

    # Sanitize: cap to 3 questions, ensure each has id/question/options
    questions = [q for q in questions if _valid_question(q)][:3]
    if not questions:
        if tracer is not None:
            tracer.record_step(
                "clarify_intent_node", status="ok",
                verdict="no_valid_questions", n_questions=0,
            )
        return {
            "clarify_attempts": 1,
            "clarifications": {},
            "sse_events": [_event("clarify_skipped", {"reason": "no valid questions"})],
        }

    logger.info("clarify_intent: emitting %d clarification question(s)", len(questions))

    if tracer is not None:
        tracer.record_step(
            "clarify_intent_node", status="awaiting_user",
            verdict="clarify_required", n_questions=len(questions),
            questions=questions,
        )

    # Pause graph and wait for user response via /agent/build/clarify-respond.
    user_response = interrupt({
        "kind": "clarify_required",
        "session_id": state.get("session_id"),
        "clarifications": questions,
    })

    # When resumed, user_response should be {"answers": {qid: value}}
    answers: dict[str, str] = {}
    if isinstance(user_response, dict):
        raw = user_response.get("answers") or {}
        for qid, val in raw.items():
            if isinstance(qid, str) and isinstance(val, (str, int, float, bool)):
                answers[qid] = str(val)

    # Augment the instruction so plan_node sees the disambiguated prompt.
    aug_instruction = _augment_instruction(instruction, questions, answers)
    logger.info("clarify_intent: applied %d answer(s); instruction extended", len(answers))

    if tracer is not None:
        tracer.record_step(
            "clarify_intent_node", status="resumed",
            verdict="answers_applied", n_answers=len(answers),
            answers=answers,
        )

    return {
        "instruction": aug_instruction,
        "clarifications": answers,
        "clarify_attempts": 1,
        "sse_events": [_event("clarify_received", {
            "answers": answers,
            "n_questions": len(questions),
        })],
    }


def _valid_question(q: Any) -> bool:
    if not isinstance(q, dict):
        return False
    if not isinstance(q.get("id"), str):
        return False
    if not isinstance(q.get("question"), str):
        return False
    opts = q.get("options")
    if not isinstance(opts, list) or not opts:
        return False
    for o in opts:
        if not isinstance(o, dict):
            return False
        if not isinstance(o.get("value"), str) or not isinstance(o.get("label"), str):
            return False
    return True


def _augment_instruction(
    original: str,
    questions: list[dict],
    answers: dict[str, str],
) -> str:
    """Append a CLARIFICATIONS section to the instruction so plan_node sees it.

    Format keeps human-readable trace alongside machine values.
    """
    if not answers:
        return original
    lines: list[str] = [original.strip(), "", "── 使用者澄清 ──"]
    qmap = {q["id"]: q for q in questions}
    for qid, val in answers.items():
        q = qmap.get(qid)
        if not q:
            lines.append(f"  - [{qid}] = {val}")
            continue
        # Find option label for value
        label = val
        for opt in q.get("options", []):
            if opt.get("value") == val:
                label = opt.get("label", val)
                break
        lines.append(f"  - {q.get('question')} → {label}  ({val})")
    return "\n".join(lines)


def _event(name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"event": name, "data": data}
