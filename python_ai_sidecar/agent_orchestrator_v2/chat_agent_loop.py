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

# Coordinator-eligible built-in READ tools the sidecar knows how to dispatch
# (each proxies to a /internal endpoint the sidecar can reach with its token).
# Only added to the Coordinator's toolset when IT admin grants them 對內.
_BUILTIN_READ: Dict[str, Dict[str, Any]] = {
    "list_alarms": {
        "desc": "查全廠告警「現況」：active alarm clusters + KPIs。使用者問「現在有什麼告警 / 廠區狀況」時用。"
                "要查歷史或處理狀況用 query_alarms。",
        "path": "/internal/alarms/situation", "args": {}},
    "get_alarm_detail": {
        "desc": "查單一告警的完整診斷（AI 綜整 + trigger + evidence）。參數 alarm_id（從 list_alarms / query_alarms 拿）。",
        "path": "/internal/alarms/{alarm_id}",
        "args": {"alarm_id": {"type": "integer", "description": "告警 id"}}},
    # Alarm 處理能力包 (2026-07-10) — history + handling-state reads.
    "query_alarms": {
        "desc": "查告警「歷史 + 處理狀況」：可依機台 / 期間 / 狀態 / 嚴重度過濾。"
                "每筆含 status(active|acknowledged|resolved)、acknowledged_by、"
                "disposition(release|hold|scrap|rerun)、disposition_reason。"
                "使用者問「EQP-07 過去有哪些告警、處理到哪了」時用；回覆用 markdown 表格整理重點。",
        "path": "/internal/alarms/query", "query": True, "required": [],
        "args": {"equipment_id": {"type": "string", "description": "機台 id，如 EQP-07（省略=全部）"},
                 "since_hours": {"type": "integer", "description": "往回看幾小時（預設 168 = 7 天）"},
                 "status": {"type": "string", "description": "active(未認領) | acknowledged | resolved（省略=全部）"},
                 "severity": {"type": "string", "description": "critical | high | medium | low（省略=全部）"},
                 "limit": {"type": "integer", "description": "最多幾筆（預設 50）"}}},
    "get_alarm_stats": {
        "desc": "告警處理統計：total、by_equipment（哪台最多）、by_status、by_severity、acked、disposed、ack_rate。"
                "使用者問「處理狀況如何 / 哪台告警最多 / 最常 OOC 的機台」時先用這個。",
        "path": "/internal/alarms/stats", "query": True, "required": [],
        "args": {"since_hours": {"type": "integer", "description": "往回看幾小時（預設 168 = 7 天）"}}},
    "list_agent_knowledge": {
        "desc": "列出目前生效的 knowledge / directives——使用者交代過的規則、偏好都在這。"
                "使用者問「我跟你說過什麼 / 有哪些 rules」時用。",
        "path": "/internal/agent-knowledge/directives/active?user_id={user_id}", "args": {}},
    "list_supervisor_proposals": {
        "desc": "列 Supervisor 待人審核的策展提案（prune / promote / merge / correct）。核准在 /supervisor 頁做。",
        "path": "/internal/supervisor/proposals-open", "args": {}},
    # Domain-Skill / activity reads (2026-07-10 — 修「有哪些 domain skills 一問
    # 就倒」: keys 已授權但 dispatch 缺席). Paths delegate to Java internal.
    "list_skills_v2": {
        "desc": "列出全部 Domain Skill（含草稿）：slug、名稱、狀態(active/draft)、角色(tool/patrol/datacheck)、"
                "有無 alarm 判斷式。使用者問「有哪些 domain skills / skill 清單」時用。",
        "path": "/internal/skills-v2", "args": {}},
    "get_skill_v2": {
        "desc": "單一 Domain Skill 的完整資訊（描述、pipeline、自動化設定）。參數 slug。",
        "path": "/internal/skills-v2/{slug}",
        "args": {"slug": {"type": "string", "description": "skill 的 slug"}}},
    "check_skill_ready_for_role": {
        "desc": "查某 Domain Skill 能否升某角色（patrol 需要 alarm 判斷式）。參數 slug + role(tool|patrol|datacheck)。"
                "設自動化前先查，能提前告訴使用者會不會被擋。",
        "path": "/internal/skills-v2/{slug}/role-readiness?role={role}",
        "args": {"slug": {"type": "string", "description": "skill slug"},
                 "role": {"type": "string", "description": "tool | patrol | datacheck"}}},
    "list_event_sources": {
        "desc": "列出可作為事件觸發來源的 Skill（active patrol 且有 alarm 判斷式）。設 event-driven 自動化時用。",
        "path": "/internal/skills-v2/alarm-sources", "args": {}},
    "list_agent_activity": {
        "desc": "平台 agent 最近的建置活動（episodes）：誰觸發、結果、成本。使用者問「agent 最近做了什麼」時用。",
        "path": "/internal/agent-episodes?limit=20", "args": {}},
    "get_agent_activity": {
        "desc": "單一 episode 的完整過程（steps、divergence、成本）。參數 episode_key（從 list_agent_activity 拿）。",
        "path": "/internal/agent-episodes/{episode_key}",
        "args": {"episode_key": {"type": "string", "description": "episode key"}}},
}

# Alarm handling WRITES (2026-07-10). The agent NEVER executes these — each
# emits an `alarm_action_confirm` card and the browser performs the POST under
# the user's JWT after they press 確認 (role gates, e.g. resolve=ADMIN/PE,
# apply as the user's own). Granted 對內 like the reads.
_ALARM_WRITES: Dict[str, Dict[str, Any]] = {
    "ack_alarm": {
        "desc": "認領告警：單筆（alarm_id）或整台機台的 cluster（equipment_id，二擇一）。"
                "會出確認卡，使用者按確認才執行。批次認領前先用 query_alarms 列給使用者看。",
        "args": {"alarm_id": {"type": "integer", "description": "要認領的告警 id"},
                 "equipment_id": {"type": "string", "description": "整台機台一次認領（cluster ack）"}},
        "required": []},
    "dispose_alarm": {
        "desc": "對告警下處置並結案：disposition ∈ release | hold | scrap | rerun + 原因。"
                "**不可逆**（尤其 scrap）——先用 get_alarm_detail 看過 evidence、跟使用者確認原因後才提出；確認卡按了才執行。",
        "args": {"alarm_id": {"type": "integer", "description": "告警 id"},
                 "disposition": {"type": "string", "description": "release | hold | scrap | rerun"},
                 "reason": {"type": "string", "description": "處置原因（會寫入記錄）"}},
        "required": ["alarm_id", "disposition"]},
    "resolve_alarm": {
        "desc": "單純結案（不下處置）。需要 ADMIN / PE 權限（以使用者本人身分執行）。確認卡按了才執行。",
        "args": {"alarm_id": {"type": "integer", "description": "告警 id"}},
        "required": ["alarm_id"]},
}


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


# 標準 Skill index (V82, 2026-07-10): name + when_to_use lines injected into
# the system prompt; the FULL manual is fetched via load_skill only when the
# request matches — progressive disclosure, the manual is DB data not code.
_skill_index_cache: dict = {"rows": [], "at": 0.0}


async def _standard_skill_index(java: Any) -> List[Dict[str, Any]]:
    import time
    now = time.monotonic()
    if _skill_index_cache["at"] > 0 and now - _skill_index_cache["at"] < _GRANTED_TTL:
        return _skill_index_cache["rows"]
    try:
        data = await java._get_data("/internal/agent-skills/index")
        _skill_index_cache["rows"] = data if isinstance(data, list) else []
        _skill_index_cache["at"] = now
    except Exception as ex:  # noqa: BLE001 — fail-soft (no index, tools still work)
        logger.warning("standard skill index fetch failed: %s", ex)
    return _skill_index_cache["rows"]


async def _call_system_mcp(java: Any, mcp_name: str, args: Dict[str, Any]) -> Any:
    """Call a granted external System MCP by name (re-enabled 2026-07-10 per
    決策: 有標準 Skill 說明書的 System MCP 可直接呼叫). Mirrors block_mcp_call's
    dispatch: resolve api_config from Java, issue the HTTP call with `args`."""
    import httpx
    mcp = await java.get_mcp_by_name(mcp_name)
    if not mcp:
        return {"error": f"MCP '{mcp_name}' 未註冊"}
    raw = mcp.get("api_config") or mcp.get("apiConfig") or "{}"
    cfg = json.loads(raw) if isinstance(raw, str) else raw
    url = cfg.get("endpoint_url")
    method = (cfg.get("method") or "GET").upper()
    headers = cfg.get("headers") or {}
    try:
        from python_ai_sidecar.pipeline_builder.blocks._http_helpers import resolve_headers
        headers = resolve_headers(headers, mcp_name=mcp_name)
    except Exception:  # noqa: BLE001 — headers as-is if helper/env missing
        pass
    if not url:
        return {"error": f"MCP '{mcp_name}' 沒有 endpoint_url"}
    async with httpx.AsyncClient(timeout=30) as c:
        r = await (c.get(url, params=args, headers=headers) if method == "GET"
                   else c.post(url, json=args, headers=headers))
        r.raise_for_status()
        return r.json() if r.content else {}


def _mcp_param_doc(schema: Any) -> str:
    """Render a System MCP's input_schema into a short param hint for the tool
    description. Tolerates both a list of param defs and a JSON-schema dict."""
    if isinstance(schema, str):
        try:
            schema = json.loads(schema)
        except (ValueError, TypeError):
            return ""
    items = []
    if isinstance(schema, list):
        for p in schema:
            if isinstance(p, dict) and p.get("name"):
                req = "必填" if p.get("required") else "選填"
                items.append(f"{p['name']}({p.get('type', 'str')},{req}) {p.get('description', '')}".strip())
    elif isinstance(schema, dict):
        props = schema.get("properties") or {}
        req = set(schema.get("required") or [])
        for k, v in props.items():
            r = "必填" if k in req else "選填"
            d = (v or {}).get("description", "") if isinstance(v, dict) else ""
            items.append(f"{k}({(v or {}).get('type', 'str') if isinstance(v, dict) else 'str'},{r}) {d}".strip())
    return "；".join(items[:12])


def is_chat_agent_loop_enabled() -> bool:
    return os.environ.get("CHAT_AGENT_LOOP_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")


# 2026-07-10 Skill 化: the system prompt is now MINIMAL — persona + a few hard
# interaction rules only. Everything about「怎麼做事」lives in 標準 Skills
# (DB, editable in /admin/agent-skills) loaded on demand via load_skill, plus
# each tool's own description. Do NOT grow this prompt with how-to knowledge.
_SYSTEM = """你是「AIOps 操作助理」，幫半導體製程的工程師 / 當班人員在這個平台上做事。
講繁體中文，專業、精準、直指核心，不說多餘客套。
**全程禁用 emoji 與類 emoji 符號**（⚠️/✅/❌/🔴 等都不行）；要標重點用文字如
[重要]/[HIGH]/[note] 或粗體、表格。

硬規則（少數，其餘看 [Skill 目錄] 的說明書）：
- 直接自然講話。可以閒聊、解釋、回答「你能幫我做什麼」——**絕對不要**丟制式選單卡逼使用者選。
- 路由（不可違反）：要**建新圖／畫圖表／分析圖** → 一律呼叫 plan_pipeline（不先反問 chart 類型等細節，
  計畫卡會收集）；要**改畫面上這張圖** → modify_current_chart；只是**查資料／查狀態** → 用查詢工具直接回。
- 做事之前：請求命中 [Skill 目錄] 某項的使用時機 → **先用 load_skill 取說明書照做**；只是閒聊或沒命中就不用。
- 只能用工具清單裡存在的工具；工具沒涵蓋的事老實說做不到；不確定使用者要什麼時，用**一句話**問清楚，不要硬猜。
- 使用者問候 / 問你是誰 / 問能力 → 自然回答，不要當成分析請求。"""


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
        "description": "使用者要建一張新的圖 / pipeline 時，**直接用這個**（這是標準做法）。"
                       "它會規劃步驟並在對話裡顯示一張『計畫卡』（列出 P1..PN + 確認/修改/取消按鈕），"
                       "使用者在卡片上按確認就會自動開始建圖——你不需要、也不應該再呼叫 build_pipeline。"
                       "**不要為了 chart 類型、站點等細節先反問**——計畫卡會把規劃結果列出讓使用者確認或修改，"
                       "那才是收集細節的地方。呼叫後只要回一句『計畫在上面了，確認後就開始建』，不要用文字重列步驟。",
        "input_schema": {"type": "object", "properties": {
            "instruction": {"type": "string", "description": "要建什麼的完整自然語言需求"},
            "edit_current": {"type": "boolean", "description":
                "使用者是要「以畫面上這張圖為基礎」修改/重新設計時設 true（會以原圖為起點增量改）；全新的圖免填。"}
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
        "description": "使用者要讓目前這張圖「自動跑」——定時巡檢 / 定期檢查 / 觸發告警——時用"
                       "（關鍵詞：巡檢、排程、定期、每天/每小時、告警通知）。"
                       "我不會在對話裡直接設定，而是把它存成 Skill 並帶使用者去設定頁。"
                       "注意：使用者只說「啟用 / 上架 / 存成正式 skill」而沒提排程時，"
                       "那是 activate_skill 的事，不要用這個。",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "activate_skill",
        "description": "使用者要把「畫面上這張圖」或某個既有 skill「啟用 / 上架 / 發布 / 存成正式 skill」"
                       "（讓它生效、可被搜尋）時用——即使他沒說出 slug，畫面上有圖就直接用這個、不用反問。"
                       "會在對話裡出一張確認卡（名稱與描述可編輯），**使用者按確認才會啟用**——你不能直接啟用。"
                       "剛在對話裡建好的圖：不用給 slug（會用畫面上這張，先存成 Skill 再啟用）；"
                       "已存在的 skill 才給 slug。suggested_name / suggested_description **由你自己**"
                       "從對話與圖的內容擬（繁中、業務語意，例：「EQP-01 OOC 次數檢查」，不寫技術結構）——"
                       "**不要為了名稱或描述反問使用者**，卡片本來就讓使用者修改。"
                       "跟 setup_automation 的分工：啟用＝生效可搜尋（這個工具）；排程巡檢＝setup_automation。",
        "input_schema": {"type": "object", "properties": {
            "slug": {"type": "string", "description": "既有 skill 的 slug（畫面上剛建的圖免填）"},
            "suggested_name": {"type": "string", "description": "你建議的 Skill 名稱（不超過 20 字）"},
            "suggested_description": {"type": "string", "description": "你建議的一句話描述（這個 Skill 做什麼、什麼時候用）"},
        }},
    },
]


async def _plan_confirm_flow(
    instr: str, ctx: Dict[str, Any], *, base_pipeline: Dict[str, Any] | None = None,
) -> AsyncIterator[tuple]:
    """Shared plan-first flow: run the Planner to the confirm gate, register the
    pending, emit the original pb_plan_confirm card. Used by plan_pipeline (new
    build / edit_current) AND by modify_current_chart's structural-redesign
    escalation (裁決 2026-07-10: 重新設計必過計畫卡). base_pipeline seeds both
    the plan (incremental edit) and, via the pending, the Live Canvas overlay."""
    from python_ai_sidecar.agent_builder.graph_build.runner import stream_graph_build
    from python_ai_sidecar.agent_orchestrator_v2 import pending_clarify as _pc
    chat_sid = str(ctx["session_id"])
    bsid = f"build-{chat_sid}"
    yield ("event", {"type": "role_marker", "role": "Planner", "text": "規劃中…"})
    plan_pause: Dict[str, Any] | None = None
    async for ev in stream_graph_build(instruction=instr, skip_confirm=False,
                                       base_pipeline=base_pipeline,
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
            base_pipeline=base_pipeline,
            skill_step_mode=False,
            user_id=ctx["user_id"],
            kind="plan_confirm",
            phases=plan_pause.get("phases") or [],
            plan_summary=str(plan_pause.get("plan_summary") or ""),
        ))
    except Exception as ex:  # noqa: BLE001
        logger.warning("plan flow: pending register failed: %s", ex)
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
        #    lifecycle (草案 → 建構中 → 完成). We do NOT re-list the plan as prose.
        #    F1 (2026-07-10): edit_current=true seeds the plan with the on-screen
        #    pipeline so redesigns are incremental AND the Live Canvas opens from
        #    the existing chart (base_pipeline rides the pending → pb_glass_start). ──
        if name == "plan_pipeline":
            base: Dict[str, Any] | None = None
            if inp.get("edit_current"):
                snap = ctx.get("pipeline_snapshot")
                if isinstance(snap, dict) and (snap.get("nodes") or []):
                    base = snap
            async for item in _plan_confirm_flow(
                    str(inp.get("instruction") or ""), ctx, base_pipeline=base):
                yield item
            return

        # ── build_pipeline — direct build WITHOUT a plan card (使用者說「直接建 /
        #    不用看計畫」時才用). Normal flow is plan_pipeline → 卡片確認 → resume;
        #    this is the skip-the-plan shortcut. Wraps the UNCHANGED Builder. ──
        if name == "build_pipeline":
            from python_ai_sidecar.agent_builder.event_wrapper import wrap_build_event_for_chat
            from python_ai_sidecar.agent_builder.graph_build.runner import stream_graph_build
            from python_ai_sidecar.executor.real_executor import execute_native
            instr = str(inp.get("instruction") or "")
            bsid = f"build-{ctx['session_id']}-direct"
            yield ("event", {"type": "role_marker", "role": "Builder", "text": "建置中…"})
            # F1 (2026-07-10): open the Live Canvas + stream pb_glass_* ops.
            # This path previously emitted only role_markers, so direct builds
            # rebuilt silently with no overlay (the native tool always did this).
            yield ("event", {"type": "pb_glass_start", "session_id": bsid, "goal": instr})
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
                if ev.type == "done":
                    final = (ev.data or {}).get("pipeline_json") or final
                wrapped = wrap_build_event_for_chat(ev, bsid)
                if wrapped is not None:
                    yield ("event", wrapped)
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
                # F1 + 裁決 (2026-07-10): 結構性重新設計不是「做不到」——
                # deterministic 升級成 plan-confirm 流程，並以畫面上這張圖為
                # 基底（計畫卡 → 確認 → Live Canvas 從原圖開始改）。
                async for item in _plan_confirm_flow(
                        str(inp.get("instruction") or ""), ctx, base_pipeline=snap):
                    yield item
                return
            cards = out.get("render_cards") or []
            if cards:
                yield ("event", {"type": "tool_done", "tool": "modify_current_chart", "render_card": cards[0]})
            msgs = out.get("messages") or []
            text = msgs[0].content if msgs else "已調整。"
            yield ("result", {"status": "ok", "message": str(text)})
            return

        # ── activate_skill (F4, 2026-07-10) — confirm-card write. The agent
        #    NEVER activates directly; it emits skill_activate_confirm with an
        #    editable name/description and the browser does the write (create-
        #    with-pipeline if needed → PUT name/nl → POST activate) under the
        #    user's auth after they press 確認 — same write-confirm model as
        #    every other internal agent write. ──
        if name == "activate_skill":
            slug = str(inp.get("slug") or "").strip()
            snap = ctx.get("pipeline_snapshot")
            has_snap = isinstance(snap, dict) and bool(snap.get("nodes") or [])
            if not slug and not has_snap:
                yield ("result", {"status": "no_target",
                                  "message": "畫面上沒有圖、也沒指定 skill——先建一張，或請使用者說要啟用哪個 skill。"})
                return
            card: Dict[str, Any] = {
                "type": "skill_activate_confirm",
                "slug": slug or None,
                "suggested_name": str(inp.get("suggested_name") or "").strip()
                                  or ((snap or {}).get("name") if has_snap else None),
                "suggested_description": str(inp.get("suggested_description") or "").strip() or None,
            }
            if not slug:
                card["pipeline_json"] = snap
            yield ("event", {"type": "tool_done", "tool": "activate_skill", "render_card": card})
            yield ("result", {"status": "confirm_pending",
                              "message": "啟用確認卡已顯示（名稱／描述可改），使用者按確認才會生效。"
                                         "只回一句『確認卡在上面了，改好名稱按啟用即可』。"})
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

        # ── load_skill — fetch a 標準 Skill's full manual (always available) ──
        if name == "load_skill":
            skill_name = str(inp.get("name") or "").strip()
            data = await java._get_data(
                f"/internal/agent-skills/{skill_name}") if skill_name else None
            if not isinstance(data, dict) or not data.get("body"):
                yield ("result", {"status": "not_found",
                                  "message": f"沒有叫「{skill_name}」的標準 Skill；目錄裡有哪些就用哪些。"})
                return
            yield ("result", {"status": "ok", "name": data.get("name"),
                              "manual": data.get("body")})
            return

        # ── granted external System MCP (re-enabled 2026-07-10; documented by
        #    the matching 標準 Skill, e.g. process-info-mcp) ──────────────────
        if name in (ctx.get("granted_mcps") or {}):
            data = await _call_system_mcp(java, name, inp.get("args") or inp or {})
            yield ("result", {"status": "ok", "data": data})
            return

        # ── manage_domain_skill — Domain Skill 管理 writes, confirm-card only ──
        if name == "manage_domain_skill":
            action = str(inp.get("action") or "").strip()
            slug = str(inp.get("slug") or "").strip()
            if action not in ("deactivate", "delete", "rename") or not slug:
                yield ("result", {"status": "bad_args",
                                  "message": "action ∈ deactivate|delete|rename 且必須給 slug（用 list_skills_v2 找）。啟用請用 activate_skill。"})
                return
            card = {"type": "skill_admin_confirm", "action": action, "slug": slug,
                    "new_name": str(inp.get("new_name") or "") or None,
                    "new_description": str(inp.get("new_description") or "") or None}
            yield ("event", {"type": "tool_done", "tool": name, "render_card": card})
            yield ("result", {"status": "confirm_pending",
                              "message": "管理動作確認卡已顯示，使用者按確認才會執行。只回一句『確認卡在上面了』。"})
            return

        # ── granted built-in READ tools (Phase 6 fast-follow) ──────────────
        if name in _BUILTIN_READ and name in (ctx.get("granted_reads") or set()):
            spec = _BUILTIN_READ[name]
            path = spec["path"]
            if spec.get("query"):
                # query-style: append only the args the model actually set
                # (empty values would break Java's @RequestParam int parsing).
                from urllib.parse import urlencode
                qp = {a: inp[a] for a in spec["args"]
                      if inp.get(a) not in (None, "", 0)}
                if qp:
                    path = f"{path}?{urlencode(qp)}"
            else:
                for a in spec["args"]:
                    path = path.replace("{" + a + "}", str(inp.get(a) or ""))
            # {user_id} comes from the caller context, never from the model.
            path = path.replace("{user_id}", str(ctx.get("user_id") or 0))
            data = await java._get_data(path)
            yield ("result", {"status": "ok", "data": data})
            return

        # ── granted alarm WRITE tools — confirm-card only, never direct ────
        if name in _ALARM_WRITES and name in (ctx.get("granted_writes") or set()):
            if name == "ack_alarm" and not (inp.get("alarm_id") or inp.get("equipment_id")):
                yield ("result", {"status": "missing_target",
                                  "message": "要認領哪筆（alarm_id）或哪台機台（equipment_id）？先用 query_alarms 找。"})
                return
            card = {"type": "alarm_action_confirm", "action": name,
                    "alarm_id": inp.get("alarm_id") or None,
                    "equipment_id": str(inp.get("equipment_id") or "") or None,
                    "disposition": str(inp.get("disposition") or "") or None,
                    "reason": str(inp.get("reason") or "") or None}
            yield ("event", {"type": "tool_done", "tool": name, "render_card": card})
            yield ("result", {"status": "confirm_pending",
                              "message": "動作確認卡已顯示，使用者按確認才會執行。只回一句『確認卡在上面了』即可，不要重複描述動作內容。"})
            return

        # ── invoke_skill — run any published domain skill's pipeline. Domain
        #    skills are the agent's default repertoire (no per-skill grant). ──
        if name == "invoke_skill":
            slug = str(inp.get("slug") or "")
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
            if isinstance(pj, str):   # /internal/pipelines returns pipeline_json as a JSON string
                try:
                    pj = json.loads(pj)
                except (ValueError, TypeError):
                    pj = None
            if not isinstance(pj, dict) or not (pj.get("nodes")):
                yield ("result", {"status": "no_pipeline", "message": f"skill「{slug}」的 pipeline 不完整。"})
                return
            skill_params = inp.get("params") if isinstance(inp.get("params"), dict) else None
            try:
                res = await execute_native(pj, inputs=skill_params)
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
                  "說「啟用 / 上架 / 存成正式 skill」是要啟用它——**立刻呼叫 activate_skill**，"
                  "不要先問名稱、描述或 slug（確認卡會讓使用者看到並修改這些）；"
                  "不用再問「有沒有圖」。")

    tools = list(_TOOLS)

    # invoke_skill is ALWAYS available — domain skills are the agent's default
    # repertoire (no per-skill grant). It runs any published skill; use
    # search_skills first to find the slug.
    tools.append({
        "name": "invoke_skill",
        "description": "直接執行一個平台上已發布的 domain skill（現成分析 pipeline）並回傳結果——"
                       "用在使用者想「用現成的 X 來看/跑」而不是重新建圖時。先用 search_skills 找到 slug。"
                       "params 可帶 skill 開放的參數（例：{\"tool_id\":\"EQP-07\",\"time_range\":\"7d\"}——"
                       "有哪些參數用 get_skill_v2 查該 skill 的 inputs；使用者指定機台/期間時務必帶上）。",
        "input_schema": {"type": "object", "properties": {
            "slug": {"type": "string", "description": "要跑的 skill slug"},
            "params": {"type": "object", "description": "skill 開放參數（鍵值對，選填）"}
        }, "required": ["slug"]},
    })

    # Phase 6: a few platform-meta READ tools IT admin granted 對內 (alarm /
    # knowledge / supervisor status). Data/analysis capabilities do NOT come
    # through here — they are Skills, run via invoke_skill. External System MCPs
    # reach the agent ONLY as their V54-derived Skills (if generated); a raw
    # System MCP with no derived Skill is simply not given (no auth needed).
    granted = await _granted_agent_tools(java)
    granted_reads = [g["key"] for g in granted
                     if g.get("kind") == "builtin" and g.get("key") in _BUILTIN_READ]
    granted_writes = [g["key"] for g in granted
                      if g.get("kind") == "builtin" and g.get("key") in _ALARM_WRITES]
    ctx["granted_reads"] = set(granted_reads)
    ctx["granted_writes"] = set(granted_writes)
    for key in granted_reads + granted_writes:
        spec = _BUILTIN_READ.get(key) or _ALARM_WRITES[key]
        props = {a: {"type": v["type"], "description": v["description"]}
                 for a, v in spec["args"].items()}
        tools.append({
            "name": key, "description": spec["desc"],
            "input_schema": {"type": "object", "properties": props,
                             "required": spec.get("required", list(spec["args"].keys()))},
        })
    # granted external System MCPs (re-enabled 2026-07-10) — one tool each;
    # params come from the MCP's own input_schema (description = the doc source);
    # the matching 標準 Skill manual teaches the workflow around them.
    granted_mcps: Dict[str, Any] = {}
    ext_keys = [g["key"] for g in granted if g.get("kind") == "external" and g.get("key")]
    if ext_keys:
        try:
            defs = {m.get("name"): m for m in (await java.list_mcps() or [])}
        except Exception:  # noqa: BLE001
            defs = {}
        for key in ext_keys:
            d = defs.get(key) or {}
            granted_mcps[key] = d
            param_doc = _mcp_param_doc(d.get("input_schema") or d.get("inputSchema"))
            tools.append({
                "name": key,
                "description": (str(d.get("description") or key)[:400]
                                + ("　參數：" + param_doc if param_doc else "")),
                "input_schema": {"type": "object", "properties": {
                    "args": {"type": "object", "description": "MCP 參數（依上面 input schema 填）"}
                }},
            })
    ctx["granted_mcps"] = granted_mcps

    # Domain Skill 管理 (標準 Skill: domain-skill-management)。writes 走確認卡。
    tools.append({
        "name": "manage_domain_skill",
        "description": "管理 Domain Skill：action ∈ deactivate（停用）| delete（刪除）| rename（改名/描述）。"
                       "會出確認卡，使用者按確認才執行。啟用用 activate_skill；查清單用 list_skills_v2。"
                       "delete 不可逆——先跟使用者確認清楚。",
        "input_schema": {"type": "object", "properties": {
            "action": {"type": "string", "description": "deactivate | delete | rename"},
            "slug": {"type": "string", "description": "目標 skill 的 slug"},
            "new_name": {"type": "string", "description": "rename 用：新名稱"},
            "new_description": {"type": "string", "description": "rename 用：新描述"},
        }, "required": ["action", "slug"]},
    })

    # 標準 Skill 目錄 (V82): lightweight index in the prompt; full manual on
    # demand via load_skill. The manuals carry the how-to (e.g. alarm 處理守則)
    # so knowledge lives in DB, editable in GUI — not hardcoded here.
    skill_index = await _standard_skill_index(java)
    if skill_index:
        tools.append({
            "name": "load_skill",
            "description": "載入一份「標準 Skill」的完整說明書（操作手冊）。當使用者的請求符合"
                           "[Skill 目錄] 某項的使用時機時，**先呼叫這個**取得作法，再照著做。參數 name。",
            "input_schema": {"type": "object", "properties": {
                "name": {"type": "string", "description": "目錄裡的 skill 名稱，如 alarm-handling"}
            }, "required": ["name"]},
        })
        lines = "\n".join(f"- {s.get('name')}：{s.get('when_to_use')}"
                          for s in skill_index[:20])
        system += ("\n\n[Skill 目錄]（命中使用時機 → 先用 load_skill 取全文說明書再動工；"
                   "只是閒聊或目錄沒命中就不用）\n" + lines)

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
            payload_str = json.dumps(result_val, ensure_ascii=False, default=str)
            # 2026-07-10: a tool once returned ~3.5MB (886K tokens) and blew the
            # context (400 prompt-too-long, user saw an error). Hard-cap every
            # tool_result — the model is told to narrow the query instead.
            if len(payload_str) > 30000:
                payload_str = (payload_str[:30000]
                               + f'…[截斷：結果過大（{len(payload_str)} 字元）。'
                                 '請改用更窄的過濾條件（機台/期間/limit）再查一次。]')
            results.append({"type": "tool_result", "tool_use_id": tu.get("id"),
                            "content": payload_str})
        messages.append({"role": "user", "content": results})

    yield {"type": "synthesis", "text": "（我想太久了，先講到這；你可以再說清楚一點我幫你查。）"}
