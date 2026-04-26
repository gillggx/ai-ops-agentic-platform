"""Briefing — AI-generated operational summary, 4 scopes.

Phase 8-A-1d port from fastapi_backend_service/app/routers/briefing.py.
The sidecar now owns the LLM call and the data fetch (direct httpx hit
to the ontology simulator); Java just forwards `/api/v1/briefing` here.

Auth: every /internal/* path is gated by ``require_service_token``.
The forwarded ``X-User-Id`` lets us include user context in future prompts
but isn't used today.
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncGenerator, Optional

import httpx
from fastapi import APIRouter
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from ..auth import CallerContext, ServiceAuth
from ..agent_helpers_native.llm_client import get_llm_client
from ..pipeline_builder._sidecar_deps import get_settings

log = logging.getLogger("python_ai_sidecar.briefing")
router = APIRouter(prefix="/internal/briefing", tags=["briefing"])


# ── Prompts (copied verbatim from old backend) ──────────────────────────────

_FAB_BRIEFING_PROMPT = """\
你是半導體廠資深值班工程師。以下是過去 24 小時的全廠製程摘要數據。
請用 200~300 字中文寫一份**過去 24 小時重點整理**，語氣精準直接，格式如下：

## 📋 過去 24 小時重點整理

**一句話概述**（正常運行 / 需要關注 / 有異常需處理）

### 異常熱點
- OOC 率最高的機台和站點各 top 3（附數字）
- 如果有連續 OOC 趨勢要特別標注

### 需立即處理
- 列出最緊急的 1~3 項（具體機台 + 站點 + 建議動作）
- 沒有緊急事項就寫「無」

### 趨勢觀察
- 哪些機台/站點的異常率在上升？
- 有沒有跨機台的共同異常模式？

⚠️ 嚴格規則：
- 只使用以下數據，不要捏造任何 ID 或數值。
- 缺少的數據直接略過不提。
- 給具體動作，不要說「建議進一步確認」。
- 語氣像資深工程師寫給同事的重點筆記。

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


_SYSTEM_PROMPT = (
    "你是半導體廠資深值班工程師，用專業簡潔的語氣寫交班簡報。"
    "只使用提供的數據。禁止說「資料不一致」「無法評估」「未包含」「無法確認」等語句。"
    "缺少的數據直接略過不提。以最新事件為準，不要跟統計數字矛盾。"
)


# ── Data fetch — direct hit to ontology simulator HTTP ─────────────────────


async def _fetch_fab_data() -> dict:
    """Fab-wide 24h summary — direct GET to ontology /process/summary."""
    base = get_settings().ONTOLOGY_SIM_URL.rstrip("/")
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            res = await client.get(f"{base}/api/v1/process/summary", params={"since": "24h"})
            res.raise_for_status()
            return res.json()
        except Exception as exc:  # noqa: BLE001
            log.warning("ontology summary fetch failed: %s", exc)
            return {}


async def _fetch_tool_data(tool_id: str) -> dict:
    """Single-tool recent events — direct GET to ontology /process/info."""
    base = get_settings().ONTOLOGY_SIM_URL.rstrip("/")
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            res = await client.get(
                f"{base}/api/v1/process/info",
                params={"toolID": tool_id, "limit": 20},
            )
            res.raise_for_status()
            return res.json()
        except Exception as exc:  # noqa: BLE001
            log.warning("ontology tool data fetch failed: %s", exc)
            return {}


def _summarize_tool_data(raw: dict) -> str:
    """Compact text summary of get_process_info for the tool prompt.

    Mirrors the old backend's _summarize_tool_data line-for-line so the
    LLM behaviour matches what users have seen pre-cutover.
    """
    events = raw.get("events", [])
    if not events:
        return "(無製程事件)"

    total = len(events)
    ooc_events = [e for e in events if e.get("spc_status") == "OOC"]
    ooc_count = len(ooc_events)
    fdc_faults = sum(
        1 for e in events
        if (e.get("FDC") or {}).get("classification") == "FAULT"
        or e.get("fdc_classification") == "FAULT"
    )
    fdc_warnings = sum(
        1 for e in events
        if (e.get("FDC") or {}).get("classification") == "WARNING"
        or e.get("fdc_classification") == "WARNING"
    )

    lines = [
        f"total_events: {total}, ooc: {ooc_count} "
        f"({ooc_count / total * 100:.1f}%), fdc_faults: {fdc_faults}, "
        f"fdc_warnings: {fdc_warnings}",
    ]

    ooc_by_step: dict[str, int] = {}
    for e in ooc_events:
        step = e.get("step", "?")
        ooc_by_step[step] = ooc_by_step.get(step, 0) + 1
    if ooc_by_step:
        sorted_steps = sorted(ooc_by_step.items(), key=lambda x: -x[1])
        lines.append("OOC by step: " + ", ".join(f"{s}={n}" for s, n in sorted_steps))

    ooc_by_recipe: dict[str, int] = {}
    for e in ooc_events:
        rv = (e.get("RECIPE") or {}).get("recipe_version", "?")
        rid = e.get("recipeID", "?")
        key = f"{rid}_v{rv}"
        ooc_by_recipe[key] = ooc_by_recipe.get(key, 0) + 1
    if ooc_by_recipe:
        sorted_recipes = sorted(ooc_by_recipe.items(), key=lambda x: -x[1])
        lines.append("OOC by recipe: " + ", ".join(f"{r}={n}" for r, n in sorted_recipes[:5]))

    apc_first = (events[-1].get("APC") or {}).get("parameters") or {}
    apc_last = (events[0].get("APC") or {}).get("parameters") or {}
    active_params = ["etch_time_offset", "rf_power_bias", "gas_flow_comp", "ff_correction", "fb_correction"]
    apc_drift: list[str] = []
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

    fault_codes: dict[str, int] = {}
    for e in events:
        fdc = e.get("FDC") or {}
        code = fdc.get("fault_code", "")
        if code:
            fault_codes[code] = fault_codes.get(code, 0) + 1
    if fault_codes:
        lines.append(
            "FDC codes: "
            + ", ".join(f"{c}={n}" for c, n in sorted(fault_codes.items(), key=lambda x: -x[1]))
        )

    return "\n".join(lines)


# ── LLM stream ──────────────────────────────────────────────────────────────


async def _stream_briefing(prompt: str) -> AsyncGenerator[dict, None]:
    """Run the LLM call once and yield the result as a single chunk + done.

    The old backend faked a typewriter effect by chopping the response into
    20-char chunks; we don't bother — the UI shows a spinner anyway and a
    single chunk avoids reordering risks under SSE proxies.
    """
    try:
        llm = get_llm_client()
        response = await llm.create(
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1024,
        )
        text = response.text or ""
        yield {"event": "message", "data": json.dumps({"type": "chunk", "text": text}, ensure_ascii=False)}
        yield {"event": "message", "data": json.dumps({"type": "done"}, ensure_ascii=False)}
    except Exception as exc:  # noqa: BLE001
        log.exception("briefing LLM call failed")
        yield {"event": "message", "data": json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False)}


# ── Endpoints ──────────────────────────────────────────────────────────────


class BriefingRequest(BaseModel):
    scope: str = "fab"          # fab | tool | alarm | alarm_detail
    toolId: Optional[str] = None
    alarmData: Optional[Any] = None  # accepts dict (preferred) or stringified JSON


async def _build_prompt(req: BriefingRequest) -> str:
    if req.scope == "tool" and req.toolId:
        raw = await _fetch_tool_data(req.toolId)
        return _TOOL_BRIEFING_PROMPT.format(
            tool_id=req.toolId,
            n_events=len(raw.get("events", [])),
            data=_summarize_tool_data(raw),
        )
    if req.scope == "alarm":
        return _ALARM_QUEUE_PROMPT.format(data=_serialize_alarm_data(req.alarmData))
    if req.scope == "alarm_detail":
        return _ALARM_SYNTHESIS_PROMPT.format(data=_serialize_alarm_data(req.alarmData))
    # Default: fab
    raw = await _fetch_fab_data()
    return _FAB_BRIEFING_PROMPT.format(
        data=json.dumps(raw, ensure_ascii=False, default=str)[:3000],
    )


def _serialize_alarm_data(data: Any) -> str:
    if data is None:
        return "{}"
    if isinstance(data, str):
        return data
    return json.dumps(data, ensure_ascii=False, default=str)


@router.post("/sse", response_class=EventSourceResponse)
async def briefing_sse(
    req: BriefingRequest,
    caller: CallerContext = ServiceAuth,  # noqa: ARG001 — auth gate only
) -> EventSourceResponse:
    """SSE briefing — Java forwards GET / POST here.

    Single endpoint takes JSON body (scope + optional toolId / alarmData).
    Java's GET handler maps query params into this body; POST passes body
    through as-is. Same flow regardless.
    """
    prompt = await _build_prompt(req)
    return EventSourceResponse(_stream_briefing(prompt))
