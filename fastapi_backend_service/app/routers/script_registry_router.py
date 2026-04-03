"""Script Registry router — versioned diagnose() lifecycle management."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import StandardResponse
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import UserModel
from app.repositories.script_version_repository import ScriptVersionRepository
from app.repositories.skill_definition_repository import SkillDefinitionRepository
from app.schemas.automation import ScriptTestRunRequest, ScriptVersionCreate
from app.services.script_registry_service import ScriptRegistryService

router = APIRouter(prefix="/script-registry", tags=["script-registry"])


def _get_svc(db: AsyncSession = Depends(get_db)) -> ScriptRegistryService:
    return ScriptRegistryService(
        script_repo=ScriptVersionRepository(db),
        skill_repo=SkillDefinitionRepository(db),
    )


# ── Pending approval list (cross-skill) ─────────────────────────────────────

@router.get("/pending", response_model=StandardResponse)
async def list_pending_scripts(
    svc: ScriptRegistryService = Depends(_get_svc),
    _: UserModel = Depends(get_current_user),
):
    """All draft scripts waiting for human review."""
    items = await svc.list_pending()
    return StandardResponse.success(data=[i.model_dump() for i in items])


# ── Per-skill version management ─────────────────────────────────────────────

@router.get("/skills/{skill_id}/versions", response_model=StandardResponse)
async def list_versions(
    skill_id: int,
    svc: ScriptRegistryService = Depends(_get_svc),
    _: UserModel = Depends(get_current_user),
):
    items = await svc.list_versions(skill_id)
    return StandardResponse.success(data=[i.model_dump() for i in items])


@router.post("/skills/{skill_id}/versions", response_model=StandardResponse, status_code=201)
async def register_version(
    skill_id: int,
    body: ScriptVersionCreate,
    svc: ScriptRegistryService = Depends(_get_svc),
    _: UserModel = Depends(get_current_user),
):
    """Register a new draft script version (typically called by Agent or Skill Builder)."""
    item = await svc.register(skill_id, body)
    return StandardResponse.success(data=item.model_dump())


@router.post("/skills/{skill_id}/test-run", response_model=StandardResponse)
async def test_run(
    skill_id: int,
    body: ScriptTestRunRequest,
    svc: ScriptRegistryService = Depends(_get_svc),
    _: UserModel = Depends(get_current_user),
):
    """Sandbox-execute a script version with a test EventContext (no side-effects)."""
    result = await svc.test_run(skill_id, body)
    return StandardResponse.success(data=result.model_dump())


@router.post("/skills/{skill_id}/rollback", response_model=StandardResponse)
async def rollback(
    skill_id: int,
    version: int = Query(..., description="Target version number to restore"),
    svc: ScriptRegistryService = Depends(_get_svc),
    _: UserModel = Depends(get_current_user),
):
    item = await svc.rollback(skill_id, version)
    return StandardResponse.success(data=item.model_dump())


# ── Version-level actions ────────────────────────────────────────────────────

@router.get("/versions/{version_id}", response_model=StandardResponse)
async def get_version(
    version_id: int,
    svc: ScriptRegistryService = Depends(_get_svc),
    _: UserModel = Depends(get_current_user),
):
    item = await svc.get_version(version_id)
    return StandardResponse.success(data=item.model_dump())


@router.post("/versions/{version_id}/approve", response_model=StandardResponse)
async def approve_version(
    version_id: int,
    current_user: UserModel = Depends(get_current_user),
    svc: ScriptRegistryService = Depends(_get_svc),
):
    """Human approves a draft → promotes to active. Requires authenticated user."""
    item = await svc.approve(version_id, reviewed_by=current_user.username)
    return StandardResponse.success(data=item.model_dump())
