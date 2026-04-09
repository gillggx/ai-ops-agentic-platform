"""Service layer for MCPDefinition CRUD + LLM generation."""

import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx


def _resolve_url_params(endpoint_url: str, params: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    """Substitute {placeholder} in URL with matching params; return (resolved_url, remaining_params)."""
    url = endpoint_url
    remaining = dict(params)
    for key in re.findall(r"\{(\w+)\}", endpoint_url):
        if key in remaining:
            url = url.replace(f"{{{key}}}", str(remaining.pop(key)))
    return url, remaining

logger = logging.getLogger(__name__)

# SPC chart_name aliases → full form expected by the analytics endpoint.
# Handles short forms (xbar), user-facing variants (P-chart, P chart), and case.
_SPC_CHART_ALIASES: Dict[str, str] = {
    # short forms
    "xbar": "xbar_chart", "r": "r_chart", "s": "s_chart", "p": "p_chart", "c": "c_chart",
    # user variants — all case/separator combos normalize to <x>_chart
    "xbar-chart": "xbar_chart", "xbar chart": "xbar_chart", "x-bar": "xbar_chart", "x_bar": "xbar_chart",
    "r-chart":    "r_chart",    "r chart":    "r_chart",
    "s-chart":    "s_chart",    "s chart":    "s_chart",
    "p-chart":    "p_chart",    "p chart":    "p_chart",
    "c-chart":    "c_chart",    "c chart":    "c_chart",
}


def _normalize_chart_name(raw: str) -> str:
    """Normalize any chart_name variant to canonical form (e.g. 'P-chart' → 'p_chart')."""
    if not isinstance(raw, str):
        return raw
    key = raw.strip().lower()
    return _SPC_CHART_ALIASES.get(key, key)


def _normalize_params(params: Dict[str, Any], mcp_name: str = "") -> Dict[str, Any]:
    """Normalize known agent short-form values before forwarding to system MCP endpoints."""
    params = dict(params)  # shallow copy — don't mutate caller's dict

    if "chart_name" in params:
        params["chart_name"] = _normalize_chart_name(params["chart_name"])

    # ── snake_case → camelCase normalization ──────────────────────────────
    # Agent LLM sometimes uses snake_case (tool_id, lot_id) instead of camelCase
    _SNAKE_TO_CAMEL = {"tool_id": "toolID", "lot_id": "lotID", "event_time": "eventTime",
                       "recipe_id": "recipeID", "apc_id": "apcID", "object_name": "objectName"}
    for snake, camel in _SNAKE_TO_CAMEL.items():
        if snake in params and camel not in params:
            params[camel] = params.pop(snake)

    # ── query_object_timeseries: step → object_id fallback ─────────────
    if mcp_name == "query_object_timeseries" and "step" in params and "object_id" not in params:
        params["object_id"] = params.pop("step")

    # ── object_name / object_id → toolID / lotID mapping ─────────────────
    # list_recent_events uses generic object_name/object_id interface;
    # the underlying simulator /api/v1/events expects toolID / lotID.
    if "object_name" in params and "object_id" in params:
        obj_name = str(params.pop("object_name", "")).upper()
        obj_id = str(params.pop("object_id", ""))
        if obj_name == "TOOL":
            params["toolID"] = obj_id
        elif obj_name == "LOT":
            params["lotID"] = obj_id
        elif obj_name:
            params["object_name"] = obj_name
            params["object_id"] = obj_id

    return params


# ── Time-window ("since") parameter handling ──────────────────────────────────
# MCPs that support time-window filtering (backed by /api/v1/events).
# When agent passes `since="7d"`, backend transforms it into `start_time=<iso>`
# by fetching the simulator's latest event time and subtracting the duration.
_TIME_WINDOW_MCPS = {"get_process_events", "get_process_info", "query_object_timeseries"}

# Per-MCP default time window (applied when agent passes no since / start_time).
_DEFAULT_SINCE: Dict[str, str] = {
    "get_process_events":      "7d",
    "get_process_info":        "7d",
    "query_object_timeseries": "7d",   # 物件時序：��設看 7 天
}

# Per-MCP safety cap on returned rows (applied when agent passes no limit).
# OntologySimulator enforces limit <= 500 on /api/v1/events.
_DEFAULT_LIMIT: Dict[str, int] = {
    "get_process_events":      500,
    "get_process_info":        100,
    "query_object_timeseries": 500,
}
_MAX_LIMIT: Dict[str, int] = {
    "get_process_events":      500,
    "get_process_info":        100,
    "query_object_timeseries": 500,
}


# ── Since-param alias normalization ────────────────────────────────────────
# Agent likes to invent parameter names ('since_hours=24', 'hours=24', etc.).
# Instead of silently ignoring these and falling back to default, translate
# well-known variants to the canonical 'since' form.
_SINCE_NUMERIC_UNITS: Dict[str, str] = {
    # key name in params → duration unit suffix
    "since_hours": "h",
    "since_days":  "d",
    "since_weeks": "w",
    "hours":       "h",
    "days":        "d",
    "weeks":       "w",
}

# String-valued aliases — agent passes these shortcut words/phrases
_SINCE_STRING_ALIASES: Dict[str, str] = {
    "today":       "24h",
    "last_day":    "24h",
    "yesterday":   "48h",
    "this_week":   "7d",
    "last_week":   "7d",
    "week":        "7d",
    "this_month":  "30d",
    "last_month":  "30d",
    "month":       "30d",
}


class SinceParamError(ValueError):
    """Raised when the caller provides an invalid `since` param that can't be repaired."""
    pass


def _normalize_since_aliases(params: Dict[str, Any]) -> Dict[str, Any]:
    """Fold well-known since-param aliases into canonical `since="<N><unit>"`.

    Supported inputs:
        since="24h" / "7d" / "14d" / "30d" / "2w"     → canonical, passthrough
        since_hours=24 / since_days=7 / since_weeks=2  → since="24h" / "7d" / "2w"
        hours=24 / days=7 / weeks=2                    → same
        timeRange="today" / "week" / "month"           → "24h" / "7d" / "30d"
        since="today" / "week"                         → string alias expanded

    Mutates a copy of params (never the original). Removes alias keys after folding.
    """
    if not isinstance(params, dict):
        return params
    result = dict(params)

    # Numeric aliases (since_hours=24 → since="24h")
    for alias_key, unit in _SINCE_NUMERIC_UNITS.items():
        if alias_key in result:
            raw_val = result.pop(alias_key)
            try:
                n = int(raw_val)
                if n <= 0:
                    continue
                result.setdefault("since", f"{n}{unit}")
            except (TypeError, ValueError):
                continue

    # String alias expansion (timeRange="today" or since="today")
    for alias_key in ("timeRange", "time_range"):
        if alias_key in result:
            raw = result.pop(alias_key)
            if isinstance(raw, str):
                mapped = _SINCE_STRING_ALIASES.get(raw.strip().lower())
                if mapped:
                    result.setdefault("since", mapped)

    if "since" in result and isinstance(result["since"], str):
        key = result["since"].strip().lower()
        if key in _SINCE_STRING_ALIASES:
            result["since"] = _SINCE_STRING_ALIASES[key]

    return result


def _parse_duration(s: str) -> Optional[timedelta]:
    """Parse duration strings like '24h', '7d', '30d', '2w' → timedelta.

    Returns None on invalid input (caller should treat as "ignore since").
    """
    if not isinstance(s, str):
        return None
    m = re.match(r"^\s*(\d+)\s*([hdw])\s*$", s.lower())
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2)
    if unit == "h":
        return timedelta(hours=n)
    if unit == "d":
        return timedelta(days=n)
    if unit == "w":
        return timedelta(weeks=n)
    return None


async def _fetch_simulator_latest_time(sim_base: str) -> Optional[datetime]:
    """Get the most recent event timestamp from OntologySimulator.

    Simulator's timeline may not match wall-clock time, so we ask it for
    its own "now". Returns None if the call fails.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{sim_base}/api/v1/events", params={"limit": 1})
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list) and data:
                ts = data[0].get("eventTime")
                if isinstance(ts, str):
                    # Handle "2026-04-05T12:11:43.698000" style
                    return datetime.fromisoformat(ts.replace("Z", "+00:00").split("+")[0])
    except Exception as exc:
        logger.warning("_fetch_simulator_latest_time failed: %s", exc)
    return None


async def _resolve_since_param(
    mcp_name: str,
    params: Dict[str, Any],
    sim_base: str,
) -> Dict[str, Any]:
    """Transform `since` param → `start_time` ISO timestamp for the simulator.

    Flow:
      1. Normalize alias params (since_hours=24 → since="24h").
      2. If caller already passed `start_time`, respect it (explicit wins).
      3. Apply default limit if missing.
      4. Use `params["since"]` or MCP-specific default from _DEFAULT_SINCE.
      5. Fetch simulator's latest event time.
      6. Compute cutoff = latest - duration and inject as `start_time`.

    Raises SinceParamError if caller passed an explicit but un-parseable `since`
    (e.g. since="1x"). Default values are never rejected.

    Mutates a copy of params (never the original).
    """
    if mcp_name not in _TIME_WINDOW_MCPS:
        return params

    # Fold aliases first so downstream logic only sees canonical 'since'
    params = _normalize_since_aliases(params)

    # Apply default limit if missing; clamp to per-MCP max (simulator API limit)
    max_lim = _MAX_LIMIT.get(mcp_name, 500)
    if "limit" not in params or params.get("limit") in (None, ""):
        params["limit"] = _DEFAULT_LIMIT.get(mcp_name, 500)
    else:
        try:
            params["limit"] = min(int(params["limit"]), max_lim)
        except (TypeError, ValueError):
            params["limit"] = _DEFAULT_LIMIT.get(mcp_name, 500)

    # Explicit start_time wins
    if params.get("start_time"):
        params.pop("since", None)
        return params

    # Determine effective since — distinguish explicit vs default for error handling
    agent_supplied_since = params.pop("since", None)
    since_raw = agent_supplied_since or _DEFAULT_SINCE.get(mcp_name, "7d")
    duration = _parse_duration(since_raw)

    if duration is None:
        # If the agent explicitly passed a bad value, reject loudly so LLM can fix it.
        # If we fell back to default and that's somehow bad, log but don't crash.
        if agent_supplied_since is not None:
            raise SinceParamError(
                f"Invalid 'since' parameter: {agent_supplied_since!r}. "
                f"Must be a string like '24h', '7d', '14d', '30d' or '2w'. "
                f"Examples: since='24h' for today, since='7d' for the past week."
            )
        logger.warning("MCP '%s': default since='%s' invalid, skipping time-window filter", mcp_name, since_raw)
        return params

    latest = await _fetch_simulator_latest_time(sim_base)
    if latest is None:
        # Simulator call failed; fall back to no filter (limit will cap the result)
        return params

    cutoff = latest - duration
    params["start_time"] = cutoff.isoformat(timespec="seconds")
    logger.info(
        "MCP '%s': since=%s → start_time=%s (latest=%s, limit=%s)",
        mcp_name, since_raw, params["start_time"], latest.isoformat(), params["limit"],
    )
    return params


from app.config import get_settings
from app.core.exceptions import AppException
from app.models.mcp_definition import MCPDefinitionModel
from app.repositories.data_subject_repository import DataSubjectRepository
from app.repositories.mcp_definition_repository import MCPDefinitionRepository
from app.repositories.system_parameter_repository import SystemParameterRepository
from app.schemas.mcp_definition import (
    MCPAgentBuildRequest,
    MCPAgentBuildResponse,
    MCPCheckIntentResponse,
    MCPDefinitionCreate,
    MCPDefinitionResponse,
    MCPDefinitionUpdate,
    MCPGenerateResponse,
    MCPRunWithDataRequest,  # noqa: F401 — imported for re-use in router
    MCPRunWithFeedbackResponse,
    MCPTryRunResponse,
)
from app.services.mcp_builder_service import MCPBuilderService
from app.services.sandbox_service import execute_script
from app.utils.llm_utils import classify_error

_JSON_OPT = ("output_schema", "ui_render_config", "input_definition")


def _is_html_chart(s: Any) -> bool:
    """Return True if value looks like an HTML string (fig.to_html() output) rather than Plotly JSON."""
    return isinstance(s, str) and s.strip().startswith("<")


def _normalize_output(output_data: Any, llm_output_schema: Any) -> Dict[str, Any]:
    """Ensure output_data conforms to Standard Payload format.

    Standard Payload = {output_schema, dataset, ui_render: {type, charts, chart_data}}.
    If the sandbox script returned old-format data (no 'ui_render' key), wrap it.

    Multi-chart support: ui_render.charts is a list of Plotly JSON strings.
    chart_data is kept as charts[0] for backward compat.

    HTML sanitisation: if chart_data / charts[] contain HTML (fig.to_html() output),
    they are discarded so the auto-chart fallback can regenerate proper JSON charts.
    """
    # Normalise legacy ui_render_payload key → ui_render (old template scripts used wrong key)
    if isinstance(output_data, dict) and "ui_render_payload" in output_data and "ui_render" not in output_data:
        p = output_data.pop("ui_render_payload")
        chart = p.get("chart_data") if isinstance(p, dict) else None
        output_data["ui_render"] = {"type": "plotly", "chart_data": chart, "charts": [chart] if chart else []}

    # Already Standard Payload — trust it
    if isinstance(output_data, dict) and "ui_render" in output_data:
        output_data = dict(output_data)
        # Ensure output_schema is present (may be missing in early LLM versions)
        if "output_schema" not in output_data:
            output_data["output_schema"] = llm_output_schema
        # Normalise ui_render.charts: build charts list if missing, backfill chart_data
        ui = dict(output_data.get("ui_render") or {})

        # ── Sanitise: strip any HTML chart_data (scripts won't execute in dynamic DOM) ──
        cd = ui.get("chart_data")
        if _is_html_chart(cd):
            logger.warning("_normalize_output: chart_data is HTML (fig.to_html()), discarding — use json.dumps(fig.to_dict())")
            ui["chart_data"] = None
            cd = None

        charts = ui.get("charts")
        if not isinstance(charts, list):
            ui["charts"] = [cd] if cd else []
        else:
            # Strip any HTML entries from charts[]
            clean = [c for c in charts if c and not _is_html_chart(c)]
            if len(clean) < len(charts):
                logger.warning("_normalize_output: %d HTML chart(s) stripped from charts[]", len(charts) - len(clean))
            # P2 fix: validate remaining entries are parseable Plotly JSON
            valid: list = []
            for c in clean:
                try:
                    json.loads(c)
                    valid.append(c)
                except (json.JSONDecodeError, TypeError, ValueError):
                    logger.warning("_normalize_output: chart entry is not valid JSON, discarding")
            if len(valid) < len(clean):
                logger.warning("_normalize_output: %d invalid JSON chart(s) discarded", len(clean) - len(valid))
            ui["charts"] = valid
            if valid and not ui.get("chart_data"):
                ui["chart_data"] = valid[0]
            elif not valid:
                ui["chart_data"] = None

        # P3 fix: dataset must be a list of dicts — reset if malformed
        dataset = output_data.get("dataset")
        if not isinstance(dataset, list):
            logger.warning("_normalize_output: dataset is %s (not list), resetting to []", type(dataset).__name__)
            output_data["dataset"] = []

        output_data["ui_render"] = ui
        # Mark as intentionally processed by the script (not wrapped by normalize)
        output_data.setdefault("_is_processed", True)
        return output_data

    # Script returned a bare list
    if isinstance(output_data, list):
        dataset = output_data
    elif isinstance(output_data, dict):
        # Try to find the first list-of-dicts value as the dataset
        dataset = None
        # Check if 'dataset' key already exists (partial Standard Payload)
        if "dataset" in output_data and isinstance(output_data["dataset"], list):
            dataset = output_data["dataset"]
        else:
            for v in output_data.values():
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    dataset = v
                    break
        if dataset is None:
            # Wrap the whole dict as a single-row dataset
            dataset = [output_data]
    else:
        dataset = [{"value": str(output_data)}]

    return {
        "output_schema": llm_output_schema or {},
        "dataset": dataset,
        "ui_render": {"type": "table", "charts": [], "chart_data": None},
        "_is_processed": False,  # wrapped by normalize — treat as raw data
    }


def _auto_chart(dataset: list, ui_render_config: Optional[dict]) -> Optional[str]:
    """Generate a Plotly JSON string from dataset + ui_render_config.

    Used as a fallback when the processing script produces no chart_data.
    Returns a Plotly JSON string (fig.to_json()) or None on failure.
    """
    if not dataset or not isinstance(dataset, list):
        return None
    try:
        import plotly.graph_objects as go  # noqa: PLC0415

        cfg = ui_render_config or {}
        x_key = cfg.get("x_axis", "")
        y_key = cfg.get("y_axis", "")
        series_keys = cfg.get("series") or []

        first = dataset[0] if dataset else {}

        x_vals = (
            [row.get(x_key) for row in dataset]
            if x_key and x_key in first
            else list(range(len(dataset)))
        )

        keys_to_plot: list = []
        if series_keys:
            keys_to_plot = [k for k in series_keys if k in first]
        elif y_key and y_key in first:
            keys_to_plot = [y_key]
        else:
            keys_to_plot = [
                k for k in first
                if isinstance(first.get(k), (int, float)) and k != x_key
            ][:4]

        if not keys_to_plot:
            return None

        fig = go.Figure()
        for key in keys_to_plot:
            fig.add_trace(go.Scatter(
                x=x_vals,
                y=[row.get(key) for row in dataset],
                mode="lines+markers",
                name=key,
            ))

        fig.update_layout(margin=dict(l=40, r=20, t=30, b=40), height=260)
        # Use json.dumps(fig.to_dict()) — avoids binary-encoded output from new Plotly versions
        return json.dumps(fig.to_dict())
    except Exception:
        logger.debug("_auto_chart failed", exc_info=True)
        return None


def _j(s: Optional[str]) -> Any:
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return None


async def auto_resolve_process_context_params(
    params_dict: Dict[str, Any],
    sim_base: str,
) -> Dict[str, Any]:
    """Resolve missing eventTime for get_process_context calls.

    Normalises lot_id alias → targetID, then auto-fetches the most recent
    matching eventTime from the OntologySimulator so callers don't need to
    know about this internal API requirement.

    Returns the (possibly mutated) params_dict.
    """
    # Normalise lot_id → targetID alias
    if "lot_id" in params_dict:
        if "targetID" not in params_dict:
            params_dict["targetID"] = params_dict.pop("lot_id")
        else:
            params_dict.pop("lot_id")

    if params_dict.get("eventTime"):
        return params_dict  # already provided — nothing to do

    _target = params_dict.get("targetID")
    _step   = params_dict.get("step")
    if not (_target and _step):
        return params_dict

    try:
        async with httpx.AsyncClient(timeout=10.0) as _c:
            _r = await _c.get(
                f"{sim_base}/api/v1/events",
                params={"lotID": _target, "limit": 200},
            )
            _r.raise_for_status()
            _events = _r.json()
        _match = [e for e in _events if e.get("step") == _step]
        if _match:
            params_dict["eventTime"] = _match[0]["eventTime"]
            return params_dict

        # Fallback: analytics/history (works for both lot & equipment targetID)
        _obj_name = params_dict.get("objectName", "DC")
        async with httpx.AsyncClient(timeout=10.0) as _c:
            _r2 = await _c.get(
                f"{sim_base}/api/v1/analytics/history",
                params={"targetID": _target, "objectName": _obj_name, "step": _step, "limit": 1},
            )
            _r2.raise_for_status()
            _hist = _r2.json()
        if isinstance(_hist, list) and _hist:
            params_dict["eventTime"] = _hist[0]["eventTime"]
    except Exception:
        pass  # Let the call proceed; API will return 422 with a clear message

    return params_dict


def _to_response(obj: MCPDefinitionModel) -> MCPDefinitionResponse:
    return MCPDefinitionResponse(
        id=obj.id,
        name=obj.name,
        description=obj.description,
        mcp_type=getattr(obj, 'mcp_type', 'custom') or 'custom',
        data_subject_id=obj.data_subject_id,
        system_mcp_id=getattr(obj, 'system_mcp_id', None),
        api_config=_j(getattr(obj, 'api_config', None)),
        input_schema=_j(getattr(obj, 'input_schema', None)),
        processing_intent=obj.processing_intent,
        processing_script=obj.processing_script,
        output_schema=_j(obj.output_schema),
        ui_render_config=_j(obj.ui_render_config),
        input_definition=_j(obj.input_definition),
        sample_output=_j(obj.sample_output),
        visibility=obj.visibility if hasattr(obj, 'visibility') and obj.visibility else "private",
        created_at=obj.created_at,
        updated_at=obj.updated_at,
    )


class MCPDefinitionService:
    def __init__(
        self,
        repo: MCPDefinitionRepository,
        ds_repo: DataSubjectRepository,
        llm: MCPBuilderService,
        sp_repo: Optional[SystemParameterRepository] = None,
    ) -> None:
        self._repo = repo
        self._ds_repo = ds_repo
        self._llm = llm
        self._sp_repo = sp_repo

    async def list_all(self, mcp_type: Optional[str] = None) -> List[MCPDefinitionResponse]:
        if mcp_type:
            objs = await self._repo.get_all_by_type(mcp_type)
        else:
            objs = await self._repo.get_all()
        return [_to_response(o) for o in objs]

    async def get(self, mcp_id: int) -> MCPDefinitionResponse:
        obj = await self._repo.get_by_id(mcp_id)
        if not obj:
            raise AppException(status_code=404, error_code="NOT_FOUND", detail="MCP 不存在")
        return _to_response(obj)

    async def create(self, data: MCPDefinitionCreate) -> MCPDefinitionResponse:
        create_kwargs: Dict[str, Any] = {
            "name": data.name,
            "description": data.description,
            "mcp_type": data.mcp_type,
            "processing_intent": data.processing_intent,
        }
        if data.mcp_type == "system":
            # System MCP: store api_config + input_schema as JSON strings
            create_kwargs["api_config"] = json.dumps(data.api_config, ensure_ascii=False) if data.api_config else None
            create_kwargs["input_schema"] = json.dumps(data.input_schema, ensure_ascii=False) if data.input_schema else None
        else:
            # Custom MCP: resolve system_mcp_id (prefer new field, fall back to legacy data_subject_id)
            if data.system_mcp_id:
                sys_mcp = await self._repo.get_by_id(data.system_mcp_id)
                if not sys_mcp:
                    raise AppException(status_code=404, error_code="NOT_FOUND", detail="System MCP 不存在")
                create_kwargs["system_mcp_id"] = data.system_mcp_id
            elif data.data_subject_id:
                # Legacy path: look up DS and find corresponding system MCP by name
                ds = await self._ds_repo.get_by_id(data.data_subject_id)
                if not ds:
                    raise AppException(status_code=404, error_code="NOT_FOUND", detail="DataSubject 不存在")
                create_kwargs["data_subject_id"] = data.data_subject_id
                # Try to resolve system_mcp_id automatically
                sys_mcp = await self._repo.get_by_name(ds.name)
                if sys_mcp and getattr(sys_mcp, 'mcp_type', 'custom') == 'system':
                    create_kwargs["system_mcp_id"] = sys_mcp.id

        obj = await self._repo.create(**create_kwargs)
        return _to_response(obj)

    async def update(self, mcp_id: int, data: MCPDefinitionUpdate) -> MCPDefinitionResponse:
        obj = await self._repo.get_by_id(mcp_id)
        if not obj:
            raise AppException(status_code=404, error_code="NOT_FOUND", detail="MCP 不存在")
        updates: Dict[str, Any] = {}
        for field in ("name", "description", "processing_intent", "processing_script", "diagnostic_prompt"):
            val = getattr(data, field, None)
            if val is not None:
                updates[field] = val
        for field in ("output_schema", "ui_render_config", "input_definition", "sample_output"):
            val = getattr(data, field, None)
            if val is not None:
                updates[field] = val
        # api_config / input_schema: accept dicts and serialize to JSON for storage
        if getattr(data, "api_config", None) is not None:
            updates["api_config"] = json.dumps(data.api_config, ensure_ascii=False)
        if getattr(data, "input_schema", None) is not None:
            updates["input_schema"] = json.dumps(data.input_schema, ensure_ascii=False)
        if getattr(data, "system_mcp_id", None) is not None:
            updates["system_mcp_id"] = data.system_mcp_id
        if getattr(data, "visibility", None) is not None:
            updates["visibility"] = data.visibility
        obj = await self._repo.update(obj, **updates)
        return _to_response(obj)

    async def delete(self, mcp_id: int) -> None:
        obj = await self._repo.get_by_id(mcp_id)
        if not obj:
            raise AppException(status_code=404, error_code="NOT_FOUND", detail="MCP 不存在")
        await self._repo.delete(obj)

    async def _resolve_system_mcp(self, data_subject_id: Optional[int]) -> Optional[Any]:
        """Resolve a system MCP from a legacy data_subject_id via name matching."""
        if not data_subject_id:
            return None
        ds = await self._ds_repo.get_by_id(data_subject_id)
        if not ds:
            return None
        sys_mcp = await self._repo.get_by_name(ds.name)
        if sys_mcp and getattr(sys_mcp, 'mcp_type', 'custom') == 'system':
            return sys_mcp
        return None

    async def _get_ds_info(self, mcp: MCPDefinitionModel) -> tuple[str, dict]:
        """Get (ds_name, output_schema) for LLM calls.

        Checks system_mcp_id first, falls back to data_subject_id → name match.
        Returns ('', {}) if not resolvable (non-blocking).
        """
        # Prefer system_mcp_id
        system_mcp_id = getattr(mcp, 'system_mcp_id', None)
        if system_mcp_id:
            sys_mcp = await self._repo.get_by_id(system_mcp_id)
            if sys_mcp:
                out_schema = _j(getattr(sys_mcp, 'output_schema', None)) or {}
                return sys_mcp.name, out_schema

        # Fall back to data_subject_id
        ds_id = getattr(mcp, 'data_subject_id', None)
        if ds_id:
            ds = await self._ds_repo.get_by_id(ds_id)
            if ds:
                return ds.name, _j(ds.output_schema) or {}

        return "", {}

    async def check_intent(
        self,
        processing_intent: str,
        system_mcp_id: Optional[int] = None,
        data_subject_id: Optional[int] = None,
    ) -> MCPCheckIntentResponse:
        """Ask LLM to verify the processing intent is clear before generation."""
        # Prefer system_mcp_id directly; fall back to resolving from data_subject_id
        if system_mcp_id:
            sys_mcp = await self._repo.get_by_id(system_mcp_id)
        else:
            sys_mcp = await self._resolve_system_mcp(data_subject_id)
        if sys_mcp:
            ds_name = sys_mcp.name
            output_schema_raw = _j(getattr(sys_mcp, 'output_schema', None)) or {}
        else:
            ds = await self._ds_repo.get_by_id(data_subject_id)
            if not ds:
                # Not found — don't block, let try-run fail with proper 404
                return MCPCheckIntentResponse(is_clear=True, questions=[])
            ds_name = ds.name
            output_schema_raw = _j(ds.output_schema) or {}

        try:
            result = await self._llm.check_intent(
                processing_intent=processing_intent,
                data_subject_name=ds_name,
                data_subject_output_schema=output_schema_raw,
            )
        except Exception as exc:
            logger.warning("check_intent LLM call failed: %s", exc)
            return MCPCheckIntentResponse(is_clear=True, questions=[])

        return MCPCheckIntentResponse(
            is_clear=result.get("is_clear", True),
            questions=result.get("questions", []),
            suggested_prompt=result.get("suggested_prompt", ""),
        )

    async def generate(self, mcp_id: int) -> MCPGenerateResponse:
        """Invoke LLM to generate script, output schema, UI config, and input definition."""
        obj = await self._repo.get_by_id(mcp_id)
        if not obj:
            raise AppException(status_code=404, error_code="NOT_FOUND", detail="MCP 不存在")

        ds_name, output_schema_raw = await self._get_ds_info(obj)
        if not ds_name:
            raise AppException(status_code=404, error_code="NOT_FOUND", detail="System MCP / DataSubject 不存在")

        # Load prompt template from DB if available
        prompt_template = None
        if self._sp_repo:
            prompt_template = await self._sp_repo.get_value("PROMPT_MCP_GENERATE")

        result = await self._llm.generate_all(
            processing_intent=obj.processing_intent,
            data_subject_name=ds_name,
            data_subject_output_schema=output_schema_raw,
            prompt_template=prompt_template,
        )

        # Persist LLM results
        await self._repo.update(
            obj,
            processing_script=result.get("processing_script", ""),
            output_schema=result.get("output_schema", {}),
            ui_render_config=result.get("ui_render_config", {}),
            input_definition=result.get("input_definition", {}),
        )

        return MCPGenerateResponse(
            mcp_id=mcp_id,
            processing_script=result.get("processing_script", ""),
            output_schema=result.get("output_schema", {}),
            ui_render_config=result.get("ui_render_config", {}),
            input_definition=result.get("input_definition", {}),
            summary=result.get("summary", ""),
        )

    async def _analyze_sandbox_error(
        self,
        script: str,
        error_message: str,
        processing_intent: str,
        data_subject_name: str,
    ) -> Dict[str, Any]:
        """Best-effort: ask LLM to triage the sandbox error. Never raises."""
        try:
            return await self._llm.triage_error(
                script=script,
                error_message=error_message,
                processing_intent=processing_intent,
                data_subject_name=data_subject_name,
            )
        except Exception as exc:
            logger.warning("triage_error failed: %s", exc)
            return {
                "error_type": "System_Issue",
                "error_reason": "",
                "script_issue": "",
                "suggested_prompt": "",
                "fix_suggestion": "",
            }

    async def try_run(
        self,
        processing_intent: str,
        sample_data: Any,
        system_mcp_id: Optional[int] = None,
        data_subject_id: Optional[int] = None,
    ) -> MCPTryRunResponse:
        """LLM generate script (with guardrails) → sandbox execute → return result."""
        # Resolve DS info: prefer system_mcp_id directly; fall back to legacy DS
        if system_mcp_id:
            sys_mcp = await self._repo.get_by_id(system_mcp_id)
        else:
            sys_mcp = await self._resolve_system_mcp(data_subject_id)
        if sys_mcp:
            ds_name = sys_mcp.name
            output_schema_raw = _j(getattr(sys_mcp, 'output_schema', None)) or {}
        else:
            ds = await self._ds_repo.get_by_id(data_subject_id)
            if not ds:
                raise AppException(status_code=404, error_code="NOT_FOUND", detail="DataSubject 不存在")
            ds_name = ds.name
            output_schema_raw = _j(ds.output_schema) or {}

        # Load system prompt from DB if available
        system_prompt = None
        if self._sp_repo:
            system_prompt = await self._sp_repo.get_value("PROMPT_MCP_TRY_RUN")

        _record_count = len(sample_data) if isinstance(sample_data, list) else 1
        # Extract 1 sample row so LLM can see exact column names/format
        if isinstance(sample_data, list) and sample_data:
            _sample_row = sample_data[0]
        elif isinstance(sample_data, dict):
            # If it's a dict with a list value, peek inside
            for _v in sample_data.values():
                if isinstance(_v, list) and _v:
                    _sample_row = _v[0]
                    break
            else:
                _sample_row = sample_data
        else:
            _sample_row = None
        try:
            _t0_llm = time.time()
            result = await self._llm.generate_for_try_run(
                processing_intent=processing_intent,
                data_subject_name=ds_name,
                data_subject_output_schema=output_schema_raw,
                system_prompt=system_prompt,
                sample_row=_sample_row,
            )
            _t1_llm = time.time()
            logger.warning(
                "try_run perf | stage=LLM_codegen elapsed=%.2fs raw_data_records=%d",
                _t1_llm - _t0_llm,
                _record_count,
            )
        except Exception as exc:
            return MCPTryRunResponse(success=False, error=f"LLM 生成失敗：{exc}")

        # Collect self-learning events from LLM generation (Schema Guard results)
        _self_learning: list = list(result.get("_learning_events", []))

        script = result.get("processing_script", "")
        if not script or not script.strip() or "def process" not in script:
            # LLM refused or produced unusable output — surface a helpful error
            refusal = script.strip() if script and script.strip() else "LLM 未生成任何腳本內容"
            return MCPTryRunResponse(
                success=False,
                error=(
                    f"LLM 拒絕生成腳本：{refusal[:300]}\n\n"
                    "建議：加工意圖請聚焦於「資料計算、統計分析、異常標記、效能排行」，"
                    "例如「計算 mean/std/skewness/kurtosis，標記超出 3σ 的點並輸出 status 欄位」。"
                    "可使用 pandas、numpy 進行統計計算。"
                ),
            )
        # v14.2: sandbox execution with one auto-retry on failure.
        # On first failure: classify error → re-ask LLM to fix the script → retry sandbox.
        _t0_sb = _t1_sb = time.time()
        output_data = None
        final_error: Optional[MCPTryRunResponse] = None

        for _sandbox_attempt in range(2):  # attempt 0 = first run; attempt 1 = auto-retry
            try:
                _t0_sb = time.time()
                output_data = await execute_script(script, sample_data)
                _t1_sb = time.time()
                logger.warning(
                    "try_run perf | stage=sandbox_exec attempt=%d elapsed=%.2fs raw_data_records=%d",
                    _sandbox_attempt + 1, _t1_sb - _t0_sb, _record_count,
                )
                if _sandbox_attempt > 0:
                    _self_learning.append("[Self-Healing ✓] 第 2 次沙盒執行成功（修正版腳本通過）")
                final_error = None
                break  # success — exit retry loop
            except (ValueError, TimeoutError, Exception) as exc:
                error_msg = f"沙盒執行失敗：{exc}"
                error_label = classify_error(str(exc))
                _self_learning.append(f"[Self-Healing] 第 {_sandbox_attempt + 1} 次沙盒失敗 — 錯誤分類：{error_label}")
                logger.warning(
                    "try_run sandbox error (attempt %d) type=%s: %s",
                    _sandbox_attempt + 1, error_label, exc,
                )

                if _sandbox_attempt == 0:
                    # First failure → ask LLM to fix the script with error context
                    logger.warning("try_run | triggering sandbox auto-retry via LLM fix (error_type=%s)", error_label)
                    _self_learning.append(f"[Self-Healing] LLM 注入錯誤上下文（{error_label}），重新生成腳本…")
                    error_context = (
                        f"[{error_label}] 上次生成的腳本在沙盒執行時失敗：\n{error_msg}\n"
                        f"請修正 process() 函式並確保欄位名稱與 Schema 一致。"
                    )
                    try:
                        fixed_result = await self._llm.generate_for_try_run(
                            processing_intent=processing_intent + f"\n\n⚠️ 前次腳本錯誤（{error_label}）：{error_msg[:300]}",
                            data_subject_name=ds_name,
                            data_subject_output_schema=output_schema_raw,
                            system_prompt=system_prompt,
                            sample_row=_sample_row,
                        )
                        fixed_script = fixed_result.get("processing_script", "")
                        if fixed_script and "def process" in fixed_script:
                            script = fixed_script
                            logger.warning("try_run | LLM fix succeeded, retrying sandbox")
                            continue  # retry sandbox with fixed script
                    except Exception as fix_exc:
                        logger.warning("try_run | LLM fix attempt failed: %s", fix_exc)

                # Second failure or LLM fix failed → return error with triage
                triage = await self._analyze_sandbox_error(
                    script, error_msg, processing_intent, ds_name
                )
                parts = []
                if triage.get("error_reason"):   parts.append(f"錯誤原因：{triage['error_reason']}")
                if triage.get("script_issue"):   parts.append(f"腳本問題：{triage['script_issue']}")
                if triage.get("fix_suggestion"): parts.append(f"修改建議：{triage['fix_suggestion']}")
                final_error = MCPTryRunResponse(
                    success=False,
                    script=script,
                    error=error_msg,
                    error_analysis="\n".join(parts) if parts else None,
                    error_type=f"[{error_label}] {triage.get('error_type', '')}".strip(" []") or error_label,
                    suggested_prompt=triage.get("suggested_prompt") or None,
                )
                break

        if final_error is not None:
            return final_error

        # ── Normalize output_data into Standard Payload format.
        # LLM scripts from before Phase 8.5 (or non-compliant ones) may return raw data
        # without the required {output_schema, dataset, ui_render} keys.
        output_data = _normalize_output(output_data, result.get("output_schema", {}))

        # ── Auto-chart fallback: if the script returned HTML (which was stripped by
        # _normalize_output) or omitted charts entirely, regenerate from dataset.
        ui_render = output_data.get("ui_render", {})
        ui_cfg = result.get("ui_render_config", {})
        chart_type = ui_cfg.get("chart_type") or ""
        logger.warning(
            "try_run chart_state | ui_render.charts=%r chart_type=%r dataset_len=%d",
            bool(ui_render.get("charts")),
            chart_type,
            len(output_data.get("dataset") or []),
        )
        if not ui_render.get("charts") and not ui_render.get("chart_data"):
            # Fix: treat missing/empty chart_type as non-table (attempt auto-chart).
            # Previously `(chart_type or "table") != "table"` wrongly skipped auto-chart
            # when chart_type was None or "".
            if chart_type != "table":
                logger.warning("try_run | triggering _auto_chart fallback (chart_type=%r)", chart_type)
                chart = _auto_chart(output_data.get("dataset", []), ui_cfg)
                if chart:
                    output_data["ui_render"] = {
                        **ui_render,
                        "charts": [chart],
                        "chart_data": chart,
                    }
                    logger.warning("try_run | _auto_chart succeeded, chart injected")

        # Attach raw DS data so frontend can show "Raw Data" tab
        raw_list = sample_data if isinstance(sample_data, list) else (
            list(sample_data.values())[0] if isinstance(sample_data, dict) and sample_data else [sample_data]
        )
        output_data = {**output_data, "_raw_dataset": raw_list}

        out_records = len(output_data.get("dataset") or [])
        _self_learning.append(
            f"[Output ✓] 輸出正規化完成 — dataset={out_records} rows · charts={len((output_data.get('ui_render') or {}).get('charts') or [])}"
        )
        return MCPTryRunResponse(
            success=True,
            script=script,
            output_data=output_data,
            ui_render_config=result.get("ui_render_config", {}),
            output_schema=result.get("output_schema", {}),
            input_definition=result.get("input_definition", {}),
            summary=result.get("summary", ""),
            llm_elapsed_s=round(_t1_llm - _t0_llm, 2),
            sandbox_elapsed_s=round(_t1_sb - _t0_sb, 2),
            input_records=_record_count,
            output_records=out_records,
            learning_events=_self_learning,
        )

    async def run_with_data(self, mcp_id: int, raw_data: Any, base_url: str = "") -> MCPTryRunResponse:
        """Execute MCP with raw_data (no LLM). Used by Skill Builder.

        For system MCPs: calls the raw API endpoint and wraps the response as a
        Standard Payload (Default Wrapper).
        For custom MCPs: runs the stored Python processing_script.
        """
        obj = await self._repo.get_by_id(mcp_id)
        if not obj:
            raise AppException(status_code=404, error_code="NOT_FOUND", detail="MCP 不存在")

        mcp_type = getattr(obj, 'mcp_type', 'custom') or 'custom'

        # ── System MCP: Default Wrapper ──────────────────────────────────────
        if mcp_type == 'system':
            api_cfg = _j(obj.api_config) if isinstance(obj.api_config, str) else (obj.api_config or {})
            endpoint_url = api_cfg.get("endpoint_url", "")
            method = api_cfg.get("method", "GET").upper()
            headers = api_cfg.get("headers", {})
            if not endpoint_url:
                raise AppException(status_code=422, error_code="DS_NO_ENDPOINT", detail="System MCP 缺少 endpoint_url")

            # Build absolute URL.
            # For relative paths, always use 127.0.0.1 to avoid routing through
            # nginx in production (external base_url may have SSL/proxy issues).
            if endpoint_url.startswith("/"):
                url = get_settings().SERVER_BASE_URL + endpoint_url
            else:
                url = endpoint_url

            # Flatten raw_data into query params / body
            params_dict: Dict[str, Any] = {}
            if isinstance(raw_data, dict):
                params_dict = raw_data
            elif isinstance(raw_data, list) and raw_data and isinstance(raw_data[0], dict):
                params_dict = raw_data[0]

            params_dict = _normalize_params(params_dict, mcp_name=obj.name)

            # ── Time-window MCPs: resolve `since` → `start_time` ─────────────
            if obj.name in _TIME_WINDOW_MCPS:
                try:
                    params_dict = await _resolve_since_param(
                        obj.name, params_dict, get_settings().ONTOLOGY_SIM_URL
                    )
                except SinceParamError as exc:
                    return MCPTryRunResponse(success=False, error=f"INVALID_SINCE: {exc}")

            # ── get_process_context: auto-resolve eventTime ───────────────────
            if obj.name == "get_process_context":
                params_dict = await auto_resolve_process_context_params(
                    params_dict, get_settings().ONTOLOGY_SIM_URL
                )

            # Substitute {path_params} and keep remaining as query/body params
            url, params_dict = _resolve_url_params(url, params_dict)

            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    if method == "GET":
                        resp = await client.get(url, params=params_dict, headers=headers)
                    else:
                        resp = await client.post(url, json=params_dict, headers=headers)
                    resp.raise_for_status()
                    response_json = resp.json()
            except Exception as exc:
                return MCPTryRunResponse(success=False, error=f"System MCP API 呼叫失敗：{exc}")

            raw_list = response_json if isinstance(response_json, list) else [response_json]
            output_data = {
                "output_schema": _j(obj.output_schema) or {},
                "dataset": raw_list,
                "ui_render": {"type": "data_grid", "charts": [], "chart_data": None},
                "_raw_dataset": raw_list,
                "_is_processed": False,
            }
            return MCPTryRunResponse(
                success=True,
                output_data=output_data,
                output_schema=_j(obj.output_schema) or {},
                ui_render_config={"chart_type": "table"},
                input_definition={},
            )

        # ── Custom MCP: run stored processing_script ──────────────────────────
        if not obj.processing_script:
            raise AppException(
                status_code=400,
                error_code="INVALID_STATE",
                detail="此 MCP 尚未生成 Python 腳本，請先在 MCP Builder 完成試跑",
            )

        # Step 1: Fetch raw data from bound System MCP (raw_data = agent params, not dataset)
        sys_mcp_id = getattr(obj, 'system_mcp_id', None)
        # Fallback: legacy custom MCPs have data_subject_id but system_mcp_id=null.
        # Resolve by fetching the old DataSubject, then name-matching to a system MCP.
        if not sys_mcp_id:
            ds_id = getattr(obj, 'data_subject_id', None)
            if ds_id:
                try:
                    old_ds = await self._ds_repo.get_by_id(ds_id)
                    if old_ds and old_ds.name:
                        from sqlalchemy import select as _select
                        from app.models.mcp_definition import MCPDefinitionModel as _MCPModel
                        _r = await self._repo._db.execute(
                            _select(_MCPModel).where(
                                _MCPModel.mcp_type == 'system',
                                _MCPModel.name == old_ds.name,
                            )
                        )
                        _matched = _r.scalar_one_or_none()
                        if _matched:
                            sys_mcp_id = _matched.id
                except Exception:
                    pass
        api_raw_data: Any = raw_data  # fallback: use params as-is
        if sys_mcp_id:
            sys_mcp = await self._repo.get_by_id(sys_mcp_id)
            if sys_mcp and getattr(sys_mcp, 'mcp_type', 'system') == 'system':
                api_cfg = _j(sys_mcp.api_config) if isinstance(sys_mcp.api_config, str) else (sys_mcp.api_config or {})
                endpoint_url = api_cfg.get("endpoint_url", "")
                method = api_cfg.get("method", "GET").upper()
                headers = api_cfg.get("headers", {})
                if endpoint_url:
                    if endpoint_url.startswith("/"):
                        url = get_settings().SERVER_BASE_URL + endpoint_url
                    else:
                        url = endpoint_url
                    params_dict: Dict[str, Any] = _normalize_params(raw_data if isinstance(raw_data, dict) else {})
                    resolved_url2, query_params2 = _resolve_url_params(url, params_dict)
                    try:
                        async with httpx.AsyncClient(timeout=30.0) as client:
                            if method == "GET":
                                resp = await client.get(resolved_url2, params=query_params2, headers=headers)
                            else:
                                resp = await client.post(resolved_url2, json=query_params2, headers=headers)
                            resp.raise_for_status()
                            response_json = resp.json()
                            api_raw_data = response_json if isinstance(response_json, list) else [response_json]
                    except Exception as exc:
                        return MCPTryRunResponse(success=False, error=f"System MCP 資料撈取失敗：{exc}")

        # Step 2: Run processing script on fetched data
        try:
            output_data = await execute_script(obj.processing_script, api_raw_data)
        except (ValueError, TimeoutError) as exc:
            return MCPTryRunResponse(
                success=False,
                script=obj.processing_script,
                error=str(exc),
            )
        except Exception as exc:
            return MCPTryRunResponse(
                success=False,
                script=obj.processing_script,
                error=f"未預期的執行錯誤：{exc}",
            )

        llm_output_schema = _j(obj.output_schema) or {}
        output_data = _normalize_output(output_data, llm_output_schema)

        # Attach raw DS data so frontend can show "Raw Data" tab
        raw_list = api_raw_data if isinstance(api_raw_data, list) else (
            list(api_raw_data.values())[0] if isinstance(api_raw_data, dict) and api_raw_data else [api_raw_data]
        )
        output_data = {**output_data, "_raw_dataset": raw_list}

        return MCPTryRunResponse(
            success=True,
            script=obj.processing_script,
            output_data=output_data,
            output_schema=llm_output_schema,
            ui_render_config=_j(obj.ui_render_config) or {},
            input_definition=_j(obj.input_definition) or {},
        )

    async def run_with_feedback(
        self,
        mcp_id: int,
        input_params: Any,
        user_feedback: str,
        previous_result_summary: Optional[str] = None,
        force_regen: bool = False,
    ) -> MCPRunWithFeedbackResponse:
        """User feedback → LLM reflection → revised script → fetch real data → sandbox re-run → persist log.

        input_params: the FORM PARAMS (e.g. {lot_id, tool_id}), NOT the raw dataset.
                      This method re-fetches the actual dataset from the system MCP API
                      before running the revised script, exactly like run_with_data().
        force_regen:  If True, skip script revision via reflection and instead call
                      try_run() with user_feedback appended to the intent (full LLM regen).
        """
        from app.models.feedback_log import FeedbackLogModel

        obj = await self._repo.get_by_id(mcp_id)
        if not obj:
            raise AppException(status_code=404, error_code="NOT_FOUND", detail="MCP 不存在")

        original_script = obj.processing_script or ""
        ds_name, _ = await self._get_ds_info(obj)

        # ── Step 0: Re-fetch actual API data (same logic as run_with_data) ───────
        api_raw_data: Any = input_params
        sys_mcp_id = getattr(obj, 'system_mcp_id', None)
        if not sys_mcp_id:
            ds_id = getattr(obj, 'data_subject_id', None)
            if ds_id:
                try:
                    old_ds = await self._ds_repo.get_by_id(ds_id)
                    if old_ds and old_ds.name:
                        from sqlalchemy import select as _select
                        from app.models.mcp_definition import MCPDefinitionModel as _MCPModel
                        _r = await self._repo._db.execute(
                            _select(_MCPModel).where(
                                _MCPModel.mcp_type == 'system',
                                _MCPModel.name == old_ds.name,
                            )
                        )
                        _matched = _r.scalar_one_or_none()
                        if _matched:
                            sys_mcp_id = _matched.id
                except Exception:
                    pass
        if sys_mcp_id:
            sys_mcp = await self._repo.get_by_id(sys_mcp_id)
            if sys_mcp and getattr(sys_mcp, 'mcp_type', 'system') == 'system':
                api_cfg = _j(sys_mcp.api_config) if isinstance(sys_mcp.api_config, str) else (sys_mcp.api_config or {})
                endpoint_url = api_cfg.get("endpoint_url", "")
                method = api_cfg.get("method", "GET").upper()
                headers = api_cfg.get("headers", {})
                if endpoint_url:
                    if endpoint_url.startswith("/"):
                        url = get_settings().SERVER_BASE_URL + endpoint_url
                    else:
                        url = endpoint_url
                    params_dict: Dict[str, Any] = _normalize_params(input_params if isinstance(input_params, dict) else {})
                    resolved_url, query_params = _resolve_url_params(url, params_dict)
                    try:
                        async with httpx.AsyncClient(timeout=30.0) as client:
                            if method == "GET":
                                resp = await client.get(resolved_url, params=query_params, headers=headers)
                            else:
                                resp = await client.post(resolved_url, json=query_params, headers=headers)
                            resp.raise_for_status()
                            response_json = resp.json()
                            api_raw_data = response_json if isinstance(response_json, list) else [response_json]
                    except Exception as exc:
                        return MCPRunWithFeedbackResponse(
                            reflection="", revised_script=original_script,
                            error=f"System MCP 資料重新撈取失敗：{exc}"
                        )

        # ── Step 1a: Force re-generation via try_run (if force_regen=True) ───────
        if force_regen:
            enriched_intent = (obj.processing_intent or "") + f"\n\n[用戶回饋 — 請根據此改善腳本]\n{user_feedback}"
            try:
                try_result = await self.try_run(
                    processing_intent=enriched_intent,
                    sample_data=api_raw_data,
                    system_mcp_id=sys_mcp_id,
                )
                if try_result.success:
                    output_data = _normalize_output(try_result.output_data, _j(obj.output_schema) or {})
                    output_data = {**output_data, "_raw_dataset": api_raw_data if isinstance(api_raw_data, list) else []}
                    # Persist new script
                    new_script = try_result.script or original_script
                    await self._repo.update(obj, processing_script=new_script)
                    self._save_feedback_log_sync(
                        mcp_id, user_feedback, previous_result_summary or "",
                        "[Force Regen] 已請 LLM 重新生成腳本", new_script, True
                    )
                    return MCPRunWithFeedbackResponse(
                        reflection=f"[重新生成腳本] {try_result.summary or '新腳本已生成'}",
                        revised_script=new_script,
                        rerun_success=True,
                        output_data=output_data,
                    )
                else:
                    return MCPRunWithFeedbackResponse(
                        reflection="LLM 重新生成腳本失敗",
                        revised_script=original_script,
                        error=try_result.error or "未知錯誤",
                    )
            except Exception as exc:
                return MCPRunWithFeedbackResponse(
                    reflection="Force regen 失敗", revised_script=original_script, error=str(exc)
                )

        # ── Step 1b: LLM reflection + revised script (normal path) ───────────────
        reflect_result = await self._llm.reflect_and_fix(
            original_script=original_script,
            processing_intent=obj.processing_intent or "",
            data_subject_name=ds_name or obj.name,
            user_feedback=user_feedback,
            previous_result_summary=previous_result_summary or "",
        )
        reflection = reflect_result.get("reflection", "")
        revised_script = reflect_result.get("revised_script", "") or original_script

        # ── Step 2: sandbox re-run with revised script on REAL fetched data ───────
        rerun_success = False
        output_data: Dict[str, Any] = {}
        error: Optional[str] = None
        try:
            raw_output = await execute_script(revised_script, api_raw_data)
            output_data = _normalize_output(raw_output, _j(obj.output_schema) or {})
            raw_list = api_raw_data if isinstance(api_raw_data, list) else []
            output_data = {**output_data, "_raw_dataset": raw_list}
            rerun_success = True
        except Exception as exc:
            error = f"修正腳本執行失敗：{exc}"

        # ── Step 3: if re-run succeeded, persist the revised script to the MCP ───
        if rerun_success and revised_script != original_script:
            await self._repo.update(obj, processing_script=revised_script)

        # ── Step 4: save feedback log ─────────────────────────────────────────────
        log_id: Optional[int] = None
        try:
            log = FeedbackLogModel(
                target_type="mcp",
                target_id=mcp_id,
                user_feedback=user_feedback,
                previous_result_summary=previous_result_summary or "",
                llm_reflection=reflection,
                revised_script=revised_script,
                rerun_success=rerun_success,
            )
            self._repo._db.add(log)
            await self._repo._db.flush()
            log_id = log.id
        except Exception as exc:
            logger.warning("run_with_feedback: failed to save feedback log: %s", exc)

        return MCPRunWithFeedbackResponse(
            reflection=reflection,
            revised_script=revised_script,
            rerun_success=rerun_success,
            output_data=output_data,
            error=error,
            feedback_log_id=log_id,
        )

    async def agent_build(self, req: MCPAgentBuildRequest) -> MCPAgentBuildResponse:
        """Full automated flow: sample-fetch → try-run (up to 2 retries) → create MCP.

        Used by the Agent's build_mcp tool so it can autonomously create a Custom MCP
        without human interaction in the Admin UI.
        """
        # ── 1. Fetch sample data from the System MCP endpoint ────────────────
        sys_mcp = await self._repo.get_by_id(req.system_mcp_id)
        if not sys_mcp or getattr(sys_mcp, 'mcp_type', 'custom') != 'system':
            return MCPAgentBuildResponse(
                success=False,
                error=f"找不到 System MCP id={req.system_mcp_id}",
            )

        api_cfg = _j(sys_mcp.api_config) if isinstance(sys_mcp.api_config, str) else (sys_mcp.api_config or {})
        endpoint_url = api_cfg.get("endpoint_url", "")
        method = api_cfg.get("method", "GET").upper()
        params = req.sample_params or {}

        if not endpoint_url:
            return MCPAgentBuildResponse(
                success=False,
                error="此 System MCP 缺少 endpoint_url，無法自動撈取樣本資料",
            )

        try:
            if endpoint_url.startswith("/"):
                url = get_settings().SERVER_BASE_URL + endpoint_url
            else:
                url = endpoint_url
            resolved_url, remaining = _resolve_url_params(url, params)
            async with httpx.AsyncClient(timeout=15.0) as client:
                if method == "POST":
                    resp = await client.post(resolved_url, json=remaining)
                else:
                    resp = await client.get(resolved_url, params=remaining)
                resp.raise_for_status()
                sample_data = resp.json()
        except Exception as exc:
            return MCPAgentBuildResponse(
                success=False,
                error=f"樣本資料撈取失敗（{endpoint_url}）: {exc}",
            )

        # ── 2. Try-run with up to 2 retries ──────────────────────────────────
        last_try: Optional[MCPTryRunResponse] = None
        for attempt in range(1, 3):
            try:
                last_try = await self.try_run(
                    processing_intent=req.processing_intent,
                    sample_data=sample_data,
                    system_mcp_id=req.system_mcp_id,
                )
            except Exception as exc:
                last_try = MCPTryRunResponse(success=False, error=str(exc))
            if last_try.success:
                break
            logger.warning("agent_build: try_run attempt %d failed: %s", attempt, last_try.error)

        if not last_try or not last_try.success:
            return MCPAgentBuildResponse(
                success=False,
                error=last_try.error if last_try else "try_run 未執行",
                error_analysis=last_try.error_analysis if last_try else None,
            )

        # ── 3. Create MCP in DB ───────────────────────────────────────────────
        new_mcp = await self.create(MCPDefinitionCreate(
            name=req.name,
            description=req.description,
            mcp_type="custom",
            system_mcp_id=req.system_mcp_id,
            processing_intent=req.processing_intent,
        ))

        # ── 4. Persist generated artefacts ────────────────────────────────────
        update_payload = MCPDefinitionUpdate(
            processing_script=last_try.script,
            output_schema=last_try.output_schema or {},
            ui_render_config=last_try.ui_render_config or {},
            input_definition=last_try.input_definition or {},
        )
        await self.update(new_mcp.id, update_payload)

        ui_render = last_try.output_data.get("ui_render", {})
        has_chart = bool(
            isinstance(ui_render, dict) and
            (ui_render.get("charts") or ui_render.get("chart_data"))
        )

        return MCPAgentBuildResponse(
            success=True,
            mcp_id=new_mcp.id,
            name=new_mcp.name,
            summary=last_try.summary,
            output_records=last_try.output_records,
            has_chart=has_chart,
        )

    def _save_feedback_log_sync(
        self, target_id: int, user_feedback: str, prev_summary: str,
        reflection: str, revised_script: str, success: bool
    ) -> None:
        """Fire-and-forget feedback log (no await needed for force_regen path)."""
        from app.models.feedback_log import FeedbackLogModel
        try:
            log = FeedbackLogModel(
                target_type="mcp", target_id=target_id,
                user_feedback=user_feedback, previous_result_summary=prev_summary,
                llm_reflection=reflection, revised_script=revised_script,
                rerun_success=success,
            )
            self._repo._db.add(log)
        except Exception as exc:
            logger.warning("_save_feedback_log_sync: %s", exc)
