"""Integration tests for authentication endpoints.

Covers:
- POST /api/v1/auth/login   — success, wrong password, user not found
- GET  /api/v1/auth/me      — success, unauthorised (missing / invalid token)
"""

import pytest
from httpx import AsyncClient

from app.models.user import UserModel
from tests.conftest import TEST_PASSWORD, TEST_USERNAME

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# POST /api/v1/auth/login
# ---------------------------------------------------------------------------


async def test_login_success(client: AsyncClient, test_user: UserModel) -> None:
    """Valid credentials return HTTP 200 with a JWT access token."""
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": TEST_USERNAME, "password": TEST_PASSWORD},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert "access_token" in body["data"]
    assert body["data"]["token_type"] == "bearer"


async def test_login_wrong_password(client: AsyncClient, test_user: UserModel) -> None:
    """Wrong password returns HTTP 401."""
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": TEST_USERNAME, "password": "wrongpassword"},
    )
    assert response.status_code == 401
    body = response.json()
    assert body["status"] == "error"
    assert body["error_code"] == "UNAUTHORIZED"


async def test_login_user_not_found(client: AsyncClient) -> None:
    """Non-existent username returns HTTP 401."""
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "nonexistent", "password": "anypassword"},
    )
    assert response.status_code == 401
    assert response.json()["status"] == "error"


async def test_login_missing_fields(client: AsyncClient) -> None:
    """Missing required fields returns HTTP 422."""
    response = await client.post("/api/v1/auth/login", json={})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/auth/me
# ---------------------------------------------------------------------------


async def test_get_me_success(
    client: AsyncClient,
    test_user: UserModel,
    auth_headers: dict,
) -> None:
    """Valid Bearer token returns the current user's profile."""
    response = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["data"]["username"] == TEST_USERNAME
    assert body["data"]["email"] == test_user.email


async def test_get_me_unauthorized_no_token(client: AsyncClient) -> None:
    """Missing token returns HTTP 401."""
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401


async def test_get_me_invalid_token(client: AsyncClient) -> None:
    """Malformed token returns HTTP 401."""
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer this.is.not.a.valid.token"},
    )
    assert response.status_code == 401
