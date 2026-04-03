"""
Specific business rule validators.

具体的业务规则验证器。
"""

import re
from typing import Any, Dict, Optional

from .engine import Rule


class PasswordStrengthRule(Rule):
    """
    Validate password strength.
    
    密码强度规则。
    
    Requirements:
    - Minimum 8 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one digit
    - At least one special character
    """

    def validate(self, data: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """Validate password strength."""
        password = data.get("password", "")

        if not password:
            return False, "Password is required"

        if len(password) < 8:
            return False, "Password must be at least 8 characters"

        if not re.search(r"[A-Z]", password):
            return False, "Password must contain at least one uppercase letter"

        if not re.search(r"[a-z]", password):
            return False, "Password must contain at least one lowercase letter"

        if not re.search(r"\d", password):
            return False, "Password must contain at least one digit"

        if not re.search(r"[!@#$%^&*()_+\-=\[\]{};:'\",.<>?/\\|`~]", password):
            return False, "Password must contain at least one special character"

        return True, None

    def apply(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Apply the rule (no transformation needed)."""
        return data


class EmailFormatRule(Rule):
    """
    Validate email format.
    
    电子邮件格式规则。
    """

    def validate(self, data: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """Validate email format."""
        email = data.get("email", "")

        if not email:
            return False, "Email is required"

        # Simple email regex
        pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        if not re.match(pattern, email):
            return False, "Invalid email format"

        return True, None

    def apply(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Apply the rule (lowercase email)."""
        data = data.copy()
        if "email" in data:
            data["email"] = data["email"].lower()
        return data


class UsernameFormatRule(Rule):
    """
    Validate username format.
    
    用户名格式规则。
    
    Requirements:
    - 3-150 characters
    - Alphanumeric and underscore only
    - Cannot start with digit
    """

    def validate(self, data: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """Validate username format."""
        username = data.get("username", "")

        if not username:
            return False, "Username is required"

        if len(username) < 3:
            return False, "Username must be at least 3 characters"

        if len(username) > 150:
            return False, "Username must be at most 150 characters"

        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", username):
            return False, "Username can only contain letters, digits, and underscores, and cannot start with a digit"

        return True, None

    def apply(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Apply the rule (strip whitespace)."""
        data = data.copy()
        if "username" in data:
            data["username"] = data["username"].strip()
        return data


class UniqueUsernameRule(Rule):
    """
    Validate unique username (requires external data).
    
    唯一用户名规则。
    
    This rule checks if username is unique.
    It requires 'existing_usernames' in data context.
    """

    def validate(self, data: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """Validate username uniqueness."""
        username = data.get("username", "")
        existing = data.get("existing_usernames", [])

        if username in existing:
            return False, f"Username '{username}' is already taken"

        return True, None

    def apply(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Apply the rule (no transformation)."""
        return data


class UniqueEmailRule(Rule):
    """
    Validate unique email (requires external data).
    
    唯一电子邮件规则。
    """

    def validate(self, data: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """Validate email uniqueness."""
        email = data.get("email", "").lower()
        existing = [e.lower() for e in data.get("existing_emails", [])]

        if email in existing:
            return False, f"Email '{email}' is already registered"

        return True, None

    def apply(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Apply the rule (no transformation)."""
        return data


class UserValidator:
    """
    Validator for user-related business rules.
    
    用户验证器。
    
    Usage:
        validator = UserValidator()
        is_valid, errors = validator.validate_user_creation({
            "username": "john_doe",
            "email": "john@example.com",
            "password": "SecurePass123!"
        })
    """

    def __init__(self):
        """Initialize user validator with default rules."""
        from .engine import RuleEngine

        self.engine = RuleEngine()
        self._setup_rules()

    def _setup_rules(self) -> None:
        """Set up default validation rules."""
        self.engine.register_rule(UsernameFormatRule(), "username_format")
        self.engine.register_rule(EmailFormatRule(), "email_format")
        self.engine.register_rule(PasswordStrengthRule(), "password_strength")

    def validate_user_creation(self, data: Dict[str, Any]) -> tuple[bool, list]:
        """
        Validate user creation data.
        
        Args:
            data: Dict - User data to validate
        
        Returns:
            tuple: (is_valid, error_messages)
        
        验证用户创建数据。
        """
        return self.engine.validate(data)

    def validate_user_update(self, data: Dict[str, Any]) -> tuple[bool, list]:
        """
        Validate user update data.
        
        Args:
            data: Dict - User data to validate
        
        Returns:
            tuple: (is_valid, error_messages)
        
        验证用户更新数据。
        """
        # For updates, some fields may be optional
        is_valid, errors = self.engine.validate(data)
        return is_valid, errors

    def transform_user_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply rules to transform user data.
        
        Args:
            data: Dict - User data
        
        Returns:
            Dict - Transformed data
        
        转换用户数据。
        """
        return self.engine.apply_rules(data)
