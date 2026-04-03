"""
Skill repository for database operations on Skill entities.

Skill 数据访问层。
"""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Skill, SkillDefinition
from .base import BaseRepository


class SkillDefinitionRepository(BaseRepository[SkillDefinition]):
    """
    Repository for SkillDefinition entity.
    
    SkillDefinition 数据访问库。
    """

    def __init__(self, db=None):
        """Initialize with SkillDefinition model."""
        super().__init__(SkillDefinition, db=db)

    async def get_by_name(
        self,
        db: AsyncSession,
        name: str,
    ) -> Optional[SkillDefinition]:
        """
        Get skill definition by name.
        
        按名称获取技能定义。
        
        Args:
            db: AsyncSession - Database session
            name: str - Skill name
        
        Returns:
            SkillDefinition or None
        """
        return await self.get_one_by_filter(db, name=name)

    async def name_exists(
        self,
        db: AsyncSession,
        name: str,
    ) -> bool:
        """
        Check if skill name exists.
        
        检查技能名称是否存在。
        
        Args:
            db: AsyncSession - Database session
            name: str - Skill name
        
        Returns:
            bool - True if exists
        """
        return await self.exists(db, name=name)

    async def get_active_skills(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
    ) -> list[SkillDefinition]:
        """
        Get all active skills.
        
        获取所有活跃技能。
        
        Args:
            db: AsyncSession - Database session
            skip: int - Records to skip
            limit: int - Max records
        
        Returns:
            list[SkillDefinition] - Active skills
        """
        stmt = select(self.model).offset(skip).limit(limit)
        result = await db.execute(stmt)
        return result.scalars().all()


class SkillRepository(BaseRepository[Skill]):
    """
    Repository for Skill entity.
    
    Skill 数据访问库。
    """

    def __init__(self, db=None):
        """Initialize with Skill model."""
        super().__init__(Skill, db=db)

    async def get_by_skill_definition(
        self,
        db: AsyncSession,
        skill_definition_id: int,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Skill]:
        """
        Get skill instances by definition.
        
        按定义获取技能实例。
        
        Args:
            db: AsyncSession - Database session
            skill_definition_id: int - Skill definition ID
            skip: int - Records to skip
            limit: int - Max records
        
        Returns:
            list[Skill] - Skill instances
        """
        stmt = (
            select(self.model)
            .where(self.model.skill_definition_id == skill_definition_id)
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_active_skills(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Skill]:
        """
        Get all active skills.
        
        获取所有活跃技能。
        
        Args:
            db: AsyncSession - Database session
            skip: int - Records to skip
            limit: int - Max records
        
        Returns:
            list[Skill] - Active skills
        """
        stmt = (
            select(self.model)
            .where(self.model.is_active == True)
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_by_name(
        self,
        db: AsyncSession,
        name: str,
    ) -> Optional[Skill]:
        """
        Get skill instance by name.
        
        按名称获取技能实例。
        
        Args:
            db: AsyncSession - Database session
            name: str - Skill name
        
        Returns:
            Skill or None
        """
        return await self.get_one_by_filter(db, name=name)
