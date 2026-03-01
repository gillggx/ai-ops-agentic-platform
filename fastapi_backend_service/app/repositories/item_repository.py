## app/repositories/item_repository.py
"""Item repository module for the FastAPI Backend Service.

This module provides the ``ItemRepository`` class, which encapsulates all
database query logic for item-related operations. It acts as the data access
layer between the service layer and the database, using SQLAlchemy 2.0
async APIs exclusively.
"""

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.item import ItemModel


class ItemRepository:
    """Repository class for item data access operations.

    Encapsulates all SQLAlchemy async queries related to the ``items`` table.
    All methods are ``async`` and must be awaited by the caller. Instances
    are created per-request and receive an injected ``AsyncSession``.

    Attributes:
        db: The async database session used for all queries in this repository.

    Examples:
        Typical usage within a service::

            async def example(db: AsyncSession):
                repo = ItemRepository(db)
                item = await repo.get_by_id(1)
    """

    def __init__(self, db: AsyncSession) -> None:
        """Initialize the ItemRepository with an async database session.

        Args:
            db: An ``AsyncSession`` instance provided via FastAPI dependency injection.
        """
        self.db: AsyncSession = db

    async def get_by_id(self, item_id: int) -> Optional[ItemModel]:
        """Retrieve an item by its primary key ID.

        Args:
            item_id: The integer primary key of the item to look up.

        Returns:
            The ``ItemModel`` instance if found, otherwise ``None``.

        Examples:
            >>> item = await repo.get_by_id(1)
            >>> if item is None:
            ...     raise AppException(404, ERROR_CODE_NOT_FOUND, "Item 不存在")
        """
        statement = select(ItemModel).where(ItemModel.id == item_id)
        result = await self.db.execute(statement)
        return result.scalar_one_or_none()

    async def get_all(self, skip: int = 0, limit: int = 10) -> List[ItemModel]:
        """Retrieve a paginated list of all items.

        Args:
            skip: The number of records to skip (offset). Defaults to ``0``.
            limit: The maximum number of records to return. Defaults to ``10``.

        Returns:
            A list of ``ItemModel`` instances ordered by ``id`` ascending.
            Returns an empty list if no items are found within the given range.

        Examples:
            >>> items = await repo.get_all(skip=0, limit=20)
            >>> len(items)
            20
        """
        statement = (
            select(ItemModel)
            .order_by(ItemModel.id)
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(statement)
        return list(result.scalars().all())

    async def get_by_owner(
        self,
        owner_id: int,
        skip: int = 0,
        limit: int = 10,
    ) -> List[ItemModel]:
        """Retrieve a paginated list of items belonging to a specific owner.

        Args:
            owner_id: The integer primary key of the owning user whose items
                      should be retrieved.
            skip: The number of records to skip (offset). Defaults to ``0``.
            limit: The maximum number of records to return. Defaults to ``10``.

        Returns:
            A list of ``ItemModel`` instances owned by the specified user,
            ordered by ``id`` ascending. Returns an empty list if no items
            are found for the given owner within the specified range.

        Examples:
            >>> items = await repo.get_by_owner(owner_id=1, skip=0, limit=10)
            >>> all(item.owner_id == 1 for item in items)
            True
        """
        statement = (
            select(ItemModel)
            .where(ItemModel.owner_id == owner_id)
            .order_by(ItemModel.id)
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(statement)
        return list(result.scalars().all())

    async def create(self, item_data: dict) -> ItemModel:
        """Create and persist a new item record.

        Constructs a new ``ItemModel`` instance from the provided dictionary,
        adds it to the session, commits the transaction, and refreshes the
        instance to populate any server-generated fields (e.g. ``id``,
        ``created_at``).

        Args:
            item_data: A dictionary containing the fields for the new item.
                       Expected keys: ``title``, ``owner_id``, and optionally
                       ``description``, ``is_active``.

        Returns:
            The newly created and persisted ``ItemModel`` instance with all
            fields populated (including auto-generated ``id`` and timestamps).

        Examples:
            >>> new_item = await repo.create({
            ...     "title": "My First Item",
            ...     "description": "A detailed description.",
            ...     "owner_id": 1,
            ... })
            >>> new_item.id
            1
        """
        db_item = ItemModel(**item_data)
        self.db.add(db_item)
        await self.db.commit()
        await self.db.refresh(db_item)
        return db_item

    async def update(
        self,
        item_id: int,
        item_data: dict,
    ) -> Optional[ItemModel]:
        """Update an existing item record with the provided field values.

        Retrieves the item by ``item_id``, applies all key-value pairs from
        ``item_data`` to the model instance, commits the transaction, and
        refreshes the instance to reflect any database-level changes.

        Args:
            item_id: The integer primary key of the item to update.
            item_data: A dictionary of field names and their new values.
                       Only the provided fields are updated; others remain unchanged.
                       Typical keys: ``title``, ``description``, ``is_active``.

        Returns:
            The updated ``ItemModel`` instance if the item was found and
            successfully updated, otherwise ``None``.

        Examples:
            >>> updated = await repo.update(1, {"title": "Updated Title"})
            >>> if updated is None:
            ...     raise AppException(404, ERROR_CODE_NOT_FOUND, "Item 不存在")
            >>> updated.title
            'Updated Title'
        """
        db_item = await self.get_by_id(item_id)
        if db_item is None:
            return None

        for field, value in item_data.items():
            setattr(db_item, field, value)

        self.db.add(db_item)
        await self.db.commit()
        await self.db.refresh(db_item)
        return db_item

    async def delete(self, item_id: int) -> bool:
        """Delete an item record by its primary key ID.

        Retrieves the item by ``item_id`` and removes the record from the
        database. If no item with the given ID exists, returns ``False``
        without raising an exception.

        Args:
            item_id: The integer primary key of the item to delete.

        Returns:
            ``True`` if the item was found and successfully deleted,
            ``False`` if no item with the given ID was found.

        Examples:
            >>> deleted = await repo.delete(1)
            >>> if not deleted:
            ...     raise AppException(404, ERROR_CODE_NOT_FOUND, "Item 不存在")
        """
        db_item = await self.get_by_id(item_id)
        if db_item is None:
            return False

        await self.db.delete(db_item)
        await self.db.commit()
        return True
