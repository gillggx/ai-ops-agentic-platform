"""Data Flattener — transforms nested ontology JSON into 6 flat datasets.

Pure Python, zero LLM. Called after MCP data retrieval to prepare data
for frontend ChartExplorer and LLM diagnosis.

Input:  raw get_process_info response {total, events: [{SPC:{...}, APC:{...}, ...}]}
Output: FlattenedResult with 6 flat datasets + metadata
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class FlattenedResult:
    """All 6 flat datasets + metadata for frontend/LLM consumption."""
    spc_data: List[Dict[str, Any]] = field(default_factory=list)
    apc_data: List[Dict[str, Any]] = field(default_factory=list)
    dc_data: List[Dict[str, Any]] = field(default_factory=list)
    recipe_data: List[Dict[str, Any]] = field(default_factory=list)
    fdc_data: List[Dict[str, Any]] = field(default_factory=list)
    ec_data: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "spc_data": self.spc_data,
            "apc_data": self.apc_data,
            "dc_data": self.dc_data,
            "recipe_data": self.recipe_data,
            "fdc_data": self.fdc_data,
            "ec_data": self.ec_data,
            "metadata": self.metadata,
        }

    def dataset_for(self, name: str) -> List[Dict[str, Any]]:
        return getattr(self, name, [])

    @property
    def available_datasets(self) -> List[str]:
        out = []
        for name in ("spc_data", "apc_data", "dc_data", "recipe_data", "fdc_data", "ec_data"):
            if getattr(self, name):
                out.append(name)
        return out


def flatten(raw_response: Any) -> FlattenedResult:
    """Main entry. Accepts get_process_info response, returns FlattenedResult."""
    # Unwrap envelope
    events: List[Dict[str, Any]] = []
    total = 0
    if isinstance(raw_response, dict):
        events = raw_response.get("events", [])
        total = raw_response.get("total", len(events))
    elif isinstance(raw_response, list):
        # Sometimes wrapped as [{total, events}]
        if len(raw_response) == 1 and isinstance(raw_response[0], dict) and "events" in raw_response[0]:
            events = raw_response[0].get("events", [])
            total = raw_response[0].get("total", len(events))
        else:
            events = raw_response
            total = len(events)

    if not events:
        return FlattenedResult(metadata={"total_events": 0, "ooc_count": 0, "ooc_rate": 0})

    result = FlattenedResult()
    result.spc_data = _flatten_spc(events)
    result.apc_data = _flatten_apc(events)
    result.dc_data = _flatten_dc(events)
    result.recipe_data = _flatten_recipe(events)
    result.fdc_data = _flatten_fdc(events)
    result.ec_data = _flatten_ec(events)
    result.metadata = _build_metadata(events, total, result)

    logger.info(
        "[DataFlattener] %d events → spc=%d apc=%d dc=%d recipe=%d fdc=%d ec=%d",
        len(events), len(result.spc_data), len(result.apc_data),
        len(result.dc_data), len(result.recipe_data),
        len(result.fdc_data), len(result.ec_data),
    )
    return result


# ── Flatten functions ─────────────────────────────────────────────────────────

def _common_fields(ev: Dict[str, Any]) -> Dict[str, Any]:
    """Extract common event fields."""
    return {
        "eventTime": ev.get("eventTime"),
        "lotID": ev.get("lotID"),
        "toolID": ev.get("toolID"),
        "step": ev.get("step"),
    }


def _flatten_spc(events: List[Dict]) -> List[Dict]:
    flat = []
    for ev in events:
        spc = ev.get("SPC")
        if not isinstance(spc, dict):
            continue
        charts = spc.get("charts")
        if not isinstance(charts, dict):
            continue
        common = _common_fields(ev)
        common["spc_status"] = ev.get("spc_status", "")
        for chart_name, chart_data in charts.items():
            if not isinstance(chart_data, dict):
                continue
            flat.append({
                **common,
                "chart_type": chart_name,
                "value": chart_data.get("value"),
                "ucl": chart_data.get("ucl"),
                "lcl": chart_data.get("lcl"),
                "is_ooc": chart_data.get("is_ooc", False),
            })
    return flat


def _flatten_apc(events: List[Dict]) -> List[Dict]:
    flat = []
    for ev in events:
        apc = ev.get("APC")
        if not isinstance(apc, dict):
            continue
        params = apc.get("parameters")
        if not isinstance(params, dict):
            continue
        common = _common_fields(ev)
        for pname, pval in params.items():
            if isinstance(pval, (int, float)):
                flat.append({**common, "param_name": pname, "value": pval})
    return flat


def _flatten_dc(events: List[Dict]) -> List[Dict]:
    flat = []
    for ev in events:
        dc = ev.get("DC")
        if not isinstance(dc, dict):
            continue
        params = dc.get("parameters")
        if not isinstance(params, dict):
            continue
        common = _common_fields(ev)
        for sname, sval in params.items():
            if isinstance(sval, (int, float)):
                flat.append({**common, "sensor_name": sname, "value": sval})
    return flat


def _flatten_recipe(events: List[Dict]) -> List[Dict]:
    flat = []
    for ev in events:
        recipe = ev.get("RECIPE")
        if not isinstance(recipe, dict):
            continue
        common = _common_fields(ev)
        common["recipe_version"] = recipe.get("recipe_version")
        params = recipe.get("parameters")
        if isinstance(params, dict):
            for pname, pval in params.items():
                flat.append({**common, "param_name": pname, "value": pval})
    return flat


def _flatten_fdc(events: List[Dict]) -> List[Dict]:
    flat = []
    for ev in events:
        fdc = ev.get("FDC")
        if not isinstance(fdc, dict):
            continue
        common = _common_fields(ev)
        flat.append({
            **common,
            "classification": fdc.get("classification", "UNKNOWN"),
            "fault_code": fdc.get("fault_code", ""),
            "confidence": fdc.get("confidence"),
            "description": fdc.get("description", ""),
            "contributing_sensors": ", ".join(fdc.get("contributing_sensors", [])) if isinstance(fdc.get("contributing_sensors"), list) else "",
        })
    return flat


def _flatten_ec(events: List[Dict]) -> List[Dict]:
    flat = []
    for ev in events:
        ec = ev.get("EC")
        if not isinstance(ec, dict):
            continue
        constants = ec.get("constants")
        if not isinstance(constants, dict):
            continue
        common = _common_fields(ev)
        for cname, cdata in constants.items():
            if not isinstance(cdata, dict):
                continue
            flat.append({
                **common,
                "constant_name": cname,
                "value": cdata.get("value"),
                "nominal": cdata.get("nominal"),
                "tolerance_pct": cdata.get("tolerance_pct"),
                "deviation_pct": cdata.get("deviation_pct"),
                "status": cdata.get("status", "NORMAL"),
                "unit": cdata.get("unit", ""),
            })
    return flat


# ── Metadata ──────────────────────────────────────────────────────────────────

def _build_metadata(events: List[Dict], total: int, result: FlattenedResult) -> Dict[str, Any]:
    ooc_count = sum(1 for e in events if e.get("spc_status") == "OOC")
    ooc_rate = round(ooc_count / len(events) * 100, 2) if events else 0

    # OOC breakdown
    ooc_by_step: Dict[str, int] = {}
    ooc_by_tool: Dict[str, int] = {}
    for e in events:
        if e.get("spc_status") == "OOC":
            s = e.get("step", "?")
            t = e.get("toolID", "?")
            ooc_by_step[s] = ooc_by_step.get(s, 0) + 1
            ooc_by_tool[t] = ooc_by_tool.get(t, 0) + 1

    # Available fields per dataset
    field_lists: Dict[str, List[str]] = {}
    for ds_name in result.available_datasets:
        ds = result.dataset_for(ds_name)
        if ds:
            field_lists[ds_name] = list(ds[0].keys())

    # Enum values (for filter dropdowns)
    tools = sorted(set(e.get("toolID", "") for e in events if e.get("toolID")))
    steps = sorted(set(e.get("step", "") for e in events if e.get("step")))
    chart_types = sorted(set(r.get("chart_type", "") for r in result.spc_data if r.get("chart_type")))
    apc_params = sorted(set(r.get("param_name", "") for r in result.apc_data if r.get("param_name")))
    dc_sensors = sorted(set(r.get("sensor_name", "") for r in result.dc_data if r.get("sensor_name")))

    return {
        "total_events": total,
        "flattened_events": len(events),
        "ooc_count": ooc_count,
        "ooc_rate": ooc_rate,
        "ooc_by_step": dict(sorted(ooc_by_step.items(), key=lambda x: -x[1])),
        "ooc_by_tool": dict(sorted(ooc_by_tool.items(), key=lambda x: -x[1])),
        "available_datasets": result.available_datasets,
        "field_lists": field_lists,
        "enums": {
            "toolID": tools,
            "step": steps,
            "chart_type": chart_types,
            "apc_param": apc_params,
            "dc_sensor": dc_sensors,
        },
        "dataset_sizes": {
            ds: len(result.dataset_for(ds)) for ds in result.available_datasets
        },
    }


def build_llm_summary(metadata: Dict[str, Any], flat_result: Optional[FlattenedResult] = None) -> str:
    """Build a concise text summary for LLM.

    Includes: metadata overview + 3-row sample per dataset (so LLM knows exact field names
    and data format for execute_analysis code generation).
    """
    import json as _json

    lines = [
        "═══ DATA OVERVIEW ═══",
        f"total_events: {metadata.get('total_events', 0)}, "
        f"ooc_count: {metadata.get('ooc_count', 0)}, "
        f"ooc_rate: {metadata.get('ooc_rate', 0)}%",
    ]
    ooc_step = metadata.get("ooc_by_step", {})
    if ooc_step:
        lines.append("ooc_by_step: " + ", ".join(f"{s}:{n}" for s, n in list(ooc_step.items())[:5]))
    ooc_tool = metadata.get("ooc_by_tool", {})
    if ooc_tool:
        lines.append("ooc_by_tool: " + ", ".join(f"{t}:{n}" for t, n in list(ooc_tool.items())[:5]))
    lines.append(f"available_data: {', '.join(metadata.get('available_datasets', []))}")
    enums = metadata.get("enums", {})
    if enums.get("toolID"):
        lines.append(f"tools: {', '.join(enums['toolID'])}")
    if enums.get("step"):
        lines.append(f"steps: {', '.join(enums['step'])}")

    # Dataset sizes
    ds_sizes = metadata.get("dataset_sizes", {})
    if ds_sizes:
        lines.append("dataset_sizes: " + ", ".join(f"{k}={v}" for k, v in ds_sizes.items()))

    # Sample rows (3 per dataset) — so LLM knows exact field names and data format
    if flat_result:
        lines.append("")
        lines.append("═══ DATASET SAMPLES (3 rows each, for format reference) ═══")
        for ds_name in flat_result.available_datasets:
            ds = flat_result.dataset_for(ds_name)
            if ds:
                lines.append(f"\n{ds_name} ({len(ds)} rows):")
                for row in ds[:3]:
                    # Truncate long values
                    compact = {k: (round(v, 6) if isinstance(v, float) else v) for k, v in row.items()}
                    lines.append(f"  {_json.dumps(compact, ensure_ascii=False, default=str)}")

    lines.append("═════════════════════")
    lines.append("")
    lines.append("⚠️ 以上 flat_data 已暫存在系統中。如果需要 execute_analysis，")
    lines.append("   sandbox code 可直接用 _flat_data['spc_data'] 等欄位讀取完整資料，不需要再呼叫 MCP。")
    return "\n".join(lines)
