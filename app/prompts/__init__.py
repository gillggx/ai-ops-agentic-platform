"""app/prompts — centralised prompt catalog and DB loader.

Usage:
    # Static catalog prompt (Category B — technical, not runtime-tunable)
    from app.prompts.catalog import SHADOW_ANALYST_SYSTEM

    # DB-first prompt (Category A — tunable via system_parameters UI)
    from app.prompts.loader import load_prompt
    prompt = await load_prompt(db, SystemParameter.KEY_AGENT_SOUL, fallback=_DEFAULT_SOUL)
"""

from .loader import load_prompt
from . import catalog

__all__ = ["load_prompt", "catalog"]
