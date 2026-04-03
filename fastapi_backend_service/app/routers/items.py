"""Items router for the FastAPI Backend Service.

Provides CRUD endpoints under the ``/api/v1/items`` prefix:

- ``GET    /``          — paginated list of all items.
- ``GET    /me``        — paginated list of the current user's items (auth required).
- ``POST   /``          — create a new item (auth required, HTTP 201).
- ``GET    /{item_id}`` — retrieve a specific item.
- ``PUT    /{item_id}`` — update an item (auth required; owner or superuser).
- ``DELETE /{item_id}`` — delete an item (auth required; owner or superuser).
"""

from typing import List

from fastapi import APIRouter, Depends, Query, status

from app.core.response import StandardResponse
from app.dependencies import get_current_user, get_item_service
from app.models.user import UserModel
from app.schemas.item import ItemCreate, ItemResponse, ItemUpdate
from app.services.item_service import ItemService

router = APIRouter(prefix="/items", tags=["items"])


@router.get(
    "/",
    response_model=StandardResponse,
    status_code=status.HTTP_200_OK,
    summary="取得所有 Item 列表",
)
async def get_items(
    skip: int = Query(default=0, ge=0, description="略過筆數"),
    limit: int = Query(default=10, ge=1, le=100, description="最大回傳筆數"),
    item_service: ItemService = Depends(get_item_service),
) -> StandardResponse:
    """Return a paginated list of all items."""
    items: List[ItemResponse] = await item_service.get_items(skip=skip, limit=limit)
    return StandardResponse.success(
        data=[i.model_dump() for i in items],
        message="Item 列表取得成功",
    )


@router.get(
    "/me",
    response_model=StandardResponse,
    status_code=status.HTTP_200_OK,
    summary="取得當前使用者的所有 Items（需驗證）",
)
async def get_my_items(
    skip: int = Query(default=0, ge=0, description="略過筆數"),
    limit: int = Query(default=10, ge=1, le=100, description="最大回傳筆數"),
    current_user: UserModel = Depends(get_current_user),
    item_service: ItemService = Depends(get_item_service),
) -> StandardResponse:
    """Return a paginated list of items owned by the current user."""
    items: List[ItemResponse] = await item_service.get_my_items(
        owner_id=current_user.id,
        skip=skip,
        limit=limit,
    )
    return StandardResponse.success(
        data=[i.model_dump() for i in items],
        message="我的 Item 列表取得成功",
    )


@router.post(
    "/",
    response_model=StandardResponse,
    status_code=status.HTTP_201_CREATED,
    summary="建立新 Item（需驗證）",
)
async def create_item(
    item_data: ItemCreate,
    current_user: UserModel = Depends(get_current_user),
    item_service: ItemService = Depends(get_item_service),
) -> StandardResponse:
    """Create a new item owned by the current user."""
    new_item: ItemResponse = await item_service.create_item(
        item_data=item_data,
        owner_id=current_user.id,
    )
    return StandardResponse.success(
        data=new_item.model_dump(),
        message="Item 建立成功",
    )


@router.get(
    "/{item_id}",
    response_model=StandardResponse,
    status_code=status.HTTP_200_OK,
    summary="取得特定 Item",
)
async def get_item(
    item_id: int,
    item_service: ItemService = Depends(get_item_service),
) -> StandardResponse:
    """Return a single item by ID. Raises HTTP 404 if not found."""
    item: ItemResponse = await item_service.get_item(item_id)
    return StandardResponse.success(
        data=item.model_dump(),
        message="Item 資訊取得成功",
    )


@router.put(
    "/{item_id}",
    response_model=StandardResponse,
    status_code=status.HTTP_200_OK,
    summary="更新 Item（需驗證，僅限擁有者或超級管理員）",
)
async def update_item(
    item_id: int,
    item_data: ItemUpdate,
    current_user: UserModel = Depends(get_current_user),
    item_service: ItemService = Depends(get_item_service),
) -> StandardResponse:
    """Update an item. Raises HTTP 403 if the user is not the owner."""
    updated: ItemResponse = await item_service.update_item(
        item_id=item_id,
        item_data=item_data,
        current_user=current_user,
    )
    return StandardResponse.success(
        data=updated.model_dump(),
        message="Item 更新成功",
    )


@router.delete(
    "/{item_id}",
    response_model=StandardResponse,
    status_code=status.HTTP_200_OK,
    summary="刪除 Item（需驗證，僅限擁有者或超級管理員）",
)
async def delete_item(
    item_id: int,
    current_user: UserModel = Depends(get_current_user),
    item_service: ItemService = Depends(get_item_service),
) -> StandardResponse:
    """Delete an item. Raises HTTP 403 if the user is not the owner."""
    await item_service.delete_item(item_id=item_id, current_user=current_user)
    return StandardResponse.success(message="Item 已刪除")
