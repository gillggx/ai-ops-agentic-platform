"""Analysis Router — execute ad-hoc analysis (one-time Skill) + promote to Diagnostic Rule.

POST /analysis/run      — execute Agent-generated python code in sandbox
POST /analysis/promote  — save successful analysis as a permanent Diagnostic Rule
"""

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.response import StandardResponse
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import UserModel
from app.repositories.skill_definition_repository import SkillDefinitionRepository
from app.services.skill_executor_service import SkillExecutorService, build_mcp_executor

router = APIRouter(prefix="/analysis", tags=["analysis"])


# ── Request / Response schemas ────────────────────────────────────────────────

class AnalysisStep(BaseModel):
    step_id: str
    nl_segment: str
    python_code: str


class RunAnalysisRequest(BaseModel):
    title: str = "Ad-hoc 分析"
    mode: str = Field(default="code", description="'code' = direct steps, 'auto' = generate from description")
    description: str = Field(default="", description="For mode=auto: natural language description")
    steps: List[AnalysisStep] = Field(default_factory=list)
    input_params: Dict[str, Any] = Field(default_factory=dict)


class PromoteRequest(BaseModel):
    name: str = Field(..., min_length=1)
    description: str = ""
    auto_check_description: str = ""
    steps_mapping: List[Dict[str, Any]] = Field(..., min_length=1)
    input_schema: List[Dict[str, Any]] = Field(default_factory=list)
    output_schema: List[Dict[str, Any]] = Field(default_factory=list)


# ── Run ad-hoc analysis ──────────────────────────────────────────────────────

@router.post("/run", response_model=StandardResponse)
async def run_analysis(
    body: RunAnalysisRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> StandardResponse:
    """Execute analysis — two modes:

    mode='code':  Agent provides steps directly (existing behavior)
    mode='auto':  Agent provides description, backend generates steps via
                  DiagnosticRuleService.generate_steps() (same pipeline as Skill gen)

    Returns findings + charts + steps_mapping (for promote to Skill).
    """
    settings = get_settings()
    svc = SkillExecutorService(
        skill_repo=SkillDefinitionRepository(db),
        mcp_executor=build_mcp_executor(db, sim_url=settings.ONTOLOGY_SIM_URL),
    )

    steps = []
    output_schema = []
    input_schema_inferred = []

    if body.mode == "auto" and body.description:
        # ── Auto mode: generate steps from description ─────────────────
        from app.services.diagnostic_rule_service import DiagnosticRuleService
        from app.schemas.diagnostic_rule import GenerateRuleStepsRequest, PatrolContext
        from app.utils.llm_client import get_llm_client

        gen_svc = DiagnosticRuleService(
            repo=SkillDefinitionRepository(db),
            db=db,
            llm=get_llm_client(),
        )

        # Build description that includes input_params info for parameterization
        enriched_desc = body.description
        if body.input_params:
            param_hint = ", ".join(f"{k}={v}" for k, v in body.input_params.items())
            enriched_desc += f"\n\n使用者提供的參數（必須設計為 input_schema，code 中用 _input.get() 讀取）：{param_hint}"

        gen_result = await gen_svc.generate_steps(
            GenerateRuleStepsRequest(auto_check_description=enriched_desc)
        )
        if not gen_result.success or not gen_result.steps_mapping:
            return StandardResponse.error(
                message=f"Auto 分析生成失敗：{gen_result.error or '未能生成步驟'}"
            )

        steps = gen_result.steps_mapping
        output_schema = gen_result.output_schema
        input_schema_inferred = gen_result.input_schema
    else:
        # ── Code mode: use provided steps ──────────────────────────────
        steps = [s.model_dump() for s in body.steps]
        input_schema_inferred = [
            {"key": k, "type": "string", "required": True, "description": ""}
            for k in body.input_params.keys()
        ]

    # Execute
    step_results, raw_findings, error, charts = await svc._run_script(
        steps=steps,
        event_payload=body.input_params,
    )

    if error:
        return StandardResponse.error(message=f"分析執行失敗：{error}")

    findings = {}
    if raw_findings and isinstance(raw_findings, dict):
        findings = raw_findings

    # ★ ChartMiddleware — auto-generate charts from output_schema types
    from app.services.chart_middleware import process as chart_process
    if output_schema and isinstance(findings.get("outputs"), dict):
        auto_charts = chart_process(findings["outputs"], output_schema)
        if auto_charts:
            charts = (charts or []) + auto_charts

    import logging as _logging
    _alog = _logging.getLogger(__name__)
    _alog.warning(
        "[analysis.run] returning charts=%d output_schema_types=%s findings_outputs_keys=%s",
        len(charts or []),
        [(s.get("key"), s.get("type")) for s in (output_schema or [])],
        list((findings.get("outputs") or {}).keys()) if isinstance(findings, dict) else None,
    )
    if charts:
        _first = charts[0]
        _data = _first.get("data") if isinstance(_first, dict) else None
        _alog.warning(
            "[analysis.run] first chart: title=%r data_rows=%s sample_row=%s",
            _first.get("title") if isinstance(_first, dict) else None,
            len(_data) if isinstance(_data, list) else "?",
            str(_data[0])[:200] if isinstance(_data, list) and _data else None,
        )

    return StandardResponse.success(
        data={
            "title": body.title,
            "findings": findings,
            "charts": charts or [],
            "step_results": [
                {
                    "step_id": sr.step_id,
                    "nl_segment": sr.nl_segment,
                    "status": sr.status,
                    "output": sr.output,
                    "error": sr.error,
                }
                for sr in step_results
            ],
            # Payload for promote
            "mode": body.mode,
            "steps_mapping": steps,
            "input_params": body.input_params,
            "input_schema": input_schema_inferred,
            "output_schema": output_schema,
        },
        message=body.title,
    )


# ── Promote to Diagnostic Rule ───────────────────────────────────────────────

@router.post("/promote", response_model=StandardResponse)
async def promote_to_rule(
    body: PromoteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> StandardResponse:
    """Save a successful ad-hoc analysis as a user Skill.

    The new Skill appears in skill_catalog (Agent's <skill_catalog>) and
    /admin/my-skills page. Agent will use execute_skill for it next time
    instead of regenerating code.
    """
    repo = SkillDefinitionRepository(db)
    obj = await repo.create({
        "name": body.name,
        "description": body.description,
        "auto_check_description": body.auto_check_description or body.description,
        "steps_mapping": body.steps_mapping,
        "input_schema": body.input_schema,
        "output_schema": body.output_schema,
        "source": "skill",
        "binding_type": "none",
        "trigger_mode": "manual",
        "visibility": "public",
        "created_by": current_user.id,
    })
    return StandardResponse.success(
        data={"id": obj.id, "name": obj.name},
        message=f"已儲存為 Skill: {body.name}",
    )
