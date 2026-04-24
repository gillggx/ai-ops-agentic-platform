"""AutoPatrolRepository — CRUD for the auto_patrols table."""

import json
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auto_patrol import AutoPatrolModel


def _j(s: Optional[str]) -> Any:
    if not s:
        return {}
    try:
        return json.loads(s)
    except Exception:
        return {}


class AutoPatrolRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def list_all(self, active_only: bool = False) -> List[AutoPatrolModel]:
        q = select(AutoPatrolModel).order_by(AutoPatrolModel.id)
        if active_only:
            q = q.where(AutoPatrolModel.is_active == True)  # noqa: E712
        result = await self._db.execute(q)
        return list(result.scalars().all())

    async def list_by_event_type(self, event_type_id: int) -> List[AutoPatrolModel]:
        """Return all active event-driven patrols bound to a given event type."""
        result = await self._db.execute(
            select(AutoPatrolModel)
            .where(AutoPatrolModel.event_type_id == event_type_id)
            .where(AutoPatrolModel.trigger_mode == "event")
            .where(AutoPatrolModel.is_active == True)  # noqa: E712
        )
        return list(result.scalars().all())

    async def get_by_skill_id(self, skill_id: int) -> Optional[AutoPatrolModel]:
        result = await self._db.execute(
            select(AutoPatrolModel).where(AutoPatrolModel.skill_id == skill_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, patrol_id: int) -> Optional[AutoPatrolModel]:
        result = await self._db.execute(
            select(AutoPatrolModel).where(AutoPatrolModel.id == patrol_id)
        )
        return result.scalar_one_or_none()

    async def create(self, data: Dict[str, Any]) -> AutoPatrolModel:
        target_scope = data.pop("target_scope", {"type": "event_driven"})
        notify_config = data.pop("notify_config", None)
        input_binding = data.pop("input_binding", None)  # Phase 4-B
        obj = AutoPatrolModel(
            **data,
            target_scope=json.dumps(target_scope, ensure_ascii=False),
            notify_config=json.dumps(notify_config, ensure_ascii=False) if notify_config else None,
            input_binding=json.dumps(input_binding, ensure_ascii=False) if input_binding else None,
        )
        self._db.add(obj)
        await self._db.commit()
        await self._db.refresh(obj)
        return obj

    async def update(self, patrol_id: int, data: Dict[str, Any]) -> Optional[AutoPatrolModel]:
        obj = await self.get_by_id(patrol_id)
        if not obj:
            return None
        if "target_scope" in data:
            data["target_scope"] = json.dumps(data["target_scope"], ensure_ascii=False)
        if "notify_config" in data:
            nc = data["notify_config"]
            data["notify_config"] = json.dumps(nc, ensure_ascii=False) if nc is not None else None
        if "input_binding" in data:
            ib = data["input_binding"]
            data["input_binding"] = json.dumps(ib, ensure_ascii=False) if ib is not None else None
        for k, v in data.items():
            setattr(obj, k, v)
        await self._db.commit()
        await self._db.refresh(obj)
        return obj

    async def delete(self, patrol_id: int) -> bool:
        obj = await self.get_by_id(patrol_id)
        if not obj:
            return False
        await self._db.delete(obj)
        await self._db.commit()
        return True

    # ── Deserialization helpers ───────────────────────────────────────────────

    def get_target_scope(self, obj: AutoPatrolModel) -> Dict[str, Any]:
        return _j(obj.target_scope)

    def get_notify_config(self, obj: AutoPatrolModel) -> Optional[Dict[str, Any]]:
        if not obj.notify_config:
            return None
        return _j(obj.notify_config)

    def get_input_binding(self, obj: AutoPatrolModel) -> Optional[Dict[str, Any]]:
        """Phase 4-B: parse input_binding JSON into dict. Returns None if unset."""
        raw = getattr(obj, "input_binding", None)
        if not raw:
            return None
        return _j(raw)

    def to_response_dict(self, obj: AutoPatrolModel) -> Dict[str, Any]:
        return {
            "id": obj.id,
            "name": obj.name,
            "description": obj.description,
            "auto_check_description": obj.auto_check_description or "",
            "skill_id": obj.skill_id,
            "pipeline_id": getattr(obj, "pipeline_id", None),
            "input_binding": self.get_input_binding(obj),
            "trigger_mode": obj.trigger_mode,
            "event_type_id": obj.event_type_id,
            "cron_expr": obj.cron_expr,
            "scheduled_at": getattr(obj, "scheduled_at", None),
            "data_context": obj.data_context or "recent_ooc",
            "target_scope": self.get_target_scope(obj),
            "alarm_severity": obj.alarm_severity,
            "alarm_title": obj.alarm_title,
            "notify_config": self.get_notify_config(obj),
            "is_active": obj.is_active,
            "created_by": obj.created_by,
            "created_at": obj.created_at,
            "updated_at": obj.updated_at,
        }
