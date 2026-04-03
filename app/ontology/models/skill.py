"""
Skill models for the Ontology layer.

Define Skill and SkillDefinition entities.
定義 Skill 和 SkillDefinition 實體。
"""

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .event import EventType

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel


class SkillDefinition(BaseModel):
    """
    Skill definition and configuration.
    
    Represents a skill that can be executed by the system.
    代表系統中可執行的技能。
    
    Attributes:
        name: str - Unique skill name (唯一技能名稱)
        description: str - Skill description (技能描述)
        version: str - Skill version (技能版本)
        mcp_ids: str - JSON array of bound MCP IDs (綁定的 MCP ID)
        diagnostic_prompt: str - Diagnostic prompt template (診斷提示模板)
        human_recommendation: str - Expert recommendation (專家建議)
    """

    __tablename__ = "skill_definitions"

    name: Mapped[str] = mapped_column(
        String(200),
        unique=True,
        nullable=False,
        index=True,
        doc="Unique skill name"
    )

    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Description of what this skill does"
    )

    version: Mapped[str] = mapped_column(
        String(20),
        default="1.0.0",
        nullable=False,
        doc="Skill version (semantic versioning)"
    )

    mcp_ids: Mapped[str] = mapped_column(
        Text,
        default="[]",
        nullable=False,
        doc="JSON array of bound MCP definition IDs"
    )

    diagnostic_prompt: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Template prompt for diagnosis logic"
    )

    human_recommendation: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Expert-written recommendation text"
    )

    last_diagnosis_result: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Last diagnosis result as JSON"
    )

    # Original dev.db fields — nullable for backward compat
    # event_type_id: when set, this skill is the designated diagnosis skill for that EventType.
    event_type_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("event_types.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # param_mappings: JSON dict mapping EventType attribute names to skill input param names.
    # Lets the agent auto-fill skill inputs from incoming event data without manual mapping.
    param_mappings: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    problem_subject: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    visibility: Mapped[Optional[str]] = mapped_column(String(10), nullable=True, default="private")

    # Relationships
    # Back-reference to the EventType that owns this skill.
    event_type: Mapped[Optional["EventType"]] = relationship(
        "EventType",
        foreign_keys=[event_type_id],
        back_populates="skill_definitions",
        doc="EventType that triggers this skill (None if not event-bound)"
    )
    skills: Mapped[list["Skill"]] = relationship(
        "Skill",
        back_populates="skill_definition",
        cascade="all, delete-orphan",
        doc="Individual skill instances"
    )

    def __repr__(self) -> str:
        return (
            f"SkillDefinition(id={self.id}, name={self.name!r}, "
            f"version={self.version!r})"
        )

    def __str__(self) -> str:
        return f"{self.name} (v{self.version})"


class Skill(BaseModel):
    """
    Individual skill instance.
    
    Represents a specific instantiation of a skill with configuration.
    代表技能的具體實例化。
    
    Attributes:
        skill_definition_id: int - FK to SkillDefinition (技能定義外鍵)
        name: str - Instance name (實例名稱)
        config: str - Instance configuration as JSON (實例配置)
        is_active: bool - Whether this skill instance is active (是否活躍)
    """

    __tablename__ = "skills"

    skill_definition_id: Mapped[int] = mapped_column(
        ForeignKey("skill_definitions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Reference to SkillDefinition"
    )

    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        index=True,
        doc="Instance name (can be same as definition name)"
    )

    config: Mapped[str] = mapped_column(
        Text,
        default="{}",
        nullable=False,
        doc="Instance-specific configuration as JSON"
    )

    is_active: Mapped[bool] = mapped_column(
        default=True,
        nullable=False,
        index=True,
        doc="Whether this skill instance is active"
    )

    # Relationships
    skill_definition: Mapped[SkillDefinition] = relationship(
        "SkillDefinition",
        back_populates="skills",
        doc="Reference to SkillDefinition"
    )

    def __repr__(self) -> str:
        return (
            f"Skill(id={self.id}, name={self.name!r}, "
            f"is_active={self.is_active})"
        )

    def __str__(self) -> str:
        return self.name
