"""
Skill system for the AI Agent layer.

Skill 基類、註冊表和實現。
"""

from .agent_management import AgentManagementSkill
from .analytics import AnalyticsSkill
from .base import BaseSkill, SkillInput, SkillMetadata, SkillMethod, SkillOutput
from .business_logic import BusinessLogicSkill
from .data_processing import DataProcessingSkill
from .registry import SkillRegistry

__all__ = [
    # Base classes and data models
    "BaseSkill",
    "SkillMetadata",
    "SkillMethod",
    "SkillInput",
    "SkillOutput",
    # Registry
    "SkillRegistry",
    # Skill implementations
    "AgentManagementSkill",
    "DataProcessingSkill",
    "AnalyticsSkill",
    "BusinessLogicSkill",
]
