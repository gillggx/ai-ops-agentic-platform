"""Conversation-first chat agent (Step 1 of CHAT_AGENT_LOOP_SPEC, 2026-07-09).

The current chat is a rigid classifier → graph dispatcher: every utterance is
forced into 4 buckets, and anything that doesn't fit ("你能做什麼" / "你不能
聊天") falls into a逼選 clarify card. It's a窗口 that can't just talk.

This is the standard agent shape instead (like cowork / Claude Code): ONE
Anthropic tool-use loop. The model sees the whole conversation + a persona +
well-described tools, and at each step decides — reply naturally OR call a
tool. No classifier, no graph, no forced cards.

Step 1 scope (this file): natural conversation + READ-ONLY tools only
(status / skill search / knowledge). The heavy tools (build_pipeline wrapping
the untouched Planner&Builder, modify, automation) arrive in Step 2 — the
spec builds conversation first so we can judge dialogue quality in isolation.

Gated by CHAT_AGENT_LOOP_ENABLED so it never touches prod until we flip it.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, AsyncIterator, Dict, List

from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client

logger = logging.getLogger("python_ai_sidecar.agent_orchestrator_v2.chat_agent_loop")

MAX_TOOL_ROUNDS = 6

# Phase 6: capabilities IT admin has granted the Coordinator (是_internal +
# coordinator-eligible), fetched from Java + cached briefly. The Coordinator
# loads these ON TOP of its curated core tools. Only Coordinator-appropriate
# capabilities are offerable 對內 (Java enforces eligibility), so this can never
# hand it a pipeline-construction primitive that would bypass Planner & Builder.
_granted_cache: dict = {"tools": [], "at": 0.0}
_GRANTED_TTL = 30.0


async def _granted_agent_tools(java: Any) -> List[Dict[str, Any]]:
    import time
    now = time.monotonic()
    if _granted_cache["at"] > 0 and now - _granted_cache["at"] < _GRANTED_TTL:
        return _granted_cache["tools"]
    try:
        data = await java._get_data("/internal/mcp-capabilities/agent-tools")
        _granted_cache["tools"] = data if isinstance(data, list) else []
        _granted_cache["at"] = now
    except Exception as ex:  # noqa: BLE001 — fail-soft (keep core tools)
        logger.warning("granted agent-tools fetch failed: %s", ex)
    return _granted_cache["tools"]


def is_chat_agent_loop_enabled() -> bool:
    return os.environ.get("CHAT_AGENT_LOOP_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")


_SYSTEM = """你是「AIOps 操作助理」，幫半導體製程的工程師 / 當班人員在這個平台上做事。
講繁體中文，專業、精準、直指核心，不說多餘客套。
**全程禁用 emoji 與類 emoji 符號**（⚠️/✅/❌/🔴 等都不行）；要標重點用文字如
[重要]/[HIGH]/[note] 或粗體、表格。

你能幫的事（需要「動作」時才用對應工具；工具沒涵蓋的先老實說）：
- 查目前的告警與機台現況（get_current_status）
- 找平台上現成的分析 Skill（search_skills）
- 建一張新的 SPC / 趨勢 / 統計圖（build_pipeline）
- 調整「目前畫面上這張圖」：拿掉區帶、加 tooltip、換機台、線改虛線…（modify_current_chart）
- 把目前這張圖設成自動執行 / 巡檢 / 告警（setup_automation，會帶去設定頁）

怎麼跟人互動（重要）：
- 直接自然講話。可以閒聊、可以解釋、可以回答「你能幫我做什麼」——用人話講清楚，
  **絕對不要**丟制式選單卡逼使用者選。
- 判斷清楚再用工具：要「建新圖」用 plan_pipeline；要「改現在這張」用
  modify_current_chart（畫面上沒圖就先建）；只是查 / 問則用查詢工具或直接回答。
- 建新圖的標準流程：呼叫 plan_pipeline → 它會在對話裡秀一張『計畫卡』（P1..PN +
  確認/修改/取消按鈕）→ 使用者在卡片上按確認，就會自動開始建圖。你**不需要**再呼叫
  build_pipeline，也**不要**用文字重列步驟（卡片自己會顯示）。呼叫 plan_pipeline 後
  只回一句「計畫在上面了，確認後就開始建」即可。
- 只有使用者明講「直接建 / 不用給我看計畫」時，才用 build_pipeline 跳過計畫卡。
- 建圖過程會花幾十秒，系統會顯示 Planner / Builder / Director 正在做什麼。
- 不確定使用者要什麼時，用**一句話**問清楚即可，不要硬猜、也不要一次丟一堆問題。
- 使用者問候 / 問你是誰 / 問能力 → 自然回答，不要當成分析請求。
- 顏色（線色 / 背景）不是我能改的參數；使用者要改色 → 請他用圖右上角的 STYLE 面板。"""


_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "get_current_status",
        "description": "查目前的告警與機台現況：有哪些 active alarm、嚴重度、哪台機台。"
                       "使用者問「現在狀況 / 有什麼告警 / 哪台機台有問題 / 最近怎樣」時用。",
        "input_schema": {"type": "object", "properties": {
            "equipment_id": {"type": "string", "description": "只看某台機台（可省略，省略=全部）"}
        }},
    },
    {
        "name": "search_skills",
        "description": "用關鍵字找平台上現成的分析 Skill（pipeline）。使用者想做某分析、"
                       "或問「有沒有現成的…」時，先用這個找有沒有可用的。",
        "input_schema": {"type": "object", "properties": {
            "query": {"type": "string", "description": "要找的分析主題，如「OOC 排名」「SPC 趨勢」"}
        }, "required": ["query"]},
    },
    {
        "name": "plan_pipeline",
        "description": "使用者要建一張新的圖 / pipeline 時，**用這個**（這是標準做法）。"
                       "它會規劃步驟並在對話裡顯示一張『計畫卡』（列出 P1..PN + 確認/修改/取消按鈕），"
                       "使用者在卡片上按確認就會自動開始建圖——你不需要、也不應該再呼叫 build_pipeline。"
                       "呼叫後只要回一句『計畫在上面了，確認後就開始建』，不要用文字重列步驟。",
        "input_schema": {"type": "object", "properties": {
            "instruction": {"type": "string", "description": "要建什麼的完整自然語言需求"}
        }, "required": ["instruction"]},
    },
    {
        "name": "build_pipeline",
        "description": "**只有**在使用者明確說『直接建 / 不用給我看計畫 / 別問我』時才用這個——"
                       "它會跳過計畫卡直接建圖。正常情況一律用 plan_pipeline（讓使用者先看到計畫卡）。",
        "input_schema": {"type": "object", "properties": {
            "instruction": {"type": "string", "description": "要建什麼的完整自然語言需求"}
        }, "required": ["instruction"]},
    },
    {
        "name": "modify_current_chart",
        "description": "調整「目前畫面上這張圖」時用（例：拿掉區帶、加 tooltip 顯示 lotID、"
                       "換成看 EQP-05、線改虛線）。只在對話中已經有一張圖時能用。",
        "input_schema": {"type": "object", "properties": {
            "instruction": {"type": "string", "description": "要怎麼調的自然語言，如「拿掉區帶」"}
        }, "required": ["instruction"]},
    },
    {
        "name": "setup_automation",
        "description": "使用者要把目前這張圖設成自動執行（定時巡檢 / 定期檢查 / 告警）時用。"
                       "我不會在對話裡直接設定，而是把它存成 Skill 並帶使用者去設定頁。",
        "input_schema": {"type": "object", "properties": {}},
    },
]


async def _run_tool(name: str, inp: Dict[str, Any], ctx: Dict[str, Any]) -> AsyncIterator[tuple]:
    """Every tool is a generator yielding ('event', <sse>) for the frontend and
    exactly one ('result', <value>) the model reads. Fail-soft: any error
    yields a result the model can relay, never crashes the loop."""
    java = ctx["java"]
    try:
        # ── read-only ──────────────────────────────────────────────
        if name == "get_current_status":
            snap = await java.get_agent_context_snapshot(
                selected_equipment_id=inp.get("equipment_id") or None)
            yield ("result", {"active_alarms": (snap or {}).get("active_alarms") or [],
                              "user_focus": (snap or {}).get("user_focus") or {},
                              "as_of": (snap or {}).get("as_of")})
            return
        if name == "search_skills":
            skills = await java.search_published_skills(str(inp.get("query") or ""), top_k=5)
            yield ("result", [{"slug": s.get("slug"), "name": s.get("name"),
                              "sub": s.get("sub"), "role": s.get("role")} for s in (skills or [])])
            return

        # ── plan_pipeline — run the Planner (原本 goal_plan) to the confirm
        #    gate, then emit the ORIGINAL `pb_plan_confirm` draft card + register
        #    the pending exactly like the native chat build tool. The user
        #    confirms on that card (decidePlan → /chat/intent-respond) which
        #    resumes the paused build — reusing the WHOLE original single-card
        #    lifecycle (草案 → 建構中 → 完成). We do NOT re-list the plan as prose. ──
        if name == "plan_pipeline":
            from python_ai_sidecar.agent_builder.graph_build.runner import stream_graph_build
            from python_ai_sidecar.agent_orchestrator_v2 import pending_clarify as _pc
            instr = str(inp.get("instruction") or "")
            chat_sid = str(ctx["session_id"])
            bsid = f"build-{chat_sid}"
            yield ("event", {"type": "role_marker", "role": "Planner", "text": "規劃中…"})
            plan_pause: Dict[str, Any] | None = None
            async for ev in stream_graph_build(instruction=instr, skip_confirm=False,
                                               user_id=ctx["user_id"], session_id=bsid):
                if ev.type == "goal_plan_confirm_required":
                    plan_pause = ev.data or {}
            if not plan_pause or not (plan_pause.get("phases")):
                yield ("result", {"status": "no_plan",
                                  "message": "沒規劃出計畫，需求可能要更具體（機台 / 站點 / 要看什麼指標）。"})
                return
            build_session = str(plan_pause.get("session_id") or bsid)
            # Register the pending so /chat/intent-respond (plan_decision) can
            # resume this exact paused build thread — same store the native path uses.
            try:
                _pc.register(_pc.PendingClarify(
                    chat_session_id=chat_sid,
                    build_session_id=build_session,
                    bullets=[],
                    instruction=instr,
                    base_pipeline=None,
                    skill_step_mode=False,
                    user_id=ctx["user_id"],
                    kind="plan_confirm",
                    phases=plan_pause.get("phases") or [],
                    plan_summary=str(plan_pause.get("plan_summary") or ""),
                ))
            except Exception as ex:  # noqa: BLE001
                logger.warning("plan_pipeline: pending register failed: %s", ex)
            # Emit the ORIGINAL plan-confirm card (frontend `case pb_plan_confirm`).
            yield ("event", {
                "type": "pb_plan_confirm",
                "session_id": chat_sid,
                "build_session_id": build_session,
                "plan_summary": plan_pause.get("plan_summary") or "",
                "phases": plan_pause.get("phases") or [],
                "removals": plan_pause.get("removals") or [],
            })
            n = len(plan_pause.get("phases") or [])
            yield ("result", {
                "status": "plan_confirm_pending", "n_phases": n,
                "note": "計畫卡（含 P1..PN 與 確認/修改/取消 按鈕）已顯示給使用者。"
                        "只回一句『計畫在上面了，確認後我就開始建』即可，"
                        "**不要**用文字重列步驟（卡片自己會顯示）。",
            })
            return

        # ── build_pipeline — direct build WITHOUT a plan card (使用者說「直接建 /
        #    不用看計畫」時才用). Normal flow is plan_pipeline → 卡片確認 → resume;
        #    this is the skip-the-plan shortcut. Wraps the UNCHANGED Builder. ──
        if name == "build_pipeline":
            from python_ai_sidecar.agent_builder.graph_build.runner import stream_graph_build
            from python_ai_sidecar.executor.real_executor import execute_native
            instr = str(inp.get("instruction") or "")
            bsid = f"build-{ctx['session_id']}-direct"
            yield ("event", {"type": "role_marker", "role": "Builder", "text": "建置中…"})
            gen = stream_graph_build(instruction=instr, skip_confirm=True,
                                     user_id=ctx["user_id"], session_id=bsid)
            final = None
            async for ev in gen:
                if ev.type == "phase_completed":
                    yield ("event", {"type": "role_marker", "role": "Builder",
                                     "text": str((ev.data or {}).get("rationale") or "建置中")})
                elif ev.type in ("plan_patched", "build_postmortem"):
                    yield ("event", {"type": "role_marker", "role": "Director",
                                     "text": "卡住了，重新調整計畫再建…"})
                elif ev.type == "done":
                    final = (ev.data or {}).get("pipeline_json") or final
            if not final or not (final.get("nodes")):
                yield ("result", {"status": "failed",
                                  "message": "這次沒建出可用的圖，可能卡在某一步。要不要換個說法或縮小範圍再試？"})
                return
            try:
                res = await execute_native(final)
                node_results = res.get("node_results") or {}
                result_summary = res.get("result_summary")
            except Exception:  # noqa: BLE001
                node_results, result_summary = {}, None
            yield ("event", {"type": "tool_done", "tool": "build_pipeline",
                             "render_card": {"type": "pb_pipeline", "pipeline_json": final,
                                             "node_results": node_results,
                                             "result_summary": result_summary, "run_id": None}})
            n = len(final.get("nodes") or [])
            yield ("event", {"type": "role_marker", "role": "Director", "text": "建好了"})
            yield ("result", {"status": "success", "nodes": n,
                              "message": f"建好了，{n} 個節點，圖已顯示在對話裡。"})
            return

        # ── modify_current_chart — the modify-mode delta on the on-screen图 ──
        if name == "modify_current_chart":
            snap = ctx.get("pipeline_snapshot")
            if not isinstance(snap, dict) or not (snap.get("nodes") or []):
                yield ("result", {"status": "no_pipeline",
                                  "message": "目前畫面上沒有可調整的圖，先請使用者建一張。"})
                return
            from python_ai_sidecar.agent_orchestrator_v2.nodes.modify_pipeline import run_modify
            state = {"pipeline_snapshot": snap, "pipeline_columns": ctx.get("pipeline_columns"),
                     "user_message": str(inp.get("instruction") or ""),
                     "session_id": ctx["session_id"], "user_id": ctx["user_id"]}
            out = await run_modify(state, snap, "presentation_change", "", str(inp.get("instruction") or ""))
            if out is None:
                yield ("result", {"status": "cant",
                                  "message": "這個調整用微調做不到（可能要重建或不支援），跟使用者說明。"})
                return
            cards = out.get("render_cards") or []
            if cards:
                yield ("event", {"type": "tool_done", "tool": "modify_current_chart", "render_card": cards[0]})
            msgs = out.get("messages") or []
            text = msgs[0].content if msgs else "已調整。"
            yield ("result", {"status": "ok", "message": str(text)})
            return

        # ── setup_automation — hand off to /skills/[slug]/automate ──
        if name == "setup_automation":
            snap = ctx.get("pipeline_snapshot")
            if not isinstance(snap, dict) or not (snap.get("nodes") or []):
                yield ("result", {"status": "no_pipeline",
                                  "message": "目前畫面上沒有圖可以設自動化，先建一張。"})
                return
            yield ("event", {"type": "tool_done", "tool": "setup_automation",
                             "render_card": {"type": "automation_handoff", "pipeline_json": snap}})
            yield ("result", {"status": "handoff",
                              "message": "已開一張卡帶使用者去自動化設定頁（跟 Skill 庫一致），不用在對話裡填設定。"})
            return

        # ── invoke_skill (Phase 6) — run a granted domain skill's pipeline ──
        if name == "invoke_skill":
            slug = str(inp.get("slug") or "")
            if slug not in (ctx.get("granted_skills") or set()):
                yield ("result", {"status": "not_allowed",
                                  "message": f"skill「{slug}」沒有授權給我；我只能跑管理員開放對內的 skill。"})
                return
            from python_ai_sidecar.executor.real_executor import execute_native
            skills = await java.search_published_skills(slug, top_k=8)
            match = next((s for s in (skills or []) if s.get("slug") == slug), None)
            pid = (match or {}).get("pipeline_id")
            if not pid:
                yield ("result", {"status": "no_pipeline",
                                  "message": f"找不到 skill「{slug}」綁定的 pipeline。"})
                return
            pipe = await java.get_pipeline(int(pid))
            pj = (pipe or {}).get("pipeline_json") or pipe
            if not isinstance(pj, dict) or not (pj.get("nodes")):
                yield ("result", {"status": "no_pipeline", "message": f"skill「{slug}」的 pipeline 不完整。"})
                return
            try:
                res = await execute_native(pj)
                node_results = res.get("node_results") or {}
                result_summary = res.get("result_summary")
            except Exception:  # noqa: BLE001
                node_results, result_summary = {}, None
            yield ("event", {"type": "tool_done", "tool": "invoke_skill",
                             "render_card": {"type": "pb_pipeline", "pipeline_json": pj,
                                             "node_results": node_results,
                                             "result_summary": result_summary, "run_id": None}})
            yield ("result", {"status": "success",
                              "message": f"已跑現成 skill「{(match or {}).get('name') or slug}」，結果顯示在對話裡。"})
            return

        yield ("result", {"error": f"unknown tool {name}"})
    except Exception as ex:  # noqa: BLE001 — fail-soft
        logger.warning("chat tool %s failed: %s", name, ex)
        yield ("result", {"error": f"工具 {name} 執行失敗：{str(ex)[:150]}"})


async def run_chat_agent(
    *, message: str, history: List[Dict[str, Any]], java: Any, user_id: int,
    session_id: str = "", pipeline_snapshot: Dict[str, Any] | None = None,
    pipeline_columns: Dict[str, Any] | None = None,
) -> AsyncIterator[Dict[str, Any]]:
    """Anthropic tool-use loop. Yields v1-style SSE events; a tool may stream
    its own events (e.g. a pb_pipeline card) before returning its result. The
    final assistant text is a `synthesis` event (same contract the orchestrator
    uses)."""
    client = get_llm_client()
    ctx = {"java": java, "user_id": user_id, "session_id": session_id or "chat",
           "pipeline_snapshot": pipeline_snapshot, "pipeline_columns": pipeline_columns}
    messages: List[Dict[str, Any]] = list(history) + [{"role": "user", "content": message}]

    # Make the model AWARE of the on-screen pipeline — without this it doesn't
    # know a chart exists, so「設自動化」/「改一下」get a "先建一張" instead of a
    # modify/automation tool call.
    system = _SYSTEM
    if isinstance(pipeline_snapshot, dict) and (pipeline_snapshot.get("nodes") or []):
        blocks = [n.get("block_id") for n in pipeline_snapshot["nodes"]]
        system = (_SYSTEM + "\n\n[目前狀態] 畫面上已經有一張建好的圖（節點："
                  + " → ".join(str(b) for b in blocks)
                  + "）。使用者說「改 / 拿掉 / 換 / 加」多半是要調它（用 modify_current_chart）；"
                  "說「設自動化 / 巡檢 / 定期跑」是要對它設自動化（用 setup_automation）；"
                  "不用再問「有沒有圖」。")

    # Phase 6: extend the toolset with capabilities IT admin granted 對內. First
    # cut wires domain skills (跑現成 skill). The build primitives are never
    # eligible, so this never lets the Coordinator bypass Planner & Builder.
    tools = list(_TOOLS)
    granted = await _granted_agent_tools(java)
    granted_skills = {g["key"]: g.get("name") or g["key"]
                      for g in granted if g.get("kind") == "domain_skill" and g.get("key")}
    ctx["granted_skills"] = set(granted_skills)
    if granted_skills:
        catalog = "、".join(f"{k}（{v}）" for k, v in list(granted_skills.items())[:20])
        tools.append({
            "name": "invoke_skill",
            "description": "直接執行一個現成的 domain skill（分析 pipeline）並回傳結果——用在"
                           "使用者想「用現成的 X 來看/跑」而不是重新建圖時。只能跑這些已授權的："
                           + catalog + "。參數 slug。",
            "input_schema": {"type": "object", "properties": {
                "slug": {"type": "string", "description": "要跑的 skill slug（必須在授權清單內）"}
            }, "required": ["slug"]},
        })

    for _round in range(MAX_TOOL_ROUNDS):
        resp = await client.create(system=system, messages=messages,
                                   tools=tools, max_tokens=1500)
        messages.append({"role": "assistant", "content": resp.content or [{"type": "text", "text": resp.text}]})
        tool_uses = [b for b in (resp.content or [])
                     if isinstance(b, dict) and b.get("type") == "tool_use"]
        if not tool_uses:
            yield {"type": "synthesis", "text": resp.text or ""}
            return
        results: List[Dict[str, Any]] = []
        for tu in tool_uses:
            logger.info("chat agent tool: %s(%s)", tu.get("name"),
                        json.dumps(tu.get("input") or {}, ensure_ascii=False)[:100])
            result_val: Any = {"error": "tool produced no result"}
            async for kind, payload in _run_tool(str(tu.get("name")), tu.get("input") or {}, ctx):
                if kind == "event":
                    yield payload            # relay to frontend (cards / progress)
                elif kind == "result":
                    result_val = payload     # what the model reads
            results.append({"type": "tool_result", "tool_use_id": tu.get("id"),
                            "content": json.dumps(result_val, ensure_ascii=False, default=str)})
        messages.append({"role": "user", "content": results})

    yield {"type": "synthesis", "text": "（我想太久了，先講到這；你可以再說清楚一點我幫你查。）"}
