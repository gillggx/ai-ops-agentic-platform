"""SkillDefinitionService v18 — CRUD + LLM steps generation."""

import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.models.event_type import EventTypeModel
from app.repositories.skill_definition_repository import SkillDefinitionRepository
from app.schemas.skill_definition import (
    CompileStepsRequest,
    CompileStepsResponse,
    GenerateStepsRequest,
    GenerateStepsResponse,
    SkillAgentBuildRequest,
    SkillAgentBuildResponse,
    SkillDefinitionCreate,
    SkillDefinitionResponse,
    SkillDefinitionUpdate,
    StepMapping,
)
from sqlalchemy import select

logger = logging.getLogger(__name__)


def _to_response(obj, event_type_name: Optional[str] = None) -> SkillDefinitionResponse:
    def _j(s):
        try:
            return json.loads(s) if s else []
        except Exception:
            return []

    return SkillDefinitionResponse(
        id=obj.id,
        name=obj.name,
        description=obj.description,
        trigger_event_id=obj.trigger_event_id,
        trigger_event_name=event_type_name,
        trigger_mode=obj.trigger_mode,
        steps_mapping=_j(obj.steps_mapping),
        input_schema=_j(obj.input_schema) if hasattr(obj, "input_schema") else [],
        output_schema=_j(obj.output_schema),
        visibility=obj.visibility,
        is_active=obj.is_active,
        created_by=obj.created_by,
        created_at=obj.created_at,
        updated_at=obj.updated_at,
        trigger_patrol_id=getattr(obj, "trigger_patrol_id", None),
    )


class SkillDefinitionService:
    def __init__(
        self,
        repo: SkillDefinitionRepository,
        db: AsyncSession,
        llm=None,  # MCPBuilderService or similar — optional
    ) -> None:
        self._repo = repo
        self._db = db
        self._llm = llm

    async def _resolve_event_name(self, event_type_id: Optional[int]) -> Optional[str]:
        if not event_type_id:
            return None
        try:
            result = await self._db.execute(
                select(EventTypeModel).where(EventTypeModel.id == event_type_id)
            )
            et = result.scalar_one_or_none()
            return et.name if et else None
        except Exception:
            return None

    async def list_all(self) -> List[SkillDefinitionResponse]:
        objs = await self._repo.list_all()
        results = []
        for obj in objs:
            name = await self._resolve_event_name(obj.trigger_event_id)
            results.append(_to_response(obj, name))
        return results

    async def get(self, skill_id: int) -> SkillDefinitionResponse:
        obj = await self._repo.get_by_id(skill_id)
        if not obj:
            raise AppException(status_code=404, error_code="NOT_FOUND", detail=f"Skill id={skill_id} 不存在")
        name = await self._resolve_event_name(obj.trigger_event_id)
        return _to_response(obj, name)

    async def create(
        self,
        body: SkillDefinitionCreate,
        created_by: Optional[int] = None,
    ) -> SkillDefinitionResponse:
        data = body.model_dump()
        data["steps_mapping"] = [s.model_dump() for s in body.steps_mapping]
        data["output_schema"] = [f.model_dump() for f in body.output_schema]
        data["created_by"] = created_by
        obj = await self._repo.create(data)
        name = await self._resolve_event_name(obj.trigger_event_id)
        return _to_response(obj, name)

    async def update(self, skill_id: int, body: SkillDefinitionUpdate) -> SkillDefinitionResponse:
        data = body.model_dump(exclude_none=True)
        if "steps_mapping" in data:
            data["steps_mapping"] = [s if isinstance(s, dict) else s.model_dump() for s in data["steps_mapping"]]
        if "output_schema" in data:
            data["output_schema"] = [f if isinstance(f, dict) else f.model_dump() for f in data["output_schema"]]
        obj = await self._repo.update(skill_id, data)
        if not obj:
            raise AppException(status_code=404, error_code="NOT_FOUND", detail=f"Skill id={skill_id} 不存在")
        name = await self._resolve_event_name(obj.trigger_event_id)
        return _to_response(obj, name)

    async def delete(self, skill_id: int) -> None:
        ok = await self._repo.delete(skill_id)
        if not ok:
            raise AppException(status_code=404, error_code="NOT_FOUND", detail=f"Skill id={skill_id} 不存在")

    async def generate_steps(self, body: GenerateStepsRequest) -> GenerateStepsResponse:
        """Use LLM to generate steps_mapping + proposal_steps from natural language."""
        if not self._llm:
            return GenerateStepsResponse(success=False, error="LLM service not configured")

        et_name = await self._resolve_event_name(body.trigger_event_id) or "Unknown"

        mcp_catalog = (
            "Available execute_mcp calls (ONLY use these — no others exist):\n"
            "\n"
            "# --- recent process history of a tool OR lot (includes recipeID, spc_status) ---\n"
            "- execute_mcp('get_process_history', {'toolID': equipment_id, 'limit': 10})\n"
            "  Use when: checking a TOOL's recent N process records (e.g. 5-in-3-out OOC, recipe check)\n"
            "  → list: [{eventTime, lotID, toolID, step, recipeID, spc_status: 'PASS'|'OOC'|null, apcID}, ...]\n"
            "  Access: history = result if isinstance(result, list) else []\n"
            "\n"
            "- execute_mcp('get_process_history', {'lotID': lot_id, 'limit': 10})\n"
            "  Use when: checking a LOT's process steps and which recipes/tools it went through\n"
            "  → list: [{eventTime, lotID, toolID, step, recipeID, spc_status: 'PASS'|'OOC'|null, apcID}, ...]\n"
            "  Access: history = result if isinstance(result, list) else []\n"
            "\n"
            "# --- single snapshot: current state of a lot at a specific step ---\n"
            "- execute_mcp('get_process_context', {'targetID': lot_id, 'step': step, 'objectName': 'SPC'})\n"
            "  Use when: need detailed SPC value/ucl/lcl breakdown for a specific lot+step\n"
            "  → dict: {charts: {xbar_chart: {value: float, ucl: float, lcl: float}}, spc_status: 'PASS'|'OOC'}\n"
            "  Access: result.get('charts', {}).get('xbar_chart', {})\n"
            "\n"
            "- execute_mcp('get_process_context', {'targetID': lot_id, 'step': step, 'objectName': 'DC'})\n"
            "  → dict: {parameters: {<param_name>: {value: float, usl: float, lsl: float}}}\n"
            "  Access: result.get('parameters', {})\n"
        )

        system_prompt = f"""You are a factory AI monitoring expert. Convert natural language monitoring logic into structured Python steps + schema definitions.
CRITICAL: Output ONLY a valid JSON object. No explanation, no markdown fences, nothing outside JSON.

{mcp_catalog}

Special functions (call only, no import):
- await execute_mcp(mcp_name: str, params: dict) -> Any

Forbidden: import, open(), exec(), eval(), os, sys, subprocess, trigger_alarm

INPUT: The skill receives a dict. Use ONLY keys declared in input_schema.
  Access them like: equipment_id = _input.get("equipment_id")  — OR if injected as top-level: equipment_id

OUTPUT: The LAST step MUST assign _findings with this exact format:
_findings = {{
    "condition_met": <bool>,
    "summary": "<one sentence human-readable conclusion, e.g. 'Machine EQP-01 had 4/5 OOC runs, threshold exceeded'>",
    "outputs": {{
        "<output_schema key>": <actual value fetched from MCP>,
        ...
    }},
    "impacted_lots": [<lot_id>] if condition_met else []
}}

Example for "Tool最近5次Process中超過3次OOC" with input equipment_id:
  history = await execute_mcp('get_process_history', {{'toolID': equipment_id, 'limit': 10}})
  history = history if isinstance(history, list) else []
  recent = history[:5]
  records = [{{"index": i, "lotID": r.get("lotID"), "step": r.get("step"), "recipeID": r.get("recipeID"), "spc_status": r.get("spc_status"), "is_ooc": r.get("spc_status") == "OOC"}} for i, r in enumerate(recent)]
  ooc_count = sum(1 for rec in records if rec["is_ooc"])
  condition_met = ooc_count > 3
  _findings = {{"condition_met": condition_met, "summary": f"Machine {{equipment_id}} had {{ooc_count}}/{{len(recent)}} OOC runs", "outputs": {{"ooc_count": ooc_count, "checked": len(recent), "records": records}}, "impacted_lots": [r["lotID"] for r in records if r["is_ooc"]]}}

Required output format (JSON only, nothing else):
{{
  "proposal_steps": ["Plain English step 1", "Plain English step 2"],
  "steps_mapping": [
    {{"step_id": "step1", "nl_segment": "...", "python_code": "..."}}
  ],
  "input_schema": [
    {{"key": "equipment_id", "type": "string",  "required": true,  "description": "目標機台 ID"}},
    {{"key": "lot_id",       "type": "string",  "required": false, "description": "批次 ID（可選）"}}
  ],
  "output_schema": [
    {{"key": "ooc_count",  "type": "scalar", "label": "OOC 次數", "unit": "次", "description": "超出控制限次數"}},
    {{"key": "records",    "type": "table",  "label": "Process 記錄",
      "columns": [
        {{"key": "spc_status", "label": "SPC狀態", "type": "str"}},
        {{"key": "value",      "label": "量測值",   "type": "float"}},
        {{"key": "ucl",        "label": "UCL",      "type": "float"}},
        {{"key": "lcl",        "label": "LCL",      "type": "float"}},
        {{"key": "is_ooc",     "label": "OOC",      "type": "bool"}}
      ], "description": "最近 N 筆 Process 記錄"}},
    {{"key": "condition_summary", "type": "badge", "label": "診斷結論", "description": "是否達到觸發條件"}}
  ]
}}"""

        user_prompt = f"Monitoring logic (natural language):\n{body.nl_description}"

        try:
            resp = await self._llm.create(
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                max_tokens=4096,
            )
            raw = resp.text.strip()

            # Fallback: extract from reasoning_content (GLM-5-turbo / DeepSeek-R1)
            if not raw and resp.content:
                import re as _re
                for block in resp.content:
                    if isinstance(block, dict) and block.get("type") == "thinking":
                        thinking = block.get("thinking", "")
                        _matches = list(_re.finditer(r'\{[\s\S]*?"steps_mapping"[\s\S]*?\}', thinking))
                        if _matches:
                            raw = _matches[-1].group(0)
                            break

            import re
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
            parsed = json.loads(raw)
            steps = parsed.get("steps_mapping", [])
            proposal = parsed.get("proposal_steps", [s.get("nl_segment", "") for s in steps])
            return GenerateStepsResponse(
                success=True,
                proposal_steps=proposal,
                steps_mapping=steps,
                input_schema=parsed.get("input_schema", []),
                output_schema=parsed.get("output_schema", []),
            )
        except Exception as exc:
            logger.warning("generate_steps LLM failed: %s", exc)
            return GenerateStepsResponse(success=False, error=str(exc))

    async def compile_steps(self, body: CompileStepsRequest) -> CompileStepsResponse:
        """Compiler mode: user provides NL steps, LLM generates Python for each + validates."""
        if not self._llm:
            return CompileStepsResponse(success=False, error="LLM service not configured")

        et_name = await self._resolve_event_name(body.trigger_event_id) or "Unknown"

        mcp_catalog = (
            "Available execute_mcp calls (ONLY use these — no others exist):\n"
            "\n"
            "# --- recent process history of a tool OR lot (includes recipeID, spc_status) ---\n"
            "- execute_mcp('get_process_history', {'toolID': equipment_id, 'limit': 10})\n"
            "  Use when: checking a TOOL's recent N process records (e.g. 5-in-3-out OOC, recipe check)\n"
            "  → list: [{eventTime, lotID, toolID, step, recipeID, spc_status: 'PASS'|'OOC'|null, apcID}, ...]\n"
            "  Access: history = result if isinstance(result, list) else []\n"
            "\n"
            "- execute_mcp('get_process_history', {'lotID': lot_id, 'limit': 10})\n"
            "  Use when: checking a LOT's process steps and which recipes/tools it went through\n"
            "  → list: [{eventTime, lotID, toolID, step, recipeID, spc_status: 'PASS'|'OOC'|null, apcID}, ...]\n"
            "  Access: history = result if isinstance(result, list) else []\n"
            "\n"
            "# --- single snapshot: current state of a lot at a specific step ---\n"
            "- execute_mcp('get_process_context', {'targetID': lot_id, 'step': step, 'objectName': 'SPC'})\n"
            "  Use when: need detailed SPC value/ucl/lcl breakdown for a specific lot+step\n"
            "  → dict: {charts: {xbar_chart: {value: float, ucl: float, lcl: float}}, spc_status: 'PASS'|'OOC'}\n"
            "  Access: result.get('charts', {}).get('xbar_chart', {})\n"
            "\n"
            "- execute_mcp('get_process_context', {'targetID': lot_id, 'step': step, 'objectName': 'DC'})\n"
            "  → dict: {parameters: {<param_name>: {value: float, usl: float, lsl: float}}}\n"
            "  Access: result.get('parameters', {})\n"
        )

        nl_steps_text = "\n".join(
            f"  - step_id: \"{s.step_id}\"\n    nl_segment: \"{s.nl_segment}\""
            for s in body.nl_steps
        )

        system_prompt = f"""You are a Python code compiler for a factory AI monitoring system.
CRITICAL: Output ONLY a valid JSON object. Do NOT add any explanation, markdown, or text outside the JSON.

Event Payload variables available directly:
- event_type: str   (e.g. "{et_name}")
- equipment_id: str (e.g. "EQP-01")
- lot_id: str       (e.g. "LOT-0001")
- step: str         (e.g. "STEP_091")
- event_time: str   (ISO8601)

{mcp_catalog}

Special functions (call only, no import needed):
- await execute_mcp(mcp_name: str, params: dict) -> Any

Forbidden: import, open(), exec(), eval(), os, sys, subprocess, trigger_alarm

REQUIREMENT: The LAST step's python_code MUST end with this assignment.
Populate evidence with REAL values from MCP results (no placeholders):
_findings = {{
    "condition_met": <actual bool>,
    "evidence": {{<key>: <actual_value_from_mcp>, ..., "recent_records": [...]}},
    "impacted_lots": [lot_id] if condition_met else []
}}

Required output format (JSON only, nothing else):
{{
  "steps_mapping": [
    {{
      "step_id": "step1",
      "nl_segment": "...",
      "python_code": "..."
    }}
  ],
  "output_schema": [
    {{"field": "condition_met", "type": "bool", "label": "條件達成"}},
    {{"field": "<key>", "type": "<type>", "label": "<Chinese label>"}}
  ],
  "validation_notes": "brief note if logic has issues, else empty string",
  "has_issues": false
}}"""

        user_prompt = f"""Compile these steps to Python:

{nl_steps_text}

Rules:
1. Keep step_id and nl_segment exactly as given
2. python_code must implement the nl_segment logic using execute_mcp
3. The LAST step must assign _findings with condition_met + evidence from real MCP data
4. Variables defined in earlier steps are available in later steps
5. Output JSON only — no markdown fences, no explanation"""

        try:
            resp = await self._llm.create(
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                max_tokens=8192,
            )
            raw = resp.text.strip()

            # If the model returned empty text but has reasoning content, try to
            # extract JSON from the reasoning (handles GLM-5-turbo / DeepSeek-R1
            # edge case where all output lands in reasoning_content).
            if not raw and resp.content:
                for block in resp.content:
                    if isinstance(block, dict) and block.get("type") == "thinking":
                        thinking = block.get("thinking", "")
                        import re as _re
                        _matches = list(_re.finditer(r'\{[\s\S]*"steps_mapping"[\s\S]*\}', thinking))
                        if _matches:
                            raw = _matches[-1].group(0)
                            break

            import re
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
            parsed = json.loads(raw)
            return CompileStepsResponse(
                success=True,
                steps_mapping=parsed.get("steps_mapping", []),
                output_schema=parsed.get("output_schema", []),
                validation_notes=parsed.get("validation_notes", ""),
                has_issues=parsed.get("has_issues", False),
            )
        except Exception as exc:
            logger.warning("compile_steps LLM failed: %s", exc)
            return CompileStepsResponse(success=False, error=str(exc))

    async def agent_build(
        self,
        body: SkillAgentBuildRequest,
        created_by: Optional[int] = None,
    ) -> SkillAgentBuildResponse:
        """Agent-initiated one-shot: LLM generate steps → create Skill."""
        gen_req = GenerateStepsRequest(
            trigger_event_id=body.trigger_event_id or 0,
            nl_description=body.nl_description,
        )
        gen_resp = await self.generate_steps(gen_req)
        if not gen_resp.success:
            return SkillAgentBuildResponse(success=False, error=gen_resp.error)

        steps = [StepMapping(**s) for s in gen_resp.steps_mapping]
        from app.schemas.skill_definition import SchemaField
        schema_fields = [SchemaField(**f) for f in gen_resp.output_schema if isinstance(f, dict)]
        create_body = SkillDefinitionCreate(
            name=body.name,
            description=body.description,
            trigger_event_id=body.trigger_event_id,
            trigger_mode="both",
            steps_mapping=steps,
            output_schema=schema_fields,
        )
        skill = await self.create(create_body, created_by=created_by)
        return SkillAgentBuildResponse(
            success=True,
            skill_id=skill.id,
            name=skill.name,
            steps_mapping=skill.steps_mapping,
            output_schema=skill.output_schema,
        )
