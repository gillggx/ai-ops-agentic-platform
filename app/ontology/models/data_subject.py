"""
DataSubject model for the Ontology layer.

Define the DataSubject entity representing subjects of data analysis.
定義 DataSubject 實體，代表數據分析的主體。
"""

from typing import Optional

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel


class DataSubject(BaseModel):
    """
    Data Subject representing an entity under observation or analysis.

    Represents a specific entity (equipment, system, process) that
    generates or is subject to data analysis (e.g., Production Line A,
    Equipment #42, Customer 12345).

    代表被觀察或分析的具體實體（設備、系統、流程等）。
    例如：生產線 A、設備 #42、客戶 12345。

    Attributes:
        name: str - Human-readable name (人類可讀的名稱)
        description: str - Detailed description (詳細描述)
        category: str - Classification category (分類)
        external_id: str - External system ID (外部系統 ID)
        metadata: str - JSON metadata (JSON 元數據)
        is_active: bool - Whether this subject is actively monitored (是否活躍監控)

    Example:
        >>> subject = DataSubject(
        ...     name="Production Line A",
        ...     description="Main manufacturing line in Building 1",
        ...     category="equipment",
        ...     external_id="line_a_001"
        ... )
    """

    __tablename__ = "data_subjects"

    name: Mapped[str] = mapped_column(
        String(200),
        unique=True,
        nullable=False,
        index=True,
        doc="Human-readable name (人類可讀的名稱)"
    )

    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Detailed description of this data subject"
    )

    category: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        doc="Classification category (e.g., equipment, process, customer)"
    )

    external_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        unique=True,
        nullable=True,
        index=True,
        doc="External system ID (e.g., from legacy system)"
    )

    custom_metadata: Mapped[str] = mapped_column(
        Text,
        default="{}",
        nullable=False,
        doc="Additional metadata as JSON (自定義元數據)"
    )

    is_active: Mapped[bool] = mapped_column(
        default=True,
        nullable=False,
        index=True,
        doc="Whether this subject is actively monitored"
    )

    # ── Ontology knowledge fields ─────────────────────────────────────────────
    #
    # api_config: JSON describing how to fetch live data for this subject.
    #   Shape example:
    #     {"endpoint": "/api/data/line_a", "method": "GET",
    #      "auth": "bearer", "params": {"resolution": "1m"}}
    #   Used by MCP execution runtime to know WHERE to pull data from.
    api_config: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        doc="JSON: API endpoint config for fetching live data for this subject"
    )
    # input_schema: JSON Schema describing the shape of data THIS subject PRODUCES.
    #   Lets the agent validate that incoming event data matches expectations
    #   and auto-map event fields to skill parameters.
    #   Shape example: {"type": "object", "properties": {"value": {"type": "number"}, ...}}
    input_schema: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        doc="JSON Schema: shape of data this subject produces (used for param auto-mapping)"
    )
    # output_schema: JSON Schema for the processed/aggregated output after MCP runs.
    output_schema: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        doc="JSON Schema: shape of the processed output after MCPs execute on this subject"
    )
    # is_builtin: platform-defined subjects cannot be deleted by users.
    is_builtin: Mapped[Optional[bool]] = mapped_column(
        nullable=True, default=False,
        doc="True = platform-defined subject (read-only to end users)"
    )

    def __repr__(self) -> str:
        """Return detailed representation."""
        return (
            f"DataSubject(id={self.id}, name={self.name!r}, "
            f"category={self.category!r}, is_active={self.is_active})"
        )

    def __str__(self) -> str:
        """Return human-readable representation."""
        return f"{self.name} ({self.category})"
