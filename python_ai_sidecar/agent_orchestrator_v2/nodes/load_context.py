"""load_context node — wraps ContextLoader.build() for the LangGraph agent.

Produces: system_blocks, system_text, retrieved_memory_ids, context_meta,
          messages (seed with system message + history), history_turns.
"""

from __future__ import annotations

import logging
from typing import Any, Dict
from langchain_core.runnables import RunnableConfig

from langchain_core.messages import HumanMessage, SystemMessage

from python_ai_sidecar.agent_helpers.context_loader import ContextLoader
from python_ai_sidecar.agent_helpers.task_context_extractor import extract as extract_task_context

logger = logging.getLogger(__name__)


async def load_context_node(state: Dict[str, Any], config: RunnableConfig) -> Dict[str, Any]:
    """Stage 1: build system prompt, retrieve memories, load session history."""
    db = config["configurable"]["db"]
    user_id = state["user_id"]
    user_message = state["user_message"]
    canvas_overrides = state.get("canvas_overrides")

    # Task context extraction (same as v1)
    _tc_type, _tc_subject, _tc_tool = extract_task_context(user_message)
    task_context = {
        "task_type": _tc_type,
        "data_subject": _tc_subject,
        "tool_name": _tc_tool,
    }

    loader = ContextLoader(db)
    system_blocks, context_meta = await loader.build(
        user_id=user_id,
        query=user_message,
        top_k_memories=5,
        canvas_overrides=canvas_overrides,
        task_context=task_context,
    )

    # Flatten system blocks into a single text (for LLM providers that
    # take system as a string, not as content blocks)
    system_text = "\n".join(
        b.get("text", "") for b in system_blocks if isinstance(b, dict)
    )

    # Phase 5: pipeline-only directive + published-skill-first heuristic + block catalog.
    try:
        from python_ai_sidecar.pipeline_builder._sidecar_deps import get_settings
        if get_settings().PIPELINE_ONLY_MODE:
            # Inject pb block catalog so LLM knows the 26 blocks it can use in build_pipeline
            try:
                from python_ai_sidecar.pipeline_builder.block_registry import BlockRegistry
                from python_ai_sidecar.pipeline_builder.prompt_hint import build_block_catalog_hint
                _pb_reg = BlockRegistry()
                await _pb_reg.load_from_db(db)
                block_hint = build_block_catalog_hint(_pb_reg.catalog)
            except Exception as e:  # noqa: BLE001
                block_hint = f"(Could not load block catalog: {e})"

            system_text += (
                "\n\n# Pipeline-Only Mode (Phase 5-UX-6 — Glass Box build)\n"
                "All data-analysis requests go through the Pipeline Builder engine.\n"
                "\n"
                "## Tool choice algorithm\n"
                "1. **Knowledge-only** question (e.g. \"WECO R5 是什麼\")\n"
                "     → Answer as plain text. No tool call.\n"
                "2. **Data / analytical** question\n"
                "     a. First call `search_published_skills(query=<user goal>)`.\n"
                "     b. If a result matches well, call `invoke_published_skill(slug, inputs)`.\n"
                "     c. **If no good match**: DO NOT immediately call `build_pipeline_live`.\n"
                "        First tell the user in one short sentence: \"找不到現成 skill，要不要\n"
                "        我幫你建一條？\"（或「沒有現成的分析可用，我可以用 Pipeline Builder\n"
                "        建一條新的，要嗎？」）— 等使用者同意（\"好\" / \"可以\" / \"ok\"）再呼叫\n"
                "        `build_pipeline_live(goal=\"...\")`. 這是強制的禮貌性確認，因為\n"
                "        build_pipeline_live 會接管使用者畫面開 canvas overlay。\n"
                "     d. 若使用者一開始就明確表達要「建 pipeline / 建新 skill」則可直接呼叫，\n"
                "        不用再問一次。\n"
                "\n"
                "## build_pipeline_live notes\n"
                "- **You do NOT emit pipeline_json**. Just pass `goal` as a clear NL brief. The\n"
                "  sub-agent knows the block catalog, will list blocks it needs, add nodes,\n"
                "  connect edges, set params, run the pipeline, and finish.\n"
                "- After it returns, you'll get `{status, summary, node_count}`. Use this to\n"
                "  write a short confirmation for the user. Do NOT repeat the full chart data —\n"
                "  the canvas overlay already shows it visually.\n"
                "- **Follow-up requests carry canvas forward automatically**. If the user asks to\n"
                "  modify / add / remove something after a previous build (e.g. 「加一張常態分佈\n"
                "  圖」、「把 step 改成 STEP_020」、「多加一條 regression」), just call\n"
                "  `build_pipeline_live` again with the incremental goal. The sub-agent sees the\n"
                "  existing canvas via session context and edits in place — you don't need to\n"
                "  re-describe everything.\n"
                "- If `base_pipeline_id` is relevant (user is editing a saved pipeline from\n"
                "  /admin/pipeline-builder), pass it explicitly to override session context.\n"
                "\n"
                "## Block catalog (for reference; the sub-agent sees this too)\n"
                + block_hint
            )
    except Exception as e:  # noqa: BLE001
        import logging as _lg
        _lg.getLogger(__name__).warning("Pipeline-only context injection failed: %s", e)

    # Extract retrieved experience memory IDs for feedback loop
    retrieved_memory_ids = [
        int(h["id"])
        for h in context_meta.get("rag_hits", [])
        if h.get("_source") == "experience" and isinstance(h.get("id"), int)
    ]

    # Load session history
    from python_ai_sidecar.agent_orchestrator_v2.session import load_session
    session_id, history_messages, cumulative_tokens = await load_session(
        db, state.get("session_id"), user_id,
    )

    # Build initial messages: history + current user message
    messages = list(history_messages) + [HumanMessage(content=user_message)]

    context_meta["history_turns"] = len(history_messages) // 2
    context_meta["cumulative_tokens"] = cumulative_tokens

    return {
        "session_id": session_id,
        "system_blocks": system_blocks,
        "system_text": system_text,
        "retrieved_memory_ids": retrieved_memory_ids,
        "context_meta": context_meta,
        "messages": messages,
        "history_turns": context_meta["history_turns"],
    }
