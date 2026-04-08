from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class AISettings(Base):
    __tablename__ = "ai_settings"
    __table_args__ = (CheckConstraint("timeout_seconds > 0", name="ck_ai_settings_timeout_positive"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ai_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    active_provider: Mapped[str] = mapped_column(String(100), nullable=False, default="ollama", server_default="ollama")
    active_model: Mapped[str] = mapped_column(
        String(255), nullable=False, default="qwen2.5:1.5b", server_default="qwen2.5:1.5b"
    )
    fallback_provider: Mapped[str] = mapped_column(
        String(100), nullable=False, default="rules", server_default="rules"
    )
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=8, server_default="8")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
