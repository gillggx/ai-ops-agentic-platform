"""block_process_history — 從 OntologySimulator 拉製程歷史資料。

底層呼叫 `{ONTOLOGY_SIM_URL}/api/v1/process/info`（等同既有 system MCP `get_process_info`）。

設計原則：
  - tool_id / lot_id / step 三擇一（至少一個必填；runtime check，因 JSON Schema anyOf 不好表達）
  - 輸出單一 dataframe，每列一筆 event
  - 欄位命名用前綴避免衝突：spc_* / apc_* / dc_* / recipe_* / fdc_* / ec_*
  - object_name 不帶 → 回所有維度展開的寬表（browse 場景）
  - object_name 指定 → 僅 base 欄位 + 該維度欄位（聚焦分析場景）
"""

from __future__ import annotations

from typing import Any, Optional

import httpx
import pandas as pd

from python_ai_sidecar.pipeline_builder._sidecar_deps import get_settings
from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)


_DEFAULT_TIMEOUT_S = 15.0

_BASE_FIELDS = ("eventTime", "toolID", "lotID", "step", "spc_status", "fdc_classification")
_OBJECT_KEYS = {"SPC", "APC", "DC", "RECIPE", "FDC", "EC"}


def _flatten_spc(row: dict[str, Any], spc: dict[str, Any]) -> None:
    """SPC.charts.<chart_name>.{value,ucl,lcl,is_ooc} → spc_<chart>_<field>"""
    charts = spc.get("charts") or {}
    for chart_name, chart_obj in charts.items():
        if not isinstance(chart_obj, dict):
            continue
        for subkey in ("value", "ucl", "lcl", "is_ooc"):
            if subkey in chart_obj:
                row[f"spc_{chart_name}_{subkey}"] = chart_obj[subkey]


def _flatten_object_id(row: dict[str, Any], obj: dict[str, Any], prefix: str) -> None:
    """obj.objectID → <prefix>_id (e.g. APC.objectID='APC-009' → apc_id='APC-009').

    2026-05-11: simulator now returns objectID for every object snapshot
    (was being stripped). Surface it as a flat column so downstream blocks
    can groupby by APC/RECIPE/FDC instance — e.g. "OOC count by APC model"
    becomes a clean groupby on `apc_id`.
    """
    oid = obj.get("objectID")
    if oid is not None:
        row[f"{prefix}_id"] = oid


def _flatten_params(row: dict[str, Any], obj: dict[str, Any], prefix: str) -> None:
    """obj.parameters[k] → <prefix>_<k>; unwrap nested {value,...} dicts to scalar."""
    params = obj.get("parameters") or {}
    if not isinstance(params, dict):
        return
    for k, v in params.items():
        if isinstance(v, dict) and "value" in v:
            row[f"{prefix}_{k}"] = v["value"]
        else:
            row[f"{prefix}_{k}"] = v


def _flatten_recipe(row: dict[str, Any], recipe: dict[str, Any]) -> None:
    if "recipe_version" in recipe:
        row["recipe_version"] = recipe["recipe_version"]
    _flatten_params(row, recipe, "recipe")


def _flatten_dc(row: dict[str, Any], dc: dict[str, Any]) -> None:
    """DC.chamberID is the chamber instance identifier (CH-1, CH-2, ...);
    keep as `dc_chamber_id` to mirror apc_id/recipe_id naming."""
    cid = dc.get("chamberID")
    if cid is not None:
        row["dc_chamber_id"] = cid
    _flatten_params(row, dc, "dc")


def _flatten_fdc(row: dict[str, Any], fdc: dict[str, Any]) -> None:
    for k in ("classification", "fault_code", "confidence", "description"):
        if k in fdc:
            row[f"fdc_{k}"] = fdc[k]


def _flatten_ec(row: dict[str, Any], ec: dict[str, Any]) -> None:
    """EC.constants.<k>.{value, nominal, deviation_pct, status} → ec_<k>_<field>"""
    consts = ec.get("constants") or {}
    if not isinstance(consts, dict):
        return
    for k, v in consts.items():
        if isinstance(v, dict):
            for sub in ("value", "nominal", "deviation_pct", "status"):
                if sub in v:
                    row[f"ec_{k}_{sub}"] = v[sub]
        else:
            row[f"ec_{k}"] = v


def _flatten_event(ev: dict[str, Any], object_name: Optional[str]) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for f in _BASE_FIELDS:
        row[f] = ev.get(f)

    include = {object_name} if object_name else _OBJECT_KEYS

    if "SPC" in include and isinstance(ev.get("SPC"), dict):
        _flatten_spc(row, ev["SPC"])
    if "APC" in include and isinstance(ev.get("APC"), dict):
        _flatten_object_id(row, ev["APC"], "apc")
        _flatten_params(row, ev["APC"], "apc")
    if "DC" in include and isinstance(ev.get("DC"), dict):
        _flatten_object_id(row, ev["DC"], "dc")
        _flatten_dc(row, ev["DC"])
    if "RECIPE" in include and isinstance(ev.get("RECIPE"), dict):
        _flatten_object_id(row, ev["RECIPE"], "recipe")
        _flatten_recipe(row, ev["RECIPE"])
    if "FDC" in include and isinstance(ev.get("FDC"), dict):
        _flatten_object_id(row, ev["FDC"], "fdc")
        _flatten_fdc(row, ev["FDC"])
    if "EC" in include and isinstance(ev.get("EC"), dict):
        _flatten_object_id(row, ev["EC"], "ec")
        _flatten_ec(row, ev["EC"])

    return row


def _nested_event(ev: dict[str, Any]) -> dict[str, Any]:
    """Object-native shape: keep SPC / APC / DC / RECIPE / FDC / EC as nested
    sub-objects. spc_charts is the SPC source-of-truth — LLM derives OOC
    count / OOC chart list via unnest + filter + count_rows / pluck.

    Returned record shape:
        {
          eventTime, lotID, toolID, step, spc_status, fdc_classification,
          spc_charts: [{name, value, ucl, lcl, is_ooc, status}, ...],
          APC: {...} or null,  # entire sub-object preserved as-is
          DC: {...},
          RECIPE: {...},
          FDC: {...},
          EC: {...},
        }
    """
    out: dict[str, Any] = {}
    for f in _BASE_FIELDS:
        out[f] = ev.get(f)

    # SPC: lift to spc_charts array (source of truth — per-chart is_ooc flag).
    spc = ev.get("SPC") or {}
    charts_obj = spc.get("charts") if isinstance(spc, dict) else None
    spc_charts: list[dict[str, Any]] = []
    if isinstance(charts_obj, dict):
        for chart_name, chart_obj in charts_obj.items():
            if not isinstance(chart_obj, dict):
                continue
            entry: dict[str, Any] = {"name": chart_name}
            for k in ("value", "ucl", "lcl", "is_ooc"):
                if k in chart_obj:
                    entry[k] = chart_obj[k]
            entry["status"] = "OOC" if entry.get("is_ooc") else "PASS"
            spc_charts.append(entry)
    out["spc_charts"] = spc_charts

    # Other object families preserved as-is — LLM uses path syntax to read.
    for key in ("APC", "DC", "RECIPE", "FDC", "EC"):
        v = ev.get(key)
        if isinstance(v, dict):
            out[key] = v
    return out


class ProcessHistoryBlockExecutor(BlockExecutor):
    block_id = "block_process_history"

    async def execute(
        self,
        *,
        params: dict[str, Any],
        inputs: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        tool_id = params.get("tool_id")
        lot_id = params.get("lot_id")
        step = params.get("step")

        # three-of-three optional but at least ONE required (matches get_process_info)
        if not any([tool_id, lot_id, step]):
            raise BlockExecutionError(
                code="MISSING_PARAM",
                message="請至少提供 tool_id / lot_id / step 其中一個（三擇一）",
                hint="原 MCP get_process_info 要求這三個參數至少帶一個",
            )

        # Reject comma-separated values up-front: agents sometimes try to pack
        # multiple toolIDs into the single `tool_id` field, which silently
        # matches zero rows. Surface a clear error + the right pattern.
        for fname, fval in (("tool_id", tool_id), ("lot_id", lot_id), ("step", step)):
            if isinstance(fval, str) and "," in fval:
                raise BlockExecutionError(
                    code="INVALID_PARAM",
                    message=f"`{fname}` 只接受單一值，不能用逗號分隔（看到：{fval!r}）",
                    hint=(
                        "需要查多台機台 / 多 lot / 多 step 時：source 不要設這個欄位，"
                        "改用 `block_filter` operator='in' value=[ ... ] 過濾。"
                        "範例：source step='STEP_001' → filter column='toolID' op='in' "
                        "value=['EQP-01','EQP-02','EQP-03','EQP-04','EQP-05']."
                    ),
                )
            if isinstance(fval, list):
                raise BlockExecutionError(
                    code="INVALID_PARAM",
                    message=f"`{fname}` 只接受單一字串，不能傳 list",
                    hint=(
                        "多值請改用 block_filter operator='in'。"
                        "block_process_history 的 tool_id / lot_id / step 是單一字串。"
                    ),
                )

        time_range = params.get("time_range", "24h")
        object_name = params.get("object_name") or None
        if object_name and object_name not in _OBJECT_KEYS:
            raise BlockExecutionError(
                code="INVALID_PARAM",
                message=f"object_name 必須是 {sorted(_OBJECT_KEYS)} 之一，或留空代表全部",
            )
        event_time = params.get("event_time")
        # Simulator API caps limit at 500. Clamp here so the block keeps
        # working when an LLM/user passes a higher value (otherwise upstream
        # returns 422 and the user sees an opaque error).
        raw_limit = int(params.get("limit", 100))
        limit = max(1, min(raw_limit, 500))

        query: dict[str, Any] = {"since": time_range, "limit": limit}
        if tool_id:
            query["toolID"] = tool_id
        if lot_id:
            query["lotID"] = lot_id
        if step:
            query["step"] = step
        if object_name:
            query["objectName"] = object_name
        if event_time:
            query["eventTime"] = event_time

        settings = get_settings()
        base = getattr(settings, "ONTOLOGY_SIM_URL", "") or ""
        if not base:
            raise BlockExecutionError(
                code="MISSING_CONFIG",
                message="ONTOLOGY_SIM_URL not configured",
                hint="Set ONTOLOGY_SIM_URL in settings / env",
            )

        url = f"{base.rstrip('/')}/api/v1/process/info"
        try:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT_S) as client:
                resp = await client.get(url, params=query)
        except httpx.HTTPError as e:
            raise BlockExecutionError(
                code="HTTP_ERROR",
                message=f"MCP fetch failed: {e}",
                hint="Check ontology_simulator is reachable",
            ) from e

        if resp.status_code >= 400:
            raise BlockExecutionError(
                code="UPSTREAM_ERROR",
                message=f"Upstream returned HTTP {resp.status_code}",
                hint=resp.text[:200],
            )

        payload = resp.json()
        events = payload.get("events", []) or []

        # 2026-05-13: nested is now DEFAULT. The 5 chart blocks that depend on
        # flat spc_<chart>_<field> columns (xbar_r / imr / ewma_cusum /
        # weco_rules / consecutive_rule) re-widen internally via
        # ensure_flat_spc, so the default flip is transparent for them.
        # Legacy callers can opt back to flat with nested=false.
        nested = params.get("nested")
        if nested is None:
            nested = True
        if nested:
            rows = [_nested_event(e) for e in events]
        else:
            rows = [_flatten_event(e, object_name) for e in events]
        df = pd.DataFrame(rows)

        return {"data": df}
