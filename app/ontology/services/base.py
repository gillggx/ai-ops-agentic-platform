"""
Base service class for all business logic services.

所有服務的基類。
"""

from typing import Any, Dict, Generic, List, Optional, Type, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

ModelType = TypeVar("ModelType")
CreateSchemaType = TypeVar("CreateSchemaType")
UpdateSchemaType = TypeVar("UpdateSchemaType")


class BaseService(Generic[ModelType, CreateSchemaType, UpdateSchemaType]):
    """
    Base service class for CRUD operations.
    
    所有服務的基類，提供 CRUD 操作。
    
    Subclasses should implement:
    - model: SQLAlchemy ORM model
    - create_schema: Pydantic create schema
    - update_schema: Pydantic update schema
    
    子類應實現:
    - model: SQLAlchemy ORM 模型
    - create_schema: Pydantic 創建 schema
    - update_schema: Pydantic 更新 schema
    
    Example:
        class UserService(BaseService[User, UserCreate, UserUpdate]):
            model = User
            create_schema = UserCreate
            update_schema = UserUpdate
    """

    model: Type[ModelType]
    create_schema: Type[CreateSchemaType]
    update_schema: Type[UpdateSchemaType]

    async def create(
        self,
        db: AsyncSession,
        obj_in: CreateSchemaType,
    ) -> ModelType:
        """
        Create a new record.
        
        Args:
            db: AsyncSession - Database session
            obj_in: CreateSchemaType - Data to create
        
        Returns:
            ModelType - Created instance
        
        Raises:
            Exception: If creation fails
        
        創建新記錄。
        """
        obj_data = obj_in.model_dump(exclude_unset=True)
        db_obj = self.model(**obj_data)
        db.add(db_obj)
        await db.flush()
        await db.refresh(db_obj)
        return db_obj

    async def read(
        self,
        db: AsyncSession,
        id: int,
    ) -> Optional[ModelType]:
        """
        Read a record by ID.
        
        Args:
            db: AsyncSession - Database session
            id: int - Record ID
        
        Returns:
            ModelType or None - Found instance or None
        
        根據 ID 讀取記錄。
        """
        from sqlalchemy import select

        stmt = select(self.model).where(self.model.id == id)
        result = await db.execute(stmt)
        return result.scalars().first()

    async def list_all(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
    ) -> List[ModelType]:
        """
        List all records with pagination.
        
        Args:
            db: AsyncSession - Database session
            skip: int - Number of records to skip
            limit: int - Maximum records to return
        
        Returns:
            List[ModelType] - List of records
        
        列出所有記錄（分頁）。
        """
        from sqlalchemy import select

        stmt = select(self.model).offset(skip).limit(limit)
        result = await db.execute(stmt)
        return result.scalars().all()

    async def update(
        self,
        db: AsyncSession,
        id: int,
        obj_in: UpdateSchemaType,
    ) -> Optional[ModelType]:
        """
        Update a record.
        
        Args:
            db: AsyncSession - Database session
            id: int - Record ID
            obj_in: UpdateSchemaType - Update data
        
        Returns:
            ModelType or None - Updated instance or None
        
        Raises:
            Exception: If update fails
        
        更新記錄。
        """
        db_obj = await self.read(db, id)
        if not db_obj:
            return None

        update_data = obj_in.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(db_obj, field, value)

        db.add(db_obj)
        await db.flush()
        await db.refresh(db_obj)
        return db_obj

    async def delete(
        self,
        db: AsyncSession,
        id: int,
    ) -> bool:
        """
        Delete a record.
        
        Args:
            db: AsyncSession - Database session
            id: int - Record ID
        
        Returns:
            bool - True if deleted, False if not found
        
        刪除記錄。
        """
        db_obj = await self.read(db, id)
        if not db_obj:
            return False

        await db.delete(db_obj)
        await db.flush()
        return True

    async def count(
        self,
        db: AsyncSession,
    ) -> int:
        """
        Count total records.
        
        Args:
            db: AsyncSession - Database session
        
        Returns:
            int - Total count
        
        計算總記錄數。
        """
        from sqlalchemy import func, select

        stmt = select(func.count(self.model.id))
        result = await db.execute(stmt)
        return result.scalar() or 0

    async def exists(
        self,
        db: AsyncSession,
        **kwargs: Any,
    ) -> bool:
        """
        Check if record exists with given conditions.
        
        Args:
            db: AsyncSession - Database session
            **kwargs: Field conditions
        
        Returns:
            bool - True if exists
        
        檢查記錄是否存在。
        """
        from sqlalchemy import select

        filters = [getattr(self.model, k) == v for k, v in kwargs.items()]
        stmt = select(self.model).where(*filters) if filters else select(self.model)
        result = await db.execute(stmt)
        return result.scalars().first() is not None
