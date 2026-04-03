"""
Database initialization and seeding module.

數據庫初始化和種子數據模塊。

This module handles:
1. Creating all database tables from ORM models
2. Seeding initial data (system parameters, default tools, etc.)
3. Migration helpers
"""

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.config import Settings
from app.ontology.models import Base

# Import seed data - will be defined below or in constants
try:
    from app.core.constants import (
        AGENT_TOOLS,
        DEFAULT_EVENT_TYPES,
        SYSTEM_PARAMETERS,
    )
except ImportError:
    # Fallback if constants are not defined
    SYSTEM_PARAMETERS = []
    DEFAULT_EVENT_TYPES = []
    AGENT_TOOLS = []


async def init_database(database_url: str) -> None:
    """
    Initialize database - create all tables.
    
    初始化數據庫 - 創建所有表。
    
    Args:
        database_url: Database connection URL
    """
    # Create async engine
    engine = create_async_engine(
        database_url,
        echo=False,
        poolclass=NullPool,
    )

    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await engine.dispose()


async def seed_database(db: AsyncSession) -> None:
    """
    Seed initial data into database.
    
    種子初始數據到數據庫。
    
    Includes:
    - System parameters
    - Event types
    - Agent tools
    
    Args:
        db: AsyncSession - Database session
    """
    from app.ontology.repositories import (
        AgentToolRepository,
        EventTypeRepository,
        SystemParameterRepository,
    )

    # Initialize repositories
    param_repo = SystemParameterRepository()
    event_type_repo = EventTypeRepository()
    tool_repo = AgentToolRepository()

    # Seed system parameters
    for param in SYSTEM_PARAMETERS:
        existing = await param_repo.get_by_key(db, param["key"])
        if not existing:
            await param_repo.create(db, **param)
            print(f"  ✅ Created parameter: {param['key']}")

    # Seed event types
    for event_type in DEFAULT_EVENT_TYPES:
        existing = await event_type_repo.get_by_name(db, event_type["name"])
        if not existing:
            await event_type_repo.create(db, **event_type)
            print(f"  ✅ Created event type: {event_type['name']}")

    # Seed agent tools
    for tool in AGENT_TOOLS:
        existing = await tool_repo.get_by_name(db, tool["name"])
        if not existing:
            await tool_repo.create(db, **tool)
            print(f"  ✅ Created tool: {tool['name']}")

    # Seed default admin user
    try:
        from app.ontology.repositories import UserRepository
        from app.ontology.models import User
        from app.services.security_service import SecurityService

        user_repo = UserRepository()
        security = SecurityService()
        existing_admin = await user_repo.get_by_username(db, "admin")
        if not existing_admin:
            import json as _json
            admin = User(
                username="admin",
                email="admin@example.com",
                hashed_password=security.hash_password("admin"),
                roles=_json.dumps(["admin"]),
                is_active=True,
            )
            db.add(admin)
            print("  ✅ Created default admin user (admin/admin)")
    except Exception as e:
        print(f"  ⚠️  Could not seed admin user: {e}")

    # Commit all changes
    await db.commit()


async def initialize_application(settings: Optional[Settings] = None) -> None:
    """
    Full application initialization sequence.
    
    完整應用初始化序列。
    
    Steps:
    1. Create database tables
    2. Seed initial data
    
    Args:
        settings: Application settings (optional)
    """
    if settings is None:
        settings = Settings()

    print("🔧 Initializing database...")
    print(f"  📍 Database: {settings.DATABASE_URL}")

    # Step 1: Create tables
    print("  📝 Creating database tables...")
    try:
        await init_database(settings.DATABASE_URL)
        print("  ✅ Database tables created")
    except Exception as e:
        print(f"  ⚠️  Tables may already exist: {e}")

    # Step 2: Seed data
    print("  🌱 Seeding initial data...")
    try:
        # Create a temporary async session for seeding
        engine = create_async_engine(settings.DATABASE_URL, echo=False)
        async_session = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        
        async with async_session() as session:
            await seed_database(session)
        
        await engine.dispose()
        print("  ✅ Initial data seeded")
    except Exception as e:
        print(f"  ⚠️  Seeding encountered issue: {e}")

    print("✅ Database initialization complete")


if __name__ == "__main__":
    import asyncio

    settings = Settings()
    asyncio.run(initialize_application(settings))
