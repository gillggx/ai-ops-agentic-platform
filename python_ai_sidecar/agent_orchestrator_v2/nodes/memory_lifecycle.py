"""memory_lifecycle node — Phase 1 reflective memory feedback + abstraction.

Runs AFTER synthesis (and optionally after self_critique). Does two things:

1. Feedback: credit cited/retrieved memories with +success
2. Abstraction: LLM extracts (intent, action) pair from successful task
   → writes to agent_experience_memory via ExperienceMemoryService

This is a terminal node — its output doesn't affect the final answer.
Side effects only (DB writes).
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from langchain_core.runnables import RunnableConfig

from python_ai_sidecar.agent_orchestrator_v2.helpers import _extract_memory_citations

logger = logging.getLogger(__name__)


async def memory_lifecycle_node(state: Dict[str, Any], config: RunnableConfig) -> Dict[str, Any]:
    """Record memory feedback + abstract new experience memory."""
    final_text = state.get("final_text", "")
    tools_used = state.get("tools_used", [])
    user_message = state.get("user_message", "")
    user_id = config["configurable"]["user_id"]
    session_id = state.get("session_id")
    retrieved_memory_ids = state.get("retrieved_memory_ids", [])

    # Skip if no meaningful work was done
    if not tools_used or len(tools_used) < 2 or not final_text:
        return {"memory_write_scheduled": False}

    # Extract [memory:N] citations from agent's answer
    cited_ids = _extract_memory_citations(final_text)
    # Fallback: if agent didn't cite but RAG retrieved, credit passively
    feedback_ids = cited_ids or retrieved_memory_ids

    # Phase 8-A-1d: native — Java client + ported helpers, no DB session.
    from python_ai_sidecar.agent_helpers_native.experience_memory_client import (
        ExperienceMemoryClient,
    )
    from python_ai_sidecar.agent_helpers_native.memory_abstraction import abstract_memory
    from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client
    from python_ai_sidecar.clients.java_client import JavaAPIClient
    from python_ai_sidecar.config import CONFIG

    try:
        java = JavaAPIClient(
            CONFIG.java_api_url, CONFIG.java_internal_token,
            timeout_sec=CONFIG.java_timeout_sec,
        )
        svc = ExperienceMemoryClient(java)

        # 1. Feedback on cited/retrieved memories
        for mem_id in feedback_ids:
            try:
                await svc.record_feedback(mem_id, outcome="success")
            except Exception as exc:
                logger.warning("Memory feedback failed for id=%d: %s", mem_id, exc)

        # 2. LLM abstraction → new experience memory
        try:
            abstraction = await abstract_memory(
                llm_client=get_llm_client(),
                user_query=user_message,
                agent_final_text=final_text,
                tool_chain=tools_used,
            )
        except Exception as exc:
            logger.warning("Memory abstraction errored: %s", exc)
            abstraction = None

        if abstraction is not None:
            try:
                await svc.write(
                    user_id=user_id,
                    intent_summary=abstraction["intent_summary"],
                    abstract_action=abstraction["abstract_action"],
                    source="auto",
                    source_session_id=session_id,
                )
                logger.info("Memory lifecycle: wrote new experience memory for user=%d", user_id)
            except Exception as exc:
                logger.warning("Memory write failed: %s", exc)
    except Exception as exc:
        logger.warning("Memory lifecycle background task failed: %s", exc)

    return {
        "cited_memory_ids": cited_ids,
        "memory_write_scheduled": True,
    }
