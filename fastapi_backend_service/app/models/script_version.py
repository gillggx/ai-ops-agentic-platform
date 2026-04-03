"""ScriptVersion — versioned diagnostic code for a Skill."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ScriptVersionModel(Base):
    """One version of the Python diagnose() code compiled from a Skill."""

    __tablename__ = "script_versions"

    id:           Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    skill_id:     Mapped[int]            = mapped_column(Integer, ForeignKey("skill_definitions.id", ondelete="CASCADE"), nullable=False, index=True)
    version:      Mapped[int]            = mapped_column(Integer, nullable=False, default=1)
    # draft | approved | active | deprecated
    status:       Mapped[str]            = mapped_column(String(20), nullable=False, default="draft", index=True)
    code:         Mapped[str]            = mapped_column(Text, nullable=False)
    change_note:  Mapped[Optional[str]]  = mapped_column(Text, nullable=True)
    reviewed_by:  Mapped[Optional[str]]  = mapped_column(String(100), nullable=True)
    approved_at:  Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    generated_at: Mapped[datetime]       = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(tz=timezone.utc), server_default=func.now(),
    )

    def __repr__(self) -> str:
        return f"ScriptVersionModel(id={self.id}, skill_id={self.skill_id}, version={self.version}, status={self.status!r})"
