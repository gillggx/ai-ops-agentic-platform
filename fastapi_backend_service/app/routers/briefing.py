"""Briefing Router — AI-generated operational briefing via SSE.

Two modes:
  GET /api/v1/briefing?scope=fab       — Fab-wide shift handoff briefing
  GET /api/v1/briefing?scope=tool&toolId=EQP-01 — Single tool health briefing

Flow:
  1. Fetch aggregate data (get_process_summary or get_process_info)
  2. Feed data to LLM with a briefing prompt
  3. Stream the LLM response via SSE (typewriter effect)
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import UserModel

router = APIRouter(prefix="/briefing", tags=["briefing"])
logger = logging.getLogger(__name__)

# ── Briefing prompt templates ─────────────────────────────────────────────────

_FAB_BRIEFING_PROMPT = """\
你是半導體廠值班簡報助理。以下是過去 24 小時的全廠製程摘要數據。
請用 200~300 字中文寫一份精準的**交班簡報**，格式如下：

## 整體狀況
（一句話概述：正常/需關注/異常）

## OOC 統計
- 整體 OOC 率
- 異常最多的機台 (top 3)
- 異常最多的站點 (top 3)

## 需關注事項
- 列出最近的 OOC 事件（時間、機台、批次）
- 如果有連續 OOC 趨勢要特別標注

## 建議動作
- 具體的建議（例如：EQP-03 需要排查 chamber_pressure drift）

⚠️ 嚴格規則：
- 只使用以下數據，不要捏造任何 ID 或數值。
- 禁止輸出「資料不一致」「無法評估」「未包含數據」「無法確認」等除錯用語。
  如果缺少某項數據，直接略過不提。
- 禁止說「建議進一步確認」— 給出具體動作或不要寫。
- 語氣要像資深工程師交班，不是 AI 在解釋自己的限制。

--- 數據開始 ---
{data}
--- 數據結束 ---
"""

_TOOL_BRIEFING_PROMPT = """\
你是半導體廠資深值班工程師。以下是機台 {tool_id} 最近 {n_events} 筆製程事件。
請用**正好 3 句話**寫出設備摘要，不要多也不要少：

**第 1 句：整體表現** — 用一句話描述這台機台的健康度（正常/需關注/異常），包含 OOC 率和 FDC 狀態。
**第 2 句：OOC 分佈** — 近期 OOC 是否集中在某個特定站點（step）？列出最嚴重的 1-2 個 step。
**第 3 句：關聯分析** — OOC 事件對應的 recipe 版本和 APC 參數是否有集中現象？（例如：都發生在同一個 recipe 版本，或 APC 的某個 active param 明顯偏移）

⚠️ 嚴格規則：
- 只能 3 句話，每句不超過 50 字。不要分段、不要標題、不要列點。
- 只使用以下數據，不要捏造。
- 缺少的數據直接略過，禁止說「未包含」「無法確認」。

--- 數據 ---
{data}
"""


async def _fetch_fab_data(db: AsyncSession) -> dict:
    """Fetch fab-wide summary via internal MCP call."""
    from app.services.skill_executor_service import build_mcp_executor
    from app.config import get_settings
    executor = build_mcp_executor(db, sim_url=get_settings().ONTOLOGY_SIM_URL)
    result = await executor("get_process_summary", {"since": "24h"})
    return result if isinstance(result, dict) else {}


async def _fetch_tool_data(db: AsyncSession, tool_id: str) -> dict:
    """Fetch tool-specific events via internal MCP call."""
    from app.services.skill_executor_service import build_mcp_executor
    from app.config import get_settings
    executor = build_mcp_executor(db, sim_url=get_settings().ONTOLOGY_SIM_URL)
    result = await executor("get_process_info", {"toolID": tool_id, "limit": 20})
    return result if isinstance(result, dict) else {}


def _summarize_tool_data(raw: dict) -> str:
    """Extract structured summary from get_process_info for LLM — focused on
    OOC distribution by step, recipe version concentration, and APC drift."""
    events = raw.get("events", [])
    if not events:
        return "(無製程事件)"

    total = len(events)
    ooc_events = [e for e in events if e.get("spc_status") == "OOC"]
    ooc_count = len(ooc_events)
    fdc_faults = sum(1 for e in events if (e.get("FDC") or {}).get("classification") == "FAULT"
                     or e.get("fdc_classification") == "FAULT")
    fdc_warnings = sum(1 for e in events if (e.get("FDC") or {}).get("classification") == "WARNING"
                       or e.get("fdc_classification") == "WARNING")

    lines = [
        f"total_events: {total}, ooc: {ooc_count} ({ooc_count/total*100:.1f}%), fdc_faults: {fdc_faults}, fdc_warnings: {fdc_warnings}",
    ]

    # OOC by step distribution
    ooc_by_step: dict = {}
    for e in ooc_events:
        step = e.get("step", "?")
        ooc_by_step[step] = ooc_by_step.get(step, 0) + 1
    if ooc_by_step:
        sorted_steps = sorted(ooc_by_step.items(), key=lambda x: -x[1])
        lines.append("OOC by step: " + ", ".join(f"{s}={n}" for s, n in sorted_steps))

    # OOC by recipe version distribution
    ooc_by_recipe: dict = {}
    for e in ooc_events:
        rv = (e.get("RECIPE") or {}).get("recipe_version", "?")
        rid = e.get("recipeID", "?")
        key = f"{rid}_v{rv}"
        ooc_by_recipe[key] = ooc_by_recipe.get(key, 0) + 1
    if ooc_by_recipe:
        sorted_recipes = sorted(ooc_by_recipe.items(), key=lambda x: -x[1])
        lines.append("OOC by recipe: " + ", ".join(f"{r}={n}" for r, n in sorted_recipes[:5]))

    # APC active params trend (first vs last event)
    apc_first = (events[-1].get("APC") or {}).get("parameters") or {}
    apc_last = (events[0].get("APC") or {}).get("parameters") or {}
    active_params = ["etch_time_offset", "rf_power_bias", "gas_flow_comp", "ff_correction", "fb_correction"]
    apc_drift = []
    for p in active_params:
        v0 = apc_first.get(p)
        v1 = apc_last.get(p)
        if isinstance(v0, (int, float)) and isinstance(v1, (int, float)) and v0 != 0:
            drift_pct = abs(v1 - v0) / abs(v0) * 100
            if drift_pct > 5:
                apc_drift.append(f"{p}: {v0:.4f}→{v1:.4f} ({drift_pct:.0f}%drift)")
    if apc_drift:
        lines.append("APC active param drift: " + ", ".join(apc_drift))
    else:
        lines.append("APC active params: stable (< 5% drift)")

    # FDC fault codes
    fault_codes: dict = {}
    for e in events:
        fdc = e.get("FDC") or {}
        code = fdc.get("fault_code", "")
        if code:
            fault_codes[code] = fault_codes.get(code, 0) + 1
    if fault_codes:
        lines.append("FDC codes: " + ", ".join(f"{c}={n}" for c, n in sorted(fault_codes.items(), key=lambda x: -x[1])))

    return "\n".join(lines)


async def _stream_briefing(prompt: str):
    """Stream LLM response as SSE events."""
    from app.utils.llm_client import get_llm_client
    llm = get_llm_client()

    try:
        response = await llm.create(
            system=(
                "你是半導體廠資深值班工程師，用專業簡潔的語氣寫交班簡報。"
                "只使用提供的數據。禁止說「資料不一致」「無法評估」「未包含」「無法確認」等語句。"
                "缺少的數據直接略過不提。以最新事件為準，不要跟統計數字矛盾。"
            ),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1024,
        )
        text = response.text or ""
        # Stream in chunks for typewriter effect
        chunk_size = 20
        for i in range(0, len(text), chunk_size):
            chunk = text[i:i + chunk_size]
            yield f"data: {json.dumps({'type': 'chunk', 'text': chunk}, ensure_ascii=False)}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    except Exception as exc:
        logger.exception("Briefing LLM failed: %s", exc)
        yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"


_ALARM_QUEUE_PROMPT = """\
你是半導體廠資深值班工程師。以下是當前的告警統計。
請用 1-2 句中文寫出「全局戰況總結」，讓接班工程師一秒抓到重點。

格式：直接講最緊急的事 + 建議動作。不要分段、不要列點、不要標題。

⚠️ 嚴格規則：只使用以下數據。禁止說「無法確認」等除錯用語。

--- 數據 ---
{data}
"""

_ALARM_SYNTHESIS_PROMPT = """\
你是半導體廠資深值班工程師。以下是一筆告警的所有 Diagnostic Rule 分析結果。
請用 2-3 句中文寫一個**綜合處置建議**，整合所有 DR 結果的重點。

格式：先判斷（是真異常還是誤報），再給具體建議動作。不要重複每條 DR 的內容。

⚠️ 嚴格規則：只使用以下數據。以 FAULT/ALERT 的 DR 結果為重點，PASS 的可簡略帶過。

--- 數據 ---
{data}
"""


@router.get("")
async def get_briefing(
    scope: str = Query("fab", description="fab | tool | alarm | alarm_detail"),
    toolId: Optional[str] = Query(None),
    alarmData: Optional[str] = Query(None, description="JSON-encoded alarm data (GET)"),
    db: AsyncSession = Depends(get_db),
    _: UserModel = Depends(get_current_user),
):
    """SSE endpoint (GET): AI-generated briefing. For alarm scopes, prefer POST."""
    return await _build_briefing_response(scope, toolId, alarmData, db)


@router.post("")
async def post_briefing(
    body: dict,
    db: AsyncSession = Depends(get_db),
    _: UserModel = Depends(get_current_user),
):
    """SSE endpoint (POST): for alarm scopes that need to send large JSON body."""
    scope = body.get("scope", "fab")
    toolId = body.get("toolId")
    alarm_data = json.dumps(body.get("alarmData", {}), ensure_ascii=False)
    return await _build_briefing_response(scope, toolId, alarm_data, db)


async def _build_briefing_response(scope, toolId, alarmData, db):
    if scope == "tool" and toolId:
        raw = await _fetch_tool_data(db, toolId)
        data_text = _summarize_tool_data(raw)
        prompt = _TOOL_BRIEFING_PROMPT.format(
            tool_id=toolId,
            n_events=len(raw.get("events", [])),
            data=data_text,
        )
    elif scope == "alarm":
        prompt = _ALARM_QUEUE_PROMPT.format(data=alarmData or "{}")
    elif scope == "alarm_detail":
        prompt = _ALARM_SYNTHESIS_PROMPT.format(data=alarmData or "{}")
    else:
        raw = await _fetch_fab_data(db)
        prompt = _FAB_BRIEFING_PROMPT.format(
            data=json.dumps(raw, ensure_ascii=False, default=str)[:3000],
        )

    return StreamingResponse(
        _stream_briefing(prompt),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
