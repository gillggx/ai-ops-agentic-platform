"""Fetches MCP + skill catalogs from Java to build the LLM prompt context.

Per CLAUDE.md: MCP/Skill descriptions are the single source of truth. We
pull them fresh each turn so prompts stay in sync with DB edits.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from ..clients.java_client import JavaAPIClient


@dataclass
class AgentContext:
    mcps: list[dict] = field(default_factory=list)
    skills: list[dict] = field(default_factory=list)

    def format_for_llm(self) -> str:
        """Render the catalog as plain text so the LLM can reason over it.

        We deliberately include each entry's full description — no summarising —
        because CLAUDE.md forbids hard-coding MCP usage notes in prompts.
        """
        lines: list[str] = []
        if self.mcps:
            lines.append("## Available MCPs")
            for m in self.mcps:
                lines.append(
                    f"- name: {m.get('name')}\n"
                    f"  type: {m.get('mcpType')}\n"
                    f"  description: {m.get('description') or '(none)'}\n"
                    f"  input_schema: {m.get('inputSchema') or '[]'}"
                )
        if self.skills:
            lines.append("\n## Available Skills")
            for s in self.skills:
                lines.append(
                    f"- name: {s.get('name')}\n"
                    f"  description: {s.get('description') or '(none)'}\n"
                    f"  trigger: {s.get('triggerMode')} / source={s.get('source')}"
                )
        if not lines:
            return "(empty catalog — no MCPs or skills registered yet)"
        return "\n".join(lines)

    def summary(self) -> dict:
        return {"mcp_count": len(self.mcps), "skill_count": len(self.skills)}


async def load_context(java: JavaAPIClient) -> AgentContext:
    """Pull MCPs + active skills in parallel-ish fashion."""
    mcps = await java.list_mcps()
    skills = await java.list_skills()
    # Skills come back as a list; filter to active only here so prompts stay lean.
    skills_active = [s for s in (skills or []) if s.get("isActive", True)]
    return AgentContext(mcps=mcps or [], skills=skills_active)


def snapshot_json(ctx: AgentContext) -> str:
    """Serialise for persistence (e.g. agent_session.workspace_state)."""
    return json.dumps(ctx.summary(), ensure_ascii=False)
