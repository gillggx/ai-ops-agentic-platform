"""Alembic environment configuration for the FastAPI Backend Service.

Supports both synchronous (``run_migrations_offline``) and asynchronous
(``run_migrations_online``) migration modes.

- **Offline mode**: Generates SQL migration scripts without a live database
  connection. Useful for reviewing or applying migrations in CI/CD pipelines.
- **Online mode**: Connects to the database (using ``asyncio.run``) and
  applies migrations in a live transaction.

The database URL is read from ``app.config.get_settings()`` so it always
reflects the active environment configuration (.env file or environment
variables), rather than being hard-coded in ``alembic.ini``.
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# ---------------------------------------------------------------------------
# Alembic Config object — provides access to alembic.ini values
# ---------------------------------------------------------------------------
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ---------------------------------------------------------------------------
# Import all models so that Base.metadata is fully populated
# ---------------------------------------------------------------------------
# These imports must happen *before* referencing Base.metadata so that
# Alembic can detect all table definitions for autogenerate support.
from app.config import get_settings  # noqa: E402
from app.database import Base  # noqa: E402
from app.models import UserModel, ItemModel  # noqa: E402, F401

# Inject the database URL from application settings into the Alembic config.
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# Metadata object used for ``--autogenerate`` support
target_metadata = Base.metadata


# ---------------------------------------------------------------------------
# Offline migration mode
# ---------------------------------------------------------------------------


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Configures the context with just a URL rather than an Engine, so an
    actual DBAPI connection is never established. Calls to
    ``context.execute()`` emit the given string to the script output.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online migration mode (async)
# ---------------------------------------------------------------------------


def do_run_migrations(connection: Connection) -> None:
    """Execute migrations within a synchronous connection context.

    Args:
        connection: A synchronous ``Connection`` instance provided by the
                    async engine's ``run_sync`` method.
    """
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations using ``run_sync``."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode using asyncio."""
    asyncio.run(run_async_migrations())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
