"""ChartMiddleware — automatic chart generation from output_schema + findings.outputs.

Middleware layer between Skill execution and frontend rendering.
Responsibility: transform raw data → chart DSL based on output_schema type declarations.

LLM code only needs to produce data in _findings.outputs.
ChartMiddleware reads output_schema types and auto-generates chart DSL.

Extensible via register():
    ChartMiddleware.register("heatmap", build_heatmap)
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# Chart DSL color palette (consistent with frontend ChartIntentRenderer)
_SERIES_COLORS = ["#4299e1", "#38a169", "#d69e2e", "#9f7aea", "#ed8936", "#e53e3e"]

# ── Chart type → builder registry ──────────────────────────────────────────────

_BUILDERS: Dict[str, Callable[[Any, dict], Any]] = {}


def register(schema_type: str, builder: Callable[[Any, dict], Any]) -> None:
    """Register a chart builder for a given output_schema type."""
    _BUILDERS[schema_type] = builder


def process(outputs: Dict[str, Any], output_schema: List[dict]) -> List[dict]:
    """Process all output_schema fields and auto-generate charts.

    Returns a list of chart DSL dicts ready for frontend rendering.
    Only processes fields whose type has a registered builder.

    Logs:
      - INFO when a builder runs and produces ≥1 chart
      - WARNING when a builder runs but produces 0 charts (likely shape mismatch)
      - WARNING when a builder raises
      - DEBUG summary at end (count of fields scanned vs charts produced)
    """
    charts: List[dict] = []
    chart_fields_scanned = 0
    builders_run = 0

    for field in output_schema:
        field_type = field.get("type", "")
        builder = _BUILDERS.get(field_type)
        if not builder:
            continue
        chart_fields_scanned += 1
        key = field.get("key", "")
        data = outputs.get(key)
        if data is None:
            logger.warning(
                "ChartMiddleware skip: field key=%r type=%r — outputs[%r] is None (LLM code did not write this output)",
                key, field_type, key,
            )
            continue
        try:
            builders_run += 1
            data_summary = (
                f"list[{len(data)}]" if isinstance(data, list)
                else f"dict[{list(data.keys())[:5]}]" if isinstance(data, dict)
                else type(data).__name__
            )
            result = builder(data, field)
            produced = 0
            if isinstance(result, list):
                charts.extend(result)
                produced = len(result)
            elif isinstance(result, dict):
                charts.append(result)
                produced = 1
            if produced > 0:
                # WARNING level (not INFO) so it shows up under default uvicorn logging
                logger.warning(
                    "[ChartMiddleware ✅] builder=%r key=%r data=%s → %d chart(s)",
                    field_type, key, data_summary, produced,
                )
                # Diagnostic: log first chart's data sample (truncated) to detect "produced
                # 5 empty charts" failure mode where the builder counts a shape but the
                # actual chart.data list is empty/wrong.
                try:
                    first = result[0] if isinstance(result, list) and result else result
                    sample_data = (first or {}).get("data") if isinstance(first, dict) else None
                    sample_len = len(sample_data) if isinstance(sample_data, list) else "?"
                    sample_first = sample_data[0] if isinstance(sample_data, list) and sample_data else None
                    logger.warning(
                        "[ChartMiddleware ↳] first_chart_title=%r data_rows=%s first_row=%s",
                        (first or {}).get("title") if isinstance(first, dict) else None,
                        sample_len,
                        str(sample_first)[:200] if sample_first else None,
                    )
                except Exception:
                    pass
            else:
                logger.warning(
                    "ChartMiddleware ZERO charts: builder=%r key=%r data=%s — "
                    "shape may not match builder expectation",
                    field_type, key, data_summary,
                )
        except Exception as exc:
            logger.warning(
                "ChartMiddleware FAIL: builder=%r key=%r exc=%s",
                field_type, key, exc, exc_info=True,
            )

    if chart_fields_scanned == 0:
        logger.debug("ChartMiddleware: output_schema has no chart-type fields")
    else:
        logger.warning(
            "[ChartMiddleware Σ] %d chart-type field(s) scanned, %d builder run(s), %d chart(s) produced",
            chart_fields_scanned, builders_run, len(charts),
        )

    return charts


# ── Builders ───────────────────────────────────────────────────────────────────

def _unwrap_chart_data(data: Any) -> Any:
    """Generic tolerant unwrap for chart builders.

    LLMs often wrap the flat row list in a metadata dict like:
        {"type": "line_chart", "x_key": "eventTime", "y_keys": [...], "data": [...]}
        {"data": [...], "metadata": {...}}
        {"records": [...]}

    This helper detects common wrapper shapes and returns the inner list.
    Falls back to the original value if no known wrapper is recognised.
    """
    if not isinstance(data, dict):
        return data
    # Common wrapper keys, tried in order
    for k in ("data", "records", "rows", "items", "points", "data_points"):
        v = data.get(k)
        if isinstance(v, list):
            return v
    return data


def _looks_like_spc_rows(lst: Any, group_key: str) -> bool:
    """True if lst is a non-empty list of dicts where at least one dict has group_key."""
    if not isinstance(lst, list) or not lst:
        return False
    # Require at least one dict element AND the group_key present somewhere in the list
    # (not every row needs it — could be missing due to LLM inconsistency, but at least one
    #  indicates this IS the flat-row list we're after rather than some coincidental list)
    has_dict = any(isinstance(r, dict) for r in lst)
    if not has_dict:
        return False
    has_group = any(isinstance(r, dict) and group_key in r for r in lst)
    # Fallback: if no row has group_key but every row has value+ucl+lcl, accept it
    # (the group_key may need to be injected from an outer key)
    if has_group:
        return True
    return False


def _deep_find_spc_list(obj: Any, group_key: str, depth: int = 0, max_depth: int = 4) -> Optional[List[dict]]:
    """Recursively search obj for the first list of dicts that looks like SPC rows."""
    if depth > max_depth:
        return None
    if _looks_like_spc_rows(obj, group_key):
        return obj  # type: ignore[return-value]
    if isinstance(obj, dict):
        # Prefer well-known wrapper keys first (faster convergence)
        for wrapper_key in ("data", "records", "rows", "items", "points", "data_points"):
            inner = obj.get(wrapper_key)
            if _looks_like_spc_rows(inner, group_key):
                return inner  # type: ignore[return-value]
        # Then walk every key
        for v in obj.values():
            found = _deep_find_spc_list(v, group_key, depth + 1, max_depth)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _deep_find_spc_list(item, group_key, depth + 1, max_depth)
            if found is not None:
                return found
    return None


def _normalize_spc_input(data: Any, group_key: str) -> List[dict]:
    """Normalize tolerated SPC input shapes into the canonical flat list.

    Canonical shape (preferred):
        [{group_key: "xbar_chart", "eventTime": ..., "value": ..., "ucl": ..., "lcl": ..., "is_ooc": ...}, ...]

    Tolerated shapes (auto-flattened):
      A) flat list at top level → use as-is
      B) any list of SPC-row-dicts nested inside a dict (any depth ≤ 4) → extract via DFS.
         Handles wrappers like:
           {"data": [...], ...metadata}
           {"chart_visualization": {"data": [...], ...}}
           {"records": [...]}
           {"items": [...]}
      C) nested-by-group: {"xbar_chart": {"data_points": [...]}, "r_chart": [...], ...}
         → flatten with group_key injected from the outer key
      D) {"charts": {...nested-by-group...}} → unwrap then flatten
      E) nested-by-group with arbitrary inner list keys: any dict value where _any_
         dict-or-list child looks like SPC rows → use that, inject group_name
      F) nested-by-group with parallel arrays: {xbar_chart: {values:[...], event_times:[...], ucl:N, lcl:N}, ...}
         → zip and flatten
    Returns [] for unrecognised shapes.
    """
    if isinstance(data, list):
        return data  # already canonical (or empty)
    if not isinstance(data, dict):
        return []

    # B) Try deep search for an explicit flat list first (handles arbitrary wrappers)
    found = _deep_find_spc_list(data, group_key)
    if found is not None:
        return found

    # D) Unwrap legacy {"charts": {...}} if present, then fall through to nested-flatten
    if "charts" in data and isinstance(data["charts"], dict):
        data = data["charts"]

    # C / E) Nested-by-group: {"xbar_chart": {...}|[...], ...}
    flat: List[dict] = []
    for group_name, group_val in data.items():
        # C1: {group_name: [{...row}, ...]}
        if isinstance(group_val, list):
            for p in group_val:
                if isinstance(p, dict):
                    row = dict(p)
                    row.setdefault(group_key, group_name)
                    flat.append(row)
            continue
        # C2: {group_name: {"data_points": [...]} or {"data": [...]} or {"records": [...]} ...}
        if isinstance(group_val, dict):
            inner_list = None
            for inner_key in ("data_points", "data", "records", "rows", "items", "points", "values"):
                v = group_val.get(inner_key)
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    inner_list = v
                    break
            if inner_list is not None:
                for p in inner_list:
                    row = dict(p)
                    row.setdefault(group_key, group_name)
                    flat.append(row)
                continue

            # F) Parallel-arrays form: {group_name: {"values":[v1,v2,...], "event_times":[t1,t2,...], "ucl": N, "lcl": N}}
            #    Detect any list of scalars and try to zip with sibling lists.
            scalar_lists = {
                k: v for k, v in group_val.items()
                if isinstance(v, list) and v and not isinstance(v[0], dict)
            }
            scalars = {
                k: v for k, v in group_val.items()
                if not isinstance(v, (list, dict))
            }
            if scalar_lists:
                # find the longest list as the row count
                n = max(len(v) for v in scalar_lists.values())
                for i in range(n):
                    row: dict = {group_key: group_name}
                    for k, v in scalar_lists.items():
                        if i < len(v):
                            # normalize common key aliases to canonical names
                            kn = {"event_times": "eventTime", "eventtimes": "eventTime",
                                  "values": "value", "ucls": "ucl", "lcls": "lcl",
                                  "is_oocs": "is_ooc"}.get(k.lower(), k)
                            row[kn] = v[i]
                    # Broadcast scalar fields onto every row (e.g. ucl/lcl)
                    for k, v in scalars.items():
                        if k != group_key:
                            row.setdefault(k, v)
                    flat.append(row)
                continue
    return flat


def _build_spc_chart(data: Any, schema: dict) -> List[dict]:
    """SPC chart: split by group_key into independent charts with per-group UCL/LCL rules.

    Input data: list of flat dicts with group_key (e.g. chart_type), value, ucl, lcl, is_ooc.
    Output: one chart DSL per group (e.g. 5 charts for xbar/r/s/p/c).
    """
    group_key = schema.get("group_key", "chart_type")
    data = _normalize_spc_input(data, group_key)
    if not data:
        return []

    x_key = schema.get("x_key", "eventTime")
    value_key = schema.get("value_key", "value")
    ucl_key = schema.get("ucl_key", "ucl")
    lcl_key = schema.get("lcl_key", "lcl")
    highlight_key = schema.get("highlight_key", "is_ooc")

    # Group data
    groups: Dict[str, list] = {}
    for record in data:
        g = str(record.get(group_key, "unknown"))
        groups.setdefault(g, []).append(record)

    _TITLE_MAP = {
        "xbar_chart": "X-bar", "r_chart": "R", "s_chart": "S",
        "p_chart": "P", "c_chart": "C",
    }

    charts = []
    for group_name in sorted(groups.keys()):
        group_data = groups[group_name]
        # Sort chronologically
        group_data.sort(key=lambda r: str(r.get(x_key, "")))

        # Extract UCL/LCL from first record (consistent within group)
        ucl = group_data[0].get(ucl_key)
        lcl = group_data[0].get(lcl_key)
        values = [r.get(value_key) for r in group_data if r.get(value_key) is not None]
        cl = sum(values) / len(values) if values else 0

        rules = []
        if ucl is not None:
            rules.append({"value": ucl, "label": "UCL", "style": "danger"})
        if lcl is not None:
            rules.append({"value": lcl, "label": "LCL", "style": "danger"})
        rules.append({"value": round(cl, 4), "label": "CL", "style": "center"})

        title = f"{_TITLE_MAP.get(group_name, group_name)} Chart"
        label = schema.get("label", "")
        if label:
            title = f"{title} — {label}"

        charts.append({
            "type": "line",
            "title": title,
            "data": group_data,
            "x": x_key,
            "y": [value_key],
            "rules": rules,
            "highlight": {"field": highlight_key, "eq": True} if highlight_key else None,
        })

    return charts


def _build_line_chart(data: Any, schema: dict) -> Optional[dict]:
    """Single line chart."""
    data = _unwrap_chart_data(data)
    if not isinstance(data, list) or not data:
        return None
    x_key = schema.get("x_key", "index")
    y_keys = schema.get("y_keys", ["value"])
    highlight_key = schema.get("highlight_key")

    rules = []
    # Auto-detect UCL/LCL from data if present
    if data and isinstance(data[0], dict):
        sample = data[0]
        if "ucl" in sample and "ucl" not in y_keys:
            rules.append({"value": sample["ucl"], "label": "UCL", "style": "danger"})
        if "lcl" in sample and "lcl" not in y_keys:
            rules.append({"value": sample["lcl"], "label": "LCL", "style": "danger"})

    return {
        "type": "line",
        "title": schema.get("label", "Chart"),
        "data": data,
        "x": x_key,
        "y": y_keys,
        "rules": rules,
        "highlight": {"field": highlight_key, "eq": True} if highlight_key else None,
    }


def _build_bar_chart(data: Any, schema: dict) -> Optional[dict]:
    """Bar chart."""
    data = _unwrap_chart_data(data)
    if not isinstance(data, list) or not data:
        return None
    return {
        "type": "bar",
        "title": schema.get("label", "Chart"),
        "data": data,
        "x": schema.get("x_key", "category"),
        "y": schema.get("y_keys", ["value"]),
        "rules": [],
        "highlight": None,
    }


def _build_scatter_chart(data: Any, schema: dict) -> Optional[dict]:
    """Scatter plot."""
    data = _unwrap_chart_data(data)
    if not isinstance(data, list) or not data:
        return None
    return {
        "type": "scatter",
        "title": schema.get("label", "Chart"),
        "data": data,
        "x": schema.get("x_key", "x"),
        "y": schema.get("y_keys", ["y"]),
        "rules": [],
        "highlight": {"field": schema.get("highlight_key"), "eq": True} if schema.get("highlight_key") else None,
    }


def _build_multi_line_chart(data: Any, schema: dict) -> List[dict]:
    """Multi-line chart: one chart per group."""
    data = _unwrap_chart_data(data)
    if not isinstance(data, list) or not data:
        return []

    group_key = schema.get("group_key", "group")
    x_key = schema.get("x_key", "eventTime")
    y_key = schema.get("y_key", "value")
    highlight_key = schema.get("highlight_key")

    groups: Dict[str, list] = {}
    for record in data:
        g = str(record.get(group_key, "default"))
        groups.setdefault(g, []).append(record)

    charts = []
    for group_name, group_data in sorted(groups.items()):
        group_data.sort(key=lambda r: str(r.get(x_key, "")))
        charts.append({
            "type": "line",
            "title": f"{schema.get('label', 'Chart')} — {group_name}",
            "data": group_data,
            "x": x_key,
            "y": [y_key],
            "rules": [],
            "highlight": {"field": highlight_key, "eq": True} if highlight_key else None,
        })

    return charts


# ── Register built-in builders ─────────────────────────────────────────────────

register("spc_chart", _build_spc_chart)
register("line_chart", _build_line_chart)
register("bar_chart", _build_bar_chart)
register("scatter_chart", _build_scatter_chart)
register("multi_line_chart", _build_multi_line_chart)
