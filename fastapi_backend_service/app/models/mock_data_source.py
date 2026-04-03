"""MockDataSource ORM model — user-defined Python-powered mock API endpoints."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MockDataSourceModel(Base):
    """A programmable mock data source.

    Exposes a GET/POST endpoint at /api/v1/mock-data/{id}/run that executes
    python_code in the sandbox and returns a System MCP-compatible response.
    Useful for demo environments where real factory APIs are unavailable.
    """

    __tablename__ = "mock_data_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # JSON: {"fields": [{"name", "type", "description", "required"}]}
    input_schema: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Python code defining generate(params: dict) -> list | dict
    python_code: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Last run output (truncated JSON for preview)
    sample_output: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Whether this source is active (exposed as a callable endpoint)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
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
        return f"MockDataSourceModel(id={self.id!r}, name={self.name!r})"
