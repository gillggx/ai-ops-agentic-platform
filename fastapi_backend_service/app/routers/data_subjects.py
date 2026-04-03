"""Data Subject CRUD router."""

from typing import List

from fastapi import APIRouter, Depends

from app.core.response import StandardResponse
from app.dependencies import get_current_user
from app.models.user import UserModel
from app.repositories.data_subject_repository import DataSubjectRepository
from app.database import get_db
from app.schemas.data_subject import DataSubjectCreate, DataSubjectResponse, DataSubjectUpdate
from app.services.data_subject_service import DataSubjectService
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/data-subjects", tags=["data-subjects"])


def _get_service(db: AsyncSession = Depends(get_db)) -> DataSubjectService:
    return DataSubjectService(DataSubjectRepository(db))


@router.get("", response_model=StandardResponse)
async def list_data_subjects(
    svc: DataSubjectService = Depends(_get_service),
    _: UserModel = Depends(get_current_user),
):
    items = await svc.list_all()
    return StandardResponse.success(data=[i.model_dump() for i in items])


@router.get("/{ds_id}", response_model=StandardResponse)
async def get_data_subject(
    ds_id: int,
    svc: DataSubjectService = Depends(_get_service),
    _: UserModel = Depends(get_current_user),
):
    item = await svc.get(ds_id)
    return StandardResponse.success(data=item.model_dump())


@router.post("", response_model=StandardResponse, status_code=201)
async def create_data_subject(
    body: DataSubjectCreate,
    svc: DataSubjectService = Depends(_get_service),
    _: UserModel = Depends(get_current_user),
):
    item = await svc.create(body)
    return StandardResponse.success(data=item.model_dump(), message="DataSubject 建立成功")


@router.patch("/{ds_id}", response_model=StandardResponse)
async def update_data_subject(
    ds_id: int,
    body: DataSubjectUpdate,
    svc: DataSubjectService = Depends(_get_service),
    _: UserModel = Depends(get_current_user),
):
    item = await svc.update(ds_id, body)
    return StandardResponse.success(data=item.model_dump(), message="DataSubject 更新成功")


@router.delete("/{ds_id}", response_model=StandardResponse)
async def delete_data_subject(
    ds_id: int,
    svc: DataSubjectService = Depends(_get_service),
    _: UserModel = Depends(get_current_user),
):
    await svc.delete(ds_id)
    return StandardResponse.success(message="DataSubject 刪除成功")
