"""Helper functions for agent_orchestrator_v2.

Migrated from the deprecated v1 agent_orchestrator.py — these are the
shared utilities that v2's nodes need (preflight validation, result
formatting, contract parsing, chart notification).

DO NOT add new logic here. New helpers should go directly into the
node that uses them, or be added to a more specific module.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from python_ai_sidecar.agent_helpers._model_stubs import MCPDefinitionModel
from python_ai_sidecar.agent_helpers._model_stubs import SkillDefinitionModel

logger = logging.getLogger(__name__)


# ── Constants ──────────────────────────────────────────────────────────────────

MAX_ITERATIONS = 12
_LLM_RESULT_MAX_CHARS = 8000      # cap applied to every tool_result before adding to messages
_SOFT_COMPACT_THRESHOLD = 40_000   # LLM-summarise oldest turns
_HARD_COMPACT_THRESHOLD = 60_000   # keep last 3 turns + summary

# Tools that require human approval before execution
_DESTRUCTIVE_TOOLS = frozenset({
    "patch_skill_raw",
    "draft_routine_check",
    "draft_event_skill_link",
})


# ── HITL Approval Registry (placeholder — v2 will use LangGraph interrupt) ─────
# Kept as no-op stubs so /agent/approve endpoint doesn't break.
# Real implementation is planned for Phase 2-D with LangGraph interrupt().

_pending_approvals: Dict[str, Optional[bool]] = {}


def set_approval(token: str, approved: bool) -> bool:
    """No-op stub. v2 has not implemented HITL yet.

    Returns False (token not found) since no token is ever registered.
    """
    return False


# ── Pre-flight Validation ──────────────────────────────────────────────────────

async def _preflight_validate(
    db: AsyncSession,
    tool_name: str,
    tool_input: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Pre-flight validation — intercept ambiguous/missing params before execution."""
    if tool_name == "execute_mcp":
        mcp_name = tool_input.get("mcp_name")
        if not mcp_name:
            return {
                "status": "error", "code": "MISSING_MCP_NAME",
                "message": (
                    "⚠️ execute_mcp 必須提供 mcp_name。"
                    "請從 <mcp_catalog> 中找到正確的 name 欄位填入，例如 'get_tool_trajectory'。"
                    "禁止使用 mcp_id（整數 ID 已棄用）。"
                ),
            }
        # Phase 8-A-1d: when no DB session, route via Java client. The mcp_name
        # → entity lookup is the only DB read here; everything else is in-memory.
        if db is None:
            from python_ai_sidecar.clients.java_client import JavaAPIClient
            from python_ai_sidecar.config import CONFIG
            java = JavaAPIClient(
                CONFIG.java_api_url, CONFIG.java_internal_token,
                timeout_sec=CONFIG.java_timeout_sec,
            )
            mcp_dict = await java.get_mcp_by_name(mcp_name)
            if mcp_dict is None:
                return {
                    "status": "error", "code": "MCP_NOT_FOUND",
                    "message": (
                        f"⚠️ 找不到名為 '{mcp_name}' 的 MCP。"
                        "請確認 <mcp_catalog> 中的 name 欄位是否正確。"
                    ),
                }
            # Wrap in attr-access so the SQLAlchemy-style path below works
            class _MCP:
                def __init__(self, d):
                    self._d = d
                def __getattr__(self, k):
                    if k in self._d:
                        return self._d[k]
                    parts = k.split("_")
                    camel = parts[0] + "".join(p.title() for p in parts[1:])
                    return self._d.get(camel)
            mcp = _MCP(mcp_dict)
        else:
            result = await db.execute(
                select(MCPDefinitionModel).where(MCPDefinitionModel.name == mcp_name)
            )
            mcp = result.scalar_one_or_none()
        if not mcp:
            return {
                "status": "error", "code": "MCP_NOT_FOUND",
                "message": (
                    f"⚠️ 找不到名為 '{mcp_name}' 的 MCP。"
                    "請確認 <mcp_catalog> 中的 name 欄位是否正確。"
                ),
            }
        mcp_type = getattr(mcp, "mcp_type", "custom") or "custom"
        if mcp_type == "system":
            schema_src = mcp
        else:
            schema_src = mcp if getattr(mcp, "input_schema", None) else None

        if schema_src and schema_src.input_schema:
            try:
                schema = json.loads(schema_src.input_schema) if isinstance(schema_src.input_schema, str) else schema_src.input_schema
                fields = schema.get("fields", [])
                required = [f["name"] for f in fields if f.get("required")]
                all_field_names = [f["name"] for f in fields]
                provided = tool_input.get("params") or {}
                if mcp.name == "get_process_context":
                    provided = dict(provided)
                    if "lot_id" in provided and "targetID" not in provided:
                        provided["targetID"] = provided["lot_id"]
                    if "event_time" in provided and "eventTime" not in provided:
                        provided["eventTime"] = provided["event_time"]
                    provided.setdefault("objectName", "DC")
                    provided.pop("lot_id", None)
                    tool_input["params"] = provided
                missing = [k for k in required if k not in provided or not provided[k]]
                if not provided and all_field_names and not required:
                    return {
                        "status": "error", "code": "MISSING_PARAMS",
                        "message": (
                            f"⛔ [STOP — 禁止再次呼叫 execute_mcp] MCP「{mcp.name}」有以下可用查詢參數：{all_field_names}。"
                            f"你必須立即停止工具呼叫，直接以文字訊息向用戶詢問他想查詢的值，等待用戶回答後才能繼續。"
                        ),
                        "available_params": all_field_names,
                    }
                if missing:
                    return {
                        "status": "error", "code": "MISSING_PARAMS",
                        "message": (
                            f"MCP「{mcp.name}」缺少必填查詢參數：{missing}。"
                            f"請先嘗試透過其他工具（如 list_recent_events）取得所需數值，"
                            f"若確實無法取得再向用戶詢問。"
                        ),
                        "missing_params": missing,
                        "required_params": required,
                    }
            except Exception:
                pass

    elif tool_name == "execute_skill":
        skill_id = tool_input.get("skill_id")
        if not skill_id:
            return {
                "status": "error", "code": "MISSING_SKILL_ID",
                "message": "⚠️ execute_skill 缺少 skill_id。請先呼叫 list_skills 確認正確的 Skill ID 後再重試。",
            }
        result = await db.execute(select(SkillDefinitionModel).where(SkillDefinitionModel.id == skill_id))
        skill = result.scalar_one_or_none()
        if not skill:
            return {
                "status": "error", "code": "SKILL_NOT_FOUND",
                "message": f"⚠️ Skill #{skill_id} 不存在。請呼叫 list_skills 取得有效的 Skill 列表後重試。",
            }

    return None


# ── ID Hallucination Detection ─────────────────────────────────────────────────

_ID_PATTERNS = [
    re.compile(r"\bLOT-\d{4}\b"),       # LOT-0001
    re.compile(r"\bSTEP_\d{3}\b"),      # STEP_001
    re.compile(r"\bEQP-\d{2}\b"),       # EQP-01
    re.compile(r"\bAPC-\d{3}\b"),       # APC-005
    re.compile(r"\bRCP-\d{3}\b"),       # RCP-018
]

_MEMORY_CITATION_PATTERN = re.compile(r"\[memory:(\d+)\]")


def _extract_memory_citations(text: str) -> List[int]:
    """Return list of unique memory ids cited in the text via [memory:<id>] tags."""
    if not text:
        return []
    seen: set = set()
    ids: List[int] = []
    for m in _MEMORY_CITATION_PATTERN.finditer(text):
        try:
            mid = int(m.group(1))
            if mid not in seen:
                seen.add(mid)
                ids.append(mid)
        except ValueError:
            continue
    return ids


def _detect_id_hallucinations(
    final_text: str,
    tools_used: List[Dict[str, Any]],
) -> List[str]:
    """Return list of IDs that appear in final_text but not in any tool result."""
    if not final_text or not tools_used:
        return []

    haystack = ""
    for t in tools_used:
        rt = t.get("result_text") or ""
        if isinstance(rt, str):
            haystack += rt + "\n"
    if not haystack:
        return []

    hallucinated: List[str] = []
    seen: set = set()
    for pattern in _ID_PATTERNS:
        for match in pattern.finditer(final_text):
            ident = match.group(0)
            if ident in seen:
                continue
            seen.add(ident)
            if ident not in haystack:
                hallucinated.append(ident)
    return hallucinated


# ── Tool Result Formatting ─────────────────────────────────────────────────────

def _result_summary(result: Dict[str, Any]) -> str:
    """One-line summary of a tool result for SSE tool_done events."""
    if "error" in result:
        return f"ERROR: {result['error']}"
    if "llm_readable_data" in result:
        lrd = result["llm_readable_data"]
        if isinstance(lrd, dict):
            status = lrd.get("status", "?")
            msg = lrd.get("diagnosis_message", "")[:80]
            return f"status={status} | {msg}"
        if "output_data" in result and isinstance(result.get("output_data"), dict):
            ds = result["output_data"].get("dataset")
            count = len(ds) if isinstance(ds, list) else result.get("row_count", 0)
            name = result.get("mcp_name") or f"MCP #{result.get('mcp_id', '?')}"
            return f"{name} 回傳 {count} 筆資料"
    if "memories" in result:
        return f"{result['count']} 條記憶"
    if "draft_id" in result:
        return f"draft_id={result['draft_id']}"
    if "data" in result and isinstance(result["data"], list):
        return f"{len(result['data'])} 筆資料"
    return json.dumps(result, ensure_ascii=False)[:100]


# ── Chart Rendering Notification ───────────────────────────────────────────────

def _notify_chart_rendered(result: Dict[str, Any], chart_intents: List[Dict[str, Any]]) -> None:
    """Inject a notice into tool result telling the LLM that charts have been rendered.

    Mutates `result` in place. Why: LLM only sees text, not side effects.
    Without this notice it keeps calling more plotting tools and embeds duplicate
    chart specs in synthesis.
    """
    if not chart_intents:
        return

    chart_lines: List[str] = []
    for intent in chart_intents:
        title = intent.get("title", "(untitled)")
        data_len = len(intent.get("data", [])) if isinstance(intent.get("data"), list) else 0
        chart_lines.append(f"  • {title}（{data_len} 點）")
    chart_list = "\n".join(chart_lines)

    notice = (
        "═══════════════════════════════════════════════\n"
        "✅ CHART RENDERED — 以下圖表已自動渲染至使用者畫面，使用者已看到：\n"
        f"{chart_list}\n"
        "\n"
        "⛔ 禁止再呼叫繪圖工具（execute_jit / analyze_data / plotly）畫同樣的圖\n"
        "⛔ synthesis 的 contract.visualization 必須為空陣列 []\n"
        "✅ 你的唯一任務：用 **文字** 說明觀察結論（OOC 點位、趨勢、建議），不要重畫圖\n"
        "═══════════════════════════════════════════════\n\n"
    )

    existing = result.get("llm_readable_data", "")
    if isinstance(existing, str):
        result["llm_readable_data"] = notice + existing
    elif isinstance(existing, dict):
        result["llm_readable_data"] = notice + json.dumps(existing, ensure_ascii=False)
    else:
        result["llm_readable_data"] = notice

    result["_chart_rendered"] = True
    result["_chart_rendered_titles"] = [intent.get("title", "") for intent in chart_intents]


# ── SPC Result Detection & Auto-Contract ───────────────────────────────────────

def _is_spc_result(result: Dict[str, Any]) -> bool:
    """Return True when an execute_mcp result contains SPC chart data."""
    try:
        od = result.get("output_data", {})
        ds = od.get("dataset", [])
        if ds:
            inner = ds[0].get("data", [])
            if inner and isinstance(inner, list):
                sample = inner[0]
                if all(k in sample for k in ("value", "ucl", "lcl", "is_ooc")):
                    return True
        if od.get("ui_render", {}).get("chart_data"):
            return True
        return False
    except Exception:
        return False


def _build_spc_contract(mcp_name: str, result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Auto-build an AIOpsReportContract from a SPC MCP result.

    Called as fallback when the LLM synthesis does not include a <contract> block.
    """
    try:
        ds = result.get("output_data", {}).get("dataset", [])
        if not ds:
            return None
        summary = ds[0]
        points = summary.get("data", [])
        if not points:
            chart_data = result.get("output_data", {}).get("ui_render", {}).get("chart_data")
            if not chart_data:
                return None
            step = summary.get("step", "")
            chart = summary.get("chart_name", "SPC")
            pass_rate = summary.get("pass_rate", 0)
            ooc_count = summary.get("ooc_count", 0)
            trend = summary.get("trend", "")
            total = summary.get("total_points", 0)
            return {
                "$schema": "aiops-report/v1",
                "summary": (
                    f"{step} {chart} — 良率 {pass_rate}%，OOC {ooc_count} 筆，"
                    f"趨勢 {trend}，共 {total} 筆量測。"
                ),
                "evidence_chain": [
                    {"step": 1, "tool": mcp_name,
                     "finding": f"共 {total} 筆，OOC={ooc_count}，Pass rate={pass_rate}%，trend={trend}",
                     "viz_ref": "spc_chart"},
                ],
                "visualization": [
                    {"id": "spc_chart", "type": "plotly",
                     "spec": {"chart_data": chart_data}},
                ],
                "suggested_actions": [
                    {"label": "查看其他管制圖", "trigger": "agent",
                     "message": f"請顯示 {step} 的 r_chart 和 s_chart"},
                ],
            }

        ucl = points[0].get("ucl", 0)
        lcl = points[0].get("lcl", 0)
        cl = round((ucl + lcl) / 2, 4)

        values = [
            {
                "x": p.get("eventTime", "")[:19].replace("T", " "),
                "lot": p.get("lotID", ""),
                "tool": p.get("toolID", ""),
                "value": round(p.get("value", 0), 4),
                "status": "OOC" if p.get("is_ooc") else "PASS",
            }
            for p in points
        ]

        step = summary.get("step", "")
        chart = summary.get("chart_name", "xbar_chart")
        pass_rate = summary.get("pass_rate", 0)
        ooc_count = summary.get("ooc_count", 0)
        trend = summary.get("trend", "")

        vega_spec = {
            "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
            "background": "white",
            "width": "container",
            "height": 280,
            "data": {"values": values},
            "layer": [
                {
                    "mark": {"type": "line", "color": "#4299e1", "strokeWidth": 1.5},
                    "encoding": {
                        "x": {"field": "x", "type": "ordinal", "title": "時間",
                              "axis": {"labelAngle": -35, "labelFontSize": 9}},
                        "y": {"field": "value", "type": "quantitative", "title": chart,
                              "scale": {"zero": False}},
                    },
                },
                {
                    "mark": {"type": "point", "size": 70, "filled": True},
                    "encoding": {
                        "x": {"field": "x", "type": "ordinal"},
                        "y": {"field": "value", "type": "quantitative"},
                        "color": {
                            "field": "status", "type": "nominal",
                            "scale": {"domain": ["PASS", "OOC"], "range": ["#38a169", "#e53e3e"]},
                            "legend": {"title": "狀態"},
                        },
                        "tooltip": [
                            {"field": "x", "title": "時間"},
                            {"field": "lot", "title": "批次"},
                            {"field": "tool", "title": "機台"},
                            {"field": "value", "title": "量測值"},
                            {"field": "status", "title": "狀態"},
                        ],
                    },
                },
                {"mark": {"type": "rule", "color": "#e53e3e", "strokeDash": [6, 4], "strokeWidth": 1.5},
                 "encoding": {"y": {"datum": ucl}}},
                {"mark": {"type": "rule", "color": "#e53e3e", "strokeDash": [6, 4], "strokeWidth": 1.5},
                 "encoding": {"y": {"datum": lcl}}},
                {"mark": {"type": "rule", "color": "#a0aec0", "strokeDash": [3, 3], "strokeWidth": 1},
                 "encoding": {"y": {"datum": cl}}},
                {"mark": {"type": "text", "align": "right", "dx": -4, "dy": -6,
                          "fontSize": 9, "color": "#e53e3e", "fontWeight": "bold"},
                 "encoding": {"y": {"datum": ucl}, "text": {"value": f"UCL={ucl}"}, "x": {"value": 0}}},
                {"mark": {"type": "text", "align": "right", "dx": -4, "dy": 10,
                          "fontSize": 9, "color": "#e53e3e", "fontWeight": "bold"},
                 "encoding": {"y": {"datum": lcl}, "text": {"value": f"LCL={lcl}"}, "x": {"value": 0}}},
            ],
        }

        return {
            "$schema": "aiops-report/v1",
            "summary": (
                f"{step} {chart} — 良率 {pass_rate}%，OOC {ooc_count} 筆，趨勢 {trend}。"
                f"管制界限 UCL={ucl} / LCL={lcl}。"
            ),
            "evidence_chain": [
                {"step": 1, "tool": mcp_name,
                 "finding": f"共 {len(values)} 筆量測，OOC={ooc_count}，Pass rate={pass_rate}%",
                 "viz_ref": "spc_chart"},
            ],
            "visualization": [
                {"id": "spc_chart", "type": "vega-lite", "spec": vega_spec}
            ],
            "suggested_actions": [
                {"label": "深入分析 OOC 批次", "trigger": "agent",
                 "message": f"請分析 {step} 的 {ooc_count} 筆 OOC 批次的根因"},
                {"label": "查看其他管制圖", "trigger": "agent",
                 "message": f"請顯示 {step} 的所有管制圖（range_chart, sigma_chart 等）"},
            ],
        }
    except Exception as exc:
        logger.warning("_build_spc_contract failed: %s", exc)
        return None


# ── Contract Parsing ───────────────────────────────────────────────────────────

def _parse_contract(text: str) -> Optional[Dict[str, Any]]:
    """Extract and parse <contract>...</contract> block from synthesis text."""
    match = re.search(r"<contract>([\s\S]*?)</contract>", text)
    if not match:
        return None
    raw = match.group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("_parse_contract: invalid JSON in <contract> block: %s", exc)
        return None
    if not isinstance(data, dict):
        return None
    if data.get("$schema") != "aiops-report/v1":
        logger.warning("_parse_contract: unknown $schema=%r, ignoring", data.get("$schema"))
        return None
    data.setdefault("evidence_chain", [])
    data.setdefault("visualization", [])
    data.setdefault("suggested_actions", [])
    data.setdefault("summary", "")
    return data


def _resolve_contract(
    text: str,
    last_spc_result: Optional[Tuple[str, Dict[str, Any]]],
    chart_already_rendered: bool = False,
) -> Optional[Dict[str, Any]]:
    """Return the best contract for a synthesis response.

    CHART 鐵律 — visualization 只能來自 tool（chart_intents / SPC auto-build）。
    LLM 若自行在 <contract> 的 visualization 欄位塞 spec，一律丟棄。
    """
    parsed = _parse_contract(text)
    auto = _build_spc_contract(*last_spc_result) if last_spc_result else None

    if parsed is not None:
        llm_viz = parsed.get("visualization") or []
        if llm_viz:
            logger.warning(
                "LLM embedded %d visualization items in <contract> — discarded per CHART 鐵律.",
                len(llm_viz),
            )
        parsed["visualization"] = []

    if chart_already_rendered:
        return parsed

    if parsed is None:
        return auto

    if auto and not parsed.get("visualization"):
        parsed["visualization"] = auto.get("visualization", [])

    return parsed
