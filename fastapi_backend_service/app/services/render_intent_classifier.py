"""Render intent classifier — decides how to present MCP raw data.

Pure structure-driven classifier. Does NOT inspect user_query keywords; instead
inspects the shape of the raw data returned by MCP and decides:

  AUTO_CHART  → instant render as chart, with [Switch to table] button
  AUTO_TABLE  → instant render as table, with [Switch to cards] button (if applicable)
  AUTO_SCALAR → render as a single status / number / badge
  ASK_USER    → multiple plausible renders, present a choice card to the user

Design principles:
  1. Description-driven, not keyword-driven. Classifier uses data structure +
     optional MCP `render_intent` hint, NEVER user_query keyword matching.
  2. Confirmation over guessing. When multiple renders are plausible, ask.
  3. No prompt-side hardcoding of MCP usage.

The classifier returns a RenderDecision with the primary render plus a list of
alternative renders that the frontend can switch to instantly (without re-call).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class RenderKind(str, Enum):
    AUTO_CHART = "auto_chart"
    AUTO_TABLE = "auto_table"
    AUTO_SCALAR = "auto_scalar"
    ASK_USER = "ask_user"


@dataclass
class RenderOption:
    """One way to present the data. Either default or alternative."""
    id: str                       # stable id (e.g. "chart_spc", "table_flat")
    label: str                    # user-visible label (Chinese)
    kind: str                     # "spc_chart" | "line_chart" | "table" | "scalar" | "filtered_chart"
    output_schema: List[Dict[str, Any]]  # passed to chart_middleware
    transform: str = "passthrough"  # how to project raw_data → outputs (see _build_outputs)
    transform_args: Dict[str, Any] = field(default_factory=dict)
    recommended: bool = False


@dataclass
class RenderDecision:
    kind: RenderKind
    primary: Optional[RenderOption]                # None when kind == ASK_USER
    alternatives: List[RenderOption] = field(default_factory=list)
    question: str = ""                             # only set when ASK_USER


# ── Structure detectors ───────────────────────────────────────────────────────

def _is_event_list(data: Any) -> bool:
    """True if data looks like a list of process events with timestamps."""
    if not isinstance(data, list) or len(data) == 0:
        return False
    first = data[0]
    if not isinstance(first, dict):
        return False
    # Heuristic: has eventTime or timestamp
    return any(k in first for k in ("eventTime", "timestamp", "time", "ts"))


def _has_spc_charts_nested(data: Any) -> bool:
    """True if event records contain SPC.charts.{xbar/r/s/p/c}_chart structure."""
    if not isinstance(data, list) or not data:
        return False
    for ev in data[:5]:  # only inspect first few
        if not isinstance(ev, dict):
            continue
        spc = ev.get("SPC")
        if isinstance(spc, dict):
            charts = spc.get("charts")
            if isinstance(charts, dict) and any(
                k.endswith("_chart") for k in charts.keys()
            ):
                return True
    return False


def _has_apc_parameters(data: Any) -> bool:
    """True if events contain APC.parameters dict."""
    if not isinstance(data, list) or not data:
        return False
    for ev in data[:5]:
        if isinstance(ev, dict) and isinstance(ev.get("APC"), dict):
            params = ev["APC"].get("parameters")
            if isinstance(params, dict) and len(params) > 0:
                return True
    return False


def _has_dc_parameters(data: Any) -> bool:
    if not isinstance(data, list) or not data:
        return False
    for ev in data[:5]:
        if isinstance(ev, dict) and isinstance(ev.get("DC"), dict):
            params = ev["DC"].get("parameters")
            if isinstance(params, dict) and len(params) > 0:
                return True
    return False


def _has_recipe_parameters(data: Any) -> bool:
    if not isinstance(data, list) or not data:
        return False
    for ev in data[:5]:
        if isinstance(ev, dict) and isinstance(ev.get("RECIPE"), dict):
            params = ev["RECIPE"].get("parameters")
            if isinstance(params, dict) and len(params) > 0:
                return True
    return False


def _has_fdc_classification(data: Any) -> bool:
    if not isinstance(data, list) or not data:
        return False
    for ev in data[:5]:
        if isinstance(ev, dict) and isinstance(ev.get("FDC"), dict):
            if ev["FDC"].get("classification"):
                return True
    return False


def _has_ec_constants(data: Any) -> bool:
    if not isinstance(data, list) or not data:
        return False
    for ev in data[:5]:
        if isinstance(ev, dict) and isinstance(ev.get("EC"), dict):
            if ev["EC"].get("constants"):
                return True
    return False


def _is_catalog_list(data: Any) -> bool:
    """True if data is a list of catalog-style records (no time, no measurement)."""
    if not isinstance(data, list) or len(data) == 0:
        return False
    first = data[0]
    if not isinstance(first, dict):
        return False
    # No time field AND no obvious measurement field
    has_time = any(k in first for k in ("eventTime", "timestamp"))
    has_value = any(k in first for k in ("value", "measurement", "reading"))
    return not has_time and not has_value


def _is_scalar_response(data: Any) -> bool:
    """True if data is a single dict with mostly scalar fields (status / counts)."""
    if not isinstance(data, dict):
        return False
    # All values are scalar (no list / no nested dict beyond 1 level)
    scalar_count = sum(
        1 for v in data.values()
        if v is None or isinstance(v, (str, int, float, bool))
    )
    return scalar_count >= max(1, len(data) - 1)


# ── Builders for each render kind ─────────────────────────────────────────────

def _build_spc_chart_option(_data: Any) -> RenderOption:
    """5-chart SPC trend (xbar/r/s/p/c) — needs flat-list transform."""
    return RenderOption(
        id="spc_5_chart",
        label="SPC 5 chart trend (X-bar / R / S / P / C)",
        kind="spc_chart",
        output_schema=[{
            "key": "spc_data",
            "type": "spc_chart",
            "label": "SPC 管制圖",
            "group_key": "chart_type",
            "x_key": "eventTime",
            "value_key": "value",
            "ucl_key": "ucl",
            "lcl_key": "lcl",
            "highlight_key": "is_ooc",
        }],
        transform="spc_flatten",
        recommended=True,
    )


def _build_event_table_option(data: List[dict]) -> RenderOption:
    """Flat table of events. Picks columns from first event keys (excluding nested objects)."""
    columns: List[Dict[str, str]] = []
    if data and isinstance(data[0], dict):
        for k, v in data[0].items():
            # Skip nested object fields (SPC/APC/DC/RECIPE) — they bloat the table
            if isinstance(v, (dict, list)):
                continue
            columns.append({"key": k, "label": k, "type": "string"})
    return RenderOption(
        id="event_table",
        label=f"Table ({len(data)} 筆)",
        kind="table",
        output_schema=[{
            "key": "events_table",
            "type": "table",
            "label": "事件列表",
            "columns": columns,
        }],
        transform="passthrough",
        transform_args={"output_key": "events_table"},
    )


def _build_ooc_only_option(data: List[dict]) -> RenderOption:
    """Filter to spc_status='OOC' only — useful when most data is PASS."""
    return RenderOption(
        id="ooc_only",
        label="只看 OOC 事件",
        kind="filtered_table",
        output_schema=[{
            "key": "ooc_events",
            "type": "table",
            "label": "OOC 事件",
            "columns": [
                {"key": "eventTime", "label": "事件時間", "type": "string"},
                {"key": "lotID", "label": "批號", "type": "string"},
                {"key": "toolID", "label": "機台", "type": "string"},
                {"key": "step", "label": "站點", "type": "string"},
                {"key": "spc_status", "label": "SPC 狀態", "type": "string"},
            ],
        }],
        transform="filter_ooc",
        transform_args={"output_key": "ooc_events"},
    )


def _build_apc_param_chart_option(_data: Any) -> RenderOption:
    """Multi-line chart of all APC params over time."""
    return RenderOption(
        id="apc_multi_line",
        label="APC 參數趨勢 (multi-line)",
        kind="multi_line_chart",
        output_schema=[{
            "key": "apc_trend",
            "type": "multi_line_chart",
            "label": "APC 參數趨勢",
            "group_key": "parameter_name",
            "x_key": "eventTime",
            "y_key": "value",
        }],
        transform="apc_flatten_multiline",
        recommended=True,
    )


def _build_dc_param_chart_option(_data: Any) -> RenderOption:
    return RenderOption(
        id="dc_multi_line",
        label="DC sensor 趨勢 (multi-line)",
        kind="multi_line_chart",
        output_schema=[{
            "key": "dc_trend",
            "type": "multi_line_chart",
            "label": "DC sensor 趨勢",
            "group_key": "parameter_name",
            "x_key": "eventTime",
            "y_key": "value",
        }],
        transform="dc_flatten_multiline",
        recommended=True,
    )


def _build_recipe_table_option(_data: Any) -> RenderOption:
    return RenderOption(
        id="recipe_table",
        label="Recipe 參數列表",
        kind="table",
        output_schema=[{
            "key": "recipe_params",
            "type": "table",
            "label": "Recipe 參數",
            "columns": [
                {"key": "parameter_name", "label": "參數名稱", "type": "string"},
                {"key": "value", "label": "數值", "type": "number"},
            ],
        }],
        transform="recipe_to_param_table",
        transform_args={"output_key": "recipe_params"},
        recommended=True,
    )


def _build_summary_text_option() -> RenderOption:
    """Pure text summary — no chart, no table. Used as 4th option in ASK_USER."""
    return RenderOption(
        id="summary_text",
        label="純文字摘要",
        kind="scalar",
        output_schema=[{"key": "summary", "type": "scalar", "label": "摘要"}],
        transform="text_summary",
    )


def _build_catalog_table_option(data: List[dict]) -> RenderOption:
    """Table for catalog data (list_tools / list_skills / etc)."""
    columns: List[Dict[str, str]] = []
    if data and isinstance(data[0], dict):
        for k in list(data[0].keys())[:8]:  # cap at 8 columns
            columns.append({"key": k, "label": k, "type": "string"})
    return RenderOption(
        id="catalog_table",
        label=f"清單 ({len(data)} 筆)",
        kind="table",
        output_schema=[{
            "key": "catalog",
            "type": "table",
            "label": "清單",
            "columns": columns,
        }],
        transform="passthrough",
        transform_args={"output_key": "catalog"},
        recommended=True,
    )


def _build_scalar_option(data: Dict[str, Any]) -> RenderOption:
    """Single scalar/badge for status responses."""
    output_schema: List[Dict[str, Any]] = []
    for k in data.keys():
        if k.lower() in ("status", "state", "result"):
            output_schema.append({"key": k, "type": "badge", "label": k})
        else:
            output_schema.append({"key": k, "type": "scalar", "label": k})
    return RenderOption(
        id="status_scalars",
        label="狀態",
        kind="scalar",
        output_schema=output_schema,
        transform="passthrough",
        transform_args={"as_dict": True},
        recommended=True,
    )


# ── Main classifier ───────────────────────────────────────────────────────────

def classify_render_intent(
    raw_response: Any,
    mcp_name: str = "",
    user_query: str = "",  # included for future use; NOT used for keyword matching
) -> RenderDecision:
    """Classify how to present MCP raw response.

    Args:
        raw_response: the parsed response from execute_mcp.
        mcp_name: the MCP name (used to disambiguate ambiguous shapes — e.g.
                  list_tools always renders as catalog table).
        user_query: kept for future ML-based hint, currently unused. We do NOT
                    pattern-match keywords here per design principle 2.

    Returns:
        RenderDecision describing the primary render and alternatives.
    """
    # ── Step 1: unwrap common envelopes ──
    data = raw_response
    # /process/info returns {"total":..., "events": [...]}
    if isinstance(data, dict) and isinstance(data.get("events"), list):
        data = data["events"]
    # Some MCPs wrap as {"data": ...} or {"result": ...}
    elif isinstance(data, dict):
        for k in ("data", "result", "items", "rows"):
            if isinstance(data.get(k), list):
                data = data[k]
                break

    # ── Step 2: scalar response → AUTO_SCALAR ──
    if _is_scalar_response(data):
        return RenderDecision(
            kind=RenderKind.AUTO_SCALAR,
            primary=_build_scalar_option(data),
            alternatives=[],
        )

    # ── Step 3: empty list → AUTO_TABLE with empty state ──
    if isinstance(data, list) and len(data) == 0:
        return RenderDecision(
            kind=RenderKind.AUTO_TABLE,
            primary=RenderOption(
                id="empty",
                label="無資料",
                kind="table",
                output_schema=[{"key": "empty", "type": "scalar", "label": "結果"}],
                transform="empty",
            ),
        )

    # ── Step 4: catalog list (no time, no measurement) → AUTO_TABLE ──
    if _is_catalog_list(data):
        return RenderDecision(
            kind=RenderKind.AUTO_TABLE,
            primary=_build_catalog_table_option(data),
            alternatives=[],
        )

    # ── Step 5: event list with SPC nested → ASK_USER (multiple renders all valid) ──
    if _is_event_list(data) and _has_spc_charts_nested(data):
        n = len(data) if isinstance(data, list) else 0
        primary = _build_spc_chart_option(data)
        alts: List[RenderOption] = [
            _build_event_table_option(data),
            _build_ooc_only_option(data),
        ]
        # APC / DC / RECIPE alternative if event also has those nested structures
        if _has_apc_parameters(data):
            alts.append(_build_apc_param_chart_option(data))
        if _has_dc_parameters(data):
            alts.append(_build_dc_param_chart_option(data))
        if _has_recipe_parameters(data):
            alts.append(_build_recipe_table_option(data))
        return RenderDecision(
            kind=RenderKind.AUTO_CHART,  # default to chart, but offer alternatives
            primary=primary,
            alternatives=alts,
        )

    # ── Step 6: event list without SPC nested ──
    if _is_event_list(data):
        n = len(data) if isinstance(data, list) else 0
        if n >= 5:
            # Multiple plausible renders → ASK_USER
            return RenderDecision(
                kind=RenderKind.ASK_USER,
                primary=None,
                question=f"取得 {n} 筆事件資料，要怎麼呈現？",
                alternatives=[
                    _build_event_table_option(data),
                    _build_ooc_only_option(data),
                    _build_summary_text_option(),
                ],
            )
        else:
            # Small list → just show as table
            return RenderDecision(
                kind=RenderKind.AUTO_TABLE,
                primary=_build_event_table_option(data),
            )

    # ── Step 7: fallback — anything we don't recognise → ASK_USER ──
    return RenderDecision(
        kind=RenderKind.ASK_USER,
        primary=None,
        question="取得資料但結構未知，要怎麼呈現？",
        alternatives=[
            _build_summary_text_option(),
        ],
    )


# ── Transform functions: build chart_middleware-ready outputs from raw_data ──

def build_outputs(option: RenderOption, raw_response: Any) -> Dict[str, Any]:
    """Apply the option's transform to raw_response, returning a dict suitable
    for chart_middleware.process(outputs, output_schema).
    """
    transform = option.transform
    args = option.transform_args or {}

    # Unwrap envelope (same as classifier)
    data = raw_response
    if isinstance(data, dict) and isinstance(data.get("events"), list):
        data = data["events"]

    if transform == "passthrough":
        if args.get("as_dict") and isinstance(raw_response, dict):
            return dict(raw_response)
        key = args.get("output_key") or (option.output_schema[0]["key"] if option.output_schema else "data")
        return {key: data}

    if transform == "spc_flatten":
        # Convert events with SPC.charts.* nested into flat list of records
        flat: List[Dict[str, Any]] = []
        events = data if isinstance(data, list) else []
        for ev in events:
            if not isinstance(ev, dict):
                continue
            spc = ev.get("SPC") or {}
            charts = spc.get("charts") or {}
            event_time = ev.get("eventTime")
            lot_id = ev.get("lotID")
            tool_id = ev.get("toolID")
            for chart_name, chart_data in charts.items():
                if not isinstance(chart_data, dict):
                    continue
                flat.append({
                    "chart_type": chart_name,
                    "eventTime": event_time,
                    "lotID": lot_id,
                    "toolID": tool_id,
                    "value": chart_data.get("value"),
                    "ucl": chart_data.get("ucl"),
                    "lcl": chart_data.get("lcl"),
                    "is_ooc": chart_data.get("is_ooc", False),
                })
        return {"spc_data": flat}

    if transform == "filter_ooc":
        events = data if isinstance(data, list) else []
        ooc = [ev for ev in events if isinstance(ev, dict) and ev.get("spc_status") == "OOC"]
        # Strip nested object fields
        flat_ooc = []
        for ev in ooc:
            flat_ooc.append({
                k: v for k, v in ev.items() if not isinstance(v, (dict, list))
            })
        return {args.get("output_key", "ooc_events"): flat_ooc}

    if transform == "apc_flatten_multiline":
        flat: List[Dict[str, Any]] = []
        events = data if isinstance(data, list) else []
        for ev in events:
            if not isinstance(ev, dict):
                continue
            apc = ev.get("APC") or {}
            params = apc.get("parameters") or {}
            event_time = ev.get("eventTime")
            for pname, pval in params.items():
                if isinstance(pval, (int, float)):
                    flat.append({
                        "parameter_name": pname,
                        "eventTime": event_time,
                        "value": pval,
                    })
        return {"apc_trend": flat}

    if transform == "dc_flatten_multiline":
        flat: List[Dict[str, Any]] = []
        events = data if isinstance(data, list) else []
        for ev in events:
            if not isinstance(ev, dict):
                continue
            dc = ev.get("DC") or {}
            params = dc.get("parameters") or {}
            event_time = ev.get("eventTime")
            for pname, pval in params.items():
                if isinstance(pval, (int, float)):
                    flat.append({
                        "parameter_name": pname,
                        "eventTime": event_time,
                        "value": pval,
                    })
        return {"dc_trend": flat}

    if transform == "recipe_to_param_table":
        # Take RECIPE.parameters from the most recent event (events sorted DESC by simulator)
        events = data if isinstance(data, list) else []
        if not events:
            return {args.get("output_key", "recipe_params"): []}
        first = events[0] if isinstance(events[0], dict) else {}
        recipe = first.get("RECIPE") or {}
        params = recipe.get("parameters") or {}
        rows = [{"parameter_name": k, "value": v} for k, v in params.items()]
        return {args.get("output_key", "recipe_params"): rows}

    if transform == "text_summary":
        n = len(data) if isinstance(data, list) else 1
        return {"summary": f"共 {n} 筆資料。"}

    if transform == "empty":
        return {"empty": "(無資料)"}

    # Unknown transform — passthrough
    return {"data": data}
