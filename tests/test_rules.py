"""
Unit tests for business rules engine.

业务规则引擎单元测试。
"""

import pytest

from app.ontology.rules import RuleEngine, UserValidator
from app.ontology.rules.validators import (
    PasswordStrengthRule,
    EmailFormatRule,
    UsernameFormatRule,
)


class TestPasswordStrengthRule:
    """Tests for PasswordStrengthRule."""

    def test_valid_password(self):
        """Test valid password."""
        rule = PasswordStrengthRule()
        is_valid, msg = rule.validate({"password": "SecurePass123!"})
        assert is_valid is True
        assert msg is None

    def test_short_password(self):
        """Test password too short."""
        rule = PasswordStrengthRule()
        is_valid, msg = rule.validate({"password": "Short1!"})
        assert is_valid is False
        assert "8 characters" in msg

    def test_no_uppercase(self):
        """Test password without uppercase."""
        rule = PasswordStrengthRule()
        is_valid, msg = rule.validate({"password": "lowercase123!"})
        assert is_valid is False
        assert "uppercase" in msg.lower()

    def test_no_number(self):
        """Test password without number."""
        rule = PasswordStrengthRule()
        is_valid, msg = rule.validate({"password": "NoNumber!"})
        assert is_valid is False
        assert "digit" in msg.lower()

    def test_no_special_char(self):
        """Test password without special character."""
        rule = PasswordStrengthRule()
        is_valid, msg = rule.validate({"password": "NoSpecial123"})
        assert is_valid is False
        assert "special" in msg.lower()


class TestEmailFormatRule:
    """Tests for EmailFormatRule."""

    def test_valid_email(self):
        """Test valid email."""
        rule = EmailFormatRule()
        is_valid, msg = rule.validate({"email": "test@example.com"})
        assert is_valid is True

    def test_invalid_email_no_at(self):
        """Test email without @."""
        rule = EmailFormatRule()
        is_valid, msg = rule.validate({"email": "testexample.com"})
        assert is_valid is False

    def test_invalid_email_no_domain(self):
        """Test email without domain."""
        rule = EmailFormatRule()
        is_valid, msg = rule.validate({"email": "test@"})
        assert is_valid is False

    def test_email_lowercase_transform(self):
        """Test email lowercase transformation."""
        rule = EmailFormatRule()
        result = rule.apply({"email": "TEST@EXAMPLE.COM"})
        assert result["email"] == "test@example.com"


class TestUsernameFormatRule:
    """Tests for UsernameFormatRule."""

    def test_valid_username(self):
        """Test valid username."""
        rule = UsernameFormatRule()
        is_valid, msg = rule.validate({"username": "user_name"})
        assert is_valid is True

    def test_username_too_short(self):
        """Test username too short."""
        rule = UsernameFormatRule()
        is_valid, msg = rule.validate({"username": "ab"})
        assert is_valid is False
        assert "3 characters" in msg

    def test_username_too_long(self):
        """Test username too long."""
        rule = UsernameFormatRule()
        long_username = "a" * 151
        is_valid, msg = rule.validate({"username": long_username})
        assert is_valid is False
        assert "150 characters" in msg

    def test_username_with_invalid_chars(self):
        """Test username with invalid characters."""
        rule = UsernameFormatRule()
        is_valid, msg = rule.validate({"username": "user@name"})
        assert is_valid is False

    def test_username_starting_with_number(self):
        """Test username starting with number."""
        rule = UsernameFormatRule()
        is_valid, msg = rule.validate({"username": "1username"})
        assert is_valid is False


class TestRuleEngine:
    """Tests for RuleEngine."""

    def test_engine_creation(self):
        """Test creating rule engine."""
        engine = RuleEngine()
        assert len(engine) == 0

    def test_register_rule(self):
        """Test registering rule."""
        engine = RuleEngine()
        rule = PasswordStrengthRule()
        engine.register_rule(rule, "password")
        assert len(engine) == 1

    def test_get_rule(self):
        """Test getting rule."""
        engine = RuleEngine()
        rule = EmailFormatRule()
        engine.register_rule(rule, "email")
        retrieved = engine.get_rule("email")
        assert retrieved is not None

    def test_list_all_rules(self):
        """Test listing all rules."""
        engine = RuleEngine()
        engine.register_rule(PasswordStrengthRule(), "password")
        engine.register_rule(EmailFormatRule(), "email")
        rules = engine.list_all_rules()
        assert len(rules) == 2

    def test_validate_with_rules(self):
        """Test validation with multiple rules."""
        engine = RuleEngine()
        engine.register_rule(PasswordStrengthRule(), "password")
        engine.register_rule(EmailFormatRule(), "email")
        
        data = {
            "password": "SecurePass123!",
            "email": "test@example.com",
        }
        is_valid, errors = engine.validate(data)
        assert is_valid is True
        assert len(errors) == 0

    def test_validate_with_errors(self):
        """Test validation with errors."""
        engine = RuleEngine()
        engine.register_rule(PasswordStrengthRule(), "password")
        
        data = {"password": "weak"}
        is_valid, errors = engine.validate(data)
        assert is_valid is False
        assert len(errors) > 0

    def test_stop_on_error(self):
        """Test stop on first error."""
        engine = RuleEngine()
        engine.register_rule(PasswordStrengthRule(), "password")
        engine.register_rule(EmailFormatRule(), "email")
        
        data = {"password": "weak", "email": "invalid"}
        is_valid, errors = engine.validate(data, stop_on_error=True)
        assert is_valid is False
        assert len(errors) == 1


class TestUserValidator:
    """Tests for UserValidator."""

    def test_validator_creation(self):
        """Test creating UserValidator."""
        validator = UserValidator()
        assert len(validator.engine) == 3  # 3 default rules

    def test_validate_user_creation(self):
        """Test validating user creation data."""
        validator = UserValidator()
        data = {
            "username": "newuser",
            "email": "new@example.com",
            "password": "SecurePass123!",
        }
        is_valid, errors = validator.validate_user_creation(data)
        assert is_valid is True

    def test_validate_invalid_user_creation(self):
        """Test validating invalid user creation."""
        validator = UserValidator()
        data = {
            "username": "ab",  # Too short
            "email": "invalid",  # Invalid email
            "password": "weak",  # Weak password
        }
        is_valid, errors = validator.validate_user_creation(data)
        assert is_valid is False
        assert len(errors) > 0

    def test_transform_user_data(self):
        """Test transforming user data."""
        validator = UserValidator()
        data = {
            "username": "  testuser  ",
            "email": "TEST@EXAMPLE.COM",
        }
        transformed = validator.transform_user_data(data)
        assert transformed["username"] == "testuser"
        assert transformed["email"] == "test@example.com"
