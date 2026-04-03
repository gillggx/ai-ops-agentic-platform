"""
AI Agent 層 - Agent 通信

本層負責：
- MCP Server 實現 (mcp/)
- Skill 系統 (skills/)
- 請求路由 (router/)
- 層間集成 (integration/)

特點：
- 實現 MCP 協議標準
- 調用 Ontology 層服務
- 集成 AI Ops 層監控
- 清晰的 Tool 和 Resource 定義
"""

from .mcp import FastAPIMCPServer
from .skills import BaseSkill, SkillRegistry

__all__ = [
    "FastAPIMCPServer",
    "BaseSkill",
    "SkillRegistry",
]
