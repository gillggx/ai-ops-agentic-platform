"""Cron Jobs router — schedule / manage cron-triggered Skill executions."""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import StandardResponse
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import UserModel
from app.repositories.cron_job_repository import CronJobRepository
from app.repositories.execution_log_repository import ExecutionLogRepository
from app.repositories.script_version_repository import ScriptVersionRepository
from app.repositories.skill_definition_repository import SkillDefinitionRepository
from app.schemas.automation import CronJobCreate, CronJobUpdate
from app.services.cron_scheduler_service import CronSchedulerService

router = APIRouter(prefix="/cron-jobs", tags=["cron-jobs"])


def _get_svc(db: AsyncSession = Depends(get_db)) -> CronSchedulerService:
    return CronSchedulerService(
        db=db,
        cron_repo=CronJobRepository(db),
        script_repo=ScriptVersionRepository(db),
        skill_repo=SkillDefinitionRepository(db),
        log_repo=ExecutionLogRepository(db),
    )


@router.get("", response_model=StandardResponse)
async def list_jobs(
    skill_id: Optional[int] = Query(default=None, description="Filter by skill_id"),
    svc: CronSchedulerService = Depends(_get_svc),
    _: UserModel = Depends(get_current_user),
):
    items = await svc.list_jobs(skill_id=skill_id)
    return StandardResponse.success(data=[i.model_dump() for i in items])


@router.get("/{job_id}", response_model=StandardResponse)
async def get_job(
    job_id: int,
    svc: CronSchedulerService = Depends(_get_svc),
    _: UserModel = Depends(get_current_user),
):
    item = await svc.get_job(job_id)
    return StandardResponse.success(data=item.model_dump())


@router.post("", response_model=StandardResponse, status_code=201)
async def create_job(
    body: CronJobCreate,
    svc: CronSchedulerService = Depends(_get_svc),
    current_user: UserModel = Depends(get_current_user),
):
    item = await svc.create_job(body, created_by=current_user.username)
    return StandardResponse.success(data=item.model_dump())


@router.patch("/{job_id}", response_model=StandardResponse)
async def update_job(
    job_id: int,
    body: CronJobUpdate,
    svc: CronSchedulerService = Depends(_get_svc),
    _: UserModel = Depends(get_current_user),
):
    item = await svc.update_job(job_id, body)
    return StandardResponse.success(data=item.model_dump())


@router.delete("/{job_id}", response_model=StandardResponse)
async def delete_job(
    job_id: int,
    svc: CronSchedulerService = Depends(_get_svc),
    _: UserModel = Depends(get_current_user),
):
    await svc.delete_job(job_id)
    return StandardResponse.success(data={"deleted": True, "job_id": job_id})
