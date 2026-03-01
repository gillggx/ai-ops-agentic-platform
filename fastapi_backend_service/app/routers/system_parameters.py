"""System Parameters router — IT Admin UI for managing LLM prompts."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.core.response import StandardResponse
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import UserModel
from app.repositories.system_parameter_repository import SystemParameterRepository
from app.schemas.system_parameter import SystemParameterUpdate

router = APIRouter(prefix="/system-parameters", tags=["system-parameters"])


@router.get("", response_model=StandardResponse)
async def list_system_parameters(
    db: AsyncSession = Depends(get_db),
    _: UserModel = Depends(get_current_user),
):
    repo = SystemParameterRepository(db)
    items = await repo.get_all()
    return StandardResponse.success(data=[
        {"key": i.key, "value": i.value, "description": i.description,
         "updated_at": i.updated_at.isoformat() if i.updated_at else None}
        for i in items
    ])


@router.patch("/{key}", response_model=StandardResponse)
async def update_system_parameter(
    key: str,
    body: SystemParameterUpdate,
    db: AsyncSession = Depends(get_db),
    _: UserModel = Depends(get_current_user),
):
    repo = SystemParameterRepository(db)
    obj = await repo.update_value(key, body.value)
    if obj is None:
        raise AppException(status_code=404, error_code="NOT_FOUND", detail=f"參數 {key!r} 不存在")
    return StandardResponse.success(
        data={"key": obj.key, "value": obj.value, "description": obj.description},
        message="系統參數更新成功",
    )
