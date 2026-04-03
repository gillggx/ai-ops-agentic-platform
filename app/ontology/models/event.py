"""
Event models for the Ontology layer.

Define Event and EventType entities for event-driven architecture.
定義事件驅動架構的 Event 和 EventType 實體。
"""

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .skill import SkillDefinition

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel


class EventType(BaseModel):
    """
    Event type definition.
    
    Represents a type of event in the system (e.g., SPC_OOC, Equipment_Down).
    定義系統中的事件類型。
    
    Attributes:
        name: str - Unique event type name (唯一事件類型名稱)
        description: str - Description of this event type (事件類型描述)
        attributes: str - JSON schema for event attributes (事件屬性的 JSON Schema)
    """

    __tablename__ = "event_types"

    name: Mapped[str] = mapped_column(
        String(200),
        unique=True,
        nullable=False,
        index=True,
        doc="Unique event type name (e.g., SPC_OOC, Equipment_Down)"
    )

    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Description of this event type"
    )

    attributes: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="JSON schema defining event attributes structure"
    )

    # Original dev.db fields — nullable for backward compat
    spc_chart: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # Legacy JSON array of skill IDs (e.g. "[1, 3, 5]").
    # Prefer the ORM relationship `skill_definitions` for new code.
    diagnosis_skill_ids: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default="[]")

    # Relationships
    events: Mapped[list["Event"]] = relationship(
        "Event",
        back_populates="event_type",
        cascade="all, delete-orphan",
        doc="Events of this type"
    )
    # SkillDefinitions whose event_type_id points to this EventType.
    # Semantics: "when this EventType fires, run these skills to diagnose it."
    skill_definitions: Mapped[list["SkillDefinition"]] = relationship(
        "SkillDefinition",
        foreign_keys="SkillDefinition.event_type_id",
        back_populates="event_type",
        doc="Skill definitions triggered by this event type (diagnosis_skill_ids authoritative for legacy data)"
    )

    def __repr__(self) -> str:
        return f"EventType(id={self.id}, name={self.name!r})"

    def __str__(self) -> str:
        return self.name


class Event(BaseModel):
    """
    Individual event instance.
    
    Represents a specific occurrence of an event in the system.
    代表系統中事件的具體發生。
    
    Attributes:
        event_type_id: int - FK to EventType (事件類型外鍵)
        source: str - Event source identifier (事件源)
        data: str - Event data as JSON (事件數據)
        processed: bool - Whether event has been processed (是否已處理)
    """

    __tablename__ = "events"

    event_type_id: Mapped[int] = mapped_column(
        ForeignKey("event_types.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Reference to EventType"
    )

    source: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        doc="Event source identifier (e.g., sensor_1, system_monitor)"
    )

    data: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Event data as JSON string"
    )

    processed: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        index=True,
        doc="Whether event has been processed"
    )

    # Relationships
    event_type: Mapped[EventType] = relationship(
        "EventType",
        back_populates="events",
        doc="Reference to EventType"
    )

    def __repr__(self) -> str:
        return (
            f"Event(id={self.id}, event_type_id={self.event_type_id}, "
            f"source={self.source!r}, processed={self.processed})"
        )

    def __str__(self) -> str:
        return f"Event#{self.id} ({self.source})"
