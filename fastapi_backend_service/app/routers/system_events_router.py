"""System Events router — v18 webhook ingest endpoint.

POST /api/v1/system-events/ingest
  Accepts an external event payload (same Standard Event Payload structure
  as the OntologySimulator), finds matching active Skills, executes them.

Auth: uses INTERNAL_API_TOKEN (static bearer) or a valid JWT.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import StandardResponse
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import UserModel
from app.repositories.alarm_repository import AlarmRepository
from app.repositories.event_type_repository import EventTypeRepository
from app.repositories.skill_definition_repository import SkillDefinitionRepository
from app.services.skill_executor_service import SkillExecutorService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/system-events", tags=["system-events"])


# ── Request / Response schemas ───────────────────────────────────────────────

class SystemEventIngestRequest(BaseModel):
    """Standard Event Payload — identical to OntologySimulator event structure."""
    event_type:   str = Field(..., description="e.g. 'SPC_OOC'")
    equipment_id: str = Field(..., description="e.g. 'EQP-01'")
    lot_id:       str = Field(..., description="e.g. 'LOT-0001'")
    step:         Optional[str] = Field(default=None, description="e.g. 'STEP_091'")
    event_time:   Optional[str] = Field(default=None, description="ISO8601 timestamp")
    extra:        Optional[Dict[str, Any]] = Field(default=None, description="Any additional fields (ignored by executor)")


class SystemEventIngestResponse(BaseModel):
    event_type:     str
    skills_matched: int = 0
    alarms_created: int = 0
    results:        List[Dict[str, Any]] = []


# ── Endpoint ─────────────────────────────────────────────────────────────────

@router.post("/ingest", response_model=StandardResponse, status_code=202)
async def ingest_system_event(
    body: SystemEventIngestRequest,
    db: AsyncSession = Depends(get_db),
    _: UserModel = Depends(get_current_user),
):
    """
    Webhook: receive an external system event, find matching Skills, execute.

    Returns HTTP 202 Accepted with a summary of skills triggered and alarms created.
    """
    # 1. Look up event_type by name
    et_repo = EventTypeRepository(db)
    event_type = await et_repo.get_by_name(body.event_type)
    if not event_type:
        return StandardResponse.success(
            data=SystemEventIngestResponse(
                event_type=body.event_type,
                skills_matched=0,
                alarms_created=0,
                results=[{"warning": f"Event type '{body.event_type}' 不在 Catalog 中，已忽略"}],
            ).model_dump(),
            message="Event type 未註冊",
        )

    if not getattr(event_type, "is_active", True):
        return StandardResponse.success(
            data=SystemEventIngestResponse(
                event_type=body.event_type,
                skills_matched=0,
                alarms_created=0,
                results=[{"warning": f"Event type '{body.event_type}' 已停用"}],
            ).model_dump(),
            message="Event type 已停用",
        )

    # 2. Find matching Skills
    skill_repo = SkillDefinitionRepository(db)
    skills = await skill_repo.list_by_trigger_event(event_type.id)

    if not skills:
        return StandardResponse.success(
            data=SystemEventIngestResponse(
                event_type=body.event_type,
                skills_matched=0,
                alarms_created=0,
            ).model_dump(),
            message="無 Skill 符合此 Event",
        )

    # 3. Build standard payload
    event_payload = {
        "event_type":   body.event_type,
        "equipment_id": body.equipment_id,
        "lot_id":       body.lot_id,
        "step":         body.step or "",
        "event_time":   body.event_time or "",
    }

    # 4. Execute each matching Skill
    alarm_repo = AlarmRepository(db)
    executor   = SkillExecutorService(
        skill_repo=skill_repo,
        alarm_repo=alarm_repo,
        mcp_executor=None,
    )

    results: List[Dict[str, Any]] = []
    total_alarms = 0

    for skill in skills:
        try:
            result = await executor.execute(
                skill_id=skill.id,
                event_payload=event_payload,
                triggered_by="webhook",
            )
            total_alarms += result.alarms_created
            results.append({
                "skill_id":      skill.id,
                "skill_name":    skill.name,
                "success":       result.success,
                "alarms_created": result.alarms_created,
                "alarm_ids":     result.alarm_ids,
                "error":         result.error,
            })
            logger.info(
                "Webhook ingest: skill=%d event=%s → %d alarms",
                skill.id, body.event_type, result.alarms_created,
            )
        except Exception as exc:
            logger.exception("Webhook: skill=%d error: %s", skill.id, exc)
            results.append({
                "skill_id":  skill.id,
                "skill_name": skill.name,
                "success":   False,
                "error":     str(exc),
            })

    response = SystemEventIngestResponse(
        event_type=body.event_type,
        skills_matched=len(skills),
        alarms_created=total_alarms,
        results=results,
    )
    return StandardResponse.success(
        data=response.model_dump(),
        message=f"Event 處理完成：{len(skills)} Skill 執行，{total_alarms} Alarm 建立",
    )
