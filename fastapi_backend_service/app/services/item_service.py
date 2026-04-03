"""Item service module for the FastAPI Backend Service.

This module provides the ``ItemService`` class, which encapsulates all
item management business logic, including retrieval, creation, update,
and deletion operations with ownership-based authorization.
"""

from typing import List, Optional

from app.core.exceptions import (
    ERROR_CODE_FORBIDDEN,
    ERROR_CODE_NOT_FOUND,
    AppException,
)
from app.models.user import UserModel
from app.repositories.item_repository import ItemRepository
from app.schemas.item import ItemCreate, ItemResponse, ItemUpdate


class ItemService:
    """Service class for item management business logic.

    Coordinates between the router layer and the repository layer to handle
    item retrieval, creation, update, and deletion. Enforces ownership-based
    authorization: users may only modify or delete their own items unless they
    are superusers.

    Attributes:
        item_repo: The repository instance used for item data access operations.

    Examples:
        Typical usage within a router dependency::

            async def get_item_service(
                db: AsyncSession = Depends(get_db),
            ) -> ItemService:
                item_repo = ItemRepository(db)
                return ItemService(item_repo=item_repo)
    """

    def __init__(self, item_repo: ItemRepository) -> None:
        """Initialize the ItemService with an item repository instance.

        Args:
            item_repo: An ``ItemRepository`` instance used for all item
                       data access operations within this service.
        """
        self.item_repo: ItemRepository = item_repo

    async def get_item(self, item_id: int) -> ItemResponse:
        """Retrieve a single item by its primary key ID.

        Args:
            item_id: The integer primary key of the item to retrieve.

        Returns:
            An ``ItemResponse`` instance containing the item's public fields.

        Raises:
            AppException: With HTTP 404 and ``ERROR_CODE_NOT_FOUND`` if no
                          item with the given ``item_id`` exists.
        """
        item = await self.item_repo.get_by_id(item_id)
        if item is None:
            raise AppException(
                status_code=404,
                error_code=ERROR_CODE_NOT_FOUND,
                detail="Item 不存在",
            )
        return ItemResponse.model_validate(item)

    async def get_items(self, skip: int = 0, limit: int = 10) -> List[ItemResponse]:
        """Retrieve a paginated list of all items.

        Args:
            skip: Number of records to skip. Defaults to ``0``.
            limit: Maximum number of records to return. Defaults to ``10``.

        Returns:
            A list of ``ItemResponse`` instances. Empty list if none found.
        """
        items = await self.item_repo.get_all(skip=skip, limit=limit)
        return [ItemResponse.model_validate(item) for item in items]

    async def get_my_items(
        self,
        owner_id: int,
        skip: int = 0,
        limit: int = 10,
    ) -> List[ItemResponse]:
        """Retrieve a paginated list of items owned by a specific user.

        Args:
            owner_id: The primary key of the owning user.
            skip: Number of records to skip. Defaults to ``0``.
            limit: Maximum number of records to return. Defaults to ``10``.

        Returns:
            A list of ``ItemResponse`` instances belonging to the given owner.
        """
        items = await self.item_repo.get_by_owner(
            owner_id=owner_id,
            skip=skip,
            limit=limit,
        )
        return [ItemResponse.model_validate(item) for item in items]

    async def create_item(
        self,
        item_data: ItemCreate,
        owner_id: int,
    ) -> ItemResponse:
        """Create a new item and associate it with the given owner.

        Args:
            item_data: An ``ItemCreate`` instance with ``title`` and optional
                       ``description``.
            owner_id: The primary key of the user who will own this item.

        Returns:
            An ``ItemResponse`` instance representing the newly created item.
        """
        create_payload: dict = {
            "title": item_data.title,
            "description": item_data.description,
            "owner_id": owner_id,
            "is_active": True,
        }
        new_item = await self.item_repo.create(create_payload)
        return ItemResponse.model_validate(new_item)

    async def update_item(
        self,
        item_id: int,
        item_data: ItemUpdate,
        current_user: UserModel,
    ) -> ItemResponse:
        """Update an existing item after verifying ownership.

        Only the fields explicitly set (non-``None``) in ``item_data`` are
        applied. Only the item's owner or a superuser may perform updates.

        Args:
            item_id: The primary key of the item to update.
            item_data: An ``ItemUpdate`` instance with optional ``title``,
                       ``description``, and/or ``is_active`` fields.
            current_user: The authenticated ``UserModel`` performing the update.

        Returns:
            An ``ItemResponse`` instance representing the updated item.

        Raises:
            AppException: HTTP 404 if the item does not exist.
            AppException: HTTP 403 if the current user does not own the item
                          and is not a superuser.
        """
        item = await self.item_repo.get_by_id(item_id)
        if item is None:
            raise AppException(
                status_code=404,
                error_code=ERROR_CODE_NOT_FOUND,
                detail="Item 不存在",
            )

        if item.owner_id != current_user.id and not current_user.is_superuser:
            raise AppException(
                status_code=403,
                error_code=ERROR_CODE_FORBIDDEN,
                detail="無權限操作此 Item",
            )

        update_payload: dict = {}
        if item_data.title is not None:
            update_payload["title"] = item_data.title
        if item_data.description is not None:
            update_payload["description"] = item_data.description
        if item_data.is_active is not None:
            update_payload["is_active"] = item_data.is_active

        if not update_payload:
            return ItemResponse.model_validate(item)

        updated_item = await self.item_repo.update(item_id, update_payload)
        if updated_item is None:
            raise AppException(
                status_code=404,
                error_code=ERROR_CODE_NOT_FOUND,
                detail="Item 不存在",
            )
        return ItemResponse.model_validate(updated_item)

    async def delete_item(
        self,
        item_id: int,
        current_user: UserModel,
    ) -> bool:
        """Delete an item after verifying ownership.

        Only the item's owner or a superuser may delete the item.

        Args:
            item_id: The primary key of the item to delete.
            current_user: The authenticated ``UserModel`` performing the deletion.

        Returns:
            ``True`` if the item was successfully deleted.

        Raises:
            AppException: HTTP 404 if the item does not exist.
            AppException: HTTP 403 if the current user does not own the item
                          and is not a superuser.
        """
        item = await self.item_repo.get_by_id(item_id)
        if item is None:
            raise AppException(
                status_code=404,
                error_code=ERROR_CODE_NOT_FOUND,
                detail="Item 不存在",
            )

        if item.owner_id != current_user.id and not current_user.is_superuser:
            raise AppException(
                status_code=403,
                error_code=ERROR_CODE_FORBIDDEN,
                detail="無權限操作此 Item",
            )

        await self.item_repo.delete(item_id)
        return True
