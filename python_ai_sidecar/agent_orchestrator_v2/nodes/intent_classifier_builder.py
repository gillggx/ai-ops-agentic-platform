"""builder-mode intent classifier — 7 buckets.

Replaces the legacy "if mode==builder: return clear_chart" bypass with a
proper graph-deterministic dispatch:

  BUILD_NEW    — instruction to build a fresh pipeline from scratch
  BUILD_MODIFY — instruction to add/remove/rewire blocks on existing canvas
  EXPLAIN      — Q&A: what does block X do?
  COMPARE      — Q&A: A vs B difference
  RECOMMEND    — Q&A: which block for use case Y?
  KNOWLEDGE    — domain question (WECO R5? Cpk?) — answered without tools
  AMBIGUOUS    — unclear; emit clarify message

The graph router then dispatches:
  BUILD_*    → llm_call (with build_pipeline_live tool, prompt biased per bucket)
  EXPLAIN/COMPARE/RECOMMEND → advisor_graph (yields advisor_answer SSE)
  KNOWLEDGE  → llm_call (NO build tool, plain text answer)
  AMBIGUOUS  → synthesis with clarify card

Heuristic shortcut: build-verb regex matches obvious BUILD requests
without an LLM call (saves ~150ms/$0.001 on hot path).

Confidence threshold: low-conf Q&A intents downgrade to AMBIGUOUS so the
graph asks rather than guesses.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Literal

from langchain_core.runnables import RunnableConfig

from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client

logger = logging.getLogger(__name__)


BuilderIntent = Literal[
    "BUILD_NEW", "BUILD_MODIFY",
    "EXPLAIN", "COMPARE", "RECOMMEND",
    "KNOWLEDGE",
    "AMBIGUOUS",
]


# Below this we collapse non-BUILD intents to AMBIGUOUS so the graph asks
# rather than guesses wrong. BUILD is the safe default fallback.
MIN_CONFIDENCE = 0.55


_SYSTEM = """You classify a Pipeline-Builder user's message into ONE of seven buckets.

The user is on a Pipeline DAG editor. They might want to ACT on the canvas
(build new / modify) OR ask QUESTIONS (about blocks, or general domain
concepts). Get this right: each bucket triggers a different downstream flow.

Buckets:

  BUILD_NEW     create a brand-new pipeline from scratch.
                Verbs/phrasing: 「幫我建一個 X」「從零做」「新做一個 SPC pipeline」
                Examples: "幫我建一個 SPC pipeline", "做一個監控 yield 的 pipeline"

  BUILD_MODIFY  add / remove / rewire blocks on the EXISTING canvas.
                Verbs/phrasing: 「加一個 X」「把 X 接到 Y」「移除 Z」「改成」
                Examples: "加一個 filter block", "把 xbar_r 接到 process_history",
                          "移除 那個 boxplot", "把 filter 改成 threshold"

  EXPLAIN       asks about ONE specific block.
                Phrasing: 「X 是什麼/怎麼用/做什麼/有什麼參數」
                Examples: "block_xbar_r 怎麼用?", "ewma_cusum 做什麼的?"

  COMPARE       differences between TWO OR MORE specific blocks.
                Phrasing: 「A 跟 B 差在哪」「A 和 B 的不同」「A vs B」
                Examples: "filter 跟 threshold 差在哪?", "xbar_r vs imr"

  RECOMMEND     describes a use case + asks which block to use.
                Phrasing: 「我有 X 想 Y，該用哪個 block」
                Examples: "我有一筆 SPC data 想看異常點，用哪個?"

  KNOWLEDGE     pure domain Q&A about concepts, NOT specific blocks.
                Phrasing: 「WECO 是什麼?」「Cpk 怎麼算?」「SPC 原理是什麼」
                Examples: "WECO R5 是什麼?", "Cpk 跟 Ppk 差在哪?",
                          "SPC 用的鐘形分布是什麼意思?"

  AMBIGUOUS     could go multiple ways; not enough signal to commit.
                Examples: "block_xbar_r" (no verb), 「幫忙看看」, 一句沒主語

Output JSON only (no markdown fence):
  {"intent": "<bucket>",
   "confidence": 0.0-1.0,
   "reason": "<one short sentence in user's language>"}

Rules of thumb:
- Action verb on canvas object (add/remove/connect/wire/replace) → BUILD_*
- BUILD_NEW vs BUILD_MODIFY: 「建/從零/做一個」=NEW; 「加/接/移除/改」=MODIFY
  When canvas already has nodes, default to BUILD_MODIFY unless user says "重新做" / "從零"
- One block name + question word → EXPLAIN
- ≥2 block names + comparison word → COMPARE
- Use case description without specific block names → RECOMMEND
- Concept question (no specific block) → KNOWLEDGE
- Otherwise → AMBIGUOUS

Be aggressive about BUILD_* — that's the most common intent on the canvas.
Only label EXPLAIN/COMPARE/RECOMMEND/KNOWLEDGE when the question nature
is unambiguous.
"""


_BUILD_NEW_RE = re.compile(
    r"(從零|新做|新建|幫我建一個|做一個新|建一個新|create\s+a\s+new\s+pipeline|build\s+a\s+new)",
    re.IGNORECASE,
)
_BUILD_MODIFY_RE = re.compile(
    r"(加一個|新增一個|連起來|接到|接成|改成|改為|移除|刪掉|拿掉|替換成|替換為|"
    r"add\s+a\s+\w+|remove\s+\w+|connect\s+\w+\s+to|replace\s+\w+\s+with)",
    re.IGNORECASE,
)


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    return text


async def classify_builder_intent(
    user_message: str,
    *,
    has_canvas_nodes: bool = False,
) -> tuple[BuilderIntent, float, str]:
    """Return (intent, confidence, reason).

    `has_canvas_nodes` biases BUILD heuristics: on a non-empty canvas the
    BUILD_MODIFY pattern wins over BUILD_NEW when both could fire.

    Falls back to BUILD_MODIFY (or BUILD_NEW on empty canvas) when the
    classifier fails — preserves the previous "user is here to build"
    expectation as the safe default.
    """
    msg = (user_message or "").strip()
    if not msg:
        default = "BUILD_MODIFY" if has_canvas_nodes else "BUILD_NEW"
        return (default, 1.0, "empty message")  # type: ignore[return-value]

    # ── Heuristic shortcuts ───────────────────────────────────────────
    if _BUILD_NEW_RE.search(msg):
        return ("BUILD_NEW", 0.95, "matches new-build verb pattern")
    if _BUILD_MODIFY_RE.search(msg):
        return ("BUILD_MODIFY", 0.95, "matches modify verb pattern")

    # ── LLM classifier ────────────────────────────────────────────────
    client = get_llm_client()
    try:
        resp = await client.create(
            system=_SYSTEM,
            messages=[{"role": "user", "content": msg}],
            max_tokens=200,
        )
        decision = json.loads(_strip_code_fence(resp.text or ""))
    except Exception as e:  # noqa: BLE001
        logger.warning("builder.classify failed (%s) — fallback to BUILD_MODIFY", e)
        default = "BUILD_MODIFY" if has_canvas_nodes else "BUILD_NEW"
        return (default, 0.0, f"classifier_error: {e}")  # type: ignore[return-value]

    intent_raw = (decision.get("intent") or "BUILD_MODIFY").upper()
    valid = {"BUILD_NEW", "BUILD_MODIFY", "EXPLAIN", "COMPARE",
             "RECOMMEND", "KNOWLEDGE", "AMBIGUOUS"}
    if intent_raw not in valid:
        intent_raw = "BUILD_MODIFY" if has_canvas_nodes else "BUILD_NEW"
    confidence = float(decision.get("confidence") or 0.0)
    reason = (decision.get("reason") or "").strip()

    # Below-threshold non-BUILD intents → AMBIGUOUS so the graph asks user.
    qa_intents = {"EXPLAIN", "COMPARE", "RECOMMEND", "KNOWLEDGE"}
    if intent_raw in qa_intents and confidence < MIN_CONFIDENCE:
        logger.info("builder.classify: %s @ conf=%.2f below threshold → AMBIGUOUS",
                    intent_raw, confidence)
        return ("AMBIGUOUS", confidence, f"low confidence on {intent_raw}: {reason}")

    logger.info("builder.classify: %s conf=%.2f reason=%r msg=%r",
                intent_raw, confidence, reason, msg[:80])
    return (intent_raw, confidence, reason)  # type: ignore[return-value]


# ── LangGraph node wrapper ────────────────────────────────────────────


async def intent_classifier_builder_node(
    state: Dict[str, Any], config: RunnableConfig,
) -> Dict[str, Any]:
    """LangGraph node: classify when mode='builder', else return None to
    let the regular intent_classifier_node handle it.

    Returns state-update dict matching GraphState schema:
      - intent: maps builder buckets onto the existing intent enum so
        downstream nodes need no change. Q&A buckets get a special
        `builder_*` prefix the graph recognises for advisor dispatch.
    """
    if state.get("mode") != "builder":
        # Not builder — caller (graph) routes through the regular classifier.
        return {}

    user_message = state.get("user_message") or ""
    snapshot = state.get("pipeline_snapshot") or {}
    nodes = snapshot.get("nodes") if isinstance(snapshot, dict) else None
    has_canvas_nodes = bool(nodes)

    # Phase 11 v6 — when launched from a Skill embed flow, the user's intent
    # to BUILD is unambiguous (they typed prose on the Skill page and pressed
    # "Build →", which opened the Builder tab). Skip the RECOMMEND/EXPLAIN
    # classifier path so the orchestrator goes straight to build_pipeline_live
    # instead of treating the prose as "advise me which block to use".
    kind = snapshot.get("_kind") if isinstance(snapshot, dict) else None
    if kind == "skill_step":
        intent = "BUILD_MODIFY" if has_canvas_nodes else "BUILD_NEW"
        confidence = 1.0
        reason = "skill_step ctx — user pressed Build on Skill page; bypass advisor."
        intent_str = f"builder_{intent.lower()}"
        return {"intent": intent_str, "intent_hint": reason}

    intent, confidence, reason = await classify_builder_intent(
        user_message, has_canvas_nodes=has_canvas_nodes,
    )

    # Map to the graph's `intent` field. Builder-mode intents use a
    # `builder_<bucket>` namespace so _route_after_intent can dispatch
    # without colliding with chat-mode buckets.
    intent_str = f"builder_{intent.lower()}"
    return {"intent": intent_str, "intent_hint": reason}
