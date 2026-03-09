"""Agent Draft Router — staging area for agent-proposed configurations.

Agent Draft lifecycle:
  1. Agent calls POST /agent/draft/{type} → creates a pending draft
  2. Backend returns draft_id + deep_link_data
  3. Agent shows user a link: "點擊開啟建構器" → UI opens Skill/MCP editor with pre-filled data
  4. User reviews → clicks "正式發佈" → POST /agent/draft/{id}/publish writes to real registry

This ensures agents can NEVER directly modify production data.
"""

import json
import uuid
from typing import Any, Dict

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.database import get_db
from app.dependencies import get_current_user
from app.models.agent_draft import AgentDraftModel
from app.models.user import UserModel
from app.repositories.mcp_definition_repository import MCPDefinitionRepository
from app.repositories.skill_definition_repository import SkillDefinitionRepository

router = APIRouter(prefix="/agent/draft", tags=["agent-draft"])


def _j(s: Any) -> Any:
    if not s:
        return None
    if isinstance(s, (dict, list)):
        return s
    try:
        return json.loads(s)
    except Exception:
        return None


_VIEW_MAP = {
    "mcp": "mcp-builder",
    "skill": "skill-builder",
    "routine_check": "nested-builder",
    "event_skill_link": "event-link-builder",
}


def _draft_response(draft: AgentDraftModel, auto_fill: Dict) -> Dict[str, Any]:
    view = _VIEW_MAP.get(draft.draft_type, "nested-builder")
    return {
        "draft_id": draft.id,
        "draft_type": draft.draft_type,
        "status": draft.status,
        "deep_link_data": {
            "view": view,
            "draft_id": draft.id,
            "auto_fill": auto_fill,
        },
    }


async def _create_draft(
    db: AsyncSession,
    draft_type: str,
    payload: Dict,
    user_id: int,
) -> AgentDraftModel:
    draft = AgentDraftModel(
        id=str(uuid.uuid4()),
        draft_type=draft_type,
        payload=json.dumps(payload, ensure_ascii=False),
        user_id=user_id,
        status="pending",
    )
    db.add(draft)
    await db.commit()
    await db.refresh(draft)
    return draft


# ── Create MCP Draft ────────────────────────────────────────────────────────

@router.post("/mcp", summary="建立 MCP 草稿 (Agent 呼叫)", response_model=Dict[str, Any])
async def create_mcp_draft(
    body: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> Dict[str, Any]:
    """Agent calls this to propose an MCP node. Human must publish to make it real.

    Body fields: name, data_subject (name or id), python_script, description, processing_intent
    """
    # Accept both system_mcp_id (new) and data_subject (legacy)
    system_mcp_id = body.get("system_mcp_id")
    data_subject = body.get("data_subject", "") or (system_mcp_id if system_mcp_id else "")
    payload = {
        "name": body.get("name", ""),
        "description": body.get("description", ""),
        "data_subject": data_subject,
        "system_mcp_id": system_mcp_id,
        "processing_intent": body.get("processing_intent", body.get("python_script", "")),
    }
    draft = await _create_draft(db, "mcp", payload, current_user.id)
    return _draft_response(draft, payload)


# ── Create Skill Draft ──────────────────────────────────────────────────────

@router.post("/skill", summary="建立 Skill 草稿 (Agent 呼叫)", response_model=Dict[str, Any])
async def create_skill_draft(
    body: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> Dict[str, Any]:
    """Agent calls this to propose a Skill. Human must publish to make it real.

    Body fields: name, description, mcp_id, diagnostic_prompt, problematic_target, expert_action
    """
    # Accept both mcp_id (singular) and mcp_ids (array from tool schema)
    mcp_id = body.get("mcp_id") or (body.get("mcp_ids") or [None])[0]
    mcp_ids = body.get("mcp_ids") or ([mcp_id] if mcp_id else [])
    payload = {
        "name": body.get("name", ""),
        "description": body.get("description", ""),
        "mcp_id": mcp_id,
        "mcp_ids": mcp_ids,
        "diagnostic_prompt": body.get("diagnostic_prompt", ""),
        "problematic_target": body.get("problematic_target", body.get("problem_subject", "")),
        "expert_action": body.get("expert_action", body.get("human_recommendation", "")),
    }
    # Capture MCP input params used by the agent so the draft card can display them
    mcp_input_params = body.get("mcp_input_params") or body.get("input_params")
    if mcp_input_params:
        payload["mcp_input_params"] = mcp_input_params
    draft = await _create_draft(db, "skill", payload, current_user.id)
    return _draft_response(draft, payload)


# ── Create Schedule Draft ───────────────────────────────────────────────────

@router.post("/schedule", summary="建立排程草稿 (Agent 呼叫)", response_model=Dict[str, Any])
async def create_schedule_draft(
    body: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> Dict[str, Any]:
    """Agent calls this to propose a scheduled check.

    Body fields: skill_id, cron_expression, name
    """
    payload = {
        "name": body.get("name", ""),
        "skill_id": body.get("skill_id"),
        "cron_expression": body.get("cron_expression", ""),
    }
    draft = await _create_draft(db, "schedule", payload, current_user.id)
    return _draft_response(draft, payload)


# ── Create Event Trigger Draft ──────────────────────────────────────────────

@router.post("/event", summary="建立事件觸發草稿 (Agent 呼叫)", response_model=Dict[str, Any])
async def create_event_draft(
    body: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> Dict[str, Any]:
    """Agent calls this to propose an event-triggered skill.

    Body fields: skill_id, event_topic, name
    """
    payload = {
        "name": body.get("name", ""),
        "skill_id": body.get("skill_id"),
        "event_topic": body.get("event_topic", ""),
    }
    draft = await _create_draft(db, "event", payload, current_user.id)
    return _draft_response(draft, payload)


# ── Get Draft ───────────────────────────────────────────────────────────────

@router.get("/{draft_id}", summary="取得草稿內容", response_model=Dict[str, Any])
async def get_draft(
    draft_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> Dict[str, Any]:
    from sqlalchemy import select
    result = await db.execute(select(AgentDraftModel).where(AgentDraftModel.id == draft_id))
    draft = result.scalar_one_or_none()
    if not draft:
        raise AppException(status_code=404, error_code="NOT_FOUND", detail="草稿不存在")
    if draft.user_id != current_user.id and not current_user.is_superuser:
        raise AppException(status_code=403, error_code="FORBIDDEN", detail="無權存取此草稿")
    payload = _j(draft.payload) or {}
    return {
        "draft_id": draft.id,
        "draft_type": draft.draft_type,
        "status": draft.status,
        "payload": payload,
        "created_at": draft.created_at.isoformat() if draft.created_at else None,
    }


# ── Publish Draft ────────────────────────────────────────────────────────────

@router.post("/{draft_id}/publish", summary="發佈草稿至正式 Registry", response_model=Dict[str, Any])
async def publish_draft(
    draft_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> Dict[str, Any]:
    """Write draft payload to the real registry table.

    - mcp draft   → creates MCPDefinitionModel entry
    - skill draft → creates SkillDefinitionModel entry
    - schedule draft → creates RoutineCheckModel entry
    - event draft → creates EventTypeModel entry (trigger binding)
    """
    from sqlalchemy import select
    result = await db.execute(select(AgentDraftModel).where(AgentDraftModel.id == draft_id))
    draft = result.scalar_one_or_none()
    if not draft:
        raise AppException(status_code=404, error_code="NOT_FOUND", detail="草稿不存在")
    if draft.user_id != current_user.id and not current_user.is_superuser:
        raise AppException(status_code=403, error_code="FORBIDDEN", detail="無權發佈此草稿")
    if draft.status == "published":
        raise AppException(status_code=409, error_code="ALREADY_PUBLISHED", detail="草稿已發佈")

    payload = _j(draft.payload) or {}
    published_id: Any = None

    if draft.draft_type == "mcp":
        published_id = await _publish_mcp(db, payload)
    elif draft.draft_type == "skill":
        published_id = await _publish_skill(db, payload)
    elif draft.draft_type == "schedule":
        published_id = await _publish_schedule(db, payload)
    elif draft.draft_type == "event":
        published_id = await _publish_event(db, payload)
    elif draft.draft_type == "routine_check":
        published_id = await _publish_routine_check(db, payload)
    elif draft.draft_type == "event_skill_link":
        published_id = await _publish_event_skill_link(db, payload)
    else:
        raise AppException(status_code=422, error_code="UNKNOWN_DRAFT_TYPE", detail=f"未知的草稿類型: {draft.draft_type}")

    # Mark as published
    draft.status = "published"
    await db.commit()

    return {
        "draft_id": draft_id,
        "draft_type": draft.draft_type,
        "status": "published",
        "published_id": published_id,
        "message": "草稿已成功發佈至正式 Registry",
    }


async def _publish_mcp(db: AsyncSession, payload: Dict) -> int:
    """Create a new MCPDefinition from draft payload."""
    from app.models.mcp_definition import MCPDefinitionModel
    from app.models.data_subject import DataSubjectModel
    from sqlalchemy import select

    # Resolve system MCP or legacy DataSubject by name/id
    ds_ref = payload.get("data_subject", "")
    system_mcp_id: Any = None
    ds_id: Any = None

    if isinstance(ds_ref, int):
        result = await db.execute(
            select(MCPDefinitionModel).where(
                MCPDefinitionModel.id == ds_ref,
                MCPDefinitionModel.mcp_type == 'system',
            )
        )
        sys_mcp = result.scalar_one_or_none()
        if sys_mcp:
            system_mcp_id = sys_mcp.id
        else:
            ds_id = ds_ref
    elif isinstance(ds_ref, str) and ds_ref:
        result = await db.execute(
            select(MCPDefinitionModel).where(
                MCPDefinitionModel.name == ds_ref,
                MCPDefinitionModel.mcp_type == 'system',
            )
        )
        sys_mcp = result.scalar_one_or_none()
        if sys_mcp:
            system_mcp_id = sys_mcp.id
        else:
            result = await db.execute(select(DataSubjectModel).where(DataSubjectModel.name == ds_ref))
            ds = result.scalar_one_or_none()
            if ds:
                ds_id = ds.id

    if not system_mcp_id and not ds_id:
        raise AppException(status_code=422, error_code="DS_NOT_FOUND", detail=f"找不到 System MCP / DataSubject: {ds_ref}")

    obj = MCPDefinitionModel(
        name=payload.get("name") or f"Draft MCP {uuid.uuid4().hex[:6]}",
        description=payload.get("description", ""),
        mcp_type="custom",
        system_mcp_id=system_mcp_id,
        data_subject_id=ds_id,
        processing_intent=payload.get("processing_intent", ""),
        visibility="private",
    )
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj.id


async def _publish_skill(db: AsyncSession, payload: Dict) -> int:
    """Create a new SkillDefinition from draft payload."""
    from app.models.skill_definition import SkillDefinitionModel

    mcp_ids = payload.get("mcp_ids") or []
    mcp_id = payload.get("mcp_id")
    if not mcp_ids and mcp_id:
        mcp_ids = [mcp_id]
    mcp_ids_json = json.dumps(mcp_ids)

    obj = SkillDefinitionModel(
        name=payload.get("name") or f"Draft Skill {uuid.uuid4().hex[:6]}",
        description=payload.get("description", ""),
        mcp_ids=mcp_ids_json,
        diagnostic_prompt=payload.get("diagnostic_prompt", ""),
        problem_subject=payload.get("problematic_target", ""),
        human_recommendation=payload.get("expert_action", ""),
        visibility="private",
    )
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj.id


async def _publish_schedule(db: AsyncSession, payload: Dict) -> int:
    """Create a new RoutineCheck from draft payload."""
    from app.models.routine_check import RoutineCheckModel

    skill_id = payload.get("skill_id")
    if not skill_id:
        raise AppException(status_code=422, error_code="MISSING_SKILL", detail="排程草稿缺少 skill_id")

    # Convert cron_expression to schedule_interval minutes (best-effort)
    cron = payload.get("cron_expression", "")
    interval = _cron_to_minutes(cron)

    obj = RoutineCheckModel(
        name=payload.get("name") or f"排程巡檢 {uuid.uuid4().hex[:6]}",
        skill_id=skill_id,
        skill_input="{}",
        schedule_interval=interval,
        is_active=False,  # Start inactive; user activates manually
    )
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj.id


async def _publish_event(db: AsyncSession, payload: Dict) -> int:
    """Create a new EventType binding from draft payload."""
    from app.models.event_type import EventTypeModel

    name = payload.get("event_topic") or payload.get("name") or f"Draft Event {uuid.uuid4().hex[:6]}"
    obj = EventTypeModel(
        name=name,
        description=f"Agent 建立的事件觸發器",
        attributes=json.dumps([]),
    )
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj.id


# ── Create Routine Check Draft ───────────────────────────────────────────────

@router.post("/routine_check", summary="建立排程巡檢草稿 (Agent 呼叫)", response_model=Dict[str, Any])
async def create_routine_check_draft(
    body: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> Dict[str, Any]:
    """Agent proposes a RoutineCheck (scheduled skill run).

    Body fields:
      name              — check name
      skill_id          — existing Skill ID (provide this OR skill_draft)
      skill_draft       — {name, description, mcp_ids, diagnostic_prompt, ...} if creating new Skill
      schedule_interval — "30m" | "1h" | "4h" | "8h" | "12h" | "daily"
      skill_input       — JSON dict of fixed params (lot_id, tool_id, etc.)
    """
    payload = {
        "name": body.get("name", ""),
        "skill_id": body.get("skill_id"),
        "skill_draft": body.get("skill_draft"),
        "schedule_interval": body.get("schedule_interval", "1h"),
        "skill_input": body.get("skill_input") or {},
        "schedule_time": body.get("schedule_time"),
        "expire_at": body.get("expire_at"),
        "generated_event_name": body.get("generated_event_name"),
    }
    draft = await _create_draft(db, "routine_check", payload, current_user.id)
    return _draft_response(draft, payload)


# ── Create Event → Skill Link Draft ─────────────────────────────────────────

@router.post("/event_skill_link", summary="建立 Event→Skill 連結草稿 (Agent 呼叫)", response_model=Dict[str, Any])
async def create_event_skill_link_draft(
    body: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> Dict[str, Any]:
    """Agent proposes linking a Skill to an EventType's diagnosis chain.

    Body fields:
      event_type_id   — existing EventType ID (provide this OR event_type_name)
      event_type_name — new EventType name (if creating a new one)
      skill_id        — existing Skill ID (provide this OR skill_draft)
      skill_draft     — {name, description, mcp_ids, diagnostic_prompt, ...} if creating new Skill
    """
    payload = {
        "event_type_id": body.get("event_type_id"),
        "event_type_name": body.get("event_type_name", ""),
        "skill_id": body.get("skill_id"),
        "skill_draft": body.get("skill_draft"),
    }
    draft = await _create_draft(db, "event_skill_link", payload, current_user.id)
    return _draft_response(draft, payload)


async def _publish_routine_check(db: AsyncSession, payload: Dict) -> int:
    """Create a RoutineCheck from draft payload.

    If payload contains skill_draft (no skill_id), first publish the Skill,
    then create the RoutineCheck referencing the new Skill's id.
    """
    from app.models.routine_check import RoutineCheckModel
    import json as _json

    skill_id = payload.get("skill_id")
    if not skill_id and payload.get("skill_draft"):
        skill_id = await _publish_skill(db, payload["skill_draft"])

    if not skill_id:
        raise AppException(status_code=422, error_code="MISSING_SKILL",
                           detail="routine_check 草稿缺少 skill_id 或 skill_draft")

    interval = payload.get("schedule_interval") or "1h"
    skill_input_raw = payload.get("skill_input") or {}
    if isinstance(skill_input_raw, dict):
        skill_input = _json.dumps(skill_input_raw, ensure_ascii=False)
    else:
        skill_input = str(skill_input_raw)

    obj = RoutineCheckModel(
        name=payload.get("name") or f"排程巡檢 {uuid.uuid4().hex[:6]}",
        skill_id=skill_id,
        skill_input=skill_input,
        schedule_interval=interval,
        is_active=False,
    )
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj.id


async def _publish_event_skill_link(db: AsyncSession, payload: Dict) -> int:
    """Link a Skill to an EventType's diagnosis_skill_ids.

    Creates Skill first if skill_draft is provided.
    Creates EventType first if only event_type_name is provided.
    Returns the EventType id.
    """
    from app.models.event_type import EventTypeModel
    from sqlalchemy import select
    import json as _json

    # Resolve or create Skill
    skill_id = payload.get("skill_id")
    if not skill_id and payload.get("skill_draft"):
        skill_id = await _publish_skill(db, payload["skill_draft"])
    if not skill_id:
        raise AppException(status_code=422, error_code="MISSING_SKILL",
                           detail="event_skill_link 草稿缺少 skill_id 或 skill_draft")

    # Resolve or create EventType
    et_id = payload.get("event_type_id")
    if et_id:
        result = await db.execute(select(EventTypeModel).where(EventTypeModel.id == et_id))
        et = result.scalar_one_or_none()
        if not et:
            raise AppException(status_code=404, error_code="ET_NOT_FOUND",
                               detail=f"EventType #{et_id} 不存在")
    else:
        et_name = payload.get("event_type_name") or f"Draft Event {uuid.uuid4().hex[:6]}"
        result = await db.execute(select(EventTypeModel).where(EventTypeModel.name == et_name))
        et = result.scalar_one_or_none()
        if not et:
            et = EventTypeModel(
                name=et_name,
                description="Agent 建立的事件類型",
                attributes=_json.dumps([]),
                diagnosis_skill_ids=_json.dumps([]),
            )
            db.add(et)
            await db.flush()

    # Append skill_id to diagnosis_skill_ids (deduplicate)
    existing_ids = _j(et.diagnosis_skill_ids) or []
    if skill_id not in existing_ids:
        existing_ids.append(skill_id)
    et.diagnosis_skill_ids = _json.dumps(existing_ids, ensure_ascii=False)
    await db.commit()
    await db.refresh(et)
    return et.id


def _cron_to_minutes(cron: str) -> int:
    """Best-effort: extract interval in minutes from common cron patterns."""
    if not cron:
        return 60
    parts = cron.strip().split()
    if len(parts) < 5:
        return 60
    # Examples: "*/30 * * * *" → 30, "0 * * * *" → 60, "0 */2 * * *" → 120
    minute_part = parts[0]
    hour_part = parts[1]
    if minute_part.startswith("*/"):
        try:
            return int(minute_part[2:])
        except ValueError:
            pass
    if hour_part.startswith("*/"):
        try:
            return int(hour_part[2:]) * 60
        except ValueError:
            pass
    if minute_part == "0" and hour_part == "*":
        return 60
    return 60
