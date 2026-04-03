"""Authentication router for the FastAPI Backend Service.

Provides the following endpoints under the ``/api/v1/auth`` prefix:

- ``POST /login``  — authenticate and obtain a JWT access token.
- ``GET  /me``     — return the currently authenticated user's profile.
"""

from fastapi import APIRouter, Depends, status

from app.core.response import StandardResponse
from app.dependencies import get_auth_service, get_current_user
from app.models.user import UserModel
from app.schemas.user import LoginRequest, TokenSchema, UserResponse
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/login",
    response_model=StandardResponse,
    status_code=status.HTTP_200_OK,
    summary="使用者登入",
    description="驗證帳號密碼後回傳 JWT Access Token。",
)
async def login(
    login_data: LoginRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> StandardResponse:
    """Authenticate a user and return a JWT access token.

    Args:
        login_data: Request body containing ``username`` and ``password``.
        auth_service: Injected ``AuthService`` instance.

    Returns:
        A ``StandardResponse`` whose ``data`` field contains a ``TokenSchema``
        with the signed ``access_token`` and ``token_type``.

    Raises:
        AppException: HTTP 401 if credentials are invalid or account is inactive.
    """
    token: TokenSchema = await auth_service.login(login_data)
    return StandardResponse.success(
        data=token.model_dump(),
        message="登入成功",
    )


@router.get(
    "/me",
    response_model=StandardResponse,
    status_code=status.HTTP_200_OK,
    summary="取得當前使用者資訊",
    description="回傳目前 Bearer Token 所對應的使用者資料。",
)
async def get_me(
    current_user: UserModel = Depends(get_current_user),
) -> StandardResponse:
    """Return the profile of the currently authenticated user.

    Args:
        current_user: Authenticated ``UserModel`` resolved from the Bearer token.

    Returns:
        A ``StandardResponse`` whose ``data`` field contains a ``UserResponse``.
    """
    return StandardResponse.success(
        data=UserResponse.model_validate(current_user).model_dump(),
        message="使用者資訊取得成功",
    )
