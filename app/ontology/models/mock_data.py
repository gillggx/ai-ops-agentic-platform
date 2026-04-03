"""
MockData model for the Ontology layer.

Define MockData entity for storing test/demo datasets.
定義 MockData 實體，用於存儲測試/演示數據集。
"""

from typing import Optional

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class MockData(BaseModel):
    """
    Mock/test data entry for demo and testing purposes.

    Stores sample datasets that can be used for demonstrations,
    testing, or training without using production data.

    存儲可用於演示、測試或訓練的示例數據，無需使用生產數據。

    Attributes:
        name: str - Mock data set name (數據集名稱)
        description: str - Description (描述)
        category: str - Data category (數據分類)
        data_content: str - Actual data as JSON (實際數據)
        is_featured: bool - Whether to show in UI (是否在 UI 中展示)
        source_url: str - Original source URL (原始源 URL)

    Example:
        >>> mock = MockData(
        ...     name="Sample Production Line Data",
        ...     description="Simulated data from Production Line A",
        ...     category="equipment",
        ...     data_content='{"timestamp": "2026-03-18T10:00:00Z", ...}'
        ... )
    """

    __tablename__ = "mock_data"

    name: Mapped[str] = mapped_column(
        String(200),
        unique=True,
        nullable=False,
        index=True,
        doc="Name of this mock dataset"
    )

    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Description of this mock dataset"
    )

    category: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        doc="Data category (e.g., equipment, process, sensor)"
    )

    data_content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Actual mock data as JSON"
    )

    is_featured: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        index=True,
        doc="Whether to feature this in UI"
    )

    source_url: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        doc="Original source URL if from external source"
    )

    def __repr__(self) -> str:
        """Return detailed representation."""
        return (
            f"MockData(id={self.id}, name={self.name!r}, "
            f"category={self.category!r}, is_featured={self.is_featured})"
        )

    def __str__(self) -> str:
        """Return human-readable representation."""
        return f"{self.name} ({self.category})"
