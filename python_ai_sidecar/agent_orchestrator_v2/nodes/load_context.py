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

    # 2026-05-04: when the user confirms a design intent card, the frontend
    # now ships the spec via client_context.intent_spec instead of inlining
    # JSON into the user_message text. Re-augment the user_message with a
    # human-readable rendering so the LLM still has the full spec context
    # WITHOUT raw JSON appearing in the chat transcript.
    intent_spec = client_context.pop("intent_spec", None) if isinstance(client_context, dict) else None
    if intent_spec and isinstance(intent_spec, dict) and "[intent_confirmed:" in user_message:
        try:
            inputs_render = "\n".join(
                f"  - ${i.get('name', '?')}"
                + (f" ({i.get('source', 'user_input')})" if i.get('source') else "")
                + (f" — {i.get('rationale', '')}" if i.get('rationale') else "")
                for i in (intent_spec.get("inputs") or [])
            ) or "  (none)"
            spec_block = (
                "\n\n# 已對齊 spec（來自 user 確認的 design intent card）\n"
                f"Inputs（**請用這些 canonical names 給 build_pipeline_live**）:\n{inputs_render}\n"
                f"Logic: {intent_spec.get('logic', '')}\n"
                f"Presentation: {intent_spec.get('presentation', 'mixed_chart_alert')}"
            )
            user_message = user_message + spec_block
        except Exception:  # noqa: BLE001
            # Best-effort augmentation — never block the chat on bad spec.
            pass

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

    # Phase E2/E3: hoisted to top so all downstream sections can branch on it.
    # builder mode = canvas-side prompts (Pipeline Builder); chat mode = default.
    mode = state.get("mode") or "chat"

    # v1.4 — Plan Panel directive (mode-aware).
    # The agent must emit a 3-item plan via update_plan(action="create")
    # BEFORE any other tool call, then update each item as it progresses.
    # Frontend renders this as a live progress checklist above the chat.
    if mode == "builder":
        system_text += (
            "\n\n# Plan-First Execution (Builder Mode)\n"
            "**EVERY new turn**, your **FIRST tool call must be `update_plan`** with\n"
            "`action='create'` and a **3-item** plan focused on pipeline construction:\n"
            "  - p1: 規劃 pipeline 結構（不是「確認需求」— 使用者已經在 canvas 上了）\n"
            "  - p2: 呼叫 build_pipeline_live 建/改\n"
            "  - p3: 收尾 / 短文字 summary\n"
            "\n"
            "Each item: `{id: \"p1\"|\"p2\"|\"p3\", title: \"<short Chinese phrase>\", status: \"pending\"}`.\n"
            "\n"
            "**禁止**：把 p1 mark 為 'done' 並 note 'waiting for user' / '等待使用者' / '需要使用者' —\n"
            "tool_execute 會 mutate 成 error 強制你重來。Builder 模式沒有「等使用者指定值」這個動作，\n"
            "使用者隨時能在 canvas 填值，你只要把 pipeline 結構建好。\n"
        )
    else:
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
    # Skipped in builder mode — that path has its own routing rules below and the
    # "search published skill first / ask user before build" heuristic actively
    # interferes with builder-mode's "build_pipeline_live directly" flow.
    try:
        from python_ai_sidecar.pipeline_builder._sidecar_deps import get_settings
        if get_settings().PIPELINE_ONLY_MODE and mode != "builder":
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
                "2. **Data / analytical** question — by the time you see the message, the\n"
                "   `intent_completeness` graph node has already gated ambiguous requests\n"
                "   (presentation/inputs/logic 不明 → user 看到 design-intent 卡片，這條\n"
                "   訊息根本不會跑到你)，所以**你看到的 user message 已經是規格完整的**。\n"
                "   按下面順序走：\n"
                "     a. Call `search_published_skills(query=<user goal>)` to find existing skills.\n"
                "     b. If a result matches well, call `invoke_published_skill(slug, inputs)`.\n"
                "     c. **If no good match**: 告訴 user「找不到現成 skill，要不要我幫你建一條？」，\n"
                "        等 user 「好/可以/ok」，再 `build_pipeline_live(goal=\"...\")`.\n"
                "     d. 若使用者一開始就明確表達要「建 pipeline / 建新 skill」可直接呼叫\n"
                "        `build_pipeline_live`，不必先 search。\n"
                "\n"
                "   注意：messages 若以 `[intent_confirmed:<id>]` 開頭表示 user 已經從\n"
                "   design-intent 卡片確認過 → **直接 build_pipeline_live**，不要再呼\n"
                "   `confirm_pipeline_intent`（會 loop）。\n"
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
    # 2026-05-11: in builder mode the alarm list is noise that triggers
    # per-machine fan-out — LLM sees "EQP-09 + EQP-03 are alarming" and
    # decides to call build_pipeline_live N times "one per failing tool"
    # even though the user already declared $tool_id as a parameter.
    # Pass mode in so the snapshot only includes user_focus (the user's
    # explicit click signal) in builder mode, not the broadcast alarm list.
    current_state_block = await _build_current_state_block(
        java, client_context, mode=mode,
    )
    enriched_user_message = (
        f"{current_state_block}\n\n{user_message}" if current_state_block else user_message
    )

    # Part B follow-on: teach the agent to USE the snapshot before reaching for
    # tools. Without this, the pipeline-only directive above ("search_published_skills
    # first") wins and the agent burns 7 LLM turns on a question whose answer is
    # already sitting in <current_state>.
    # Skipped in builder mode — there the user's intent is pipeline construction,
    # not status Q&A; this directive's "answer in plain text, do NOT call
    # build_pipeline_live" rule directly contradicts builder-mode's flow.
    if current_state_block and mode != "builder":
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

    # Phase E2/E3: builder-mode section. Overrides Plan-First / Pipeline-Only /
    # Use<current_state> sections above (which are now skipped when mode==builder,
    # but we still spell out the routing here so the LLM has one canonical
    # contract instead of inferring from absence).
    if mode == "builder":
        system_text += (
            "\n\n# Pipeline-Builder Mode (CANONICAL — overrides any earlier directive)\n"
            "User is on a Pipeline Builder canvas with the pipeline open in front of them.\n"
            "Their intent is **almost always pipeline modification / construction**, not Q&A.\n"
            "\n"
            "## ✅ 你只有三個 productive 動作\n"
            "  1. `update_plan` — 維護 3-item 計畫（規劃 / build / 收尾）\n"
            "  2. `confirm_pipeline_intent(...)` — **prompt 模糊時** 先寫下你打算建什麼，等 user 點 ✅ 才繼續\n"
            "  3. `build_pipeline_live(goal=...)` — 委派給 Glass Box sub-agent 建 / 改 pipeline\n"
            "\n"
            "其他 tools（execute_mcp / search_published_skills / invoke_published_skill）\n"
            "**幾乎不會用到** — 不要繞道去查資料或找 skill，直接 build。\n"
            "\n"
            "## 🛑 模糊 prompt 必先 confirm_pipeline_intent，不要直接 build\n"
            "今天 #32 #34 都是「user 問 X，agent 直接建 Y」。Pattern:\n"
            "  - 「請確認該機台最後一次 OOC 的 APC 參數」→ agent 卻建 SPC connect-2-OOC ←❌\n"
            "  - 「分析最近異常」→ agent 自選一個 metric 軸 ←❌\n"
            "\n"
            "判斷模糊（任一條件成立 → 先呼 confirm_pipeline_intent）：\n"
            "  - 含模糊指代：「該機台」「該站」「這個 lot」「最近一次」\n"
            "  - 跨 metric 領域（同時提 SPC + APC + FDC，沒指定要看哪一種）\n"
            "  - 動詞模糊：「分析」「確認」「看看」（沒指定產出什麼）\n"
            "  - 呈現方式不明（沒提 chart / table / alert）\n"
            "\n"
            "判斷具體（直接 build_pipeline_live，不用 confirm）：\n"
            "  - 「把 alert severity 改 HIGH」（精確動作）\n"
            "  - 「檢查 STEP_001 SPC charts 連 2 次 OOC 告警」（精確 input + 規則 + 輸出）\n"
            "  - 「加一張 EQP-01 xbar trend chart」（精確 metric + 圖表）\n"
            "\n"
            "## ✅ User 點完 ✅ 後的 follow-up\n"
            "User confirm 後，他的下一條訊息會帶 prefix `[intent_confirmed:<card_id>]` +\n"
            "原 prompt + 你寫的 spec。看到這 prefix：\n"
            "  - **絕對不要** 再呼 confirm_pipeline_intent（會 loop）\n"
            "  - 直接呼 build_pipeline_live，goal 用 spec 的 logic + inputs 描述\n"
            "  - sub-agent 會把 spec 當主要意圖，按 inputs 宣告 / logic 建結構 / presentation 選 terminal block\n"
            "\n"
            "## ❗ 絕對禁止的 anti-patterns\n"
            "  - ❌ 呼叫 `declare_input` — **這個工具不存在於你的工具表**。declare_input 是\n"
            "    Glass Box sub-agent 的 Glass Op；你不能直接呼叫，要透過 build_pipeline_live\n"
            "    委派。如果使用者用模糊指代（「該站點」「該機台」），把它寫進 goal 裡：\n"
            "    `goal=\"檢查 $step 站點的所有 SPC charts...\"`，sub-agent 會自己 declare $step。\n"
            "  - ❌ Mark plan item 'done' 並 note 「等待使用者...」/「需要使用者...」 —\n"
            "    tool_execute 會把這個 result mutate 成 error 強制重來。Builder 模式裡使用者\n"
            "    隨時能在 canvas 填值，你的工作是把結構建好，不是停下來問。\n"
            "  - ❌ 「找不到現成 skill，要不要建一條？」這種 confirmation —\n"
            "    user 已經在 builder canvas 上，那本身就是 confirmation；直接 build。\n"
            "\n"
            "## Routing examples\n"
            "  | User msg | Action |\n"
            "  |---|---|\n"
            "  | 「加一個 chart」 | build_pipeline_live(goal=\"加一個 ... chart\") |\n"
            "  | 「檢查該站點 SPC，連 2 次 OOC 告警」 | build_pipeline_live(goal=\"檢查 $step 站點所有 SPC charts，連 2 次都 OOC 就告警\") |\n"
            "  | 「換 alert 嚴重度為 HIGH」 | build_pipeline_live(goal=\"把 alert block 的 severity 改 HIGH\") |\n"
            "  | 「為什麼這條 pipeline 失敗」 | 純文字回答，不呼工具 |\n"
            "  | 「WECO R5 是什麼」 | 純文字答（這是 KNOWLEDGE，不要 build） |\n"
            "  Note: 「block_X 怎麼用」/「A vs B」/「我想 X 用哪個 block」**已被 graph-level\n"
            "  advisor classifier 攔截**，不會進到這裡 — 看到這類訊息表示分類失誤，仍以\n"
            "  純文字答案，不要 build。\n"
            "\n"
            "## Plan template（builder 專用，3 items）\n"
            "  - p1: 「規劃 pipeline 結構」（**不是**「確認需求」）\n"
            "  - p2: 「呼叫 build_pipeline_live 建/改」\n"
            "  - p3: 「收尾 / 短文字 summary」\n"
            "\n"
            "## Auto-Run 失敗處理（**最多 1 次 retry**）\n"
            "build_pipeline_live 回 status=success 但**伴隨 pb_run_error**（auto-run 失敗）\n"
            "→ 再呼 1 次 build_pipeline_live，goal 寫成『修正 <nodeX> 的 <param>』描述具體要改的點\n"
            "（sub-agent 會看到既有 canvas 並做 in-place edit，不重建整條）。\n"
            "\n"
            "**只允許 1 次 retry**。若 retry 後仍失敗：\n"
            "  ✅ 改用純文字告訴使用者：「Auto-Run 仍失敗，錯誤：<err 摘要>。\n"
            "     請在 canvas 手動檢查 nodeX 的 ___ 參數」並 stop。\n"
            "  ❌ **不要**再呼第三次 build_pipeline_live、不要 update_plan 後又跑一輪 —\n"
            "     會撞 recursion limit。連兩次都失敗就把問題交回給使用者。\n"
            "\n"
            "## SPC / APC 寬→長 reshape — 看到請優先用專用 block\n"
            "若使用者要「站點所有 SPC charts 連 N 次 OOC」或「任一 APC 參數連續超標」，\n"
            "在 build_pipeline_live 的 goal 裡指明用 `block_spc_long_form` /\n"
            "`block_apc_long_form` 接 `block_consecutive_rule`，**不要**讓 sub-agent\n"
            "用 generic block_unpivot 拼湊 — 那會踩 column naming 坑。\n"
            "\n"
            "Style: terse, builder-engineer-to-builder-engineer. The PE will see the\n"
            "canvas update live as you call build_pipeline_live; you only need a sentence\n"
            "summarising what changed afterwards.\n"
        )

        # Phase E3 follow-up: surface canvas snapshot so the agent reuses
        # already-declared $name references and doesn't invent parallel
        # ones. Mirrors agent_builder/orchestrator.py:142 which does the
        # same thing for direct /agent/build calls.
        snapshot = state.get("pipeline_snapshot") or {}
        declared = snapshot.get("inputs") or []
        nodes = snapshot.get("nodes") or []
        kind = snapshot.get("_kind")  # "auto_patrol" | "auto_check" | "skill" | None
        if kind:
            kind_hints = {
                "auto_patrol": (
                    "## 🔔 Pipeline kind: auto_patrol\n"
                    "  - Inputs typically `event_payload` (event-mode 從 OOC event 帶 equipment_id/step/lot_id)\n"
                    "    或 `user_input` (schedule/once 模式由使用者填入)\n"
                    "  - 不要把 input 標成 user_input 如果 trigger_mode=event — runtime 會從 event payload 帶。\n"
                ),
                "auto_check": (
                    "## 🔬 Pipeline kind: auto_check\n"
                    "  - 這條 pipeline 是用來**接收 alarm**做進一步診斷的。\n"
                    "  - Inputs 幾乎全部是 `event_payload`（從 alarm payload 自動帶入：\n"
                    "    equipment_id / lot_id / step / event_time / trigger_event / severity）。\n"
                    "  - **不要** 把 equipment_id/step 等標成 `user_input` — runtime 是 alarm 自動帶的。\n"
                    "  - 不會自己生 alarm（無 block_alert），只是分析給 user 看。\n"
                ),
                "skill": (
                    "## 📚 Pipeline kind: skill\n"
                    "  - 給 Agent / 使用者依需求呼叫的可重用 pipeline。\n"
                    "  - Inputs 通常是 `user_input` (Agent / 使用者每次呼叫時填)。\n"
                ),
                # Phase 11 v6 — skill_step is a CONFIRM or CHECKLIST step inside a
                # Skill Document. The terminator MUST be block_step_check (not
                # block_chart, not block_alert) so SkillRunner can read the
                # pass/fail verdict. Inputs come from the parent skill's
                # trigger payload (see seedInputsFromCtx in SkillEmbedBanner.tsx).
                "skill_step": (
                    "## 🩺 Pipeline kind: skill_step (CONFIRM / CHECKLIST)\n"
                    "  - 這是一個 Skill Document 的 confirm / checklist step。\n"
                    "  - **🛠 MANDATORY ACTION**: 你的下一步是**呼叫 `build_pipeline_live` tool**。\n"
                    "    不要只用文字描述 plan、不要列出 1./2./3. block 清單給 user 看；\n"
                    "    user 不需要看 plan，他要的是 canvas 上長出 pipeline。立刻 invoke tool。\n"
                    "  - **🛑 FORBIDDEN**: 不要呼 `confirm_pipeline_intent`（user 已從 Skill 頁面按 Build\n"
                    "    才開到 Builder，意圖無模糊；再 confirm 一次是多餘 friction）。\n"
                    "  - **Terminator MUST be block_step_check** — 不可用 block_chart / block_alert。\n"
                    "    block_step_check 會 emit { pass: bool, value, note } 給 SkillRunner 讀。\n"
                    "  - Inputs 來自 Skill 的 trigger payload — 已 seeded 在 canvas inputs 裡，\n"
                    "    **禁** 自創 input；source / filter block 必用 $name 引用。\n"
                ),
            }
            if kind in kind_hints:
                system_text += "\n" + kind_hints[kind]

        if declared or nodes:
            lines: list[str] = []
            if declared:
                lines.append("\n## 當前 canvas 已宣告的 inputs（**MUST 用這些 $name 引用**）")
                for inp in declared:
                    if not isinstance(inp, dict):
                        continue
                    name = inp.get("name")
                    if not name:
                        continue
                    typ = inp.get("type") or "string"
                    req = "required" if inp.get("required") else "optional"
                    desc = inp.get("description") or ""
                    ex = inp.get("example") or inp.get("default")
                    extra = (f" — example: {ex}" if ex else "") + (f" — {desc}" if desc else "")
                    lines.append(f"  - $`{name}` ({typ}, {req}){extra}")
                lines.append(
                    "  ⚠ 凡 source / filter block 的 param 對應上述 input（如 tool_id、step），\n"
                    "    **必寫 `$name`、禁寫字面值；禁止用同義詞另開**（例如 list 列了\n"
                    "    `$tool_id`，**不要**自己 declare `equipment_id` 然後寫 `$equipment_id`，\n"
                    "    那會跟既有 input 對不上、Auto-Patrol fan-out / Auto-Run 都會失敗）。"
                )
            if nodes:
                node_count = len(nodes)
                terminal_kinds = sorted({
                    n.get("block_id", "") for n in nodes if isinstance(n, dict)
                    and n.get("block_id") in ("block_alert", "block_chart", "block_data_view")
                })
                lines.append(
                    f"\n## 當前 canvas 已有 {node_count} 個 nodes" +
                    (f"（含 {', '.join(terminal_kinds)}）" if terminal_kinds else "") +
                    "。修改既有結構優先於整個重建。"
                )
            system_text += "\n" + "\n".join(lines) + "\n"

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


async def _build_current_state_block(
    java, client_context: Dict[str, Any], mode: str = "chat",
) -> str:
    """Fetch agent-context-snapshot from Java + format as <current_state>...</current_state>.

    Returns "" when the snapshot is empty AND there's no client focus — no point
    sending an empty block. Failures are swallowed (logged); chat should still
    work without dynamic context.

    2026-05-11: in builder mode (`mode="builder"`), the broadcast `active_alarms`
    list is suppressed. It was causing the LLM to fan-out per-failing-tool
    ("user wants SPC trend skill + EQP-09/EQP-03 are alarming → build 2 skills")
    when the user already declared `$tool_id` as a pipeline parameter. The
    user_focus line is still emitted because that represents the user's
    *explicit* click on a specific machine (not background noise).
    """
    try:
        selected = client_context.get("selected_equipment_id")
        snapshot = await java.get_agent_context_snapshot(selected_equipment_id=selected)
    except Exception as e:  # noqa: BLE001
        logger.warning("agent-context-snapshot fetch failed (%s) — proceeding without dynamic context", e)
        return ""

    alarms = snapshot.get("active_alarms") or []
    user_focus = snapshot.get("user_focus") or {}
    is_builder = (mode == "builder")
    # In builder mode, drop the alarm list entirely (noise) but keep user_focus.
    if is_builder:
        alarms = []

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
