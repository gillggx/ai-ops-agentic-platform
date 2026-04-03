"""
Base models for Ontology Layer.

This module provides the base classes and mixins for all ORM models
in the Ontology layer. All models inherit from these base classes
to ensure consistency and common functionality.

本模塊提供 Ontology 層所有 ORM 模型的基類和 Mixin。
所有模型繼承自這些基類，確保一致性和通用功能。
"""

from datetime import datetime
from typing import Any

from sqlalchemy import Column, DateTime, Integer
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """
    Base declarative class for all SQLAlchemy ORM models.
    
    SQLAlchemy 2.0 異步 ORM 的基類。
    """

    pass


class TimestampMixin:
    """
    Mixin class that adds timestamp tracking to models.
    
    Provides automatic tracking of:
    - created_at: 記錄創建時間
    - updated_at: 記錄最後更新時間
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
        doc="Creation timestamp (UTC)"
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
        doc="Last update timestamp (UTC)"
    )


class CommonMixin(TimestampMixin):
    """
    Common mixin for all business entities.
    
    Combines timestamp tracking with other common functionality.
    繼承 TimestampMixin，為所有業務實體提供通用功能。
    """

    pass


class BaseModel(Base, CommonMixin):
    """
    Base model class for all Ontology layer entities.
    
    All business models should inherit from this class.
    
    Provides:
    - id: Primary key
    - created_at, updated_at: Timestamps
    - __repr__, __str__: String representations
    
    所有業務模型應繼承此類。
    """

    __abstract__ = True

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        doc="Primary key"
    )

    def __repr__(self) -> str:
        """
        Return a detailed representation of the model instance.
        
        用於調試，顯示所有屬性。
        """
        attrs = []
        for column in self.__table__.columns:
            value = getattr(self, column.name)
            attrs.append(f"{column.name}={value!r}")
        return f"{self.__class__.__name__}({', '.join(attrs)})"

    def __str__(self) -> str:
        """
        Return a human-readable string representation.
        
        用於顯示，簡潔清晰。
        """
        return f"{self.__class__.__name__}(id={self.id})"

    def to_dict(self) -> dict[str, Any]:
        """
        Convert model instance to a dictionary.
        
        Returns a dictionary representation of all attributes.
        用於序列化，返回所有屬性的字典。
        
        Returns:
            dict: 模型的字典表示，包含所有列
        
        Example:
            >>> user = User(id=1, username="test")
            >>> user.to_dict()
            {'id': 1, 'username': 'test', 'created_at': ..., ...}
        """
        result = {}
        for column in self.__table__.columns:
            value = getattr(self, column.name)
            # Handle datetime objects
            if isinstance(value, datetime):
                result[column.name] = value.isoformat()
            else:
                result[column.name] = value
        return result


# 類型別名，用於類型提示
ModelType = BaseModel
