"""Service layer for SkillDefinition CRUD."""

import json
from typing import Any, Dict, List, Optional

from app.core.exceptions import AppException
from app.ontology.models.skill import SkillDefinition as SkillDefinitionModel
from app.ontology.repositories.data_subject_repository import DataSubjectRepository
from app.ontology.repositories.event_type_repository import EventTypeRepository
from app.ontology.repositories.mcp_definition_repository import MCPDefinitionRepository
from app.ontology.repositories.skill_definition_repository import SkillDefinitionRepository
from app.ontology.repositories.system_parameter_repository import SystemParameterRepository
from app.ontology.schemas.skill_definition import (
    SkillCheckCodeDiagnosisIntentResponse,
    SkillDefinitionCreate,
    SkillDefinitionResponse,
    SkillDefinitionUpdate,
    SkillDiagnoseWithFeedbackResponse,
    SkillGenerateCodeDiagnosisResponse,
    SkillTryDiagnosisResponse,
)
from app.services.mcp_builder_service import MCPBuilderService


def _j(s: Optional[str]) -> Any:
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return None


def _to_response(obj: SkillDefinitionModel) -> SkillDefinitionResponse:
    mcp_ids_list = _j(obj.mcp_ids) or []
    return SkillDefinitionResponse(
        id=obj.id,
        name=obj.name,
        description=obj.description,
        problem_subject=obj.problem_subject,
        event_type_id=obj.event_type_id,
        mcp_id=mcp_ids_list[0] if mcp_ids_list else None,
        mcp_ids=obj.mcp_ids or "[]",
        param_mappings=_j(obj.param_mappings),
        diagnostic_prompt=obj.diagnostic_prompt,
        human_recommendation=obj.human_recommendation,
        last_diagnosis_result=_j(obj.last_diagnosis_result),
        visibility=obj.visibility if hasattr(obj, 'visibility') and obj.visibility else "private",
        created_at=obj.created_at,
        updated_at=obj.updated_at,
    )


class SkillDefinitionService:
    def __init__(
        self,
        repo: SkillDefinitionRepository,
        et_repo: EventTypeRepository,
        mcp_repo: MCPDefinitionRepository,
        llm: Optional[MCPBuilderService] = None,
        sp_repo: Optional[SystemParameterRepository] = None,
        ds_repo: Optional[DataSubjectRepository] = None,
    ) -> None:
        self._repo = repo
        self._et_repo = et_repo
        self._mcp_repo = mcp_repo
        self._llm = llm
        self._sp_repo = sp_repo
        self._ds_repo = ds_repo

    async def list_all(self) -> List[SkillDefinitionResponse]:
        return [_to_response(o) for o in await self._repo.get_all()]

    async def get(self, skill_id: int) -> SkillDefinitionResponse:
        obj = await self._repo.get_by_id(skill_id)
        if not obj:
            raise AppException(status_code=404, error_code="NOT_FOUND", detail="Skill 不存在")
        return _to_response(obj)

    async def create(self, data: SkillDefinitionCreate) -> SkillDefinitionResponse:
        if data.event_type_id is not None and not await self._et_repo.get_by_id(data.event_type_id):
            raise AppException(status_code=404, error_code="NOT_FOUND", detail="EventType 不存在")
        kwargs: Dict[str, Any] = {
            "name": data.name,
            "description": data.description,
            "mcp_ids": [data.mcp_id] if data.mcp_id else [],
        }
        if data.event_type_id is not None:
            kwargs["event_type_id"] = data.event_type_id
        if data.param_mappings is not None:
            kwargs["param_mappings"] = [m.model_dump() for m in data.param_mappings]
        if data.problem_subject is not None:
            kwargs["problem_subject"] = data.problem_subject
        if data.diagnostic_prompt is not None:
            kwargs["diagnostic_prompt"] = data.diagnostic_prompt
        if data.human_recommendation is not None:
            kwargs["human_recommendation"] = data.human_recommendation
        if data.last_diagnosis_result is not None:
            kwargs["last_diagnosis_result"] = data.last_diagnosis_result
        obj = await self._repo.create(**kwargs)
        return _to_response(obj)

    async def update(self, skill_id: int, data: SkillDefinitionUpdate) -> SkillDefinitionResponse:
        obj = await self._repo.get_by_id(skill_id)
        if not obj:
            raise AppException(status_code=404, error_code="NOT_FOUND", detail="Skill 不存在")
        updates: Dict[str, Any] = {}
        if data.name is not None:
            updates["name"] = data.name
        if data.description is not None:
            updates["description"] = data.description
        if data.problem_subject is not None:
            updates["problem_subject"] = data.problem_subject
        if "mcp_id" in data.model_fields_set:
            updates["mcp_ids"] = [data.mcp_id] if data.mcp_id else []
        if data.param_mappings is not None:
            updates["param_mappings"] = [m.model_dump() for m in data.param_mappings]
        if data.diagnostic_prompt is not None:
            updates["diagnostic_prompt"] = data.diagnostic_prompt
        if data.human_recommendation is not None:
            updates["human_recommendation"] = data.human_recommendation
        if "last_diagnosis_result" in data.model_fields_set:
            updates["last_diagnosis_result"] = (
                json.dumps(data.last_diagnosis_result, ensure_ascii=False)
                if data.last_diagnosis_result is not None else None
            )
        if data.visibility is not None:
            updates["visibility"] = data.visibility
        obj = await self._repo.update(obj, **updates)
        return _to_response(obj)

    async def delete(self, skill_id: int) -> None:
        obj = await self._repo.get_by_id(skill_id)
        if not obj:
            raise AppException(status_code=404, error_code="NOT_FOUND", detail="Skill 不存在")
        await self._repo.delete(obj)

    async def get_mcp_output_schemas(self, skill_id: int) -> Dict[str, Any]:
        """Return output schemas + sample outputs of all MCPs bound to this skill."""
        obj = await self._repo.get_by_id(skill_id)
        if not obj:
            raise AppException(status_code=404, error_code="NOT_FOUND", detail="Skill 不存在")
        mcp_ids = _j(obj.mcp_ids) or []
        schemas: Dict[str, Any] = {}
        for mcp_id in mcp_ids:
            mcp = await self._mcp_repo.get_by_id(mcp_id)
            if not mcp:
                continue
            entry: Dict[str, Any] = {}
            if mcp.output_schema:
                try:
                    entry["output_schema"] = json.loads(mcp.output_schema)
                except Exception:
                    pass
            if mcp.sample_output:
                try:
                    entry["sample_output"] = json.loads(mcp.sample_output)
                except Exception:
                    pass
            if entry:
                schemas[f"mcp_{mcp_id}_{mcp.name}"] = entry
        return schemas

    async def try_diagnosis(
        self,
        diagnostic_prompt: str,
        mcp_sample_outputs: Dict[str, Any],
    ) -> SkillTryDiagnosisResponse:
        """Simulate Skill diagnosis: send MCP sample_outputs + prompt to LLM."""
        if not self._llm:
            return SkillTryDiagnosisResponse(
                success=False, error="LLM service not configured"
            )

        # Load system prompt from DB if available
        system_prompt = None
        if self._sp_repo:
            system_prompt = await self._sp_repo.get_value("PROMPT_SKILL_DIAGNOSIS")

        try:
            result = await self._llm.try_diagnosis(
                diagnostic_prompt=diagnostic_prompt,
                mcp_outputs=mcp_sample_outputs,
                system_prompt=system_prompt,
            )
        except Exception as exc:
            return SkillTryDiagnosisResponse(success=False, error=f"LLM 推論失敗：{exc}")

        return SkillTryDiagnosisResponse(
            success=True,
            status=result.get("status", "NORMAL"),
            conclusion=result.get("conclusion", ""),
            evidence=result.get("evidence", []),
            summary=result.get("summary", ""),
        )

    async def check_diagnosis_intent(
        self,
        diagnostic_prompt: str,
        mcp_output_sample: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Check if the diagnostic prompt is clear enough for LLM diagnosis."""
        if not self._llm:
            return {"is_clear": True, "questions": [], "suggested_prompt": ""}
        return await self._llm.check_diagnosis_intent(
            diagnostic_prompt=diagnostic_prompt,
            mcp_output_sample=mcp_output_sample,
        )

    async def check_code_diagnosis_intent(
        self,
        diagnostic_prompt: str,
        problem_subject: Optional[str],
        mcp_output_sample: Dict[str, Any],
        event_attributes: List[Dict[str, Any]],
    ) -> SkillCheckCodeDiagnosisIntentResponse:
        """Check clarity of diagnostic_prompt + problem_subject for code generation."""
        if not self._llm:
            return SkillCheckCodeDiagnosisIntentResponse(
                is_clear=True,
                suggested_prompt=diagnostic_prompt,
                suggested_problem_subject=problem_subject or "",
            )
        data = await self._llm.check_code_diagnosis_intent(
            diagnostic_prompt=diagnostic_prompt,
            problem_subject=problem_subject,
            mcp_output_sample=mcp_output_sample,
            event_attributes=event_attributes,
        )
        return SkillCheckCodeDiagnosisIntentResponse(**data)

    async def generate_code_diagnosis(
        self,
        diagnostic_prompt: str,
        problem_subject: Optional[str],
        mcp_sample_outputs: Dict[str, Any],
        event_attributes: Optional[List[Dict[str, Any]]] = None,
    ) -> SkillGenerateCodeDiagnosisResponse:
        """Generate Python diagnostic code that returns diagnosis_message + problem_object."""
        if not self._llm:
            return SkillGenerateCodeDiagnosisResponse(
                success=False, error="LLM service not configured"
            )
        try:
            result = await self._llm.generate_code_diagnosis(
                diagnostic_prompt=diagnostic_prompt,
                problem_subject=problem_subject,
                mcp_sample_outputs=mcp_sample_outputs,
                event_attributes=event_attributes or [],
            )
        except Exception as exc:
            return SkillGenerateCodeDiagnosisResponse(success=False, error=str(exc))
        return SkillGenerateCodeDiagnosisResponse(**result)

    async def auto_map(self, mcp_id: int, event_type_id: int) -> Dict[str, Any]:
        """LLM semantic mapping: match DataSubject input fields → Event attributes.

        Looks up the MCP's DataSubject to get input_schema.fields, then calls
        MCPBuilderService.auto_map() to perform semantic matching via LLM.
        """
        if not self._llm:
            return {"mapping": []}
        mcp = await self._mcp_repo.get_by_id(mcp_id)
        if not mcp:
            raise AppException(status_code=404, error_code="NOT_FOUND", detail="MCP 不存在")
        et = await self._et_repo.get_by_id(event_type_id)
        if not et:
            raise AppException(status_code=404, error_code="NOT_FOUND", detail="EventType 不存在")
        if not self._ds_repo:
            return {"mapping": []}
        ds = await self._ds_repo.get_by_id(mcp.data_subject_id)
        if not ds:
            raise AppException(status_code=404, error_code="NOT_FOUND", detail="DataSubject 不存在")

        ds_input_schema = _j(ds.input_schema) if isinstance(ds.input_schema, str) else (ds.input_schema or {})
        ds_inputs = ds_input_schema.get("fields", [])
        event_attrs = et.attributes if isinstance(et.attributes, list) else (_j(et.attributes) or [])

        return await self._llm.auto_map(
            data_subject_inputs=ds_inputs,
            event_attributes=event_attrs,
        )

    async def diagnose_with_feedback(
        self,
        skill_id: int,
        mcp_sample_outputs: Dict[str, Any],
        user_feedback: str,
        previous_result_summary: Optional[str] = None,
    ) -> SkillDiagnoseWithFeedbackResponse:
        """User feedback → LLM reflects on diagnostic_prompt → revised prompt → re-run diagnosis → persist log."""
        import logging
        from app.ontology.models.feedback_log import FeedbackLogModel
        from app.services.sandbox_service import execute_script

        logger = logging.getLogger(__name__)

        skill = await self._repo.get_by_id(skill_id)
        if not skill:
            raise AppException(status_code=404, error_code="NOT_FOUND", detail="Skill 不存在")

        original_prompt = skill.diagnostic_prompt or ""

        # Step 1: LLM reflection on diagnostic prompt
        if not self._llm:
            return SkillDiagnoseWithFeedbackResponse(
                reflection="LLM service not configured",
                error="LLM service not configured",
            )

        reflect_prompt = f"""\
你是一位半導體製程智能診斷 AI。使用者對你之前的診斷結果提出了問題，請你反思並改善診斷提示詞。

【原始診斷提示詞（diagnostic_prompt）】
{original_prompt}

【上次診斷結果摘要】
{previous_result_summary or "(未提供)"}

【使用者回饋】
{user_feedback}

【MCP 輸出資料樣本】
{json.dumps(mcp_sample_outputs, ensure_ascii=False)[:2000]}

請完成以下兩項任務，以 JSON 格式回傳：

1. **reflection**（str）：分析上次診斷為何不準確（2~4 句）
2. **revised_prompt**（str）：修正後的診斷提示詞，使判斷更精確

只回傳 JSON：
{{"reflection": "...", "revised_prompt": "..."}}"""

        try:
            response = await self._llm._client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2048,
                messages=[{"role": "user", "content": reflect_prompt}],
            )
            from app.services.mcp_builder_service import _extract_json, _get_text
            result = _extract_json(_get_text(response.content))
            reflection = result.get("reflection", "")
            revised_prompt = result.get("revised_prompt", "") or original_prompt
        except Exception as exc:
            reflection = f"LLM 反思失敗：{exc}"
            revised_prompt = original_prompt

        # Step 2: re-run diagnosis with revised prompt
        rerun_success = False
        status = ""
        diagnosis_message = ""
        problem_object = None
        error: Optional[str] = None

        try:
            diag_result = await self._llm.try_diagnosis(
                diagnostic_prompt=revised_prompt,
                mcp_sample_outputs=mcp_sample_outputs,
            )
            status = diag_result.get("status", "")
            diagnosis_message = diag_result.get("summary", "") or diag_result.get("conclusion", "")
            problem_object = diag_result.get("problem_object")
            rerun_success = True
        except Exception as exc:
            error = f"重跑診斷失敗：{exc}"

        # Step 3: if revised prompt differs, persist it
        if revised_prompt != original_prompt and rerun_success:
            await self._repo.update(skill, diagnostic_prompt=revised_prompt)

        # Step 4: save feedback log
        log_id: Optional[int] = None
        try:
            log = FeedbackLogModel(
                target_type="skill",
                target_id=skill_id,
                user_feedback=user_feedback,
                previous_result_summary=previous_result_summary or "",
                llm_reflection=reflection,
                revised_script=revised_prompt,
                rerun_success=rerun_success,
            )
            self._repo._db.add(log)
            await self._repo._db.flush()
            log_id = log.id
        except Exception as exc:
            logger.warning("diagnose_with_feedback: failed to save log: %s", exc)

        return SkillDiagnoseWithFeedbackResponse(
            reflection=reflection,
            revised_prompt=revised_prompt,
            rerun_success=rerun_success,
            status=status,
            diagnosis_message=diagnosis_message,
            problem_object=problem_object,
            error=error,
            feedback_log_id=log_id,
        )
