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
    """Stage 1: build system prompt, retrieve memories, load session history.

    Part B (SPEC_context_engineering): also fetches a dynamic-state snapshot
    (active alarms + user focus) from Java and prepends a <current_state>
    block to the user message so the LLM has prior context instead of
    reasoning from scratch.
    """
    db = config["configurable"].get("db")
    user_id = state["user_id"]
    user_message = state["user_message"]
    canvas_overrides = state.get("canvas_overrides")
    client_context = state.get("client_context") or {}

    # Task context extraction (same as v1)
    _tc_type, _tc_subject, _tc_tool = extract_task_context(user_message)
    task_context = {
        "task_type": _tc_type,
        "data_subject": _tc_subject,
        "tool_name": _tc_tool,
    }

    # Phase 8-A-1d: native chat path uses Java client; legacy in-process tests
    # may still pass a SQLAlchemy session (db != None, java=None).
    from python_ai_sidecar.clients.java_client import JavaAPIClient
    from python_ai_sidecar.config import CONFIG
    java = JavaAPIClient(
        CONFIG.java_api_url, CONFIG.java_internal_token,
        timeout_sec=CONFIG.java_timeout_sec,
    )

    loader = ContextLoader(db, java=java)
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

    # v1.4 — Plan Panel directive (independent of pipeline-only mode).
    # The agent must emit a 3-7 item plan via update_plan(action="create")
    # BEFORE any other tool call, then update each item as it progresses.
    # Frontend renders this as a live progress checklist above the chat.
    system_text += (
        "\n\n# Plan-First Execution (v1.4 Plan Panel)\n"
        "**EVERY new turn**, your **FIRST tool call must be `update_plan`** with\n"
        "`action='create'` and 3-7 high-level todo items covering the work for THIS\n"
        "request. Items typically follow: 確認需求 → 取資料 → 處理 / 計算 → 呈現結果 → 結論。\n"
        "\n"
        "Each item: `{id: \"p1\"|\"p2\"|..., title: \"<short Chinese phrase>\", status: \"pending\"}`.\n"
        "\n"
        "As you complete each phase, immediately call `update_plan(action='update', id, status='done')`.\n"
        "Mark a step `'in_progress'` when you start it, `'done'` when finished, `'failed'` if it errors.\n"
        "Optional `note` 加額外說明（如「已加 4 個 nodes」、「執行 12.3 秒」）。\n"
        "\n"
        "The PE sees a Claude-Code-style live checklist — this is the primary signal\n"
        "that you're making progress. Skipping the plan or never updating it makes the\n"
        "UI feel stuck.\n"
        "\n"
        "# Auto-Run after Build (chat path only)\n"
        "After `build_pipeline_live` returns success, the system **automatically runs\n"
        "the resulting pipeline** and shows results via the AnalysisPanel — you do NOT\n"
        "need to call execute manually. Just update_plan to mark the relevant items\n"
        "done and write a short synthesis. If the auto-run fails, you'll see\n"
        "`pb_run_error` come through and you should call `propose_pipeline_patch`\n"
        "with a targeted fix (only ONE retry — if it fails again, explain the issue\n"
        "in plain language and stop).\n"
        "\n"
        "**If `build_pipeline_live` itself returns `status='failed'`** (the sub-agent\n"
        "hit MAX_TURNS / errored out before producing a usable pipeline): DO NOT call\n"
        "`build_pipeline_live` again with the same goal. The user has already seen\n"
        "the partial canvas + a takeover link. Just acknowledge in plain language\n"
        "(\"建構未完成，可以在 Pipeline Builder 自己接手\") and stop — retrying with the\n"
        "same prompt will hit the same failure mode.\n"
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

    # Phase v1.3 P0 — ON_DUTY-specific guidance.
    # ON_DUTY callers have build_pipeline_live + draft/build/patch/save_*
    # tools removed from their catalog. Without telling the LLM why, it
    # tries to fall back to hallucinated tools or gives an unhelpful
    # answer when no published skill matches. Spell out the recovery
    # path here so the LLM produces a useful explanation instead.
    caller_roles = config["configurable"].get("caller_roles") or ()
    role_set = {r.upper() for r in caller_roles}
    if role_set and "IT_ADMIN" not in role_set and "PE" not in role_set:
        # Strict ON_DUTY (or no role at all — fail-closed).
        system_text += (
            "\n\n# 角色限制（你正在服務「值班工程師」，權限有限）\n"
            "你目前可用的工具只有「查詢」+「執行已 published 的 Skill」這條路徑。\n"
            "**禁止能力**：建新 Pipeline / 建 Skill / 建 MCP / 建規則 / 寫共用記憶 — 這些工具已從你的工具表中移除。\n"
            "\n"
            "## 找不到對應 Skill 時的標準回應\n"
            "如果 `search_published_skills(query)` **沒有適合的命中**，**禁止亂選**或試呼叫被移除的工具。\n"
            "請直接用文字回覆使用者，內容包含：\n"
            "  1. 一句話說明：「目前沒有對應的現成 skill 可用」\n"
            "  2. 簡短列出這個分析需要看的方向（給值班參考用）\n"
            "  3. 結尾固定句型：「**建議聯繫 PE 或 IT_ADMIN 協助建立此 skill**，或告訴我您想先看哪一筆 raw data，我可以用 `execute_mcp` 直接幫您查。」\n"
            "\n"
            "## 退路：raw data 直查\n"
            "如果使用者改要求看 raw data（單筆告警、特定機台事件、製程歷史），你**仍可以**呼叫\n"
            "`execute_mcp` + `search_published_skills` + `invoke_published_skill` 直接查詢回覆。\n"
            "這條路在值班場景超有用——告警背景查證、單機台健康度、批次 trace 都走這。\n"
        )

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

    # Part B: dynamic-state block. Best-effort — failure should never block
    # the chat (fall back to "no context, agent reasons from scratch").
    current_state_block = await _build_current_state_block(java, client_context)
    enriched_user_message = (
        f"{current_state_block}\n\n{user_message}" if current_state_block else user_message
    )

    # Part B follow-on: teach the agent to USE the snapshot before reaching for
    # tools. Without this, the pipeline-only directive above ("search_published_skills
    # first") wins and the agent burns 7 LLM turns on a question whose answer is
    # already sitting in <current_state>.
    if current_state_block:
        system_text += (
            "\n\n# Use <current_state> first (Part B)\n"
            "Each user message is now prepended with a `<current_state>` block carrying live\n"
            "system state (active alarms with severity + age, user_focus equipment). When the\n"
            "user's question can be answered **directly** from that block — e.g.:\n"
            "  - 「現在有幾個 alarm」/ 「哪台機台 alarm 最嚴重」\n"
            "  - 「最近哪些機台 OOC」/ 「列出 alarm 清單」\n"
            "  - 「目前狀況」when the snapshot already shows it\n"
            "**answer in plain text from the snapshot. Do NOT call search_published_skills /\n"
            "execute_skill / build_pipeline_live for these.** Tool calls are for *new* analysis\n"
            "the snapshot doesn't cover. Ignoring this rule wastes 5-10x tokens and triggers\n"
            "MAX_ITERATIONS.\n"
        )

    # Phase E2: mode-aware section. Same orchestrator handles both chat
    # turns (mode="chat", default — keep current behaviour, no extra prompt
    # to avoid regressions) and Pipeline-Builder canvas-side prompts
    # (mode="builder", aggressive build_pipeline_live). For chat mode we
    # let the existing PIPELINE_ONLY_MODE / Use<current_state> rules drive.
    mode = state.get("mode") or "chat"
    if mode == "builder":
        system_text += (
            "\n\n# Pipeline-Builder Mode (Phase E2)\n"
            "User is on a Pipeline Builder canvas with the pipeline open in front of them.\n"
            "Their intent is **almost always pipeline modification / construction**, not Q&A.\n"
            "\n"
            "Routing rules:\n"
            "  - 「加一個 chart」/「改 cron」/「換 alert 規則」/ vague structural goals\n"
            "      → call `build_pipeline_live` directly (no '要建嗎' confirmation needed —\n"
            "        user's already in the builder, that IS the confirmation)\n"
            "  - 「為什麼這條 pipeline 失敗」/「這個 block 做什麼」 → answer in plain text\n"
            "  - When the user references **declared inputs** of the current pipeline\n"
            "    (e.g. tool_id, step), pass them through to build_pipeline_live's `goal`\n"
            "    so the sub-agent uses the SAME variable names.\n"
            "  - Pipeline already has declared inputs in its snapshot → DO NOT\n"
            "    re-declare them under a different name. Reuse the exact `$name`.\n"
            "\n"
            "Style: terse, builder-engineer-to-builder-engineer. The PE will see the\n"
            "canvas update live as you call build_pipeline_live; you only need a sentence\n"
            "summarising what changed afterwards.\n"
        )

    # Build initial messages: history + current user message (with prepended state)
    messages = list(history_messages) + [HumanMessage(content=enriched_user_message)]

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


async def _build_current_state_block(java, client_context: Dict[str, Any]) -> str:
    """Fetch agent-context-snapshot from Java + format as <current_state>...</current_state>.

    Returns "" when the snapshot is empty AND there's no client focus — no point
    sending an empty block. Failures are swallowed (logged); chat should still
    work without dynamic context.
    """
    try:
        selected = client_context.get("selected_equipment_id")
        snapshot = await java.get_agent_context_snapshot(selected_equipment_id=selected)
    except Exception as e:  # noqa: BLE001
        logger.warning("agent-context-snapshot fetch failed (%s) — proceeding without dynamic context", e)
        return ""

    alarms = snapshot.get("active_alarms") or []
    user_focus = snapshot.get("user_focus") or {}
    if not alarms and not user_focus:
        return ""

    lines: list[str] = []
    if alarms:
        # Cap to ~10 lines, keep entries terse: "EQP-03 STEP_001 OOC@2h (HIGH)"
        rendered = []
        for a in alarms[:10]:
            eq = a.get("equipment_id") or "?"
            step = a.get("step") or "-"
            sev = (a.get("severity") or "").upper() or "MEDIUM"
            age = a.get("age_seconds") or 0
            age_str = _format_age(int(age))
            title = a.get("title") or ""
            rendered.append(f"  - {eq} {step} active@{age_str} ({sev}){' — ' + title if title else ''}")
        lines.append(f"active_alarms ({len(alarms)}):")
        lines.extend(rendered)
    if user_focus.get("selected_equipment_id"):
        lines.append(f"user_focus: {user_focus['selected_equipment_id']}")

    body = "\n".join(lines)
    as_of = snapshot.get("as_of") or ""
    return f"<current_state ts=\"{as_of}\">\n{body}\n</current_state>"


def _format_age(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"
