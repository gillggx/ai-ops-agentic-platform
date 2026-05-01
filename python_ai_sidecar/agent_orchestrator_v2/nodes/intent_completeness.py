"""intent_completeness_node — graph-level gate that asks the user for missing
spec dimensions BEFORE the main LLM ever sees the prompt.

Why a graph node and not a system-prompt rule:
  Empirical (2026-05-02 chat session log): the main LLM was given an explicit
  "if presentation unspecified → call confirm_pipeline_intent" rule in the
  system prompt and ignored it, choosing search_published_skills →
  build_pipeline_live anyway. Per the operating principle "流程是 agent 的工
  作，LLM 是大腦，只做思考才對", flow control belongs in the graph; the
  system-prompt rule was demoted to advisory text only.

Decision:
  complete       — spec is fully specified across (inputs, logic, presentation)
  incomplete     — at least one of the three is missing/ambiguous → emit a
                   `design_intent_confirm` SSE card with the haiku's best
                   guess + alternatives, force_synthesis to stop the turn.

Bypass conditions (return complete without calling the LLM):
  - intent in {"vague","clarified"}      — earlier nodes handled clarification
  - intent does NOT start with "clear_"   — fallback / unknown
  - user_message contains [intent_confirmed:<id>] — user already confirmed
  - user_message contains [intent=<id>]   — clarify-card pick (other path)

NOTE on builder mode:
  We deliberately do NOT bypass for mode=="builder". Even when the user is
  staring at a Pipeline Builder canvas, "presentation 不明" is a real concern
  — without an explicit chart/table/alert hint, the sub-agent picks a default
  that may not match user intent. The classification prompt is permissive
  enough that pure modification verbs ("改成 5 天") classify as `complete`
  (the existing canvas IS the presentation), so we won't over-fire.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Dict

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client

logger = logging.getLogger(__name__)


# Match either prefix anywhere near the start (e.g. after a "[Focused on ...]"
# header the panel may inject); same tolerance as intent_classifier.
_CONFIRMED_PREFIX_RE = re.compile(r"\[intent_confirmed:[a-zA-Z0-9_\-]+\]")
_INTENT_PREFIX_RE = re.compile(r"\[intent=[a-zA-Z0-9_\-]+\]")


_COMPLETENESS_SYSTEM = """You judge whether a manufacturing-engineer chat
request is fully specified enough to build a pipeline without guessing.

## STEP 0 — Is this even a pipeline-building request?
If the user is asking a **knowledge / definition / how-does-X-work question**,
they're NOT trying to build a pipeline. Output `{"complete": true}` and let
the main LLM answer in plain text.

Knowledge-question signals (any of these → return complete=true immediately):
  - 「X 是什麼」/「什麼是 X」/「X 怎麼解讀」/「X 的意思」
  - 「為什麼/為何」 about a concept (not "why is EQP-07 OOC")
  - 「如何/怎麼」 about a method (e.g.「WECO 怎麼判讀」)
  - 「what is X」/ "define X" / "explain X"
  - User mentions a rule/algorithm name ALONE without a target equipment / lot
    (e.g. "WECO R5", "Cpk", "Nelson rule", "1σ band") — they're asking about
    the concept, not running it.

If it IS a pipeline-building request, check three dimensions:
  - inputs:       did the user say WHICH equipment / lot / step / date range?
                  (any concrete reference is enough — "EQP-07", "all stations",
                  "5 days", etc.)
  - logic:        did the user say WHAT to compute? (OOC rate, count,
                  trend, cpk, threshold check, etc.)
  - presentation: did the user say HOW to present?
                  Explicit cues: 表格/列表/table/清單 → table
                                  圖/圖表/趨勢圖/chart/折線/長條 → chart
                                  告警/alert/通知 → alert
                                  數值/scalar/單一數字 → scalar
                                  pareto/分佈圖/直方圖 → chart
                  If user said NONE of these — presentation is missing.

Output JSON only (no markdown fences). Keep keys/values lowercase ASCII.

If complete (or knowledge-only):
  {"complete": true}

If incomplete (at least one of inputs/logic/presentation is missing or ambiguous):
  {
    "complete": false,
    "missing": ["presentation", ...],     // 1-3 items
    "guess": {                              // your best guess so the user
                                            // can ✅ accept without typing
      "inputs": [
        {"name": "<short_name>", "source": "user_input|event_payload|literal",
         "rationale": "<one short sentence>"}
      ],
      "logic": "<one-sentence plain language description>",
      "presentation": "alert|chart|table|scalar|mixed",
      "alternatives": [
        {"summary": "<another way to interpret, ≤30 chars>"}
      ]
    }
  }

Rules:
  - presentation is the dimension users skip most often — be strict here
  - inputs missing: only flag if user said NO concrete identifier at all
  - logic missing: only flag if user used vague verbs alone (analyze, look,
    check, etc.) without saying what
  - 0-2 alternatives is fine; pick contrasting interpretations
  - Output JSON only. No prose. No code fences."""


_FORCE_SYNTH_REPLY = (
    "我先跟你確認要建什麼 ↑\n"
    "點 ✅ 開始建、✏️ 想修改、❌ 取消。"
)


def _has_bypass_prefix(msg: str) -> bool:
    return bool(_CONFIRMED_PREFIX_RE.search(msg) or _INTENT_PREFIX_RE.search(msg))


def _parse_decision(text: str) -> Dict[str, Any] | None:
    text = text.strip()
    # Tolerate models that wrap JSON in code fences despite the instruction.
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        return None


async def intent_completeness_node(
    state: Dict[str, Any], config: RunnableConfig,
) -> Dict[str, Any]:
    user_message = state.get("user_message") or ""
    mode = state.get("mode") or "chat"
    intent = (state.get("intent") or "").lower()

    # ── Bypass conditions (return without calling the LLM) ─────────
    # We intentionally do NOT bypass for mode=="builder" — see module docstring.
    # Pure-modification prompts ("改成 5 天") classify as complete; ambiguous
    # ones ("分析 EQP-07 OOC") still deserve a confirm card on canvas too.
    if intent in ("vague", "clarified"):
        logger.info("intent_completeness: bypass (intent=%s already routed)", intent)
        return {}
    if not intent.startswith("clear_"):
        # Unknown / fallback intent — let llm_call handle it; don't gate.
        logger.info("intent_completeness: bypass (intent=%r not gateable)", intent)
        return {}
    if _has_bypass_prefix(user_message):
        logger.info("intent_completeness: bypass via [intent_*] prefix")
        return {}

    # ── Completeness classification (one haiku-class call) ────────
    client = get_llm_client()
    try:
        resp = await client.create(
            system=_COMPLETENESS_SYSTEM,
            messages=[{"role": "user", "content": user_message}],
            max_tokens=600,
        )
        decision = _parse_decision(resp.text or "")
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "intent_completeness: classification failed (%s) — pass-through to llm_call",
            e,
        )
        return {}

    if not decision:
        logger.warning("intent_completeness: unparseable decision — pass-through")
        return {}

    if decision.get("complete") is True:
        logger.info("intent_completeness.decision complete=True intent=%s", intent)
        return {}

    # ── Incomplete: emit design_intent_confirm + force synthesis ──
    guess = decision.get("guess") or {}
    missing = decision.get("missing") or []

    card_id = f"intent-{uuid.uuid4().hex[:8]}"
    spec_payload = {
        "card_id": card_id,
        "inputs": guess.get("inputs") or [],
        "logic": guess.get("logic") or "",
        "presentation": guess.get("presentation") or "mixed",
        "alternatives": guess.get("alternatives") or [],
    }

    logger.info(
        "intent_completeness.decision complete=False missing=%s card_id=%s "
        "guess_presentation=%s",
        missing, card_id, spec_payload["presentation"],
    )

    pb_emit = (config.get("configurable", {}) or {}).get("pb_event_emit") if config else None
    if pb_emit is not None:
        try:
            pb_emit({"type": "design_intent_confirm", **spec_payload})
        except Exception as ee:  # noqa: BLE001
            logger.warning("intent_completeness: pb_emit failed: %s", ee)

    # Synthetic AIMessage so synthesis just renders this without another LLM call.
    return {
        "force_synthesis": True,
        "messages": [AIMessage(content=_FORCE_SYNTH_REPLY)],
    }
