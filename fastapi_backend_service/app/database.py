## app/database.py
"""Database configuration and session management module for the FastAPI Backend Service.

This module provides async database engine setup, session factory, declarative base,
and utility functions for database initialization and dependency injection.
All database operations in this project use SQLAlchemy 2.0 async APIs.
"""

from collections.abc import AsyncGenerator
from typing import Optional

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

# ---------------------------------------------------------------------------
# Declarative Base
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    """SQLAlchemy declarative base class for all ORM models.

    All ORM model classes (e.g. UserModel, ItemModel) should inherit from
    this ``Base`` class so that their table metadata is registered and can
    be used for schema creation and Alembic migrations.

    Examples:
        >>> class MyModel(Base):
        ...     __tablename__ = "my_table"
        ...     id: Mapped[int] = mapped_column(primary_key=True)
    """

    pass


# ---------------------------------------------------------------------------
# Module-level engine and session factory (lazy-initialized)
# ---------------------------------------------------------------------------

_engine: Optional[AsyncEngine] = None
_async_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def _get_engine() -> AsyncEngine:
    """Get or create the async database engine singleton.

    Creates the engine on first call using the DATABASE_URL from application
    settings. Subsequent calls return the cached engine instance.

    Returns:
        The singleton ``AsyncEngine`` instance.
    """
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.DATABASE_URL,
            echo=settings.DEBUG,
            future=True,
        )
    return _engine


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get or create the async session factory singleton.

    Creates the session factory on first call using the current engine.
    Subsequent calls return the cached factory instance.

    Returns:
        The singleton ``async_sessionmaker[AsyncSession]`` instance.
    """
    global _async_session_factory
    if _async_session_factory is None:
        _async_session_factory = async_sessionmaker(
            bind=_get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )
    return _async_session_factory


# ---------------------------------------------------------------------------
# Public Database Utilities
# ---------------------------------------------------------------------------


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Async generator that yields a database session for use in FastAPI dependencies.

    Provides a scoped ``AsyncSession`` for each incoming request. The session
    is automatically closed after the request completes (or on error), ensuring
    proper resource cleanup. This function is designed to be used with
    FastAPI's ``Depends`` mechanism.

    Yields:
        An ``AsyncSession`` instance bound to the current request lifecycle.

    Examples:
        Usage as a FastAPI dependency::

            @router.get("/example")
            async def example_endpoint(db: AsyncSession = Depends(get_db)):
                result = await db.execute(select(UserModel))
                return result.scalars().all()

        Usage in a context manager (e.g. tests)::

            async for session in get_db():
                result = await session.execute(select(UserModel))
    """
    session_factory = _get_session_factory()
    async with session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Initialize the database by creating all registered tables.

    Iterates over all ORM models registered with ``Base.metadata`` and
    creates their corresponding tables in the database if they do not already
    exist. This function is intended to be called once during application
    startup (e.g. in the FastAPI ``lifespan`` handler).

    .. note::
        In production environments, prefer using Alembic migrations
        (``alembic upgrade head``) instead of this function for schema
        management and version control.

    Examples:
        Calling during FastAPI lifespan startup::

            @asynccontextmanager
            async def lifespan(app: FastAPI):
                await init_db()
                yield

        Calling in tests::

            async def setup():
                await init_db()
    """
    engine = _get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Safe-migrate: add new columns to existing tables without Alembic
        await _safe_add_columns(conn)


async def _safe_add_columns(conn) -> None:
    """Add missing columns to existing tables (idempotent, SQLite-compatible)."""
    migrations = [
        ("skill_definitions", "human_recommendation", "TEXT"),
        ("event_types", "spc_chart", "VARCHAR(100)"),
    ]
    for table, column, col_type in migrations:
        try:
            await conn.execute(
                __import__("sqlalchemy").text(
                    f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
                )
            )
        except Exception:
            pass  # Column already exists — safe to ignore
