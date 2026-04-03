## app/repositories/user_repository.py
"""User repository module for the FastAPI Backend Service.

This module provides the ``UserRepository`` class, which encapsulates all
database query logic for user-related operations. It acts as the data access
layer between the service layer and the database, using SQLAlchemy 2.0
async APIs exclusively.
"""

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import UserModel


class UserRepository:
    """Repository class for user data access operations.

    Encapsulates all SQLAlchemy async queries related to the ``users`` table.
    All methods are ``async`` and must be awaited by the caller. Instances
    are created per-request and receive an injected ``AsyncSession``.

    Attributes:
        db: The async database session used for all queries in this repository.

    Examples:
        Typical usage within a service::

            async def example(db: AsyncSession):
                repo = UserRepository(db)
                user = await repo.get_by_id(1)
    """

    def __init__(self, db: AsyncSession) -> None:
        """Initialize the UserRepository with an async database session.

        Args:
            db: An ``AsyncSession`` instance provided via FastAPI dependency injection.
        """
        self.db: AsyncSession = db

    async def get_by_id(self, user_id: int) -> Optional[UserModel]:
        """Retrieve a user by their primary key ID.

        Args:
            user_id: The integer primary key of the user to look up.

        Returns:
            The ``UserModel`` instance if found, otherwise ``None``.

        Examples:
            >>> user = await repo.get_by_id(1)
            >>> if user is None:
            ...     raise AppException(404, ERROR_CODE_NOT_FOUND, "使用者不存在")
        """
        statement = select(UserModel).where(UserModel.id == user_id)
        result = await self.db.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> Optional[UserModel]:
        """Retrieve a user by their unique username.

        Args:
            username: The unique username string to search for.

        Returns:
            The ``UserModel`` instance if found, otherwise ``None``.

        Examples:
            >>> user = await repo.get_by_username("alice")
            >>> if user is None:
            ...     raise AppException(404, ERROR_CODE_NOT_FOUND, "使用者不存在")
        """
        statement = select(UserModel).where(UserModel.username == username)
        result = await self.db.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> Optional[UserModel]:
        """Retrieve a user by their unique email address.

        Args:
            email: The unique email address string to search for.

        Returns:
            The ``UserModel`` instance if found, otherwise ``None``.

        Examples:
            >>> user = await repo.get_by_email("alice@example.com")
            >>> if user is not None:
            ...     raise AppException(409, ERROR_CODE_CONFLICT, "電子郵件已被使用")
        """
        statement = select(UserModel).where(UserModel.email == email)
        result = await self.db.execute(statement)
        return result.scalar_one_or_none()

    async def get_all(self, skip: int = 0, limit: int = 10) -> List[UserModel]:
        """Retrieve a paginated list of all users.

        Args:
            skip: The number of records to skip (offset). Defaults to ``0``.
            limit: The maximum number of records to return. Defaults to ``10``.

        Returns:
            A list of ``UserModel`` instances. Returns an empty list if no
            users are found within the given range.

        Examples:
            >>> users = await repo.get_all(skip=0, limit=20)
            >>> len(users)
            20
        """
        statement = (
            select(UserModel)
            .order_by(UserModel.id)
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(statement)
        return list(result.scalars().all())

    async def create(self, user_data: dict) -> UserModel:
        """Create and persist a new user record.

        Constructs a new ``UserModel`` instance from the provided dictionary,
        adds it to the session, commits the transaction, and refreshes the
        instance to populate any server-generated fields (e.g. ``id``,
        ``created_at``).

        Args:
            user_data: A dictionary containing the fields for the new user.
                       Expected keys: ``username``, ``email``, ``hashed_password``,
                       and optionally ``is_active``, ``is_superuser``.

        Returns:
            The newly created and persisted ``UserModel`` instance with all
            fields populated (including auto-generated ``id`` and timestamps).

        Examples:
            >>> new_user = await repo.create({
            ...     "username": "alice",
            ...     "email": "alice@example.com",
            ...     "hashed_password": "$2b$12$...",
            ... })
            >>> new_user.id
            1
        """
        db_user = UserModel(**user_data)
        self.db.add(db_user)
        await self.db.commit()
        await self.db.refresh(db_user)
        return db_user

    async def update(
        self, user_id: int, user_data: dict
    ) -> Optional[UserModel]:
        """Update an existing user record with the provided field values.

        Retrieves the user by ``user_id``, applies all key-value pairs from
        ``user_data`` to the model instance, commits the transaction, and
        refreshes the instance to reflect any database-level changes.

        Args:
            user_id: The integer primary key of the user to update.
            user_data: A dictionary of field names and their new values.
                       Only the provided fields are updated; others remain unchanged.
                       Typical keys: ``username``, ``email``, ``hashed_password``,
                       ``is_active``.

        Returns:
            The updated ``UserModel`` instance if the user was found and
            successfully updated, otherwise ``None``.

        Examples:
            >>> updated = await repo.update(1, {"username": "alice_v2"})
            >>> if updated is None:
            ...     raise AppException(404, ERROR_CODE_NOT_FOUND, "使用者不存在")
            >>> updated.username
            'alice_v2'
        """
        db_user = await self.get_by_id(user_id)
        if db_user is None:
            return None

        for field, value in user_data.items():
            setattr(db_user, field, value)

        self.db.add(db_user)
        await self.db.commit()
        await self.db.refresh(db_user)
        return db_user

    async def delete(self, user_id: int) -> bool:
        """Delete a user record by their primary key ID.

        Retrieves the user by ``user_id`` and removes the record from the
        database. If no user with the given ID exists, returns ``False``
        without raising an exception.

        Args:
            user_id: The integer primary key of the user to delete.

        Returns:
            ``True`` if the user was found and successfully deleted,
            ``False`` if no user with the given ID was found.

        Examples:
            >>> deleted = await repo.delete(1)
            >>> if not deleted:
            ...     raise AppException(404, ERROR_CODE_NOT_FOUND, "使用者不存在")
        """
        db_user = await self.get_by_id(user_id)
        if db_user is None:
            return False

        await self.db.delete(db_user)
        await self.db.commit()
        return True
