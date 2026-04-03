"""
Event repository for database operations on Event entities.

Event 数据访问层。
"""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Event, EventType
from .base import BaseRepository


class EventTypeRepository(BaseRepository[EventType]):
    """
    Repository for EventType entity.
    
    EventType 数据访问库。
    """

    def __init__(self, db=None):
        """Initialize with EventType model."""
        super().__init__(EventType, db=db)

    async def get_by_name(
        self,
        db: AsyncSession,
        name: str,
    ) -> Optional[EventType]:
        """
        Get event type by name.
        
        按名称获取事件类型。
        
        Args:
            db: AsyncSession - Database session
            name: str - Event type name
        
        Returns:
            EventType or None
        """
        return await self.get_one_by_filter(db, name=name)

    async def name_exists(
        self,
        db: AsyncSession,
        name: str,
    ) -> bool:
        """
        Check if event type name exists.
        
        检查事件类型名称是否存在。
        
        Args:
            db: AsyncSession - Database session
            name: str - Event type name
        
        Returns:
            bool - True if exists
        """
        return await self.exists(db, name=name)


class EventRepository(BaseRepository[Event]):
    """
    Repository for Event entity.
    
    Event 数据访问库。
    """

    def __init__(self, db=None):
        """Initialize with Event model."""
        super().__init__(Event, db=db)

    async def get_by_event_type(
        self,
        db: AsyncSession,
        event_type_id: int,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Event]:
        """
        Get events by event type.
        
        按事件类型获取事件。
        
        Args:
            db: AsyncSession - Database session
            event_type_id: int - Event type ID
            skip: int - Records to skip
            limit: int - Max records
        
        Returns:
            list[Event] - Events of this type
        """
        stmt = (
            select(self.model)
            .where(self.model.event_type_id == event_type_id)
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_by_source(
        self,
        db: AsyncSession,
        source: str,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Event]:
        """
        Get events by source.
        
        按来源获取事件。
        
        Args:
            db: AsyncSession - Database session
            source: str - Event source
            skip: int - Records to skip
            limit: int - Max records
        
        Returns:
            list[Event] - Events from this source
        """
        stmt = (
            select(self.model)
            .where(self.model.source == source)
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_unprocessed(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Event]:
        """
        Get unprocessed events.
        
        获取未处理的事件。
        
        Args:
            db: AsyncSession - Database session
            skip: int - Records to skip
            limit: int - Max records
        
        Returns:
            list[Event] - Unprocessed events
        """
        stmt = (
            select(self.model)
            .where(self.model.processed == False)
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def count_unprocessed(
        self,
        db: AsyncSession,
    ) -> int:
        """
        Count unprocessed events.
        
        计数未处理的事件。
        
        Args:
            db: AsyncSession - Database session
        
        Returns:
            int - Count of unprocessed events
        """
        return await self.count(db, processed=False)

    async def mark_processed(
        self,
        db: AsyncSession,
        id: int,
    ) -> Optional[Event]:
        """
        Mark event as processed.
        
        标记事件为已处理。
        
        Args:
            db: AsyncSession - Database session
            id: int - Event ID
        
        Returns:
            Event or None - Updated event
        """
        return await self.update(db, id, processed=True)
