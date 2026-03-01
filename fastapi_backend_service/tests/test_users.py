"""Integration tests for user management endpoints.

Covers:
- GET    /api/v1/users          — list users
- POST   /api/v1/users          — create user (success, duplicate username, duplicate email)
- GET    /api/v1/users/{id}     — get user (success, not found)
- PUT    /api/v1/users/{id}     — update user (success, forbidden, not found)
- DELETE /api/v1/users/{id}     — delete user (success, forbidden)
"""

import pytest
from httpx import AsyncClient

from app.models.user import UserModel
from tests.conftest import TEST_EMAIL, TEST_USERNAME

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# GET /api/v1/users
# ---------------------------------------------------------------------------


async def test_get_users(client: AsyncClient, test_user: UserModel) -> None:
    """Returns a paginated list of users."""
    response = await client.get("/api/v1/users/")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert isinstance(body["data"], list)


async def test_get_users_pagination(client: AsyncClient, test_user: UserModel) -> None:
    """Pagination parameters are respected."""
    response = await client.get("/api/v1/users/?skip=0&limit=1")
    assert response.status_code == 200
    assert len(response.json()["data"]) <= 1


# ---------------------------------------------------------------------------
# POST /api/v1/users
# ---------------------------------------------------------------------------


async def test_create_user_success(client: AsyncClient) -> None:
    """Creating a new user returns HTTP 201 with user data."""
    response = await client.post(
        "/api/v1/users/",
        json={
            "username": "newuser",
            "email": "newuser@example.com",
            "password": "password123",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "success"
    assert body["data"]["username"] == "newuser"
    assert "hashed_password" not in body["data"]


async def test_create_user_duplicate_username(
    client: AsyncClient,
    test_user: UserModel,
) -> None:
    """Creating a user with an existing username returns HTTP 409."""
    response = await client.post(
        "/api/v1/users/",
        json={
            "username": TEST_USERNAME,
            "email": "other@example.com",
            "password": "password123",
        },
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "CONFLICT"


async def test_create_user_duplicate_email(
    client: AsyncClient,
    test_user: UserModel,
) -> None:
    """Creating a user with an existing email returns HTTP 409."""
    response = await client.post(
        "/api/v1/users/",
        json={
            "username": "otherusername",
            "email": TEST_EMAIL,
            "password": "password123",
        },
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "CONFLICT"


async def test_create_user_short_password(client: AsyncClient) -> None:
    """Password shorter than 6 characters returns HTTP 422."""
    response = await client.post(
        "/api/v1/users/",
        json={"username": "newuser2", "email": "new2@example.com", "password": "abc"},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/users/{user_id}
# ---------------------------------------------------------------------------


async def test_get_user_by_id(client: AsyncClient, test_user: UserModel) -> None:
    """Returns the correct user by ID."""
    response = await client.get(f"/api/v1/users/{test_user.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["id"] == test_user.id
    assert body["data"]["username"] == TEST_USERNAME


async def test_get_user_not_found(client: AsyncClient) -> None:
    """Non-existent user ID returns HTTP 404."""
    response = await client.get("/api/v1/users/99999")
    assert response.status_code == 404
    assert response.json()["error_code"] == "NOT_FOUND"


# ---------------------------------------------------------------------------
# PUT /api/v1/users/{user_id}
# ---------------------------------------------------------------------------


async def test_update_user_success(
    client: AsyncClient,
    test_user: UserModel,
    auth_headers: dict,
) -> None:
    """Owner can update their own account."""
    response = await client.put(
        f"/api/v1/users/{test_user.id}",
        json={"username": "updatedusername"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["data"]["username"] == "updatedusername"


async def test_update_user_forbidden(
    client: AsyncClient,
    test_user: UserModel,
    superuser: UserModel,
) -> None:
    """A non-owner, non-superuser cannot update another user's account."""
    from app.core.security import create_access_token

    other_token = create_access_token(data={"sub": "admin"})
    # Create a third user that is NOT superuser
    third_user_response = await client.post(
        "/api/v1/users/",
        json={
            "username": "thirduser",
            "email": "third@example.com",
            "password": "password123",
        },
    )
    third_user_id = third_user_response.json()["data"]["id"]

    # test_user tries to update the third user — should be forbidden
    response = await client.put(
        f"/api/v1/users/{third_user_id}",
        json={"username": "hackedname"},
        headers={"Authorization": f"Bearer {create_access_token(data={'sub': TEST_USERNAME})}"},
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "FORBIDDEN"


async def test_update_user_unauthenticated(
    client: AsyncClient,
    test_user: UserModel,
) -> None:
    """Update without a token returns HTTP 401."""
    response = await client.put(
        f"/api/v1/users/{test_user.id}",
        json={"username": "notoken"},
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# DELETE /api/v1/users/{user_id}
# ---------------------------------------------------------------------------


async def test_delete_user_success(
    client: AsyncClient,
    db_session,
    auth_headers: dict,
) -> None:
    """Owner can delete their own account."""
    from app.core.security import create_access_token, get_password_hash
    from app.models.user import UserModel as UM

    # Create a disposable user
    disposable = UM(
        username="disposable",
        email="disposable@example.com",
        hashed_password=get_password_hash("password123"),
        is_active=True,
        is_superuser=False,
    )
    db_session.add(disposable)
    await db_session.commit()
    await db_session.refresh(disposable)

    token = create_access_token(data={"sub": "disposable"})
    response = await client.delete(
        f"/api/v1/users/{disposable.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "success"


async def test_delete_user_forbidden(
    client: AsyncClient,
    test_user: UserModel,
    superuser: UserModel,
) -> None:
    """A non-owner, non-superuser cannot delete another user."""
    from app.core.security import create_access_token

    # Create a target user
    target_response = await client.post(
        "/api/v1/users/",
        json={
            "username": "target_del",
            "email": "target_del@example.com",
            "password": "password123",
        },
    )
    target_id = target_response.json()["data"]["id"]

    response = await client.delete(
        f"/api/v1/users/{target_id}",
        headers={"Authorization": f"Bearer {create_access_token(data={'sub': TEST_USERNAME})}"},
    )
    assert response.status_code == 403
