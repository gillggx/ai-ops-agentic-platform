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


def AsyncSessionLocal() -> AsyncSession:
    """Return a new async session (context manager style, for use outside requests).

    Intended for background tasks (e.g. APScheduler jobs) that cannot use FastAPI's
    ``Depends(get_db)`` mechanism.

    Usage::

        async with AsyncSessionLocal() as session:
            result = await session.execute(...)
    """
    return _get_session_factory()()


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


async def _rebuild_v18_tables(conn) -> None:
    """Detect old schema and drop tables for clean v18 rebuild.

    Checks whether ``skill_definitions`` still carries the pre-v18 ``mcp_ids``
    column.  If it does, both ``skill_definitions`` and ``generated_events`` are
    dropped so that ``create_all`` can recreate them with the new v18 schema.

    Dialect-aware: uses PRAGMA on SQLite, information_schema on Postgres.
    """
    import logging

    import sqlalchemy as sa

    dialect = conn.dialect.name
    try:
        if dialect == "sqlite":
            result = await conn.execute(sa.text("PRAGMA table_info(skill_definitions)"))
            columns = {row[1] for row in result.fetchall()}
        else:
            # Postgres / other: use information_schema
            result = await conn.execute(sa.text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'skill_definitions'"
            ))
            columns = {row[0] for row in result.fetchall()}

        if "mcp_ids" in columns:
            await conn.execute(sa.text("DROP TABLE IF EXISTS skill_definitions CASCADE"))
            await conn.execute(sa.text("DROP TABLE IF EXISTS generated_events CASCADE"))
            logging.getLogger(__name__).info(
                "v18 migration: dropped old skill_definitions + generated_events tables"
            )
    except Exception:
        pass  # Table doesn't exist yet — fine


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
        await _rebuild_v18_tables(conn)   # v18: drop stale tables before create_all
        await conn.run_sync(Base.metadata.create_all)
        # Safe-migrate: add new columns to existing tables without Alembic
        await _safe_add_columns(conn)


async def _safe_add_columns(conn) -> None:
    """Add missing columns to existing tables (idempotent, dialect-aware).

    On Postgres with a fresh DB, create_all() already builds the correct
    schema from ORM models, so these no-op (column already exists). On
    legacy SQLite instances, these patch older schemas up to current.
    """
    dialect = conn.dialect.name
    # Boolean column type differs between dialects
    bool_default_true = "BOOLEAN NOT NULL DEFAULT TRUE" if dialect != "sqlite" else "INTEGER NOT NULL DEFAULT 1"

    migrations = [
        # v18: extend event_types with source and is_active
        ("event_types", "source", "TEXT NOT NULL DEFAULT 'simulator'"),
        ("event_types", "is_active", bool_default_true),
        # Keep legacy migrations
        ("routine_checks", "trigger_event_id", "INTEGER"),
        # v2.0: execution_logs — add auto_patrol_id, widen triggered_by
        ("execution_logs", "auto_patrol_id", "INTEGER REFERENCES auto_patrols(id) ON DELETE SET NULL"),
        # skill_definitions: source + auto_check_description + input_schema
        ("skill_definitions", "source", "TEXT NOT NULL DEFAULT 'legacy'"),
        ("skill_definitions", "auto_check_description", "TEXT NOT NULL DEFAULT ''"),
        ("skill_definitions", "input_schema", "TEXT NOT NULL DEFAULT '[]'"),
        # auto_patrols: auto_check_description + data_context + target_scope
        ("auto_patrols", "auto_check_description", "TEXT NOT NULL DEFAULT ''"),
        ("auto_patrols", "data_context", "TEXT"),
        ("auto_patrols", "target_scope", "TEXT NOT NULL DEFAULT '{\"type\":\"event_driven\"}'"),
        # alarms: AP execution log + DR diagnostic log
        ("alarms", "execution_log_id", "INTEGER REFERENCES execution_logs(id) ON DELETE SET NULL"),
        ("alarms", "diagnostic_log_id", "INTEGER REFERENCES execution_logs(id) ON DELETE SET NULL"),
        # skill_definitions: which auto_patrol alarm triggers this Diagnostic Rule
        ("skill_definitions", "trigger_patrol_id", "INTEGER REFERENCES auto_patrols(id) ON DELETE SET NULL"),
        # v3.4 Pipeline Builder: block examples (JSON array text)
        ("pb_blocks", "examples", "TEXT NOT NULL DEFAULT '[]'"),
        # Phase 5-UX-3b: flat-column schema hints for LLM (JSON array)
        ("pb_blocks", "output_columns_hint", "TEXT NOT NULL DEFAULT '[]'"),
        # Phase 5-UX-3b: session mode — persist Agent-built pipeline + run_id + title
        ("agent_sessions", "last_pipeline_json", "TEXT"),
        ("agent_sessions", "last_pipeline_run_id", "INTEGER"),
        ("agent_sessions", "title", "TEXT"),
        ("agent_sessions", "updated_at", "TIMESTAMP"),
        # Phase 4-A: skill_definitions.pipeline_config (declared in ORM model, missing in legacy DB)
        ("skill_definitions", "pipeline_config", "TEXT"),
        # Phase 4-A follow-on: skill_definitions.pipeline_id — P1 DR migration binds skill 1:1 to pipeline
        ("skill_definitions", "pipeline_id", "INTEGER REFERENCES pb_pipelines(id) ON DELETE SET NULL"),
        # Phase 4-B: auto_patrols links pipeline (with input_binding) instead of skill
        ("auto_patrols", "pipeline_id", "INTEGER REFERENCES pb_pipelines(id) ON DELETE SET NULL"),
        ("auto_patrols", "input_binding", "TEXT"),
        # P3: one-shot trigger — DateTrigger fires once at scheduled_at, then deactivates.
        ("auto_patrols", "scheduled_at", "TIMESTAMP WITH TIME ZONE"),
        # PR-B / Phase 5-lifecycle: pipeline_kind + usage_stats
        ("pb_pipelines", "pipeline_kind", "VARCHAR(20) NOT NULL DEFAULT 'diagnostic'"),
        ("pb_pipelines", "usage_stats", "TEXT NOT NULL DEFAULT '{\"invoke_count\":0,\"last_invoked_at\":null,\"last_triggered_at\":null}'"),
        ("pb_pipelines", "locked_at", "TIMESTAMP"),
        ("pb_pipelines", "locked_by", "TEXT"),
        ("pb_pipelines", "auto_doc", "TEXT"),
        ("pb_pipelines", "published_at", "TIMESTAMP"),
        ("pb_pipelines", "archived_at", "TIMESTAMP"),
    ]
    import logging as _logging
    import sqlalchemy as sa  # used below for parametrized UPDATEs
    _mig_logger = _logging.getLogger(__name__)
    for table, column, col_type in migrations:
        # PR-D fix: each ALTER in its own savepoint so one failure doesn't
        # poison the outer transaction and silently skip later migrations.
        # Use exec_driver_sql (not text()) so JSON defaults containing `:0` etc.
        # are NOT misread as bind parameter placeholders.
        try:
            if dialect != "sqlite":
                sql = f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {col_type}"
            else:
                sql = f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
            async with conn.begin_nested():
                await conn.exec_driver_sql(sql)
        except Exception as e:
            _mig_logger.warning(
                "migration ALTER TABLE %s ADD COLUMN %s failed (may already exist): %s",
                table, column, e,
            )

    # Phase 4-B: relax NOT NULL on skill_id now that pipeline_id is an alternative.
    # Postgres-only (SQLite has limited ALTER COLUMN semantics).
    if dialect != "sqlite":
        for table, column in [("auto_patrols", "skill_id")]:
            try:
                async with conn.begin_nested():
                    await conn.exec_driver_sql(
                        f"ALTER TABLE {table} ALTER COLUMN {column} DROP NOT NULL"
                    )
            except Exception as e:
                _mig_logger.debug("DROP NOT NULL on %s.%s skipped: %s", table, column, e)

        # PR-B: widen pb_pipelines.status VARCHAR(16) → VARCHAR(20) to fit
        # 'validating' + 'archived' names. Idempotent — ALTER to same size is no-op.
        try:
            async with conn.begin_nested():
                await conn.exec_driver_sql(
                    "ALTER TABLE pb_pipelines ALTER COLUMN status TYPE VARCHAR(20)"
                )
        except Exception as e:
            _mig_logger.debug("widen pb_pipelines.status skipped: %s", e)

        # Phase 5-UX-3b: relax pb_pipelines.pipeline_kind NOT NULL — ad-hoc
        # session pipelines don't carry a kind until they're published.
        try:
            async with conn.begin_nested():
                await conn.exec_driver_sql(
                    "ALTER TABLE pb_pipelines ALTER COLUMN pipeline_kind DROP NOT NULL"
                )
        except Exception as e:
            _mig_logger.debug("DROP NOT NULL on pb_pipelines.pipeline_kind skipped: %s", e)

    # PR-B: remap legacy pipeline status names idempotently.
    # draft → draft (unchanged); pi_run → validating; production → active; deprecated → archived
    for old_name, new_name in [
        ("pi_run", "validating"),
        ("production", "active"),
        ("deprecated", "archived"),
    ]:
        try:
            async with conn.begin_nested():
                await conn.execute(
                    sa.text("UPDATE pb_pipelines SET status = :new WHERE status = :old"),
                    {"new": new_name, "old": old_name},
                )
        except Exception as e:
            _mig_logger.debug("status remap %s→%s skipped: %s", old_name, new_name, e)

    # PR-B: backfill pipeline_kind — pipelines that contain block_alert in JSON
    # are classified as auto_patrol; others stay diagnostic.
    try:
        async with conn.begin_nested():
            await conn.exec_driver_sql(
                "UPDATE pb_pipelines SET pipeline_kind = 'auto_patrol' "
                "WHERE pipeline_kind = 'diagnostic' "
                "AND pipeline_json LIKE '%block_alert%'"
            )
    except Exception as e:
        _mig_logger.debug("pipeline_kind backfill skipped: %s", e)

    # Phase 5-UX-7: 3-kind split.
    # diagnostic + has block_alert → auto_check (alarm-triggered diagnosis)
    # diagnostic + no block_alert  → skill (agent-invocable on-demand)
    try:
        async with conn.begin_nested():
            await conn.exec_driver_sql(
                "UPDATE pb_pipelines SET pipeline_kind = 'auto_check' "
                "WHERE pipeline_kind = 'diagnostic' "
                "AND pipeline_json LIKE '%block_alert%'"
            )
    except Exception as e:
        _mig_logger.debug("diagnostic→auto_check backfill skipped: %s", e)
    try:
        async with conn.begin_nested():
            await conn.exec_driver_sql(
                "UPDATE pb_pipelines SET pipeline_kind = 'skill' "
                "WHERE pipeline_kind = 'diagnostic'"
            )
    except Exception as e:
        _mig_logger.debug("diagnostic→skill backfill skipped: %s", e)
