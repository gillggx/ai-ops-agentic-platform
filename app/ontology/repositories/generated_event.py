"""
GeneratedEvent and RoutineCheck repository for database operations.

GeneratedEvent and RoutineCheck 数据访问层。
"""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import GeneratedEvent
from .base import BaseRepository


class GeneratedEventRepository(BaseRepository[GeneratedEvent]):
    """
    Repository for GeneratedEvent entity.
    
    GeneratedEvent 数据访问库。
    """

    def __init__(self, db=None):
        """Initialize with GeneratedEvent model."""
        super().__init__(GeneratedEvent, db=db)

    async def get_by_event_type(
        self,
        db: AsyncSession,
        event_type_id: int,
        skip: int = 0,
        limit: int = 100,
    ) -> list[GeneratedEvent]:
        """
        Get generated events by event type.
        
        按事件类型获取生成的事件。
        
        Args:
            db: AsyncSession - Database session
            event_type_id: int - Event type ID
            skip: int - Records to skip
            limit: int - Max records
        
        Returns:
            list[GeneratedEvent] - Generated events
        """
        stmt = (
            select(self.model)
            .where(self.model.event_type_id == event_type_id)
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_by_skill(
        self,
        db: AsyncSession,
        source_skill_id: int,
        skip: int = 0,
        limit: int = 100,
    ) -> list[GeneratedEvent]:
        """
        Get generated events by source skill.
        
        按源技能获取生成的事件。
        
        Args:
            db: AsyncSession - Database session
            source_skill_id: int - Skill ID
            skip: int - Records to skip
            limit: int - Max records
        
        Returns:
            list[GeneratedEvent] - Generated events
        """
        stmt = (
            select(self.model)
            .where(self.model.source_skill_id == source_skill_id)
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_by_data_subject(
        self,
        db: AsyncSession,
        data_subject_id: int,
        skip: int = 0,
        limit: int = 100,
    ) -> list[GeneratedEvent]:
        """
        Get generated events by data subject.
        
        按数据主体获取生成的事件。
        
        Args:
            db: AsyncSession - Database session
            data_subject_id: int - Data subject ID
            skip: int - Records to skip
            limit: int - Max records
        
        Returns:
            list[GeneratedEvent] - Generated events
        """
        stmt = (
            select(self.model)
            .where(self.model.data_subject_id == data_subject_id)
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_actionable_events(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
    ) -> list[GeneratedEvent]:
        """
        Get actionable events (high confidence).
        
        获取可操作的事件（高信心）。
        
        Args:
            db: AsyncSession - Database session
            skip: int - Records to skip
            limit: int - Max records
        
        Returns:
            list[GeneratedEvent] - Actionable events
        """
        stmt = (
            select(self.model)
            .where(self.model.is_actionable == True)
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def count_by_confidence(
        self,
        db: AsyncSession,
        min_confidence: float,
    ) -> int:
        """
        Count events above confidence threshold.
        
        计数高于信心阈值的事件。
        
        Args:
            db: AsyncSession - Database session
            min_confidence: float - Minimum confidence (0.0-1.0)
        
        Returns:
            int - Count of events
        """
        stmt = select(self.model).where(self.model.confidence_score >= min_confidence)
        result = await db.execute(stmt)
        events = result.scalars().all()
        return len(events)


class _UnusedRoutineCheckRepository:
    """
    Repository for RoutineCheck entity.
    
    RoutineCheck 数据访问库。
    """

    def __init__(self, db=None):
        """Initialize with RoutineCheck model."""
        super().__init__(RoutineCheck, db=db)

    async def get_by_skill(
        self,
        db: AsyncSession,
        skill_definition_id: int,
        skip: int = 0,
        limit: int = 100,
    ) -> list[RoutineCheck]:
        """
        Get routine checks by skill.
        
        按技能获取例行检查。
        
        Args:
            db: AsyncSession - Database session
            skill_definition_id: int - Skill definition ID
            skip: int - Records to skip
            limit: int - Max records
        
        Returns:
            list[RoutineCheck] - Routine checks
        """
        stmt = (
            select(self.model)
            .where(self.model.skill_definition_id == skill_definition_id)
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_by_data_subject(
        self,
        db: AsyncSession,
        data_subject_id: int,
        skip: int = 0,
        limit: int = 100,
    ) -> list[RoutineCheck]:
        """
        Get routine checks by data subject.
        
        按数据主体获取例行检查。
        
        Args:
            db: AsyncSession - Database session
            data_subject_id: int - Data subject ID
            skip: int - Records to skip
            limit: int - Max records
        
        Returns:
            list[RoutineCheck] - Routine checks
        """
        stmt = (
            select(self.model)
            .where(self.model.data_subject_id == data_subject_id)
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_enabled_checks(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
    ) -> list[RoutineCheck]:
        """
        Get all enabled routine checks.
        
        获取所有启用的例行检查。
        
        Args:
            db: AsyncSession - Database session
            skip: int - Records to skip
            limit: int - Max records
        
        Returns:
            list[RoutineCheck] - Enabled checks
        """
        stmt = (
            select(self.model)
            .where(self.model.is_enabled == True)
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_by_name(
        self,
        db: AsyncSession,
        name: str,
    ) -> Optional[RoutineCheck]:
        """
        Get routine check by name.
        
        按名称获取例行检查。
        
        Args:
            db: AsyncSession - Database session
            name: str - Check name
        
        Returns:
            RoutineCheck or None
        """
        return await self.get_one_by_filter(db, name=name)

    async def count_enabled(
        self,
        db: AsyncSession,
    ) -> int:
        """
        Count enabled routine checks.
        
        计数启用的例行检查。
        
        Args:
            db: AsyncSession - Database session
        
        Returns:
            int - Count of enabled checks
        """
        return await self.count(db, is_enabled=True)
