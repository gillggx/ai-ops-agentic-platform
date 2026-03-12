"""MCP Definition CRUD + LLM generation router."""

import asyncio
import json
import time
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import StandardResponse
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import UserModel
from app.repositories.data_subject_repository import DataSubjectRepository
from app.repositories.mcp_definition_repository import MCPDefinitionRepository
from app.repositories.system_parameter_repository import SystemParameterRepository
from app.schemas.mcp_definition import (
    MCPCheckIntentRequest,
    MCPDefinitionCreate,
    MCPDefinitionUpdate,
    MCPGenerateRequest,
    MCPRunWithDataRequest,
    MCPRunWithFeedbackRequest,
    MCPTryRunRequest,
)
from app.services.mcp_builder_service import MCPBuilderService
from app.services.mcp_definition_service import MCPDefinitionService

router = APIRouter(prefix="/mcp-definitions", tags=["mcp-definitions"])


def _get_service(db: AsyncSession = Depends(get_db)) -> MCPDefinitionService:
    return MCPDefinitionService(
        repo=MCPDefinitionRepository(db),
        ds_repo=DataSubjectRepository(db),
        llm=MCPBuilderService(),
        sp_repo=SystemParameterRepository(db),
    )


@router.get("", response_model=StandardResponse)
async def list_mcp_definitions(
    type: Optional[str] = Query(default=None, description="Filter by mcp_type: 'system' or 'custom'"),
    svc: MCPDefinitionService = Depends(_get_service),
    _: UserModel = Depends(get_current_user),
):
    items = await svc.list_all(mcp_type=type)
    return StandardResponse.success(data=[i.model_dump() for i in items])


@router.get("/{mcp_id}", response_model=StandardResponse)
async def get_mcp_definition(
    mcp_id: int,
    svc: MCPDefinitionService = Depends(_get_service),
    _: UserModel = Depends(get_current_user),
):
    item = await svc.get(mcp_id)
    return StandardResponse.success(data=item.model_dump())


@router.post("", response_model=StandardResponse, status_code=201)
async def create_mcp_definition(
    body: MCPDefinitionCreate,
    svc: MCPDefinitionService = Depends(_get_service),
    _: UserModel = Depends(get_current_user),
):
    item = await svc.create(body)
    return StandardResponse.success(data=item.model_dump(), message="MCP 建立成功")


@router.patch("/{mcp_id}", response_model=StandardResponse)
async def update_mcp_definition(
    mcp_id: int,
    body: MCPDefinitionUpdate,
    svc: MCPDefinitionService = Depends(_get_service),
    _: UserModel = Depends(get_current_user),
):
    item = await svc.update(mcp_id, body)
    return StandardResponse.success(data=item.model_dump(), message="MCP 更新成功")


@router.delete("/{mcp_id}", response_model=StandardResponse)
async def delete_mcp_definition(
    mcp_id: int,
    svc: MCPDefinitionService = Depends(_get_service),
    _: UserModel = Depends(get_current_user),
):
    await svc.delete(mcp_id)
    return StandardResponse.success(message="MCP 刪除成功")


@router.post("/{mcp_id}/generate", response_model=StandardResponse)
async def generate_mcp_artefacts(
    mcp_id: int,
    svc: MCPDefinitionService = Depends(_get_service),
    _: UserModel = Depends(get_current_user),
):
    """LLM background task: generate script, output schema, UI config, and input params."""
    result = await svc.generate(mcp_id)
    return StandardResponse.success(data=result.model_dump(), message="LLM 生成完成")


@router.post("/check-intent", response_model=StandardResponse)
async def check_intent_clarity(
    body: MCPCheckIntentRequest,
    svc: MCPDefinitionService = Depends(_get_service),
    _: UserModel = Depends(get_current_user),
):
    """Ask LLM to verify the processing intent is clear and unambiguous before generation."""
    result = await svc.check_intent(
        processing_intent=body.processing_intent,
        system_mcp_id=body.system_mcp_id,
        data_subject_id=body.data_subject_id,
    )
    return StandardResponse.success(data=result.model_dump())


@router.post("/try-run", response_model=StandardResponse)
async def try_run_mcp(
    body: MCPTryRunRequest,
    svc: MCPDefinitionService = Depends(_get_service),
    _: UserModel = Depends(get_current_user),
):
    """Generate a script from intent (with safety guardrails) and execute it in sandbox."""
    result = await svc.try_run(
        processing_intent=body.processing_intent,
        system_mcp_id=body.system_mcp_id,
        data_subject_id=body.data_subject_id,
        sample_data=body.sample_data,
    )
    return StandardResponse.success(data=result.model_dump())


@router.post("/try-run-stream")
async def try_run_mcp_stream(
    body: MCPTryRunRequest,
    svc: MCPDefinitionService = Depends(_get_service),
    _: UserModel = Depends(get_current_user),
) -> StreamingResponse:
    """SSE variant of try-run: streams progress pings to prevent proxy 504 timeout.

    Events:
      data: {"type": "progress", "step": "codegen|sandbox|retry", "message": "...", "elapsed_s": N}
      data: {"type": "done",     "result": {...}}
      data: {"type": "error",    "message": "..."}
    """
    # Step messages keyed by minimum elapsed seconds (heuristic)
    _STEPS = [
        (0,  "codegen", "🧠 LLM 生成腳本中"),
        (50, "sandbox", "⚙ 沙盒執行中"),
        (90, "retry",   "🔄 AI 自癒：偵測錯誤，重新生成腳本"),
    ]

    async def _stream():
        t0 = time.time()
        task = asyncio.create_task(svc.try_run(
            processing_intent=body.processing_intent,
            system_mcp_id=body.system_mcp_id,
            data_subject_id=body.data_subject_id,
            sample_data=body.sample_data,
        ))

        # Send keep-alive progress pings every 2 s until task completes
        while not task.done():
            elapsed = int(time.time() - t0)
            step, msg = "codegen", "🧠 LLM 生成腳本中"
            for threshold, s, m in sorted(_STEPS, reverse=True):
                if elapsed >= threshold:
                    step, msg = s, m
                    break
            yield f"data: {json.dumps({'type': 'progress', 'step': step, 'message': f'{msg}...', 'elapsed_s': elapsed}, ensure_ascii=False)}\n\n"
            await asyncio.sleep(2)

        try:
            result = task.result()
            yield f"data: {json.dumps({'type': 'done', 'result': result.model_dump()}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{mcp_id}/run-with-data", response_model=StandardResponse)
async def run_mcp_with_data(
    mcp_id: int,
    body: MCPRunWithDataRequest,
    svc: MCPDefinitionService = Depends(_get_service),
    _: UserModel = Depends(get_current_user),
):
    """Execute stored processing_script with provided raw_data (no LLM generation).

    Used by Skill Builder '▶️ 執行載入 MCP 數據' to run the existing script against
    freshly fetched DataSubject data so the expert can see real output before writing
    the diagnostic prompt.
    """
    result = await svc.run_with_data(mcp_id, body.raw_data)
    return StandardResponse.success(data=result.model_dump())


@router.post("/{mcp_id}/run-with-feedback", response_model=StandardResponse)
async def run_mcp_with_feedback(
    mcp_id: int,
    body: MCPRunWithFeedbackRequest,
    svc: MCPDefinitionService = Depends(_get_service),
    _: UserModel = Depends(get_current_user),
):
    """User feedback → LLM reflection → revised script → sandbox re-run.

    Returns reflection text, revised_script, and re-run output_data.
    If re-run succeeds, the revised script is persisted to the MCP.
    """
    result = await svc.run_with_feedback(
        mcp_id=mcp_id,
        input_params=body.input_params,
        user_feedback=body.user_feedback,
        previous_result_summary=body.previous_result_summary,
        force_regen=body.force_regen,
    )
    return StandardResponse.success(data=result.model_dump())
