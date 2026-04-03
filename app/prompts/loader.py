"""Prompt Loader — async utility for DB-first prompt resolution.

Usage:
    from app.prompts.loader import load_prompt

    system_prompt = await load_prompt(db, "ANALYSIS_SYSTEM", fallback=_ANALYSIS_SYSTEM)

Priority:
  1. system_parameters[key]  (editable in UI without redeploy)
  2. fallback                 (module-level constant in catalog.py)
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def load_prompt(db: AsyncSession, key: str, fallback: str) -> str:
    """Return DB-stored prompt for *key* if present, otherwise *fallback*.

    Args:
        db:       Active async DB session.
        key:      system_parameters.key to look up.
        fallback: Hardcoded default (from catalog.py or service module).

    Returns:
        Resolved prompt string — guaranteed non-empty.
    """
    try:
        from app.ontology.models.system_parameter import SystemParameter
        result = await db.execute(
            select(SystemParameter).where(SystemParameter.key == key)
        )
        sp = result.scalar_one_or_none()
        if sp and sp.value:
            return sp.value
    except Exception as exc:
        logger.warning("load_prompt: DB lookup failed for key=%r — using fallback. Error: %s", key, exc)
    return fallback
