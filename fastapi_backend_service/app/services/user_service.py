## app/services/user_service.py
"""User service module for the FastAPI Backend Service.

This module provides the ``UserService`` class, which encapsulates all
user management business logic, including user retrieval, creation, update,
and deletion operations. It coordinates between the router layer and the
repository layer, enforcing business rules such as duplicate email/username
checks and password hashing.
"""

from typing import List

from app.core.exceptions import (
    ERROR_CODE_CONFLICT,
    ERROR_CODE_NOT_FOUND,
    AppException,
)
from app.core.security import get_password_hash
from app.models.user import UserModel
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate, UserResponse, UserUpdate


class UserService:
    """Service class for user management business logic.

    Coordinates between the router layer and the repository layer to handle
    user retrieval, creation, update, and deletion. Enforces business rules
    such as uniqueness constraints on ``username`` and ``email``, and
    delegates password hashing to the security module.

    Attributes:
        user_repo: The repository instance used for user data access operations.

    Examples:
        Typical usage within a router dependency::

            async def get_user_service(
                db: AsyncSession = Depends(get_db),
            ) -> UserService:
                user_repo = UserRepository(db)
                return UserService(user_repo=user_repo)
    """

    def __init__(self, user_repo: UserRepository) -> None:
        """Initialize the UserService with a user repository instance.

        Args:
            user_repo: A ``UserRepository`` instance used for all user
                       data access operations within this service.
        """
        self.user_repo: UserRepository = user_repo

    async def get_user(self, user_id: int) -> UserResponse:
        """Retrieve a single user by their primary key ID.

        Args:
            user_id: The integer primary key of the user to retrieve.

        Returns:
            A ``UserResponse`` instance containing the user's public fields.

        Raises:
            AppException: With HTTP 404 and ``ERROR_CODE_NOT_FOUND`` if no
                          user with the given ``user_id`` exists in the database.

        Examples:
            >>> user_response = await user_service.get_user(user_id=1)
            >>> user_response.username
            'alice'

            >>> await user_service.get_user(user_id=999)
            # Raises AppException(status_code=404, error_code="NOT_FOUND", ...)
        """
        user: UserModel | None = await self.user_repo.get_by_id(user_id)

        if user is None:
            raise AppException(
                status_code=404,
                error_code=ERROR_CODE_NOT_FOUND,
                detail="使用者不存在",
            )

        return UserResponse.model_validate(user)

    async def get_users(self, skip: int = 0, limit: int = 10) -> List[UserResponse]:
        """Retrieve a paginated list of all users.

        Args:
            skip: The number of records to skip (offset). Must be non-negative.
                  Defaults to ``0``.
            limit: The maximum number of records to return. Must be between
                   1 and 100. Defaults to ``10``.

        Returns:
            A list of ``UserResponse`` instances. Returns an empty list if
            no users are found within the given range.

        Examples:
            >>> users = await user_service.get_users(skip=0, limit=20)
            >>> len(users)
            20

            >>> users = await user_service.get_users()
            >>> isinstance(users, list)
            True
        """
        users: List[UserModel] = await self.user_repo.get_all(skip=skip, limit=limit)
        return [UserResponse.model_validate(user) for user in users]

    async def create_user(self, user_data: UserCreate) -> UserResponse:
        """Create a new user account after validating uniqueness constraints.

        Checks that neither the ``username`` nor the ``email`` is already
        registered in the database. If either is taken, raises a conflict
        exception. Hashes the plain-text password before persisting the record.

        Args:
            user_data: A ``UserCreate`` instance containing the validated
                       ``username``, ``email``, and plain-text ``password``.

        Returns:
            A ``UserResponse`` instance representing the newly created user.

        Raises:
            AppException: With HTTP 409 and ``ERROR_CODE_CONFLICT`` if the
                          provided ``username`` is already registered.
            AppException: With HTTP 409 and ``ERROR_CODE_CONFLICT`` if the
                          provided ``email`` is already registered.

        Examples:
            >>> new_user = await user_service.create_user(
            ...     UserCreate(
            ...         username="alice",
            ...         email="alice@example.com",
            ...         password="secret123",
            ...     )
            ... )
            >>> new_user.username
            'alice'

            >>> await user_service.create_user(
            ...     UserCreate(username="alice", email="other@example.com", password="pw")
            ... )
            # Raises AppException(status_code=409, error_code="CONFLICT", ...)
        """
        # Check username uniqueness
        existing_by_username: UserModel | None = await self.user_repo.get_by_username(
            user_data.username
        )
        if existing_by_username is not None:
            raise AppException(
                status_code=409,
                error_code=ERROR_CODE_CONFLICT,
                detail="使用者名稱已被使用",
            )

        # Check email uniqueness
        existing_by_email: UserModel | None = await self.user_repo.get_by_email(
            user_data.email
        )
        if existing_by_email is not None:
            raise AppException(
                status_code=409,
                error_code=ERROR_CODE_CONFLICT,
                detail="電子郵件已被使用",
            )

        # Hash the password before storing
        hashed_password: str = get_password_hash(user_data.password)

        create_payload: dict = {
            "username": user_data.username,
            "email": user_data.email,
            "hashed_password": hashed_password,
            "is_active": True,
            "is_superuser": False,
        }

        new_user: UserModel = await self.user_repo.create(create_payload)
        return UserResponse.model_validate(new_user)

    async def update_user(
        self, user_id: int, user_data: UserUpdate
    ) -> UserResponse:
        """Update an existing user account with the provided field values.

        Only the fields explicitly set in ``user_data`` (i.e. non-``None`` values)
        are applied to the user record. Validates uniqueness constraints for
        ``username`` and ``email`` if those fields are being changed. Hashes
        the new password if one is provided.

        Args:
            user_id: The integer primary key of the user to update.
            user_data: A ``UserUpdate`` instance containing the optional fields
                       to update: ``username``, ``email``, ``password``,
                       and/or ``is_active``.

        Returns:
            A ``UserResponse`` instance representing the updated user.

        Raises:
            AppException: With HTTP 404 and ``ERROR_CODE_NOT_FOUND`` if no
                          user with the given ``user_id`` exists.
            AppException: With HTTP 409 and ``ERROR_CODE_CONFLICT`` if the
                          new ``username`` is already taken by another user.
            AppException: With HTTP 409 and ``ERROR_CODE_CONFLICT`` if the
                          new ``email`` is already taken by another user.

        Examples:
            >>> updated = await user_service.update_user(
            ...     user_id=1,
            ...     user_data=UserUpdate(username="alice_v2"),
            ... )
            >>> updated.username
            'alice_v2'

            >>> await user_service.update_user(
            ...     user_id=999,
            ...     user_data=UserUpdate(username="ghost"),
            ... )
            # Raises AppException(status_code=404, error_code="NOT_FOUND", ...)
        """
        # Verify target user exists
        existing_user: UserModel | None = await self.user_repo.get_by_id(user_id)
        if existing_user is None:
            raise AppException(
                status_code=404,
                error_code=ERROR_CODE_NOT_FOUND,
                detail="使用者不存在",
            )

        update_payload: dict = {}

        # Validate and prepare username update
        if user_data.username is not None:
            conflict_user: UserModel | None = await self.user_repo.get_by_username(
                user_data.username
            )
            if conflict_user is not None and conflict_user.id != user_id:
                raise AppException(
                    status_code=409,
                    error_code=ERROR_CODE_CONFLICT,
                    detail="使用者名稱已被使用",
                )
            update_payload["username"] = user_data.username

        # Validate and prepare email update
        if user_data.email is not None:
            conflict_user_by_email: UserModel | None = await self.user_repo.get_by_email(
                user_data.email
            )
            if (
                conflict_user_by_email is not None
                and conflict_user_by_email.id != user_id
            ):
                raise AppException(
                    status_code=409,
                    error_code=ERROR_CODE_CONFLICT,
                    detail="電子郵件已被使用",
                )
            update_payload["email"] = user_data.email

        # Hash and prepare password update
        if user_data.password is not None:
            update_payload["hashed_password"] = get_password_hash(user_data.password)

        # Prepare is_active update
        if user_data.is_active is not None:
            update_payload["is_active"] = user_data.is_active

        # If there is nothing to update, return current state
        if not update_payload:
            return UserResponse.model_validate(existing_user)

        updated_user: UserModel | None = await self.user_repo.update(
            user_id, update_payload
        )

        if updated_user is None:
            raise AppException(
                status_code=404,
                error_code=ERROR_CODE_NOT_FOUND,
                detail="使用者不存在",
            )

        return UserResponse.model_validate(updated_user)

    async def delete_user(self, user_id: int) -> bool:
        """Delete a user account by their primary key ID.

        Verifies that the user exists before attempting deletion. If the
        user is not found, raises a 404 exception. On successful deletion,
        returns ``True``.

        Args:
            user_id: The integer primary key of the user to delete.

        Returns:
            ``True`` if the user was successfully deleted.

        Raises:
            AppException: With HTTP 404 and ``ERROR_CODE_NOT_FOUND`` if no
                          user with the given ``user_id`` exists in the database.

        Examples:
            >>> result = await user_service.delete_user(user_id=1)
            >>> result
            True

            >>> await user_service.delete_user(user_id=999)
            # Raises AppException(status_code=404, error_code="NOT_FOUND", ...)
        """
        deleted: bool = await self.user_repo.delete(user_id)

        if not deleted:
            raise AppException(
                status_code=404,
                error_code=ERROR_CODE_NOT_FOUND,
                detail="使用者不存在",
            )

        return True
