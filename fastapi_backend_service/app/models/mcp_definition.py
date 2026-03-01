"""MCPDefinition ORM model — a data-processing + visualization pipeline block."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MCPDefinitionModel(Base):
    """MCP (Measurement Collection Pipeline) — turns raw DataSubject data into
    processed datasets and UI-renderable charts."""

    __tablename__ = "mcp_definitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    data_subject_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("data_subjects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # What the user wants to compute, e.g. "計算移動平均線並標示 OOC 點位"
    processing_intent: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # LLM-generated Python script (runs in sandbox)
    processing_script: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # LLM-defined output dataset schema: {"fields": [...]}
    output_schema: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # LLM-suggested UI render config: {"chart_type": "trend|table|bar", "x_axis": str, "y_axis": str, ...}
    ui_render_config: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # LLM-analyzed input params: {"params": [{"name": str, "type": str, "source": "event|manual", "description": str}]}
    input_definition: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Real output produced by the Try Run sandbox execution (stored as truncated JSON)
    sample_output: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(tz=timezone.utc), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(tz=timezone.utc), server_default=func.now(),
        onupdate=lambda: datetime.now(tz=timezone.utc),
    )

    def __repr__(self) -> str:
        return f"MCPDefinitionModel(id={self.id!r}, name={self.name!r})"
