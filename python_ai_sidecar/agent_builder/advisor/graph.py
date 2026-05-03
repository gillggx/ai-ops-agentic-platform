"""Advisor graph — deterministic dispatcher for the four non-BUILD intents.

This is intentionally NOT LangGraph. The Glass Box codebase uses a plain
async tool-loop, not LangGraph; matching that style keeps the cognitive
surface small. The "graph" is just `if intent == X: ...` over a fixed set
of nodes — no LLM-driven tool routing.

Yields StreamEvent objects (same shape as stream_agent_build) so the SSE
endpoint and frontend can treat both flows identically.
"""

from __future__ import annotations

import logging
from typing import AsyncGenerator, Optional

from python_ai_sidecar.agent_builder.advisor.classifier import (
    AdvisorIntent,
    classify_advisor_intent,
)
from python_ai_sidecar.agent_builder.advisor.extract import (
    extract_block_target,
    extract_block_targets,
    extract_use_case_keywords,
)
from python_ai_sidecar.agent_builder.advisor.synthesize import (
    synthesize_compare,
    synthesize_explain,
    synthesize_knowledge,
    synthesize_recommend,
)
from python_ai_sidecar.agent_builder.session import StreamEvent
from python_ai_sidecar.clients.java_client import JavaAPIClient

logger = logging.getLogger(__name__)


_RECOMMEND_TOP_K = 3


def _score_block_for_keywords(block: dict, keywords: list[str]) -> float:
    """Naïve substring score across name + description + category + tags.
    Same scoring shape Java's PublishedSkill search uses. pgvector embedding
    upgrade is future work.

    Deprecation penalty (2026-05-03): blocks with ``status='deprecated'`` get
    multiplied by 0.3 so legacy mega-blocks (like ``block_chart``) don't
    out-score active dedicated replacements just because their description
    happens to mention multiple chart_type options. Surfaced by eval harness
    case ``recommend_001`` — SPC outlier query was returning ``block_chart``
    over the dedicated SPC family.
    """
    haystack = " ".join(
        str(block.get(field) or "") for field in ("name", "description", "category", "tags")
    ).lower()
    score = 0
    for kw in keywords:
        kw_lower = kw.strip().lower()
        if not kw_lower:
            continue
        idx = 0
        while True:
            hit = haystack.find(kw_lower, idx)
            if hit < 0:
                break
            score += max(1, len(kw_lower) // 3)
            idx = hit + len(kw_lower)

    if (block.get("status") or "").lower() == "deprecated":
        score = score * 0.3
    return score


# ── Public API ────────────────────────────────────────────────────────


async def stream_block_advisor(
    user_message: str,
    intent: AdvisorIntent,
    *,
    java: JavaAPIClient,
) -> AsyncGenerator[StreamEvent, None]:
    """Run the advisor for one user message. Caller must have already
    classified intent (so the router can short-circuit BUILD)."""
    if intent == "AMBIGUOUS":
        yield StreamEvent(
            type="advisor_answer",
            data={
                "kind": "ambiguous",
                "markdown": (
                    "聽起來你可能是想**問 block 的用法**，也可能是想**建/改 pipeline**。"
                    "請更明確一點：\n\n"
                    "- 想問用法 → 「block_xbar_r 怎麼用?」\n"
                    "- 想對比 → 「filter 跟 threshold 差在哪?」\n"
                    "- 想推薦 → 「我有 SPC data 想看異常點，用哪個 block?」\n"
                    "- 想建構 → 「幫我建一個 SPC pipeline」"
                ),
            },
        )
        yield StreamEvent(type="done", data={"status": "advisor_done", "intent": intent})
        return

    if intent == "EXPLAIN":
        async for ev in _run_explain(user_message, java):
            yield ev
        return

    if intent == "COMPARE":
        async for ev in _run_compare(user_message, java):
            yield ev
        return

    if intent == "RECOMMEND":
        async for ev in _run_recommend(user_message, java):
            yield ev
        return

    if intent == "KNOWLEDGE":
        async for ev in _run_knowledge(user_message):
            yield ev
        return

    # BUILD reaches here only if caller forgot to dispatch — defensive.
    yield StreamEvent(
        type="error",
        data={"op": "advisor", "message": f"intent={intent} should not reach advisor", "ts": 0.0},
    )
    yield StreamEvent(type="done", data={"status": "failed"})


# ── Per-intent runners ────────────────────────────────────────────────


async def _run_explain(user_message: str, java: JavaAPIClient) -> AsyncGenerator[StreamEvent, None]:
    name, fallback_query = await extract_block_target(user_message)
    block: Optional[dict] = None
    if name:
        block = await java.get_block_by_name(name)
        if block is None:
            logger.info("advisor.explain: %s not found, falling back to recommend", name)
            # Couldn't find the named block → degrade to RECOMMEND-style
            # search using the fallback query.
            async for ev in _run_recommend(fallback_query, java, intent_summary_override=user_message):
                yield ev
            return
    else:
        # No specific name extracted → recommend instead.
        async for ev in _run_recommend(fallback_query, java, intent_summary_override=user_message):
            yield ev
        return

    md = await synthesize_explain(user_message, block)
    yield StreamEvent(
        type="advisor_answer",
        data={"kind": "explain", "block_name": block.get("name"), "markdown": md},
    )
    yield StreamEvent(type="done", data={"status": "advisor_done", "intent": "EXPLAIN"})


async def _run_compare(user_message: str, java: JavaAPIClient) -> AsyncGenerator[StreamEvent, None]:
    names = await extract_block_targets(user_message)
    if len(names) < 2:
        # Not enough blocks identified — degrade to recommend.
        async for ev in _run_recommend(user_message, java, intent_summary_override=user_message):
            yield ev
        return

    all_blocks = await java.list_blocks()
    by_name = {b.get("name"): b for b in all_blocks}
    fetched = [by_name[n] for n in names if n in by_name]

    if len(fetched) < 2:
        missing = [n for n in names if n not in by_name]
        yield StreamEvent(
            type="advisor_answer",
            data={
                "kind": "compare_failed",
                "markdown": (
                    f"找不到這些 block：{', '.join(missing)}。"
                    "請確認名稱是否正確（用 `block_` 前綴 + snake_case）。"
                ),
            },
        )
        yield StreamEvent(type="done", data={"status": "advisor_done", "intent": "COMPARE"})
        return

    md = await synthesize_compare(user_message, fetched)
    yield StreamEvent(
        type="advisor_answer",
        data={"kind": "compare", "block_names": [b.get("name") for b in fetched], "markdown": md},
    )
    yield StreamEvent(type="done", data={"status": "advisor_done", "intent": "COMPARE"})


async def _run_recommend(
    user_message: str,
    java: JavaAPIClient,
    *,
    intent_summary_override: Optional[str] = None,
) -> AsyncGenerator[StreamEvent, None]:
    keywords, intent_summary = await extract_use_case_keywords(user_message)
    if intent_summary_override:
        intent_summary = intent_summary_override

    all_blocks = await java.list_blocks()
    scored = [(b, _score_block_for_keywords(b, keywords)) for b in all_blocks]
    scored = [(b, s) for b, s in scored if s > 0]
    scored.sort(key=lambda t: t[1], reverse=True)
    candidates = [b for b, _ in scored[:_RECOMMEND_TOP_K]]

    md = await synthesize_recommend(user_message, intent_summary, candidates)
    yield StreamEvent(
        type="advisor_answer",
        data={
            "kind": "recommend",
            "candidates": [b.get("name") for b in candidates],
            "intent_summary": intent_summary,
            "keywords": keywords,
            "markdown": md,
        },
    )
    yield StreamEvent(type="done", data={"status": "advisor_done", "intent": "RECOMMEND"})


async def _run_knowledge(user_message: str) -> AsyncGenerator[StreamEvent, None]:
    """Concept Q&A — pure LLM markdown answer, no Java fetch / no tool use.
    Subjects are domain terms (WECO, Cpk, ANOVA, etc.) that aren't blocks
    so there's nothing to look up. The reply is a small markdown card."""
    md = await synthesize_knowledge(user_message)
    yield StreamEvent(
        type="advisor_answer",
        data={"kind": "knowledge", "markdown": md},
    )
    yield StreamEvent(type="done", data={"status": "advisor_done", "intent": "KNOWLEDGE"})
