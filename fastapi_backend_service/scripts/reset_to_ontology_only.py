#!/usr/bin/env python3
"""
reset_to_ontology_only.py
=========================
One-shot DB reset: removes all Skills, RoutineChecks, GeneratedEvents,
custom MCPs, and legacy system MCPs — then re-seeds the canonical
ontology system MCPs from main._ONTOLOGY_SYSTEM_MCPS.

Usage (run from /opt/aiops/fastapi_backend_service):
    python3 scripts/reset_to_ontology_only.py

Or with a custom DATABASE_URL:
    DATABASE_URL=postgresql+asyncpg://... python3 scripts/reset_to_ontology_only.py
"""

import asyncio
import json
import os
import sys

# Make sure app package is importable from /opt/aiops/fastapi_backend_service
_APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _APP_ROOT)

# Change CWD so pydantic-settings finds .env in the correct directory
os.chdir(_APP_ROOT)

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker


async def reset():
    # ── DB URL — read from app config (same source as production server) ─────
    from app.config import get_settings
    _settings = get_settings()
    db_url = str(_settings.DATABASE_URL)
    # SQLAlchemy async requires asyncpg driver for PostgreSQL
    db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")
    db_url = db_url.replace("postgres://", "postgresql+asyncpg://")

    print(f"Connecting to: {db_url[:60]}...")
    engine = create_async_engine(db_url, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # ── Import models ─────────────────────────────────────────────────────────
    import app.models  # noqa — registers all models with Base
    from app.models.generated_event import GeneratedEventModel
    from app.models.routine_check import RoutineCheckModel
    from app.models.skill_definition import SkillDefinitionModel
    from app.models.mcp_definition import MCPDefinitionModel

    # ── Import canonical MCP list from main.py ────────────────────────────────
    from main import _ONTOLOGY_SYSTEM_MCPS

    canonical_names = {s["name"] for s in _ONTOLOGY_SYSTEM_MCPS}

    async with Session() as db:
        # Count before (skip tables that may not exist yet)
        for tbl in ("generated_events", "routine_checks", "skill_definitions", "mcp_definitions"):
            try:
                r = await db.execute(text(f"SELECT COUNT(*) FROM {tbl}"))
                print(f"  Before — {tbl}: {r.scalar()}")
            except Exception:
                print(f"  Before — {tbl}: (table not found, skipping)")

        print()

        # 1. generated_events (FK RESTRICT on skill_definitions)
        try:
            r = await db.execute(delete(GeneratedEventModel))
            print(f"  Deleted generated_events: {r.rowcount}")
        except Exception as e:
            print(f"  Skipped generated_events: {e}")
            await db.rollback()

        # 2. routine_checks
        try:
            r = await db.execute(delete(RoutineCheckModel))
            print(f"  Deleted routine_checks:   {r.rowcount}")
        except Exception as e:
            print(f"  Skipped routine_checks:   {e}")
            await db.rollback()

        # 3. skills
        try:
            r = await db.execute(delete(SkillDefinitionModel))
            print(f"  Deleted skill_definitions:{r.rowcount}")
        except Exception as e:
            print(f"  Skipped skill_definitions:{e}")
            await db.rollback()

        # 4. custom MCPs
        try:
            r = await db.execute(delete(MCPDefinitionModel).where(MCPDefinitionModel.mcp_type == "custom"))
            print(f"  Deleted custom MCPs:      {r.rowcount}")
        except Exception as e:
            print(f"  Skipped custom MCPs:      {e}")
            await db.rollback()

        # 5. legacy system MCPs not in canonical list
        try:
            r = await db.execute(
                delete(MCPDefinitionModel).where(
                    (MCPDefinitionModel.mcp_type == "system") &
                    (MCPDefinitionModel.name.notin_(canonical_names))
                )
            )
            print(f"  Deleted legacy sys MCPs:  {r.rowcount}")
        except Exception as e:
            print(f"  Skipped legacy sys MCPs:  {e}")
            await db.rollback()

        await db.commit()
        print()

        # 6. Upsert canonical ontology system MCPs
        for spec in _ONTOLOGY_SYSTEM_MCPS:
            result = await db.execute(
                select(MCPDefinitionModel).where(
                    MCPDefinitionModel.name == spec["name"],
                    MCPDefinitionModel.mcp_type == "system",
                )
            )
            existing = result.scalar_one_or_none()
            if existing is None:
                db.add(MCPDefinitionModel(
                    name=spec["name"],
                    description=spec["description"],
                    mcp_type="system",
                    api_config=json.dumps(spec["api_config"], ensure_ascii=False),
                    input_schema=json.dumps(spec["input_schema"], ensure_ascii=False),
                    processing_intent="",
                    visibility="public",
                ))
                print(f"  Seeded:  {spec['name']}")
            else:
                existing.description = spec["description"]
                existing.api_config = json.dumps(spec["api_config"], ensure_ascii=False)
                existing.input_schema = json.dumps(spec["input_schema"], ensure_ascii=False)
                print(f"  Updated: {spec['name']}")

        await db.commit()

        # Final count
        print()
        r = await db.execute(text("SELECT COUNT(*) FROM mcp_definitions WHERE mcp_type='system'"))
        print(f"  Final system MCPs: {r.scalar()} (expected {len(_ONTOLOGY_SYSTEM_MCPS)})")

    await engine.dispose()
    print()
    print("Reset complete.")


if __name__ == "__main__":
    asyncio.run(reset())
