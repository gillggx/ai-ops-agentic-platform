"""Event Type CRUD router."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import StandardResponse
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import UserModel
from app.repositories.event_type_repository import EventTypeRepository
from app.schemas.event_type import EventTypeCreate, EventTypeUpdate
from app.services.event_type_service import EventTypeService

router = APIRouter(prefix="/event-types", tags=["event-types"])


def _get_service(db: AsyncSession = Depends(get_db)) -> EventTypeService:
    return EventTypeService(EventTypeRepository(db))


@router.get("", response_model=StandardResponse)
async def list_event_types(
    svc: EventTypeService = Depends(_get_service),
    _: UserModel = Depends(get_current_user),
):
    items = await svc.list_all()
    return StandardResponse.success(data=[i.model_dump() for i in items])


@router.get("/{et_id}", response_model=StandardResponse)
async def get_event_type(
    et_id: int,
    svc: EventTypeService = Depends(_get_service),
    _: UserModel = Depends(get_current_user),
):
    item = await svc.get(et_id)
    return StandardResponse.success(data=item.model_dump())


@router.post("", response_model=StandardResponse, status_code=201)
async def create_event_type(
    body: EventTypeCreate,
    svc: EventTypeService = Depends(_get_service),
    _: UserModel = Depends(get_current_user),
):
    item = await svc.create(body)
    return StandardResponse.success(data=item.model_dump(), message="EventType 建立成功")


@router.patch("/{et_id}", response_model=StandardResponse)
async def update_event_type(
    et_id: int,
    body: EventTypeUpdate,
    svc: EventTypeService = Depends(_get_service),
    _: UserModel = Depends(get_current_user),
):
    item = await svc.update(et_id, body)
    return StandardResponse.success(data=item.model_dump(), message="EventType 更新成功")


@router.delete("/{et_id}", response_model=StandardResponse)
async def delete_event_type(
    et_id: int,
    svc: EventTypeService = Depends(_get_service),
    _: UserModel = Depends(get_current_user),
):
    await svc.delete(et_id)
    return StandardResponse.success(message="EventType 刪除成功")
