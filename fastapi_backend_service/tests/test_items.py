"""Integration tests for item management endpoints.

Covers:
- GET    /api/v1/items        — list all items
- GET    /api/v1/items/me     — list current user's items (auth required)
- POST   /api/v1/items        — create item (auth required)
- GET    /api/v1/items/{id}   — get item (success, not found)
- PUT    /api/v1/items/{id}   — update item (success, forbidden)
- DELETE /api/v1/items/{id}   — delete item (success, forbidden)
"""

import pytest
from httpx import AsyncClient

from app.models.item import ItemModel
from app.models.user import UserModel

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# GET /api/v1/items
# ---------------------------------------------------------------------------


async def test_get_items(client: AsyncClient, test_item: ItemModel) -> None:
    """Returns a paginated list of all items."""
    response = await client.get("/api/v1/items/")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert isinstance(body["data"], list)


async def test_get_items_pagination(client: AsyncClient, test_item: ItemModel) -> None:
    """Pagination parameters are respected."""
    response = await client.get("/api/v1/items/?skip=0&limit=1")
    assert response.status_code == 200
    assert len(response.json()["data"]) <= 1


# ---------------------------------------------------------------------------
# GET /api/v1/items/me
# ---------------------------------------------------------------------------


async def test_get_my_items(
    client: AsyncClient,
    test_item: ItemModel,
    auth_headers: dict,
) -> None:
    """Authenticated user receives only their own items."""
    response = await client.get("/api/v1/items/me", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert all(i["owner_id"] == test_item.owner_id for i in body["data"])


async def test_get_my_items_unauthorized(client: AsyncClient) -> None:
    """Missing token returns HTTP 401."""
    response = await client.get("/api/v1/items/me")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/v1/items
# ---------------------------------------------------------------------------


async def test_create_item_success(
    client: AsyncClient,
    test_user: UserModel,
    auth_headers: dict,
) -> None:
    """Authenticated user can create a new item (HTTP 201)."""
    response = await client.post(
        "/api/v1/items/",
        json={"title": "New Test Item", "description": "A description"},
        headers=auth_headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "success"
    assert body["data"]["title"] == "New Test Item"
    assert body["data"]["owner_id"] == test_user.id


async def test_create_item_unauthorized(client: AsyncClient) -> None:
    """Creating an item without a token returns HTTP 401."""
    response = await client.post(
        "/api/v1/items/",
        json={"title": "Unauthorized Item"},
    )
    assert response.status_code == 401


async def test_create_item_missing_title(
    client: AsyncClient,
    auth_headers: dict,
) -> None:
    """Missing required title returns HTTP 422."""
    response = await client.post(
        "/api/v1/items/",
        json={"description": "No title here"},
        headers=auth_headers,
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/items/{item_id}
# ---------------------------------------------------------------------------


async def test_get_item_by_id(client: AsyncClient, test_item: ItemModel) -> None:
    """Returns the correct item by ID."""
    response = await client.get(f"/api/v1/items/{test_item.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["id"] == test_item.id
    assert body["data"]["title"] == test_item.title


async def test_get_item_not_found(client: AsyncClient) -> None:
    """Non-existent item ID returns HTTP 404."""
    response = await client.get("/api/v1/items/99999")
    assert response.status_code == 404
    assert response.json()["error_code"] == "NOT_FOUND"


# ---------------------------------------------------------------------------
# PUT /api/v1/items/{item_id}
# ---------------------------------------------------------------------------


async def test_update_item_success(
    client: AsyncClient,
    test_item: ItemModel,
    auth_headers: dict,
) -> None:
    """Item owner can update their item."""
    response = await client.put(
        f"/api/v1/items/{test_item.id}",
        json={"title": "Updated Title"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["data"]["title"] == "Updated Title"


async def test_update_item_forbidden(
    client: AsyncClient,
    test_item: ItemModel,
    db_session,
) -> None:
    """A non-owner, non-superuser cannot update another user's item."""
    from app.core.security import create_access_token, get_password_hash
    from app.models.user import UserModel as UM

    # Create a second user
    other_user = UM(
        username="otheruser_item",
        email="otheruser_item@example.com",
        hashed_password=get_password_hash("password123"),
        is_active=True,
        is_superuser=False,
    )
    db_session.add(other_user)
    await db_session.commit()
    await db_session.refresh(other_user)

    other_token = create_access_token(data={"sub": "otheruser_item"})
    response = await client.put(
        f"/api/v1/items/{test_item.id}",
        json={"title": "Hacked Title"},
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "FORBIDDEN"


async def test_update_item_not_found(
    client: AsyncClient,
    auth_headers: dict,
) -> None:
    """Updating a non-existent item returns HTTP 404."""
    response = await client.put(
        "/api/v1/items/99999",
        json={"title": "Ghost"},
        headers=auth_headers,
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/v1/items/{item_id}
# ---------------------------------------------------------------------------


async def test_delete_item_success(
    client: AsyncClient,
    test_user: UserModel,
    db_session,
    auth_headers: dict,
) -> None:
    """Item owner can delete their item."""
    from app.models.item import ItemModel as IM

    disposable = IM(
        title="Disposable Item",
        is_active=True,
        owner_id=test_user.id,
    )
    db_session.add(disposable)
    await db_session.commit()
    await db_session.refresh(disposable)

    response = await client.delete(
        f"/api/v1/items/{disposable.id}",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "success"


async def test_delete_item_forbidden(
    client: AsyncClient,
    test_item: ItemModel,
    db_session,
) -> None:
    """A non-owner, non-superuser cannot delete another user's item."""
    from app.core.security import create_access_token, get_password_hash
    from app.models.user import UserModel as UM

    other_user = UM(
        username="delattacker",
        email="delattacker@example.com",
        hashed_password=get_password_hash("password123"),
        is_active=True,
        is_superuser=False,
    )
    db_session.add(other_user)
    await db_session.commit()
    await db_session.refresh(other_user)

    token = create_access_token(data={"sub": "delattacker"})
    response = await client.delete(
        f"/api/v1/items/{test_item.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "FORBIDDEN"


async def test_delete_item_unauthorized(
    client: AsyncClient,
    test_item: ItemModel,
) -> None:
    """Delete without a token returns HTTP 401."""
    response = await client.delete(f"/api/v1/items/{test_item.id}")
    assert response.status_code == 401
