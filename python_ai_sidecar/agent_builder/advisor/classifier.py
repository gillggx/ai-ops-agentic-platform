"""Node 1 — classify the user's builder-panel message into one of five buckets.

Returns AdvisorIntent (a string literal) so the graph can route deterministically.
The LLM does NOT see a tool list — it only labels the message.

Confidence threshold: when the LLM's confidence is below MIN_CONFIDENCE we
return AMBIGUOUS instead of trusting a coin-flip — the graph then surfaces
a clarification message rather than committing to the wrong path.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Literal

from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client

logger = logging.getLogger(__name__)


AdvisorIntent = Literal["BUILD", "EXPLAIN", "COMPARE", "RECOMMEND", "KNOWLEDGE", "AMBIGUOUS"]


MIN_CONFIDENCE = 0.55


_SYSTEM = """You classify a Pipeline-Builder user's message into ONE bucket.

The user is sitting in front of a pipeline DAG editor. They might want to
ACT on the canvas (build / modify / connect blocks), ask about a SPECIFIC
block (what does X do? compare A vs B? which block fits Y?), or ask a
DOMAIN CONCEPT question (what is WECO? Cpk vs Ppk?).

Buckets:
  BUILD      — instruction to construct or modify the pipeline.
               Verbs: 「建/做/加/接/改/移除/連/設」 / "build/add/connect/modify/wire".
               Examples: "幫我建一個 SPC pipeline", "加一個 filter block",
                          "把 xbar_r 接到 process_history 後面"

  EXPLAIN    — asks about ONE specific BLOCK (must reference a block_xxx
               name, an obvious block alias like "xbar_r"/"filter", or
               a chart-type vocabulary that maps 1-1 to a block).
               Phrases: 「X 是什麼/怎麼用/做什麼/有什麼參數」 / "what is X" /
                        "how do I use X" / "X parameters"
               Examples: "block_xbar_r 是做什麼的?", "ewma_cusum 怎麼用?"
               ⚠ "WECO 是什麼?" is NOT EXPLAIN — WECO isn't a block, it's
                 a domain rule set → that's KNOWLEDGE.

  COMPARE    — asks differences between TWO OR MORE specific BLOCKS.
               Phrases: 「A 跟 B 差在哪/有什麼不同」 / "diff between A and B" /
                        "compare A B" / "A vs B"
               Examples: "filter 和 threshold 差在哪?", "xbar_r vs imr"
               ⚠ "Cpk 跟 Ppk 差在哪?" is NOT COMPARE — those are domain
                 metrics, not blocks → KNOWLEDGE.

  RECOMMEND  — describes a USE CASE and asks which block(s) to use.
               Phrases: 「我想 ___ 該用哪個 block」 / "which block for ___" /
                        "I have ___, what should I use"
               Examples: "我有一筆 SPC data 想看異常點，該用哪個?",
                          "想做相關性分析用哪個 block?"

  KNOWLEDGE  — pure DOMAIN concept Q&A. Subject is NOT a block — it's a
               manufacturing / SPC / statistics term, an algorithm, a
               metric, a rule set, or a general concept.
               Phrases: 「X 是什麼?」「X 怎麼算?」「X 和 Y 差在哪?」 where
                        X/Y are NOT block names.
               Examples: "WECO R5 是什麼?", "Cpk 跟 Ppk 差在哪?",
                          "SPC 用的鐘形分布是什麼意思?", "what is WECO?",
                          "explain anderson-darling test"
               KNOWLEDGE is answered with a plain markdown explanation —
               no Java block lookup, no canvas mutation.

  AMBIGUOUS  — could be BUILD or a question; not enough signal.
               Examples: "block_xbar_r" (no verb / no question), "幫忙看看",
                          一句沒主語

Output JSON only (no markdown fence):
  {"intent": "BUILD"|"EXPLAIN"|"COMPARE"|"RECOMMEND"|"KNOWLEDGE"|"AMBIGUOUS",
   "confidence": 0.0-1.0,
   "reason": "<one short sentence in user's language>"}

Disambiguation cheatsheet:
- Action verb on canvas object → BUILD
- Mentions ONE block name + question word → EXPLAIN
- Mentions ≥2 block names + comparison word → COMPARE
- Describes a goal WITHOUT naming a specific block → RECOMMEND
- Question about a CONCEPT / METRIC / ALGORITHM (not a block) → KNOWLEDGE
- Otherwise → AMBIGUOUS

Be aggressive about BUILD — that's the most common intent. EXPLAIN /
COMPARE need an actual block name in the message. KNOWLEDGE is for
domain terms (WECO, Cpk, ANOVA, control chart theory, etc.) that
aren't blocks.
"""


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    return text


# Local trivial heuristics — we don't want to pay an LLM call for the
# obvious BUILD case ("幫我建一個 ..." 等). These are conservative — when in
# doubt the heuristic abstains and the LLM decides.
_BUILD_VERBS_RE = re.compile(
    r"(幫我建|做一個|建一個|做個|新增一個|加一個|連起來|接到|設成|改成|build\s+\w+|create\s+\w+|add\s+a\s+\w+\s+block)",
    re.IGNORECASE,
)


async def classify_advisor_intent(user_message: str) -> tuple[AdvisorIntent, float, str]:
    """Return (intent, confidence, reason).

    Falls back to BUILD when classifier fails — preserves the existing
    Glass Box behaviour as the safe default (worst case: we run the build
    path on a question, user gets a "I'm not sure what to build" reply).
    """
    msg = (user_message or "").strip()
    if not msg:
        return ("BUILD", 1.0, "empty message")

    # Heuristic shortcut for clearly-build requests.
    if _BUILD_VERBS_RE.search(msg):
        return ("BUILD", 0.95, "matches build-verb pattern")

    client = get_llm_client()
    try:
        resp = await client.create(
            system=_SYSTEM,
            messages=[{"role": "user", "content": msg}],
            max_tokens=200,
        )
        text = _strip_code_fence(resp.text or "")
        decision = json.loads(text)
    except Exception as e:  # noqa: BLE001
        logger.warning("advisor.classify failed (%s) — defaulting to BUILD", e)
        return ("BUILD", 0.0, f"classifier_error: {e}")

    intent_raw = (decision.get("intent") or "BUILD").upper()
    if intent_raw not in {"BUILD", "EXPLAIN", "COMPARE", "RECOMMEND", "KNOWLEDGE", "AMBIGUOUS"}:
        intent_raw = "BUILD"
    confidence = float(decision.get("confidence") or 0.0)
    reason = (decision.get("reason") or "").strip()

    # Below-confidence question intents collapse to AMBIGUOUS so the graph
    # asks the user to clarify instead of guessing wrong.
    if intent_raw in {"EXPLAIN", "COMPARE", "RECOMMEND", "KNOWLEDGE"} and confidence < MIN_CONFIDENCE:
        logger.info("advisor.classify: %s @ conf=%.2f below threshold → AMBIGUOUS",
                    intent_raw, confidence)
        return ("AMBIGUOUS", confidence, f"low confidence on {intent_raw}: {reason}")

    logger.info("advisor.classify: %s conf=%.2f reason=%r msg=%r",
                intent_raw, confidence, reason, msg[:80])
    return (intent_raw, confidence, reason)  # type: ignore[return-value]
