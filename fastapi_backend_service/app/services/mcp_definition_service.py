"""Service layer for MCPDefinition CRUD + LLM generation."""

import json
import logging
import time
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

from app.core.exceptions import AppException
from app.models.mcp_definition import MCPDefinitionModel
from app.repositories.data_subject_repository import DataSubjectRepository
from app.repositories.mcp_definition_repository import MCPDefinitionRepository
from app.repositories.system_parameter_repository import SystemParameterRepository
from app.schemas.mcp_definition import (
    MCPCheckIntentResponse,
    MCPDefinitionCreate,
    MCPDefinitionResponse,
    MCPDefinitionUpdate,
    MCPGenerateResponse,
    MCPRunWithDataRequest,  # noqa: F401 — imported for re-use in router
    MCPTryRunResponse,
)
from app.services.mcp_builder_service import MCPBuilderService
from app.services.sandbox_service import execute_script

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
            ui["charts"] = clean
            if clean and not ui.get("chart_data"):
                ui["chart_data"] = clean[0]
            elif not clean:
                ui["chart_data"] = None

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
        try:
            _t0_llm = time.time()
            result = await self._llm.generate_for_try_run(
                processing_intent=processing_intent,
                data_subject_name=ds_name,
                data_subject_output_schema=output_schema_raw,
                system_prompt=system_prompt,
            )
            _t1_llm = time.time()
            logger.warning(
                "try_run perf | stage=LLM_codegen elapsed=%.2fs raw_data_records=%d",
                _t1_llm - _t0_llm,
                _record_count,
            )
        except Exception as exc:
            return MCPTryRunResponse(success=False, error=f"LLM 生成失敗：{exc}")

        script = result.get("processing_script", "")
        if not script or not script.strip() or "def process" not in script:
            # LLM refused or produced unusable output — surface a helpful error
            refusal = script.strip() if script and script.strip() else "LLM 未生成任何腳本內容"
            return MCPTryRunResponse(
                success=False,
                error=(
                    f"LLM 拒絕生成腳本：{refusal[:300]}\n\n"
                    "建議：加工意圖請聚焦於「資料計算、統計分析、異常標記」，"
                    "例如「計算 mean/std，標記超出 3σ 的點並輸出 status 欄位」。"
                    "「診斷」邏輯應放在 Skill 層而非 MCP 層。"
                ),
            )
        try:
            _t0_sb = time.time()
            output_data = await execute_script(script, sample_data)
            _t1_sb = time.time()
            logger.warning(
                "try_run perf | stage=sandbox_exec elapsed=%.2fs raw_data_records=%d",
                _t1_sb - _t0_sb,
                _record_count,
            )
        except (ValueError, TimeoutError) as exc:
            error_msg = f"沙盒執行失敗：{exc}"
            triage = await self._analyze_sandbox_error(
                script, error_msg, processing_intent, ds_name
            )
            parts = []
            if triage.get("error_reason"):  parts.append(f"錯誤原因：{triage['error_reason']}")
            if triage.get("script_issue"):  parts.append(f"腳本問題：{triage['script_issue']}")
            if triage.get("fix_suggestion"): parts.append(f"修改建議：{triage['fix_suggestion']}")
            return MCPTryRunResponse(
                success=False,
                script=script,
                error=error_msg,
                error_analysis="\n".join(parts) if parts else None,
                error_type=triage.get("error_type"),
                suggested_prompt=triage.get("suggested_prompt") or None,
            )
        except Exception as exc:
            error_msg = f"未預期的執行錯誤：{exc}"
            triage = await self._analyze_sandbox_error(
                script, error_msg, processing_intent, ds_name
            )
            parts = []
            if triage.get("error_reason"):  parts.append(f"錯誤原因：{triage['error_reason']}")
            if triage.get("script_issue"):  parts.append(f"腳本問題：{triage['script_issue']}")
            if triage.get("fix_suggestion"): parts.append(f"修改建議：{triage['fix_suggestion']}")
            return MCPTryRunResponse(
                success=False,
                script=script,
                error=error_msg,
                error_analysis="\n".join(parts) if parts else None,
                error_type=triage.get("error_type"),
                suggested_prompt=triage.get("suggested_prompt") or None,
            )

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

        return MCPTryRunResponse(
            success=True,
            script=script,
            output_data=output_data,
            ui_render_config=result.get("ui_render_config", {}),
            output_schema=result.get("output_schema", {}),
            input_definition=result.get("input_definition", {}),
            summary=result.get("summary", ""),
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
                url = "http://127.0.0.1:8000" + endpoint_url
            else:
                url = endpoint_url

            # Flatten raw_data into query params / body
            params_dict: Dict[str, Any] = {}
            if isinstance(raw_data, dict):
                params_dict = raw_data
            elif isinstance(raw_data, list) and raw_data and isinstance(raw_data[0], dict):
                params_dict = raw_data[0]

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
                        url = "http://127.0.0.1:8000" + endpoint_url
                    else:
                        url = endpoint_url
                    params_dict: Dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
                    try:
                        async with httpx.AsyncClient(timeout=30.0) as client:
                            if method == "GET":
                                resp = await client.get(url, params=params_dict, headers=headers)
                            else:
                                resp = await client.post(url, json=params_dict, headers=headers)
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
