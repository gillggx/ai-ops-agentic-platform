## app/services/auth_service.py
"""Authentication service module for the FastAPI Backend Service.

This module provides the ``AuthService`` class, which encapsulates all
authentication-related business logic, including user credential verification,
JWT token generation, and current user resolution from a Bearer token.
"""

from typing import Optional

from jose import JWTError

from app.core.exceptions import (
    ERROR_CODE_UNAUTHORIZED,
    AppException,
)
from app.core.security import (
    create_access_token,
    decode_access_token,
    verify_password,
)
from app.models.user import UserModel
from app.repositories.user_repository import UserRepository
from app.schemas.user import LoginRequest, TokenSchema


class AuthService:
    """Service class for authentication and token management.

    Coordinates between the router layer and the repository layer to handle
    user authentication, JWT access token generation, and current user
    resolution. All business logic related to identity verification is
    encapsulated within this class.

    Attributes:
        user_repo: The repository instance used for user data access operations.

    Examples:
        Typical usage within a router dependency::

            async def get_auth_service(
                db: AsyncSession = Depends(get_db),
            ) -> AuthService:
                user_repo = UserRepository(db)
                return AuthService(user_repo=user_repo)
    """

    def __init__(self, user_repo: UserRepository) -> None:
        """Initialize the AuthService with a user repository instance.

        Args:
            user_repo: A ``UserRepository`` instance used for all user
                       data access operations within this service.
        """
        self.user_repo: UserRepository = user_repo

    async def authenticate_user(
        self,
        username: str,
        password: str,
    ) -> Optional[UserModel]:
        """Verify a user's credentials against the database.

        Looks up the user by ``username`` and verifies the provided plain-text
        ``password`` against the stored bcrypt hash. Also checks that the user
        account is active before returning the model instance.

        Args:
            username: The username string provided by the client.
            password: The plain-text password string provided by the client.

        Returns:
            The authenticated ``UserModel`` instance if the credentials are
            valid and the account is active, otherwise ``None``.

        Examples:
            >>> user = await auth_service.authenticate_user("alice", "secret123")
            >>> if user is None:
            ...     raise AppException(401, ERROR_CODE_UNAUTHORIZED, "帳號或密碼錯誤")
        """
        user: Optional[UserModel] = await self.user_repo.get_by_username(username)

        if user is None:
            return None

        if not verify_password(password, user.hashed_password):
            return None

        if not user.is_active:
            return None

        return user

    async def login(self, login_data: LoginRequest) -> TokenSchema:
        """Authenticate a user and generate a JWT access token.

        Validates the provided credentials via ``authenticate_user``. If
        authentication succeeds, generates and returns a signed JWT access
        token encapsulating the user's ``username`` as the ``sub`` claim.

        Args:
            login_data: A ``LoginRequest`` instance containing the ``username``
                        and ``password`` fields from the request body.

        Returns:
            A ``TokenSchema`` instance containing the signed ``access_token``
            and ``token_type`` (always ``"bearer"``).

        Raises:
            AppException: With HTTP 401 and ``ERROR_CODE_UNAUTHORIZED`` if the
                          username/password combination is incorrect or the
                          account is inactive.

        Examples:
            >>> token = await auth_service.login(
            ...     LoginRequest(username="alice", password="secret123")
            ... )
            >>> token.token_type
            'bearer'
            >>> isinstance(token.access_token, str)
            True
        """
        user: Optional[UserModel] = await self.authenticate_user(
            username=login_data.username,
            password=login_data.password,
        )

        if user is None:
            raise AppException(
                status_code=401,
                error_code=ERROR_CODE_UNAUTHORIZED,
                detail="帳號或密碼錯誤",
            )

        access_token: str = create_access_token(
            data={"sub": user.username},
        )

        return TokenSchema(
            access_token=access_token,
            token_type="bearer",
        )

    async def get_current_user(self, token: str) -> UserModel:
        """Resolve the currently authenticated user from a JWT Bearer token.

        Decodes and validates the provided JWT token, extracts the ``sub``
        claim (username), and retrieves the corresponding user from the
        database. Verifies that the user exists and the account is active.

        Args:
            token: The raw JWT token string extracted from the
                   ``Authorization: Bearer <token>`` request header.

        Returns:
            The ``UserModel`` instance corresponding to the authenticated user.

        Raises:
            AppException: With HTTP 401 and ``ERROR_CODE_UNAUTHORIZED`` in any
                          of the following cases:

                          - The token cannot be decoded or has an invalid signature.
                          - The token is expired.
                          - The ``sub`` claim is missing or empty.
                          - No user with the given username exists in the database.
                          - The user account is inactive.

        Examples:
            >>> user = await auth_service.get_current_user(token="eyJhbGci...")
            >>> user.username
            'alice'

            >>> await auth_service.get_current_user("invalid.token")
            # Raises AppException(status_code=401, error_code="UNAUTHORIZED", ...)
        """
        credentials_exception = AppException(
            status_code=401,
            error_code=ERROR_CODE_UNAUTHORIZED,
            detail="無效的身份驗證憑證",
        )

        try:
            payload: dict = decode_access_token(token)
        except JWTError:
            raise credentials_exception

        username: Optional[str] = payload.get("sub")
        if not username:
            raise credentials_exception

        user: Optional[UserModel] = await self.user_repo.get_by_username(username)
        if user is None:
            raise credentials_exception

        if not user.is_active:
            raise AppException(
                status_code=401,
                error_code=ERROR_CODE_UNAUTHORIZED,
                detail="使用者帳號已停用",
            )

        return user
