"""advisor_dispatch — bridge chat orchestrator → block advisor.

When the builder-mode classifier picks EXPLAIN / COMPARE / RECOMMEND /
AMBIGUOUS, this node runs the existing `agent_builder.advisor.stream_block_advisor`
graph and pushes its `advisor_answer` events out via the SSE pb_event_emit
channel. After advisor finishes, we set force_synthesis so the chat graph
short-circuits to synthesis (no LLM call, no tool loop — advisor already
gave the final answer).

This keeps the advisor graph as a single source of truth: it's reused by
both /agent/build and /agent/chat (builder mode).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from python_ai_sidecar.agent_builder.advisor import stream_block_advisor
from python_ai_sidecar.clients.java_client import JavaAPIClient
from python_ai_sidecar.config import CONFIG

logger = logging.getLogger(__name__)


# Map graph-level intent string back to the advisor's AdvisorIntent enum.
_INTENT_MAP = {
    "builder_explain":    "EXPLAIN",
    "builder_compare":    "COMPARE",
    "builder_recommend":  "RECOMMEND",
    "builder_ambiguous":  "AMBIGUOUS",
}


async def advisor_dispatch_node(
    state: Dict[str, Any], config: RunnableConfig,
) -> Dict[str, Any]:
    """Run the block advisor for a Q&A intent. Yields advisor_answer SSE
    frames; sets force_synthesis to short-circuit the rest of the graph."""
    intent = (state.get("intent") or "").lower()
    advisor_intent = _INTENT_MAP.get(intent)
    if advisor_intent is None:
        logger.warning("advisor_dispatch: unexpected intent=%s — falling through", intent)
        return {}

    user_message = state.get("user_message") or ""
    pb_emit = config.get("configurable", {}).get("pb_event_emit") if config else None

    # Lazy Java client — chat orchestrator already has CONFIG available.
    # We don't get a CallerContext here so use service token directly.
    java = JavaAPIClient(
        base_url=CONFIG.java_api_url,
        token=CONFIG.java_internal_token,
        timeout_sec=CONFIG.java_timeout_sec,
    )

    # Stream advisor events to SSE.
    final_markdown_parts: list[str] = []
    try:
        async for ev in stream_block_advisor(user_message, advisor_intent, java=java):
            if ev.type == "advisor_answer":
                if pb_emit:
                    try:
                        pb_emit({"type": "advisor_answer", **ev.data})
                    except Exception as ee:  # noqa: BLE001
                        logger.warning("advisor_dispatch: pb_emit failed: %s", ee)
                md = ev.data.get("markdown")
                if isinstance(md, str):
                    final_markdown_parts.append(md)
            # `done` events are advisor-internal; chat graph emits its own
            # done at the end of synthesis. Skip.
    except Exception as e:  # noqa: BLE001
        logger.exception("advisor_dispatch: advisor failed (%s)", e)
        if pb_emit:
            try:
                pb_emit({
                    "type": "advisor_answer",
                    "kind": "error",
                    "markdown": f"⚠ Advisor 失敗：{e.__class__.__name__}: {str(e)[:200]}",
                })
            except Exception:  # noqa: BLE001
                pass
        final_markdown_parts.append(f"Advisor failed: {e}")

    # Inject the markdown as an AIMessage so synthesis can fall through
    # to it without a fresh LLM call. force_synthesis routes around
    # llm_call + tool_execute.
    final_text = "\n\n".join(final_markdown_parts) or "(empty advisor response)"
    return {
        "force_synthesis": True,
        "messages": [AIMessage(content=final_text)],
        "final_text": final_text,
    }
