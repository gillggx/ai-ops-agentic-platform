"""
Base repository for data access operations.

数据访问的基类。
"""

from typing import Any, Generic, List, Optional, Type, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

ModelType = TypeVar("ModelType")


class BaseRepository(Generic[ModelType]):
    """
    Base repository class for database operations.
    
    数据访问基类。
    
    Provides:
    - Query building
    - Filtering and pagination
    - Aggregation functions
    - Batch operations
    
    This layer isolates ORM operations from business logic.
    
    职责:
    - 数据库查询构建
    - 过滤和分页
    - 聚合函数
    - 批量操作
    """

    def __init__(self, model: Type[ModelType], db: Optional[AsyncSession] = None):
        """Initialize repository.

        Args:
            model: SQLAlchemy model class.
            db:    Optional session for callers that pass db in constructor
                   (Pattern 2). If None, all methods require db as first arg
                   (Pattern 1).
        """
        self.model = model
        self._db: Optional[AsyncSession] = db

    def _resolve(self, db: Optional[AsyncSession]) -> AsyncSession:
        """Return provided db or fall back to self._db; raise if neither."""
        resolved = db if db is not None else self._db
        if resolved is None:
            raise RuntimeError(
                f"{type(self).__name__}: no db session — pass db to __init__ or to each method"
            )
        return resolved

    async def get_by_id(self, db: Optional[AsyncSession] = None, id: int = 0) -> Optional[ModelType]:
        _db = self._resolve(db)
        result = await _db.execute(select(self.model).where(self.model.id == id))
        return result.scalars().first()

    async def get_all(self, db: Optional[AsyncSession] = None, skip: int = 0, limit: int = 100) -> List[ModelType]:
        _db = self._resolve(db)
        result = await _db.execute(select(self.model).offset(skip).limit(limit))
        return result.scalars().all()

    async def count_all(self, db: Optional[AsyncSession] = None) -> int:
        _db = self._resolve(db)
        result = await _db.execute(select(func.count()).select_from(self.model))
        return result.scalar_one()

    async def get_by_filter(self, db: Optional[AsyncSession] = None, **filters: Any) -> List[ModelType]:
        _db = self._resolve(db)
        conditions = [getattr(self.model, k) == v for k, v in filters.items()]
        stmt = select(self.model).where(*conditions) if conditions else select(self.model)
        result = await _db.execute(stmt)
        return result.scalars().all()

    async def get_one_by_filter(self, db: Optional[AsyncSession] = None, **filters: Any) -> Optional[ModelType]:
        _db = self._resolve(db)
        conditions = [getattr(self.model, k) == v for k, v in filters.items()]
        stmt = select(self.model).where(*conditions) if conditions else select(self.model)
        result = await _db.execute(stmt)
        return result.scalars().first()

    async def count(self, db: Optional[AsyncSession] = None, **filters: Any) -> int:
        _db = self._resolve(db)
        conditions = [getattr(self.model, k) == v for k, v in filters.items()]
        stmt = (
            select(func.count(self.model.id)).where(*conditions)
            if conditions
            else select(func.count(self.model.id))
        )
        result = await _db.execute(stmt)
        return result.scalar() or 0

    async def exists(self, db: Optional[AsyncSession] = None, **filters: Any) -> bool:
        return await self.count(db, **filters) > 0

    async def create(self, db: Optional[AsyncSession] = None, **data: Any) -> ModelType:
        _db = self._resolve(db)
        obj = self.model(**data)
        _db.add(obj)
        await _db.flush()
        await _db.refresh(obj)
        return obj

    async def update(self, db: Optional[AsyncSession] = None, id: int = 0, **data: Any) -> Optional[ModelType]:
        obj = await self.get_by_id(db, id)
        if not obj:
            return None
        _db = self._resolve(db)
        for key, value in data.items():
            setattr(obj, key, value)
        _db.add(obj)
        await _db.flush()
        await _db.refresh(obj)
        return obj

    async def delete(self, db: Optional[AsyncSession] = None, id: int = 0) -> bool:
        obj = await self.get_by_id(db, id)
        if not obj:
            return False
        _db = self._resolve(db)
        await _db.delete(obj)
        await _db.flush()
        return True

    async def delete_many(self, db: Optional[AsyncSession] = None, **filters: Any) -> int:
        _db = self._resolve(db)
        conditions = [getattr(self.model, k) == v for k, v in filters.items()]
        stmt = select(self.model).where(*conditions) if conditions else select(self.model)
        result = await _db.execute(stmt)
        objs = result.scalars().all()
        count = 0
        for obj in objs:
            await _db.delete(obj)
            count += 1
        await _db.flush()
        return count
