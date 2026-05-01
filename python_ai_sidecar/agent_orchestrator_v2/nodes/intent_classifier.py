"""intent_classifier_node — gate vague queries before they hit Pipeline Builder.

Spec: docs/SPEC_context_engineering Part A.

Decision:
  clear_chart   — user explicitly asks for a chart
  clear_rca     — user asks why / root cause
  clear_status  — user asks for current state / count
  knowledge     — definition / how-does-it-work question (pure concept Q&A)
  vague         — open-ended status check; emit clarify event + force synthesis

When vague: pushes a `clarify` SSE event via pb_event_emit, replaces the
trailing user message with a short prompt, and sets force_synthesis so the
graph short-circuits to synthesis (no expensive llm_call / Pipeline Builder
detour).

When the user re-submits with a `[intent=<id>] <message>` prefix (selected
from the clarify card), we bypass classification entirely.

knowledge intent passes through to llm_call so Claude can answer in plain
text. The downstream intent_completeness node also bypasses non-clear_*
intents, so knowledge skips the spec-completeness gate naturally.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client

logger = logging.getLogger(__name__)


_CLARIFY_PROMPT_REPLY = "我先確認一下你想看哪一面 ↑ 從上面選一個方向，或選「全部都要」我幫你建完整 pipeline。"

_CLASSIFIER_SYSTEM = """You classify a manufacturing-engineer's chat request into ONE of five buckets.

Buckets:
  - clear_chart   "give me X chart" / 圖表 / 趨勢圖 / xbar / distribution / SPC / 顯示
  - clear_rca     "why is X OOC" / 為什麼 X 異常 / 根因 / 連續 / 異常原因 / 怎麼會
  - clear_status  "how many alarms now" / 現在有幾個 / 列表 / 清單 / OOC 機台
  - knowledge     pure definition / concept / how-does-X-work question:
                    「X 是什麼」/「什麼是 X」/「X 怎麼解讀」/「X 的意思」
                    「what is X」/「define X」/「explain X」
                    「為什麼/為何」 about a CONCEPT (e.g. "為什麼用 SPC", not
                    "為什麼 EQP-07 OOC"); a rule / algorithm name STANDING
                    ALONE without a target equipment ("WECO R5", "Cpk",
                    "Nelson rule") = knowledge.
                  ⚠ "為什麼 EQP-07 OOC" stays as clear_rca (has a target).
  - vague         open-ended / 「最近怎樣」/ 「狀況如何」/ unclear scope.
                  Don't use vague for knowledge questions — those go to
                  knowledge.

Output JSON only (no markdown code fences):

For clear_*/knowledge:
  {"intent": "<bucket>", "confidence": 0.0-1.0}

For vague — provide 2-3 disambiguation options:
  {"intent": "vague", "confidence": 0.0-1.0,
   "clarify": {
     "question": "<one short Chinese question, ≤20 chars>",
     "options": [
       {"id": "<short-id>", "label": "<≤8 char Chinese label>", "preview": "<≤20 char hint>"}
     ]
   }}

Be aggressive about labeling clear queries — the user explicitly mentioned a chart
type, said why/為什麼 about a target, or asked for a count/list. Only fall back to
vague when the request is genuinely ambiguous about scope (chart? alarm? RCA?
something else?). Definitions / concept Q&A → knowledge, never vague.
"""


_INTENT_PREFIX_RE = re.compile(r"\[intent=([a-zA-Z0-9_\-]+)\]\s*")


def _strip_intent_prefix(message: str) -> tuple[str | None, str]:
    """If message contains a `[intent=<id>]` tag (anywhere in the first chunk —
    in particular, after a `[Focused on ...]` prefix the panel may add), return
    (id, cleaned_message). Otherwise (None, original_message)."""
    m = _INTENT_PREFIX_RE.search(message)
    if not m:
        return None, message
    intent_id = m.group(1)
    cleaned = (message[: m.start()] + message[m.end():]).strip()
    return intent_id or None, cleaned


async def intent_classifier_node(
    state: Dict[str, Any], config: RunnableConfig,
) -> Dict[str, Any]:
    user_message = state.get("user_message") or ""
    if not user_message.strip():
        return {"intent": "clear_chart"}

    # Phase E3 follow-up: in builder mode the user is on a Pipeline Builder
    # canvas — they're (almost certainly) asking for pipeline construction
    # or modification. Don't gate them through vague-clarify; let the LLM
    # judge whether to declare \$inputs / build directly. Otherwise vague
    # references like 「該站點」 trigger a clarify card and the agent stalls
    # at "計畫 0/4 — 等待使用者提供站點資訊" while the user expects it to
    # just declare a \$step input and proceed.
    if state.get("mode") == "builder":
        logger.info("intent_classifier: bypass for builder mode (msg=%r)", user_message[:80])
        return {"intent": "clear_chart"}

    # Re-submit from clarify card — bypass classification.
    # Strip prefix from user_message + record intent_hint so llm_call
    # downstream can lean on it.
    picked, cleaned = _strip_intent_prefix(user_message)
    if picked is not None:
        logger.info("intent_classifier: bypass via [intent=%s] prefix", picked)
        return {"intent": "clarified", "intent_hint": picked, "user_message": cleaned}

    pb_emit = config.get("configurable", {}).get("pb_event_emit") if config else None
    client = get_llm_client()

    try:
        resp = await client.create(
            system=_CLASSIFIER_SYSTEM,
            messages=[{"role": "user", "content": user_message}],
            max_tokens=300,
        )
        text = (resp.text or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
            text = text.strip()
        decision = json.loads(text)
    except Exception as e:  # noqa: BLE001
        logger.warning("intent_classifier failed (%s) — defaulting to clear_chart pass-through", e)
        return {"intent": "clear_chart"}

    intent = (decision.get("intent") or "clear_chart").lower()
    confidence = decision.get("confidence")
    logger.info("intent_classifier: decided intent=%s confidence=%s msg=%r",
                intent, confidence, user_message[:80])

    if intent == "vague" and isinstance(decision.get("clarify"), dict):
        clarify = decision["clarify"]
        options = clarify.get("options") or []
        question = clarify.get("question") or "你想看哪一面？"
        if pb_emit:
            try:
                pb_emit({
                    "type": "clarify",
                    "question": question,
                    "options": options,
                    "fallback_label": "全部都要（建完整 pipeline）",
                })
            except Exception as ee:  # noqa: BLE001
                logger.warning("pb_emit clarify failed: %s", ee)

        # Inject a synthetic AIMessage so synthesis reads our reply directly
        # without making another LLM call. force_synthesis routes the graph
        # straight to synthesis, skipping llm_call + tool_execute.
        return {
            "intent": "vague",
            "force_synthesis": True,
            "messages": [AIMessage(content=_CLARIFY_PROMPT_REPLY)],
        }

    return {"intent": intent}
