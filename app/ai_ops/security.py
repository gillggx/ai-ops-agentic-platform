"""
Security layer for AI Ops - JWT and RBAC.

安全層 - JWT 和 RBAC。
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set


class JWTManager:
    """
    JWT token management.
    
    JWT 令牌管理。
    
    Manages:
    - Token generation
    - Token validation
    - Token refresh
    - Token revocation
    """

    def __init__(self, secret_key: str = "your-secret-key"):
        """
        Initialize JWT manager.
        
        Args:
            secret_key: str - Secret key for signing
        
        初始化 JWT 管理器。
        """
        self.secret_key = secret_key
        self._revoked_tokens: Set[str] = set()

    def generate_token(
        self,
        user_id: str,
        expires_in: int = 3600,
        **claims: Any,
    ) -> str:
        """
        Generate JWT token.
        
        Args:
            user_id: str - User identifier
            expires_in: int - Token expiry in seconds (default: 1 hour)
            **claims: Additional claims
        
        Returns:
            str - JWT token
        
        生成 JWT 令牌。
        """
        import json
        import base64

        header = {"typ": "JWT", "alg": "HS256"}
        payload = {
            "sub": user_id,
            "iat": datetime.utcnow().timestamp(),
            "exp": (datetime.utcnow() + timedelta(seconds=expires_in)).timestamp(),
            **claims,
        }

        # Mock JWT encoding (real implementation would use PyJWT)
        encoded = base64.b64encode(json.dumps(payload).encode()).decode()
        return f"{base64.b64encode(json.dumps(header).encode()).decode()}.{encoded}.signature"

    def validate_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Validate JWT token.
        
        Args:
            token: str - JWT token
        
        Returns:
            Dict or None - Token claims or None if invalid
        
        驗證 JWT 令牌。
        """
        if token in self._revoked_tokens:
            return None

        try:
            # Mock JWT decoding
            parts = token.split(".")
            if len(parts) != 3:
                return None

            import json
            import base64

            payload = json.loads(base64.b64decode(parts[1]))

            # Check expiration
            if payload.get("exp", 0) < datetime.utcnow().timestamp():
                return None

            return payload

        except Exception:
            return None

    def revoke_token(self, token: str) -> None:
        """
        Revoke a token.
        
        Args:
            token: str - Token to revoke
        
        撤銷令牌。
        """
        self._revoked_tokens.add(token)

    def refresh_token(
        self,
        token: str,
        expires_in: int = 3600,
    ) -> Optional[str]:
        """
        Refresh a token.
        
        Args:
            token: str - Current token
            expires_in: int - New expiry
        
        Returns:
            str or None - New token or None if invalid
        
        刷新令牌。
        """
        claims = self.validate_token(token)
        if not claims:
            return None

        user_id = claims.get("sub")
        return self.generate_token(user_id, expires_in=expires_in)

    def __repr__(self) -> str:
        """Return detailed representation."""
        return f"JWTManager(revoked_tokens={len(self._revoked_tokens)})"


class RBACManager:
    """
    Role-Based Access Control manager.
    
    基於角色的訪問控制管理器。
    
    Manages:
    - Roles and permissions
    - User role assignments
    - Permission checking
    - Access control policies
    """

    def __init__(self):
        """Initialize RBAC manager."""
        self._roles: Dict[str, Set[str]] = {}
        self._user_roles: Dict[str, Set[str]] = {}
        self._setup_default_roles()

    def _setup_default_roles(self) -> None:
        """Set up default roles."""
        self._roles = {
            "admin": {"read", "write", "delete", "manage_users", "manage_roles"},
            "architect": {"read", "write", "delete", "design"},
            "backend": {"read", "write", "delete"},
            "devops": {"read", "deploy", "monitor"},
            "qa": {"read", "test"},
            "user": {"read"},
        }

    def create_role(
        self,
        role_name: str,
        permissions: Set[str],
    ) -> None:
        """
        Create a new role.
        
        Args:
            role_name: str - Role name
            permissions: Set[str] - Permissions
        
        創建新角色。
        """
        self._roles[role_name] = permissions.copy()

    def assign_role(
        self,
        user_id: str,
        role_name: str,
    ) -> bool:
        """
        Assign a role to user.
        
        Args:
            user_id: str - User ID
            role_name: str - Role name
        
        Returns:
            bool - True if assigned, False if role not found
        
        為用戶分配角色。
        """
        if role_name not in self._roles:
            return False

        if user_id not in self._user_roles:
            self._user_roles[user_id] = set()

        self._user_roles[user_id].add(role_name)
        return True

    def remove_role(
        self,
        user_id: str,
        role_name: str,
    ) -> bool:
        """
        Remove a role from user.
        
        Args:
            user_id: str - User ID
            role_name: str - Role name
        
        Returns:
            bool - True if removed, False if not found
        
        從用戶移除角色。
        """
        if user_id not in self._user_roles:
            return False

        return bool(self._user_roles[user_id].discard(role_name))

    def check_permission(
        self,
        user_id: str,
        permission: str,
    ) -> bool:
        """
        Check if user has permission.
        
        Args:
            user_id: str - User ID
            permission: str - Permission to check
        
        Returns:
            bool - True if user has permission
        
        檢查用戶是否有權限。
        """
        if user_id not in self._user_roles:
            return False

        for role_name in self._user_roles[user_id]:
            if permission in self._roles.get(role_name, set()):
                return True

        return False

    def get_user_permissions(self, user_id: str) -> Set[str]:
        """
        Get all permissions for a user.
        
        Args:
            user_id: str - User ID
        
        Returns:
            Set[str] - All permissions
        
        獲取用戶的所有權限。
        """
        permissions = set()

        for role_name in self._user_roles.get(user_id, set()):
            permissions.update(self._roles.get(role_name, set()))

        return permissions

    def __repr__(self) -> str:
        """Return detailed representation."""
        return f"RBACManager(roles={len(self._roles)}, users={len(self._user_roles)})"
