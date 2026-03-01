"""Users router for the FastAPI Backend Service.

Provides CRUD endpoints under the ``/api/v1/users`` prefix:

- ``GET    /``          — paginated list of all users.
- ``POST   /``          — create a new user (HTTP 201).
- ``GET    /{user_id}`` — retrieve a specific user.
- ``PUT    /{user_id}`` — update a user (auth required; own account or superuser).
- ``DELETE /{user_id}`` — delete a user (auth required; own account or superuser).
"""

from typing import List

from fastapi import APIRouter, Depends, Query, status

from app.core.exceptions import ERROR_CODE_FORBIDDEN, AppException
from app.core.response import StandardResponse
from app.dependencies import get_current_user, get_user_service
from app.models.user import UserModel
from app.schemas.user import UserCreate, UserResponse, UserUpdate
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "/",
    response_model=StandardResponse,
    status_code=status.HTTP_200_OK,
    summary="取得所有使用者列表",
)
async def get_users(
    skip: int = Query(default=0, ge=0, description="略過筆數"),
    limit: int = Query(default=10, ge=1, le=100, description="最大回傳筆數"),
    user_service: UserService = Depends(get_user_service),
) -> StandardResponse:
    """Return a paginated list of all users."""
    users: List[UserResponse] = await user_service.get_users(skip=skip, limit=limit)
    return StandardResponse.success(
        data=[u.model_dump() for u in users],
        message="使用者列表取得成功",
    )


@router.post(
    "/",
    response_model=StandardResponse,
    status_code=status.HTTP_201_CREATED,
    summary="建立新使用者",
)
async def create_user(
    user_data: UserCreate,
    user_service: UserService = Depends(get_user_service),
) -> StandardResponse:
    """Create a new user account.

    Raises HTTP 409 if ``username`` or ``email`` is already registered.
    """
    new_user: UserResponse = await user_service.create_user(user_data)
    return StandardResponse.success(
        data=new_user.model_dump(),
        message="使用者建立成功",
    )


@router.get(
    "/{user_id}",
    response_model=StandardResponse,
    status_code=status.HTTP_200_OK,
    summary="取得特定使用者",
)
async def get_user(
    user_id: int,
    user_service: UserService = Depends(get_user_service),
) -> StandardResponse:
    """Return a single user by ID. Raises HTTP 404 if not found."""
    user: UserResponse = await user_service.get_user(user_id)
    return StandardResponse.success(
        data=user.model_dump(),
        message="使用者資訊取得成功",
    )


@router.put(
    "/{user_id}",
    response_model=StandardResponse,
    status_code=status.HTTP_200_OK,
    summary="更新使用者資訊（需驗證）",
)
async def update_user(
    user_id: int,
    user_data: UserUpdate,
    current_user: UserModel = Depends(get_current_user),
    user_service: UserService = Depends(get_user_service),
) -> StandardResponse:
    """Update a user account.

    Only the account owner or a superuser may update the record.
    Raises HTTP 403 if the current user has no permission.
    """
    if current_user.id != user_id and not current_user.is_superuser:
        raise AppException(
            status_code=403,
            error_code=ERROR_CODE_FORBIDDEN,
            detail="無權限操作此使用者",
        )
    updated: UserResponse = await user_service.update_user(user_id, user_data)
    return StandardResponse.success(
        data=updated.model_dump(),
        message="使用者資訊更新成功",
    )


@router.delete(
    "/{user_id}",
    response_model=StandardResponse,
    status_code=status.HTTP_200_OK,
    summary="刪除使用者（需驗證）",
)
async def delete_user(
    user_id: int,
    current_user: UserModel = Depends(get_current_user),
    user_service: UserService = Depends(get_user_service),
) -> StandardResponse:
    """Delete a user account.

    Only the account owner or a superuser may delete the record.
    Raises HTTP 403 if the current user has no permission.
    """
    if current_user.id != user_id and not current_user.is_superuser:
        raise AppException(
            status_code=403,
            error_code=ERROR_CODE_FORBIDDEN,
            detail="無權限操作此使用者",
        )
    await user_service.delete_user(user_id)
    return StandardResponse.success(message="使用者已刪除")
