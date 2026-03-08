"""Skill Execute Service — run a Skill and return strict view-separated output.

This implements the PRD v12 Section 3.1 execution contract:
  - llm_readable_data: concise, hallucination-resistant data for the AI agent
  - ui_render_payload: chart/table data for the frontend UI (agent must NOT parse this)
"""

import json
import logging
from typing import Any, Dict, List, Optional

from app.core.exceptions import AppException
from app.repositories.data_subject_repository import DataSubjectRepository
from app.repositories.mcp_definition_repository import MCPDefinitionRepository
from app.repositories.skill_definition_repository import SkillDefinitionRepository
from app.services.event_pipeline_service import EventPipelineService
from app.services.mcp_definition_service import _normalize_output
from app.services.sandbox_service import execute_diagnose_fn, execute_script

logger = logging.getLogger(__name__)


def _j(s: Optional[str]) -> Any:
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return None


class SkillExecuteService:
    """Execute a Skill pipeline and return strictly separated llm/ui payloads."""

    def __init__(
        self,
        skill_repo: SkillDefinitionRepository,
        mcp_repo: MCPDefinitionRepository,
        ds_repo: DataSubjectRepository,
    ) -> None:
        self._skill_repo = skill_repo
        self._mcp_repo = mcp_repo
        self._ds_repo = ds_repo

    async def execute(
        self,
        skill_id: int,
        params: Dict[str, Any],
        base_url: str = "",
    ) -> Dict[str, Any]:
        """Execute skill and return {status, llm_readable_data, ui_render_payload}.

        Raises AppException on configuration errors (404 etc.).
        Returns error payload dict on runtime errors (so agent can see the message).
        """
        skill = await self._skill_repo.get_by_id(skill_id)
        if not skill:
            raise AppException(status_code=404, error_code="NOT_FOUND", detail=f"Skill id={skill_id} 不存在")

        mcp_id_list: List[int] = _j(skill.mcp_ids) or []
        if not mcp_id_list:
            raise AppException(status_code=422, error_code="SKILL_NO_MCP", detail="此 Skill 尚未綁定 MCP")

        # Use first MCP for execution
        mcp_id = mcp_id_list[0]
        mcp = await self._mcp_repo.get_by_id(mcp_id)
        if not mcp:
            raise AppException(status_code=404, error_code="NOT_FOUND", detail=f"MCP id={mcp_id} 不存在")

        # Resolve data source:
        #   - mcp_type='system' → this MCP IS the data source; use its api_config directly
        #   - mcp_type='custom' + system_mcp_id → look up parent system MCP
        #   - fallback → legacy data_subject_id
        mcp_is_system = getattr(mcp, 'mcp_type', 'custom') == 'system'
        if mcp_is_system:
            sys_mcp = mcp
            ds_api_config = _j(mcp.api_config) if isinstance(mcp.api_config, str) else (mcp.api_config or {})
        else:
            system_mcp_id = getattr(mcp, 'system_mcp_id', None)
            if system_mcp_id:
                sys_mcp = await self._mcp_repo.get_by_id(system_mcp_id)
                if not sys_mcp:
                    raise AppException(status_code=404, error_code="NOT_FOUND", detail=f"System MCP id={system_mcp_id} 不存在")
                ds_api_config = _j(sys_mcp.api_config) if isinstance(sys_mcp.api_config, str) else (sys_mcp.api_config or {})
            else:
                ds = await self._ds_repo.get_by_id(mcp.data_subject_id)
                if not ds:
                    raise AppException(status_code=404, error_code="NOT_FOUND", detail="System MCP / DataSubject 不存在")
                ds_api_config = _j(ds.api_config) if isinstance(ds.api_config, str) else (ds.api_config or {})

        endpoint_url = ds_api_config.get("endpoint_url", "")

        if not endpoint_url:
            raise AppException(status_code=422, error_code="DS_NO_ENDPOINT", detail="System MCP / DataSubject 缺少 endpoint_url")

        # System MCPs have no processing_script — pass raw data directly to LLM diagnosis
        if not mcp_is_system and not mcp.processing_script:
            raise AppException(status_code=422, error_code="MCP_NO_SCRIPT", detail="MCP 尚未生成腳本，請先在 MCP Builder 完成設定")

        if not skill.diagnostic_prompt:
            raise AppException(status_code=422, error_code="SKILL_NO_PROMPT", detail="Skill 尚未設定 Diagnostic Prompt")

        # ── 1. Fetch DataSubject raw data ──
        try:
            raw_data = await EventPipelineService._fetch_ds_data(endpoint_url, params, base_url)
        except Exception as exc:
            return {
                "status": "error",
                "llm_readable_data": {"status": "ERROR", "error": f"資料查詢失敗：{exc}"},
                "ui_render_payload": {"has_chart": False},
            }

        # ── 2. Run MCP processing script in sandbox (or use raw data for system MCPs) ──
        if mcp_is_system:
            # System MCP: no transformation script — wrap raw data as standard output
            rows = raw_data if isinstance(raw_data, list) else [raw_data]
            output_data = {
                "dataset": rows,
                "output_schema": {"fields": []},
                "ui_render": {"type": "table", "charts": [], "chart_data": None},
            }
        else:
            try:
                output_data = await execute_script(mcp.processing_script, raw_data)
            except Exception as exc:
                return {
                    "status": "error",
                    "llm_readable_data": {"status": "ERROR", "error": f"腳本執行失敗：{exc}"},
                    "ui_render_payload": {"has_chart": False},
                }

        llm_schema = _j(mcp.output_schema) if not mcp_is_system else None
        output_data = _normalize_output(output_data, llm_schema)

        # Auto-generate chart if script produced no chart_data
        if not output_data.get("ui_render", {}).get("chart_data") and output_data.get("dataset"):
            ui_cfg = _j(mcp.ui_render_config) if isinstance(mcp.ui_render_config, str) else (mcp.ui_render_config or {})
            if ui_cfg.get("chart_type", "table") not in ("table", "", None):
                from app.services.mcp_definition_service import _auto_chart  # noqa: PLC0415
                chart = _auto_chart(output_data["dataset"], ui_cfg)
                if chart:
                    output_data = {
                        **output_data,
                        "ui_render": {**(output_data.get("ui_render") or {}), "chart_data": chart, "charts": [chart], "type": "chart"},
                    }

        # ── 3. Python diagnose() execution (no LLM) ──
        # Load generated_code saved from Skill Builder simulation
        last_result = _j(skill.last_diagnosis_result) or {}
        diagnose_code = last_result.get("generated_code") or ""
        if not diagnose_code:
            return {
                "status": "error",
                "llm_readable_data": {
                    "status": "ERROR",
                    "error": "此 Skill 尚未在 Skill Builder 完成模擬，缺少診斷腳本。請先在 Skill Builder 執行「試跑」以生成診斷邏輯。",
                },
                "ui_render_payload": {"has_chart": False},
            }

        try:
            diag_result = await execute_diagnose_fn(
                code=diagnose_code,
                mcp_outputs={mcp.name: output_data},
            )
        except Exception as exc:
            return {
                "status": "error",
                "llm_readable_data": {"status": "ERROR", "error": f"診斷腳本執行失敗：{exc}"},
                "ui_render_payload": {"has_chart": False},
            }

        raw_status = str(diag_result.get("status", "")).upper()
        diag_status = "NORMAL" if raw_status == "NORMAL" else "ABNORMAL"

        # Extract problematic targets from problem_object
        problem_obj = diag_result.get("problem_object") or {}
        problematic_targets: List[str] = []
        if isinstance(problem_obj, dict):
            for v in problem_obj.values():
                if isinstance(v, list):
                    problematic_targets.extend([str(x) for x in v])
                elif v:
                    problematic_targets.append(str(v))
        if not problematic_targets and diag_status == "ABNORMAL" and skill.problem_subject:
            problematic_targets = [skill.problem_subject]

        # ── 4. Build strict view-separated response ──

        # llm_readable_data: minimal, anti-hallucination data for the AI agent
        llm_readable_data: Dict[str, Any] = {
            "status": diag_status,
            "diagnosis_message": diag_result.get("diagnosis_message", ""),
            "problematic_targets": problematic_targets,
        }
        if diag_status == "ABNORMAL" and skill.human_recommendation:
            llm_readable_data["expert_action"] = skill.human_recommendation

        # ui_render_payload: rich rendering data for frontend (agent must NOT parse)
        ui_render = output_data.get("ui_render") or {}
        chart_data_raw = ui_render.get("chart_data")
        chart_data_parsed: Any = None
        if chart_data_raw:
            if isinstance(chart_data_raw, str):
                try:
                    chart_data_parsed = json.loads(chart_data_raw)
                except Exception:
                    chart_data_parsed = None
            elif isinstance(chart_data_raw, dict):
                chart_data_parsed = chart_data_raw

        ui_render_payload: Dict[str, Any] = {
            "has_chart": chart_data_parsed is not None,
            "chart_type": "plotly" if chart_data_parsed else None,
            "chart_data": chart_data_parsed,
            "dataset": output_data.get("dataset"),
            "output_schema": output_data.get("output_schema"),
        }

        return {
            "status": "success",
            "skill_id": skill_id,
            "skill_name": skill.name,
            "llm_readable_data": llm_readable_data,
            "ui_render_payload": ui_render_payload,
        }
