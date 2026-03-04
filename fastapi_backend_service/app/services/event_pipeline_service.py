"""Event-Driven Diagnosis Pipeline Service.

Executes the full end-to-end chain for a triggered event:
  Event params → Skill lookup → param mapping → DataSubject API call
  → MCP script execution → LLM diagnosis → structured report per Skill.
"""

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from app.config import get_settings
from app.repositories.data_subject_repository import DataSubjectRepository
from app.repositories.event_type_repository import EventTypeRepository
from app.repositories.mcp_definition_repository import MCPDefinitionRepository
from app.repositories.skill_definition_repository import SkillDefinitionRepository
from app.repositories.system_parameter_repository import SystemParameterRepository
from app.services.mcp_builder_service import MCPBuilderService
from app.services.mcp_definition_service import _normalize_output
from app.services.sandbox_service import execute_script

logger = logging.getLogger(__name__)


def _j(s: Optional[str]) -> Any:
    """Parse a JSON string, returning None on failure or empty input."""
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return None


def _parse_et_diagnosis_skills(raw: Optional[str]) -> tuple[List[int], Dict[int, List]]:
    """Parse ET's diagnosis_skill_ids column into (skill_id_list, {skill_id: param_mappings}).

    Handles both old format [int, ...] and new format [{skill_id, param_mappings}, ...].
    Returns (ordered_ids, mapping_dict).
    """
    try:
        data = json.loads(raw) if raw else []
    except Exception:
        data = []

    skill_ids: List[int] = []
    skill_param_map: Dict[int, List] = {}
    for entry in data:
        if isinstance(entry, int):
            skill_ids.append(entry)
            skill_param_map[entry] = []
        elif isinstance(entry, dict) and "skill_id" in entry:
            sid = int(entry["skill_id"])
            skill_ids.append(sid)
            skill_param_map[sid] = entry.get("param_mappings", [])
    return skill_ids, skill_param_map


class SkillPipelineResult:
    """Result of running the full pipeline for one Skill."""

    def __init__(
        self,
        skill_id: int,
        skill_name: str,
        mcp_name: str,
        status: str = "NORMAL",
        conclusion: str = "",
        evidence: Optional[List[str]] = None,
        summary: str = "",
        human_recommendation: str = "",
        problem_object: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        mcp_output: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialise a SkillPipelineResult with all pipeline output fields."""
        self.skill_id = skill_id
        self.skill_name = skill_name
        self.mcp_name = mcp_name
        self.status = status
        self.conclusion = conclusion
        self.evidence = evidence or []
        self.summary = summary
        self.human_recommendation = human_recommendation
        self.problem_object = problem_object or {}
        self.error = error
        self.mcp_output = mcp_output

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the result to a plain dict for SSE / API responses."""
        return {
            "skill_id": self.skill_id,
            "skill_name": self.skill_name,
            "mcp_name": self.mcp_name,
            "status": self.status,
            "conclusion": self.conclusion,
            "evidence": self.evidence,
            "summary": self.summary,
            "human_recommendation": self.human_recommendation,
            "problem_object": self.problem_object,
            "error": self.error,
            "mcp_output": self.mcp_output,
        }


class EventPipelineService:
    """Orchestrates the full event-driven diagnosis pipeline: skill lookup → DS fetch → MCP script → LLM diagnosis."""

    def __init__(
        self,
        skill_repo: SkillDefinitionRepository,
        et_repo: EventTypeRepository,
        mcp_repo: MCPDefinitionRepository,
        ds_repo: DataSubjectRepository,
        llm: MCPBuilderService,
        sp_repo: Optional[SystemParameterRepository] = None,
    ) -> None:
        self._skill_repo = skill_repo
        self._et_repo = et_repo
        self._mcp_repo = mcp_repo
        self._ds_repo = ds_repo
        self._llm = llm
        self._sp_repo = sp_repo

    async def run(
        self,
        event_type_name: str,
        event_id: str,
        event_params: Dict[str, str],
        base_url: str = "",
    ) -> Dict[str, Any]:
        """Run the full event-driven diagnosis pipeline.

        Returns a dict with 'event' metadata and a 'skills' list of results.
        """
        # 1. Resolve event type by name
        et = await self._et_repo.get_by_name(event_type_name)
        if et is None:
            return {
                "event": {"event_type": event_type_name, "event_id": event_id},
                "skills": [],
                "error": f"找不到 Event Type: {event_type_name}",
            }

        # 2. Find bound skills from ET's diagnosis_skills list
        skill_ids, skill_param_map = _parse_et_diagnosis_skills(
            getattr(et, "diagnosis_skill_ids", None)
        )
        if not skill_ids:
            return {
                "event": {"event_type": event_type_name, "event_id": event_id},
                "skills": [],
                "error": f"尚無 Skill 綁定至 {event_type_name}，請先在 EventType 設定診斷 Skills。",
            }
        skills = await self._skill_repo.get_by_ids(skill_ids)

        # 3. Load system prompt (optional)
        system_prompt = None
        if self._sp_repo:
            system_prompt = await self._sp_repo.get_value("PROMPT_SKILL_DIAGNOSIS")

        # 4. Process each skill using ET-specific param mappings
        results: List[Dict[str, Any]] = []
        for skill in skills:
            et_pm = skill_param_map.get(skill.id, [])
            result = await self._run_skill(skill, event_params, system_prompt, base_url, et_param_mappings=et_pm)
            results.append(result.to_dict())

        return {
            "event": {
                "event_type": event_type_name,
                "event_id": event_id,
                "params": event_params,
            },
            "skills": results,
        }

    async def stream(
        self,
        event_type_name: str,
        event_id: str,
        event_params: Dict[str, str],
        base_url: str = "",
    ):
        """Async generator that yields SSE-ready dicts as each skill completes.

        Yields:
            {"type": "start", "event": {...}, "skill_count": N}
            {"type": "skill_start", "index": i, "skill_name": ..., "mcp_name": ...}
            {"type": "skill_done", "index": i, ...result.to_dict()}
            {"type": "done"}
        """
        # 1. Resolve event type
        et = await self._et_repo.get_by_name(event_type_name)
        if et is None:
            yield {
                "type": "error",
                "message": f"找不到 Event Type: {event_type_name}",
            }
            return

        # 2. Find bound skills from ET's diagnosis_skills list
        skill_ids, skill_param_map = _parse_et_diagnosis_skills(
            getattr(et, "diagnosis_skill_ids", None)
        )
        if not skill_ids:
            yield {
                "type": "error",
                "message": f"尚無 Skill 綁定至 {event_type_name}，請先在 EventType 設定診斷 Skills。",
            }
            return
        skills = await self._skill_repo.get_by_ids(skill_ids)

        # 3. Load system prompt
        system_prompt = None
        if self._sp_repo:
            system_prompt = await self._sp_repo.get_value("PROMPT_SKILL_DIAGNOSIS")

        # 4. Yield start event
        yield {
            "type": "start",
            "event": {
                "event_type": event_type_name,
                "event_id": event_id,
                "params": event_params,
            },
            "skill_count": len(skills),
        }

        # 5. Process each skill, yield as each completes
        for i, skill in enumerate(skills):
            yield {
                "type": "skill_start",
                "index": i,
                "skill_name": skill.name,
                "mcp_name": "",  # filled in after MCP load
            }

            et_pm = skill_param_map.get(skill.id, [])
            result = await self._run_skill(skill, event_params, system_prompt, base_url, et_param_mappings=et_pm)

            yield {"type": "skill_done", "index": i, **result.to_dict()}

        yield {"type": "done"}

    async def _run_skill(self, skill, event_params: Dict[str, str], system_prompt, base_url: str = "", et_param_mappings: Optional[List[Dict]] = None) -> SkillPipelineResult:
        """Execute the full pipeline for a single Skill."""
        skill_name = skill.name
        mcp_id_list = _j(skill.mcp_ids) or []
        mcp_id = mcp_id_list[0] if mcp_id_list else None

        if not mcp_id:
            return SkillPipelineResult(
                skill_id=skill.id, skill_name=skill_name, mcp_name="—",
                error="此 Skill 尚未綁定 MCP",
            )

        # Load MCP
        mcp = await self._mcp_repo.get_by_id(mcp_id)
        if not mcp:
            return SkillPipelineResult(
                skill_id=skill.id, skill_name=skill_name, mcp_name="—",
                error=f"MCP id={mcp_id} 不存在",
            )

        mcp_name = mcp.name

        if not mcp.processing_script:
            return SkillPipelineResult(
                skill_id=skill.id, skill_name=skill_name, mcp_name=mcp_name,
                error="此 MCP 尚未生成 Python 腳本，請先在 MCP Builder 完成試跑並儲存。",
            )

        # Load DataSubject
        ds = await self._ds_repo.get_by_id(mcp.data_subject_id)
        if not ds:
            return SkillPipelineResult(
                skill_id=skill.id, skill_name=skill_name, mcp_name=mcp_name,
                error="找不到對應的 DataSubject",
            )

        ds_api_config = _j(ds.api_config) if isinstance(ds.api_config, str) else (ds.api_config or {})
        endpoint_url = ds_api_config.get("endpoint_url", "")
        if not endpoint_url:
            return SkillPipelineResult(
                skill_id=skill.id, skill_name=skill_name, mcp_name=mcp_name,
                error="DataSubject 缺少 endpoint_url 設定",
            )

        # Resolve param mappings: prefer ET-level mappings, fall back to skill's own
        if et_param_mappings is not None:
            param_mappings = et_param_mappings
        else:
            param_mappings = _j(skill.param_mappings) or []
        resolved: Dict[str, str] = {}
        for mapping in param_mappings:
            event_field = mapping.get("event_field", "")
            mcp_param   = mapping.get("mcp_param", "")
            if event_field and mcp_param:
                # Look up the event_field value (case-insensitive key match)
                val = None
                for k, v in event_params.items():
                    if k.lower() == event_field.lower():
                        val = v
                        break
                if val is not None:
                    resolved[mcp_param] = val

        # Fetch raw data from DataSubject API
        try:
            raw_data = await self._fetch_ds_data(endpoint_url, resolved, base_url)
        except Exception as exc:
            return SkillPipelineResult(
                skill_id=skill.id, skill_name=skill_name, mcp_name=mcp_name,
                error=f"DataSubject API 呼叫失敗：{exc}",
            )

        # Run MCP processing script
        try:
            output_data = await execute_script(mcp.processing_script, raw_data)
        except Exception as exc:
            return SkillPipelineResult(
                skill_id=skill.id, skill_name=skill_name, mcp_name=mcp_name,
                error=f"MCP 腳本執行失敗：{exc}",
            )

        # Normalise output into Standard Payload {dataset, ui_render, output_schema}
        # so the frontend evidence section always has a consistent structure.
        llm_schema = _j(mcp.output_schema) if hasattr(mcp, "output_schema") else None
        output_data = _normalize_output(output_data, llm_schema)

        # Auto-generate chart when script produced no chart_data but dataset is available
        if not output_data.get("ui_render", {}).get("chart_data") and output_data.get("dataset"):
            ui_cfg = _j(mcp.ui_render_config) if isinstance(mcp.ui_render_config, str) else (mcp.ui_render_config or {})
            if ui_cfg.get("chart_type", "table") not in ("table", "", None):
                from app.services.mcp_definition_service import _auto_chart  # noqa: PLC0415
                chart = _auto_chart(output_data["dataset"], ui_cfg)
                if chart:
                    output_data = {
                        **output_data,
                        "ui_render": {**(output_data.get("ui_render") or {}), "chart_data": chart, "type": "chart"},
                    }

        # Attach call params so the frontend can display which parameters were used
        output_data = {**output_data, "_call_params": resolved}

        # Run LLM diagnosis
        diagnostic_prompt = skill.diagnostic_prompt or ""
        if not diagnostic_prompt:
            return SkillPipelineResult(
                skill_id=skill.id, skill_name=skill_name, mcp_name=mcp_name,
                error="此 Skill 尚未設定 Diagnostic Prompt",
            )

        try:
            llm_result = await self._llm.try_diagnosis(
                diagnostic_prompt=diagnostic_prompt,
                mcp_outputs={mcp_name: output_data},
                system_prompt=system_prompt,
            )
        except Exception as exc:
            return SkillPipelineResult(
                skill_id=skill.id, skill_name=skill_name, mcp_name=mcp_name,
                error=f"LLM 診斷失敗：{exc}",
            )

        raw_status = llm_result.get("status") or llm_result.get("severity") or ""
        status = "NORMAL" if raw_status.upper() == "NORMAL" else "ABNORMAL"

        return SkillPipelineResult(
            skill_id=skill.id,
            skill_name=skill_name,
            mcp_name=mcp_name,
            status=status,
            conclusion=llm_result.get("conclusion", ""),
            evidence=llm_result.get("evidence", []),
            summary=llm_result.get("summary", ""),
            human_recommendation=skill.human_recommendation or "",
            problem_object=llm_result.get("problem_object") or {},
            mcp_output=output_data,
        )

    @staticmethod
    async def _fetch_ds_data(endpoint_url: str, params: Dict[str, str], base_url: str = "") -> Any:
        """Fetch raw data from DataSubject endpoint using httpx (no auth needed for /mock/*)."""
        if endpoint_url.startswith("/") and base_url:
            endpoint_url = base_url + endpoint_url
        async with httpx.AsyncClient(timeout=get_settings().HTTPX_TIMEOUT_SECONDS) as client:
            response = await client.get(endpoint_url, params=params)
            response.raise_for_status()
            payload = response.json()
        # Unwrap StandardResponse envelope if present
        return payload.get("data", payload) if isinstance(payload, dict) and "data" in payload else payload
