## app/services/__init__.py
"""Services package for the FastAPI Backend Service.

This package exposes all service classes used for business logic throughout
the application. Services coordinate between the router layer and the
repository layer, enforcing business rules and handling domain-specific logic.

Modules:
    auth_service: Defines :class:`AuthService` for authentication and token management.
    user_service: Defines :class:`UserService` for user management business logic.
    item_service: Defines :class:`ItemService` for item management business logic.
"""

from app.services.auth_service import AuthService
from app.services.user_service import UserService
from app.services.item_service import ItemService

__all__ = [
    "AuthService",
    "UserService",
    "ItemService",
]
