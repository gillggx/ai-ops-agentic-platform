"""DataSubject ORM model — represents a data source with API configuration."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DataSubjectModel(Base):
    """Defines a data source, its API connection, and input/output schemas."""

    __tablename__ = "data_subjects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # JSON: {"endpoint_url": str, "method": "GET|POST", "headers": {}}
    api_config: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    # JSON: {"fields": [{"name": str, "type": str, "description": str, "required": bool}]}
    input_schema: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    # JSON: {"fields": [{"name": str, "type": str, "description": str}]}
    output_schema: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
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
        return f"DataSubjectModel(id={self.id!r}, name={self.name!r})"
