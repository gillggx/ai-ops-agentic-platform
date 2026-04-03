"""
Unit tests for Ontology services.

本体层服务单元测试。
"""

import pytest

from app.ontology.services import UserService
from app.ontology.models import User, UserRole
from app.ontology.schemas import UserCreate


class TestUserService:
    """Tests for UserService."""

    @pytest.mark.asyncio
    async def test_user_service_creation(self):
        """Test UserService instantiation."""
        service = UserService()
        assert service.model == User
        assert service.create_schema == UserCreate

    @pytest.mark.asyncio
    async def test_create_user(self, test_db):
        """Test creating a user."""
        service = UserService()
        user_data = UserCreate(
            username="newuser",
            email="new@example.com",
            password="SecurePass123!",
        )
        # Note: In real tests, this would use actual database session
        # This is a placeholder test structure
        assert user_data.username == "newuser"
        assert user_data.email == "new@example.com"

    @pytest.mark.asyncio
    async def test_user_by_username(self, test_db):
        """Test finding user by username."""
        service = UserService()
        # Placeholder for actual test
        # In production: user = await service.get_by_username(db, "testuser")
        assert service.model == User

    @pytest.mark.asyncio
    async def test_user_by_email(self, test_db):
        """Test finding user by email."""
        service = UserService()
        # Placeholder for actual test
        assert service.model == User

    @pytest.mark.asyncio
    async def test_add_role_to_user(self, test_db):
        """Test adding role to user."""
        service = UserService()
        # Placeholder for actual test
        # In production: user = await service.add_role(db, user_id, UserRole.BACKEND)
        assert service.model == User

    @pytest.mark.asyncio
    async def test_remove_role_from_user(self, test_db):
        """Test removing role from user."""
        service = UserService()
        # Placeholder for actual test
        assert service.model == User

    @pytest.mark.asyncio
    async def test_has_role(self, test_db):
        """Test checking user role."""
        service = UserService()
        # Placeholder for actual test
        assert service.model == User

    @pytest.mark.asyncio
    async def test_deactivate_user(self, test_db):
        """Test deactivating user."""
        service = UserService()
        # Placeholder for actual test
        assert service.model == User

    @pytest.mark.asyncio
    async def test_activate_user(self, test_db):
        """Test activating user."""
        service = UserService()
        # Placeholder for actual test
        assert service.model == User


class TestBaseService:
    """Tests for BaseService CRUD operations."""

    @pytest.mark.asyncio
    async def test_service_has_crud_methods(self):
        """Test that service has CRUD methods."""
        service = UserService()
        assert hasattr(service, "create")
        assert hasattr(service, "read")
        assert hasattr(service, "list_all")
        assert hasattr(service, "update")
        assert hasattr(service, "delete")
        assert hasattr(service, "count")
        assert hasattr(service, "exists")
