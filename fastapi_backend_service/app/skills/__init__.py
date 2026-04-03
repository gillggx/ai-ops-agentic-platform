"""Skills package — MCP-compatible tool registry.

All ``BaseMCPSkill`` subclasses defined here are automatically available to
the diagnostic agent.  To add a new skill:

1. Create a new module (e.g. ``app/skills/my_skill.py``) and subclass
   ``BaseMCPSkill``.
2. Import it here and add an instance to ``_ALL_SKILLS``.

Registry ordering
-----------------
``mcp_event_triage`` MUST be the first entry.  The System Prompt enforces
that the LLM calls it first, but placing it first in the registry also makes
the ordering self-documenting and testable.
"""

from app.skills.ask_user import AskUserRecentChangesSkill
from app.skills.base import BaseMCPSkill
from app.skills.etch_apc_check import EtchApcCheckSkill
from app.skills.etch_equipment_constants import EtchEquipmentConstantsSkill
from app.skills.etch_recipe_offset import EtchRecipeOffsetSkill
from app.skills.event_triage import EventTriageSkill

# ---------------------------------------------------------------------------
# Skill registry — mcp_event_triage MUST remain first
# ---------------------------------------------------------------------------

_ALL_SKILLS: list[BaseMCPSkill] = [
    EventTriageSkill(),             # ← ALWAYS FIRST: triage before everything else
    EtchRecipeOffsetSkill(),
    EtchEquipmentConstantsSkill(),
    EtchApcCheckSkill(),
    AskUserRecentChangesSkill(),
]

SKILL_REGISTRY: dict[str, BaseMCPSkill] = {skill.name: skill for skill in _ALL_SKILLS}

__all__ = [
    "BaseMCPSkill",
    "EventTriageSkill",
    "EtchRecipeOffsetSkill",
    "EtchEquipmentConstantsSkill",
    "EtchApcCheckSkill",
    "AskUserRecentChangesSkill",
    "SKILL_REGISTRY",
]
