## app/repositories/__init__.py
"""Repositories package for the FastAPI Backend Service.

This package exposes all repository classes used for data access throughout
the application. Repositories encapsulate all database query logic and
provide a clean interface between the service layer and the database layer.

Modules:
    user_repository: Defines :class:`UserRepository` for user data access operations.
    item_repository: Defines :class:`ItemRepository` for item data access operations.
"""

from app.repositories.user_repository import UserRepository
from app.repositories.item_repository import ItemRepository

__all__ = [
    "UserRepository",
    "ItemRepository",
]
