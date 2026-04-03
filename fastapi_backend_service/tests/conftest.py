"""Pytest configuration and shared fixtures for the FastAPI Backend Service tests.

Each test function gets a **brand-new in-memory SQLite database** (function-scoped
engine) so there is zero data leakage between tests.  The dependency injection
override ensures that every HTTP request made through `client` uses the same
`db_session` that the test fixtures write to.

Fixtures provided:
- ``engine``       — function-scoped async SQLite in-memory engine.
- ``db_session``   — async session bound to the test's engine.
- ``client``       — ``httpx.AsyncClient`` wired to the FastAPI app.
- ``test_user``    — a pre-created active ``UserModel`` row.
- ``superuser``    — a pre-created superuser ``UserModel`` row.
- ``test_item``    — a pre-created ``ItemModel`` owned by ``test_user``.
- ``auth_headers`` — ``Authorization: Bearer`` headers for ``test_user``.
- ``superuser_auth_headers`` — Bearer headers for the superuser.
"""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.security import create_access_token, get_password_hash
from app.database import Base, get_db
from app.models.item import ItemModel
from app.models.user import UserModel

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEST_USERNAME = "testuser"
TEST_EMAIL = "testuser@example.com"
TEST_PASSWORD = "testpassword123"

# ---------------------------------------------------------------------------
# Database fixtures  (function-scoped → fresh DB per test)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def engine():
    """Create a fresh in-memory SQLite engine for each individual test.

    Using function scope guarantees complete isolation: committed rows from
    one test never bleed into another, avoiding UNIQUE constraint failures.
    """
    _engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        future=True,
    )
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield _engine
    await _engine.dispose()


@pytest_asyncio.fixture
async def db_session(engine) -> AsyncGenerator[AsyncSession, None]:
    """Provide an ``AsyncSession`` bound to the test's in-memory database."""
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    async with session_factory() as session:
        yield session


# ---------------------------------------------------------------------------
# HTTP client fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Provide an ``httpx.AsyncClient`` that routes requests through the app.

    Overrides the ``get_db`` dependency so every request handler in the test
    receives the same ``db_session`` that fixtures use — data written by
    fixtures is immediately visible to the server.
    """
    from main import app

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# User fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> UserModel:
    """Insert and return a standard active test user."""
    user = UserModel(
        username=TEST_USERNAME,
        email=TEST_EMAIL,
        hashed_password=get_password_hash(TEST_PASSWORD),
        is_active=True,
        is_superuser=False,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def superuser(db_session: AsyncSession) -> UserModel:
    """Insert and return a superuser."""
    user = UserModel(
        username="admin",
        email="admin@example.com",
        hashed_password=get_password_hash("adminpassword"),
        is_active=True,
        is_superuser=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
def auth_headers(test_user: UserModel) -> dict:
    """Return ``Authorization: Bearer`` headers signed for ``test_user``."""
    token = create_access_token(data={"sub": test_user.username})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def superuser_auth_headers(superuser: UserModel) -> dict:
    """Return ``Authorization: Bearer`` headers signed for the superuser."""
    token = create_access_token(data={"sub": superuser.username})
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Item fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def test_item(db_session: AsyncSession, test_user: UserModel) -> ItemModel:
    """Insert and return a test item owned by ``test_user``."""
    item = ItemModel(
        title="Test Item",
        description="A test item description",
        is_active=True,
        owner_id=test_user.id,
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    return item
