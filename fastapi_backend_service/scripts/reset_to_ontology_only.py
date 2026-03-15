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
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker


async def reset():
    # ── DB URL ────────────────────────────────────────────────────────────────
    db_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./dev.db")
    # FastAPI app uses psycopg2-style URLs in env but SQLAlchemy async needs asyncpg
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
        # Count before
        for tbl in ("generated_events", "routine_checks", "skill_definitions", "mcp_definitions"):
            r = await db.execute(text(f"SELECT COUNT(*) FROM {tbl}"))
            print(f"  Before — {tbl}: {r.scalar()}")

        print()

        # 1. generated_events (FK RESTRICT on skill_definitions)
        r = await db.execute(delete(GeneratedEventModel))
        print(f"  Deleted generated_events: {r.rowcount}")

        # 2. routine_checks
        r = await db.execute(delete(RoutineCheckModel))
        print(f"  Deleted routine_checks:   {r.rowcount}")

        # 3. skills
        r = await db.execute(delete(SkillDefinitionModel))
        print(f"  Deleted skill_definitions:{r.rowcount}")

        # 4. custom MCPs
        r = await db.execute(delete(MCPDefinitionModel).where(MCPDefinitionModel.mcp_type == "custom"))
        print(f"  Deleted custom MCPs:      {r.rowcount}")

        # 5. legacy system MCPs not in canonical list
        r = await db.execute(
            delete(MCPDefinitionModel).where(
                (MCPDefinitionModel.mcp_type == "system") &
                (MCPDefinitionModel.name.notin_(canonical_names))
            )
        )
        print(f"  Deleted legacy sys MCPs:  {r.rowcount}")

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
