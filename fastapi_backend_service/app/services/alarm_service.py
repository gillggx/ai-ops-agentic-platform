"""AlarmService — create and manage Alarms."""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.core.exceptions import AppException
from app.repositories.alarm_repository import AlarmRepository
from app.schemas.alarm import AlarmResponse, AlarmStatsResponse

logger = logging.getLogger(__name__)


def _to_response(alarm) -> AlarmResponse:
    return AlarmResponse.model_validate(alarm)


class AlarmService:
    def __init__(self, repo: AlarmRepository) -> None:
        self._repo = repo

    async def list_alarms(
        self,
        status: Optional[str] = "active",
        severity: Optional[str] = None,
        equipment_id: Optional[str] = None,
        lot_id: Optional[str] = None,
        trigger_event: Optional[str] = None,
        days: int = 7,
        limit: int = 50,
        offset: int = 0,
    ) -> List[AlarmResponse]:
        alarms = await self._repo.list_alarms(
            status=status, severity=severity, equipment_id=equipment_id,
            lot_id=lot_id, trigger_event=trigger_event,
            days=days, limit=limit, offset=offset,
        )
        return [_to_response(a) for a in alarms]

    async def get(self, alarm_id: int) -> AlarmResponse:
        alarm = await self._repo.get_by_id(alarm_id)
        if not alarm:
            raise AppException(status_code=404, error_code="NOT_FOUND", detail=f"Alarm id={alarm_id} 不存在")
        return _to_response(alarm)

    async def acknowledge(self, alarm_id: int, acknowledged_by: str) -> AlarmResponse:
        alarm = await self._repo.acknowledge(alarm_id, acknowledged_by)
        if not alarm:
            raise AppException(status_code=404, error_code="NOT_FOUND", detail=f"Alarm id={alarm_id} 不存在")
        return _to_response(alarm)

    async def resolve(self, alarm_id: int) -> AlarmResponse:
        alarm = await self._repo.resolve(alarm_id)
        if not alarm:
            raise AppException(status_code=404, error_code="NOT_FOUND", detail=f"Alarm id={alarm_id} 不存在")
        return _to_response(alarm)

    async def get_stats(self, days: int = 7) -> AlarmStatsResponse:
        stats = await self._repo.get_stats(days=days)
        return AlarmStatsResponse(**stats)
