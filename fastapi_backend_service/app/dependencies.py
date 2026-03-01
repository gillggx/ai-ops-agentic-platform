"""FastAPI dependency injection functions for the FastAPI Backend Service.

This module centralises all ``Depends``-compatible factory functions used
throughout the router layer. The dependency chain is:

    DB Session → Repository → Service → Router

All dependencies are defined here to avoid circular imports and to provide
a single place to override them in tests (via ``app.dependency_overrides``).
"""

from collections.abc import AsyncGenerator

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.core.exceptions import ERROR_CODE_UNAUTHORIZED, AppException
from app.database import get_db
from app.models.user import UserModel
from app.repositories.item_repository import ItemRepository
from app.repositories.user_repository import UserRepository
from app.services.auth_service import AuthService
from app.services.item_service import ItemService
from app.services.user_service import UserService

# OAuth2 scheme — reads the Bearer token from the Authorization header.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


# ---------------------------------------------------------------------------
# Repository dependencies
# ---------------------------------------------------------------------------


async def get_user_repository(
    db: AsyncSession = Depends(get_db),
) -> UserRepository:
    """Provide a ``UserRepository`` scoped to the current request session.

    Args:
        db: Async database session injected by ``get_db``.

    Returns:
        A ``UserRepository`` instance bound to the request's ``AsyncSession``.
    """
    return UserRepository(db)


async def get_item_repository(
    db: AsyncSession = Depends(get_db),
) -> ItemRepository:
    """Provide an ``ItemRepository`` scoped to the current request session.

    Args:
        db: Async database session injected by ``get_db``.

    Returns:
        An ``ItemRepository`` instance bound to the request's ``AsyncSession``.
    """
    return ItemRepository(db)


# ---------------------------------------------------------------------------
# Service dependencies
# ---------------------------------------------------------------------------


async def get_auth_service(
    user_repo: UserRepository = Depends(get_user_repository),
) -> AuthService:
    """Provide an ``AuthService`` instance for the current request.

    Args:
        user_repo: ``UserRepository`` injected via ``get_user_repository``.

    Returns:
        An ``AuthService`` instance.
    """
    return AuthService(user_repo=user_repo)


async def get_user_service(
    user_repo: UserRepository = Depends(get_user_repository),
) -> UserService:
    """Provide a ``UserService`` instance for the current request.

    Args:
        user_repo: ``UserRepository`` injected via ``get_user_repository``.

    Returns:
        A ``UserService`` instance.
    """
    return UserService(user_repo=user_repo)


async def get_item_service(
    item_repo: ItemRepository = Depends(get_item_repository),
) -> ItemService:
    """Provide an ``ItemService`` instance for the current request.

    Args:
        item_repo: ``ItemRepository`` injected via ``get_item_repository``.

    Returns:
        An ``ItemService`` instance.
    """
    return ItemService(item_repo=item_repo)


# ---------------------------------------------------------------------------
# Authentication dependency
# ---------------------------------------------------------------------------


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    user_repo: UserRepository = Depends(get_user_repository),
) -> UserModel:
    """Resolve and return the currently authenticated user from a Bearer token.

    Decodes the JWT token extracted by ``oauth2_scheme``, looks up the user
    by the ``sub`` claim, and verifies the account is active.

    Args:
        token: Raw JWT string from the ``Authorization: Bearer`` header.
        user_repo: ``UserRepository`` for user look-up.

    Returns:
        The authenticated ``UserModel`` instance.

    Raises:
        AppException: HTTP 401 if the token is invalid, expired, the ``sub``
                      claim is missing, the user does not exist, or the account
                      is inactive.

    Examples:
        Usage in a protected router endpoint::

            @router.get("/protected")
            async def protected(current_user: UserModel = Depends(get_current_user)):
                return {"user": current_user.username}
    """
    from jose import JWTError  # local import to avoid circular at module load

    credentials_exception = AppException(
        status_code=401,
        error_code=ERROR_CODE_UNAUTHORIZED,
        detail="無效的身份驗證憑證",
    )

    try:
        payload: dict = decode_access_token(token)
    except JWTError:
        raise credentials_exception

    username: str | None = payload.get("sub")
    if not username:
        raise credentials_exception

    user: UserModel | None = await user_repo.get_by_username(username)
    if user is None:
        raise credentials_exception

    if not user.is_active:
        raise AppException(
            status_code=401,
            error_code=ERROR_CODE_UNAUTHORIZED,
            detail="使用者帳號已停用",
        )

    return user
