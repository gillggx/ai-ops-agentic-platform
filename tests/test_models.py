"""
Unit tests for Ontology models.

本体层模型单元测试。
"""

import pytest

from app.ontology.models import User, UserRole, Event, EventType


class TestUserModel:
    """Tests for User model."""

    def test_user_creation(self):
        """Test creating a user."""
        user = User(
            username="testuser",
            email="test@example.com",
            hashed_password="hashed_pass",
        )
        assert user.username == "testuser"
        assert user.email == "test@example.com"
        assert user.is_active is True
        assert user.is_superuser is False

    def test_user_add_role(self):
        """Test adding role to user."""
        user = User(
            username="testuser",
            email="test@example.com",
            hashed_password="hashed_pass",
        )
        user.add_role(UserRole.ARCHITECT)
        assert user.has_role(UserRole.ARCHITECT)

    def test_user_remove_role(self):
        """Test removing role from user."""
        user = User(
            username="testuser",
            email="test@example.com",
            hashed_password="hashed_pass",
        )
        user.add_role(UserRole.BACKEND)
        user.remove_role(UserRole.BACKEND)
        assert not user.has_role(UserRole.BACKEND)

    def test_user_multiple_roles(self):
        """Test user with multiple roles."""
        user = User(
            username="testuser",
            email="test@example.com",
            hashed_password="hashed_pass",
        )
        user.add_role(UserRole.ARCHITECT)
        user.add_role(UserRole.BACKEND)
        assert user.has_role(UserRole.ARCHITECT)
        assert user.has_role(UserRole.BACKEND)

    def test_user_get_roles(self):
        """Test getting all user roles."""
        user = User(
            username="testuser",
            email="test@example.com",
            hashed_password="hashed_pass",
        )
        user.add_role(UserRole.QA)
        roles = user.get_roles()
        assert UserRole.QA.value in roles

    def test_user_repr(self):
        """Test user repr."""
        user = User(
            id=1,
            username="testuser",
            email="test@example.com",
            hashed_password="hashed_pass",
        )
        repr_str = repr(user)
        assert "testuser" in repr_str
        assert "test@example.com" in repr_str

    def test_user_str(self):
        """Test user str."""
        user = User(
            username="testuser",
            email="test@example.com",
            hashed_password="hashed_pass",
        )
        str_repr = str(user)
        assert "testuser" in str_repr
        assert "test@example.com" in str_repr


class TestEventModel:
    """Tests for Event model."""

    def test_event_type_creation(self):
        """Test creating event type."""
        event_type = EventType(
            name="SPC_OOC",
            description="Statistical Process Control Out of Control",
            attributes="{}",
        )
        assert event_type.name == "SPC_OOC"
        assert event_type.description == "Statistical Process Control Out of Control"

    def test_event_creation(self):
        """Test creating event."""
        event_type = EventType(
            name="SPC_OOC",
            description="Statistical Process Control Out of Control",
            attributes="{}",
        )
        event = Event(
            event_type_id=1,
            source="sensor_1",
            data='{"value": 100}',
        )
        assert event.source == "sensor_1"
        assert event.processed is False

    def test_event_type_repr(self):
        """Test event type repr."""
        event_type = EventType(
            id=1,
            name="SPC_OOC",
            description="Description",
            attributes="{}",
        )
        repr_str = repr(event_type)
        assert "SPC_OOC" in repr_str


class TestModelSerialization:
    """Tests for model serialization."""

    def test_user_to_dict(self):
        """Test converting user to dict."""
        user = User(
            id=1,
            username="testuser",
            email="test@example.com",
            hashed_password="hashed_pass",
        )
        user_dict = user.to_dict()
        assert user_dict["username"] == "testuser"
        assert user_dict["email"] == "test@example.com"
        assert "id" in user_dict

    def test_event_to_dict(self):
        """Test converting event to dict."""
        event = Event(
            id=1,
            event_type_id=1,
            source="sensor_1",
            data='{"value": 100}',
        )
        event_dict = event.to_dict()
        assert event_dict["source"] == "sensor_1"
        assert event_dict["event_type_id"] == 1
