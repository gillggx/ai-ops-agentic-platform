"""Generated Events (auto-alarms) router (Phase 11)."""

import json

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.response import StandardResponse
from app.dependencies import get_current_user
from app.models.user import UserModel
from app.repositories.generated_event_repository import GeneratedEventRepository
from app.schemas.generated_event import GeneratedEventResponse, GeneratedEventStatusUpdate
from app.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/generated-events", tags=["generated-events"])


def _to_response(obj) -> GeneratedEventResponse:
    params = {}
    if obj.mapped_parameters:
        try:
            params = json.loads(obj.mapped_parameters)
        except Exception:
            params = {}
    return GeneratedEventResponse(
        id=obj.id,
        event_type_id=obj.event_type_id,
        source_skill_id=obj.source_skill_id,
        source_routine_check_id=obj.source_routine_check_id,
        mapped_parameters=params,
        skill_conclusion=obj.skill_conclusion,
        status=obj.status,
        created_at=obj.created_at,
        updated_at=obj.updated_at,
    )


@router.get("", summary="列出所有自動生成警報", response_model=StandardResponse)
async def list_generated_events(
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    repo = GeneratedEventRepository(db)
    items = await repo.get_all(limit=200)
    return StandardResponse.success(data=[_to_response(i).model_dump() for i in items])


@router.get("/{event_id}", summary="取得單一生成警報", response_model=StandardResponse)
async def get_generated_event(
    event_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    repo = GeneratedEventRepository(db)
    obj = await repo.get_by_id(event_id)
    if obj is None:
        raise HTTPException(status_code=404, detail=f"GeneratedEvent id={event_id} 不存在")
    return StandardResponse.success(data=_to_response(obj).model_dump())


@router.patch("/{event_id}/status", summary="更新警報狀態", response_model=StandardResponse)
async def update_event_status(
    event_id: int,
    body: GeneratedEventStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    repo = GeneratedEventRepository(db)
    obj = await repo.get_by_id(event_id)
    if obj is None:
        raise HTTPException(status_code=404, detail=f"GeneratedEvent id={event_id} 不存在")
    obj = await repo.update(obj, status=body.status)
    return StandardResponse.success(data=_to_response(obj).model_dump())


@router.delete("/{event_id}", summary="刪除生成警報", response_model=StandardResponse)
async def delete_generated_event(
    event_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    repo = GeneratedEventRepository(db)
    obj = await repo.get_by_id(event_id)
    if obj is None:
        raise HTTPException(status_code=404, detail=f"GeneratedEvent id={event_id} 不存在")
    await repo.delete(obj)
    return StandardResponse.success(data={"deleted_id": event_id})
