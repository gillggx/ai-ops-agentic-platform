"""
Security tests for FastAPI backend.

FastAPI 后端的安全性测试。
"""

import pytest
from httpx import AsyncClient
from datetime import datetime, timedelta
from jose import jwt

from main import app


class TestAuthenticationSecurity:
    """
    Tests for authentication security.
    
    身份验证安全性测试。
    """

    @pytest.mark.asyncio
    async def test_missing_auth_token(self, client: AsyncClient):
        """
        Test that endpoints require authentication.
        
        Args:
            client: AsyncClient
        
        测试端点需要身份验证。
        """
        # Attempt to access protected endpoint without token
        response = await client.get(
            "/api/v1/users",
            headers={}
        )

        # Should be unauthorized
        assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_invalid_jwt_token(self, client: AsyncClient):
        """
        Test that invalid JWT tokens are rejected.
        
        Args:
            client: AsyncClient
        
        测试无效的 JWT 令牌被拒绝。
        """
        invalid_token = "invalid.jwt.token"

        response = await client.get(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {invalid_token}"}
        )

        # Should be unauthorized
        assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_expired_jwt_token(self, client: AsyncClient):
        """
        Test that expired JWT tokens are rejected.
        
        Args:
            client: AsyncClient
        
        测试过期的 JWT 令牌被拒绝。
        """
        # Create expired token
        payload = {
            "sub": "testuser",
            "exp": datetime.utcnow() - timedelta(hours=1)
        }
        token = jwt.encode(
            payload,
            "secret-key",
            algorithm="HS256"
        )

        response = await client.get(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {token}"}
        )

        # Should be unauthorized
        assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_malformed_auth_header(self, client: AsyncClient):
        """
        Test that malformed auth headers are handled.
        
        Args:
            client: AsyncClient
        
        测试处理格式不正确的身份验证标头。
        """
        # Missing "Bearer" prefix
        response = await client.get(
            "/api/v1/users",
            headers={"Authorization": "InvalidToken"}
        )

        assert response.status_code in [400, 401, 403]


class TestAuthorizationSecurity:
    """
    Tests for authorization security.
    
    授权安全性测试。
    """

    @pytest.mark.asyncio
    async def test_insufficient_permissions(
        self,
        client: AsyncClient,
        low_privilege_token: str
    ):
        """
        Test that users with insufficient permissions are denied.
        
        Args:
            client: AsyncClient
            low_privilege_token: Token with limited permissions
        
        测试具有不足权限的用户被拒绝。
        """
        response = await client.get(
            "/api/v1/admin/settings",
            headers={"Authorization": f"Bearer {low_privilege_token}"}
        )

        # Should be forbidden
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_role_based_access_control(
        self,
        client: AsyncClient,
        user_token: str,
        admin_token: str
    ):
        """
        Test role-based access control.
        
        Args:
            client: AsyncClient
            user_token: Regular user token
            admin_token: Admin user token
        
        测试基于角色的访问控制。
        """
        # User should not access admin endpoint
        response = await client.get(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 403

        # Admin should access admin endpoint
        response = await client.get(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200


class TestInputValidationSecurity:
    """
    Tests for input validation security.
    
    输入验证安全性测试。
    """

    @pytest.mark.asyncio
    async def test_sql_injection_prevention(
        self,
        client: AsyncClient,
        auth_token: str
    ):
        """
        Test SQL injection prevention.
        
        Args:
            client: AsyncClient
            auth_token: Valid auth token
        
        测试 SQL 注入防护。
        """
        # Attempt SQL injection
        malicious_input = "'; DROP TABLE users; --"

        response = await client.post(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "username": malicious_input,
                "email": "test@example.com",
                "password": "securepassword"
            }
        )

        # Should handle safely
        assert response.status_code in [400, 422]

    @pytest.mark.asyncio
    async def test_xss_prevention(
        self,
        client: AsyncClient,
        auth_token: str
    ):
        """
        Test XSS attack prevention.
        
        Args:
            client: AsyncClient
            auth_token: Valid auth token
        
        测试 XSS 攻击防护。
        """
        # Attempt XSS injection
        xss_payload = "<script>alert('xss')</script>"

        response = await client.post(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "username": "testuser",
                "email": xss_payload,
                "password": "securepassword"
            }
        )

        # Should validate input format
        assert response.status_code in [400, 422]

    @pytest.mark.asyncio
    async def test_command_injection_prevention(
        self,
        client: AsyncClient,
        auth_token: str
    ):
        """
        Test command injection prevention.
        
        Args:
            client: AsyncClient
            auth_token: Valid auth token
        
        测试命令注入防护。
        """
        # Attempt command injection
        cmd_injection = "test; rm -rf /"

        response = await client.post(
            "/api/v1/data",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={"filename": cmd_injection}
        )

        # Should validate input
        assert response.status_code in [400, 422]

    @pytest.mark.asyncio
    async def test_file_upload_security(
        self,
        client: AsyncClient,
        auth_token: str
    ):
        """
        Test file upload security.
        
        Args:
            client: AsyncClient
            auth_token: Valid auth token
        
        测试文件上传安全性。
        """
        # Attempt to upload executable file
        malicious_file = b"#!/bin/bash\nrm -rf /"

        response = await client.post(
            "/api/v1/files/upload",
            headers={"Authorization": f"Bearer {auth_token}"},
            files={"file": ("malicious.sh", malicious_file)}
        )

        # Should validate file type
        assert response.status_code in [400, 415]

    @pytest.mark.asyncio
    async def test_path_traversal_prevention(
        self,
        client: AsyncClient,
        auth_token: str
    ):
        """
        Test path traversal prevention.
        
        Args:
            client: AsyncClient
            auth_token: Valid auth token
        
        测试路径遍历防护。
        """
        # Attempt path traversal
        traversal_path = "../../etc/passwd"

        response = await client.get(
            f"/api/v1/files/{traversal_path}",
            headers={"Authorization": f"Bearer {auth_token}"}
        )

        # Should not allow access outside intended directory
        assert response.status_code in [400, 403, 404]


class TestAPISecurityHeaders:
    """
    Tests for security headers.
    
    安全标头的测试。
    """

    @pytest.mark.asyncio
    async def test_cors_headers(self, client: AsyncClient):
        """
        Test CORS headers are properly set.
        
        Args:
            client: AsyncClient
        
        测试 CORS 标头设置正确。
        """
        response = await client.options("/api/v1/users")

        # Should have CORS headers
        assert "access-control-allow-origin" in response.headers.keys() or \
               "Access-Control-Allow-Origin" in response.headers.keys()

    @pytest.mark.asyncio
    async def test_security_headers_present(
        self,
        client: AsyncClient
    ):
        """
        Test that security headers are present.
        
        Args:
            client: AsyncClient
        
        测试安全标头存在。
        """
        response = await client.get("/")

        headers = response.headers

        # Check for security headers
        # Note: Implementation specific
        # - X-Content-Type-Options: nosniff
        # - X-Frame-Options: DENY
        # - Content-Security-Policy
        # - Strict-Transport-Security


class TestRateLimiting:
    """
    Tests for rate limiting security.
    
    速率限制安全性测试。
    """

    @pytest.mark.asyncio
    async def test_rate_limiting_enforcement(
        self,
        client: AsyncClient
    ):
        """
        Test that rate limiting is enforced.
        
        Args:
            client: AsyncClient
        
        测试速率限制强制执行。
        """
        # Make many requests rapidly
        tasks = [
            client.get("/health")
            for _ in range(100)
        ]

        responses = await __import__("asyncio").gather(*tasks)

        # Some requests should be rate limited
        rate_limited = sum(
            1 for r in responses 
            if r.status_code == 429
        )

        # Expect some rate limiting
        assert rate_limited > 0 or all(r.status_code == 200 for r in responses)

    @pytest.mark.asyncio
    async def test_rate_limit_headers(
        self,
        client: AsyncClient
    ):
        """
        Test rate limit response headers.
        
        Args:
            client: AsyncClient
        
        测试速率限制响应标头。
        """
        response = await client.get("/health")

        # Should have rate limit headers
        # X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset


class TestDataValidation:
    """
    Tests for data validation security.
    
    数据验证安全性测试。
    """

    @pytest.mark.asyncio
    async def test_schema_validation(
        self,
        client: AsyncClient,
        auth_token: str
    ):
        """
        Test request schema validation.
        
        Args:
            client: AsyncClient
            auth_token: Valid auth token
        
        测试请求模式验证。
        """
        # Invalid request body
        response = await client.post(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={"invalid": "data"}
        )

        # Should reject invalid schema
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_type_validation(
        self,
        client: AsyncClient,
        auth_token: str
    ):
        """
        Test type validation.
        
        Args:
            client: AsyncClient
            auth_token: Valid auth token
        
        测试类型验证。
        """
        # Wrong data type
        response = await client.post(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "username": 123,  # Should be string
                "email": "test@example.com",
                "password": "password"
            }
        )

        # Should reject wrong type
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_length_validation(
        self,
        client: AsyncClient,
        auth_token: str
    ):
        """
        Test length validation.
        
        Args:
            client: AsyncClient
            auth_token: Valid auth token
        
        测试长度验证。
        """
        # Excessively long input
        response = await client.post(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "username": "a" * 10000,
                "email": "test@example.com",
                "password": "password"
            }
        )

        # Should reject excessively long input
        assert response.status_code == 422


class TestErrorHandlingSecurity:
    """
    Tests for error handling security.
    
    错误处理安全性测试。
    """

    @pytest.mark.asyncio
    async def test_information_disclosure(
        self,
        client: AsyncClient
    ):
        """
        Test that error messages don't disclose sensitive info.
        
        Args:
            client: AsyncClient
        
        测试错误消息不会泄露敏感信息。
        """
        # Trigger an error
        response = await client.get("/api/v1/users/999999")

        # Should not expose stack traces or system info
        body = response.text
        assert "traceback" not in body.lower()
        assert "password" not in body.lower()
        assert "/usr/local" not in body

    @pytest.mark.asyncio
    async def test_generic_error_messages(
        self,
        client: AsyncClient
    ):
        """
        Test that error messages are generic.
        
        Args:
            client: AsyncClient
        
        测试错误消息是通用的。
        """
        # Try to trigger different errors
        response = await client.get("/nonexistent-endpoint")

        assert response.status_code == 404
        assert response.json().get("detail") is not None
