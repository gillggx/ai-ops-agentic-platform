"""
Skill-related Pydantic schemas.

技能相關的驗證模型。
"""

from typing import Optional

from pydantic import Field

from .common import IdSchema


class SkillDefinitionCreate(IdSchema):
    """
    Schema for creating a skill definition.
    
    創建技能定義的驗證模型。
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Unique skill name"
    )
    description: str = Field(
        ...,
        min_length=1,
        description="Skill description"
    )
    version: str = Field(
        default="1.0.0",
        description="Skill version (semantic versioning)"
    )
    mcp_ids: str = Field(
        default="[]",
        description="JSON array of bound MCP IDs"
    )
    diagnostic_prompt: Optional[str] = Field(
        default=None,
        description="Diagnostic prompt template"
    )
    human_recommendation: Optional[str] = Field(
        default=None,
        description="Expert recommendation text"
    )


class SkillDefinitionRead(IdSchema):
    """
    Schema for reading skill definition data.
    
    讀取技能定義數據的驗證模型。
    """

    id: int = Field(
        ...,
        description="Skill definition ID"
    )
    name: str = Field(
        ...,
        description="Skill name"
    )
    description: str = Field(
        ...,
        description="Skill description"
    )
    version: str = Field(
        ...,
        description="Skill version"
    )
    mcp_ids: str = Field(
        ...,
        description="Bound MCP IDs (JSON array)"
    )
    diagnostic_prompt: Optional[str] = Field(
        default=None,
        description="Diagnostic prompt template"
    )
    human_recommendation: Optional[str] = Field(
        default=None,
        description="Expert recommendation"
    )

    class Config:
        """Pydantic config."""

        from_attributes = True


class SkillCreate(IdSchema):
    """
    Schema for creating a skill instance.
    
    創建技能實例的驗證模型。
    """

    skill_definition_id: int = Field(
        ...,
        description="Reference to SkillDefinition"
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Instance name"
    )
    config: str = Field(
        default="{}",
        description="Instance configuration (JSON)"
    )
    is_active: bool = Field(
        default=True,
        description="Whether this skill instance is active"
    )


class SkillRead(IdSchema):
    """
    Schema for reading skill instance data.
    
    讀取技能實例數據的驗證模型。
    """

    id: int = Field(
        ...,
        description="Skill instance ID"
    )
    skill_definition_id: int = Field(
        ...,
        description="Reference to SkillDefinition"
    )
    name: str = Field(
        ...,
        description="Instance name"
    )
    config: str = Field(
        ...,
        description="Instance configuration"
    )
    is_active: bool = Field(
        ...,
        description="Whether instance is active"
    )

    class Config:
        """Pydantic config."""

        from_attributes = True
