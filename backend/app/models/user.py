from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm import relationship

from backend.app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    approval_status: Mapped[str] = mapped_column(String(20), default="approved", nullable=False, server_default="approved")
    show_in_member_lists: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, server_default="true")
    theme_preference: Mapped[str] = mapped_column(String(20), default="light", nullable=False, server_default="light")
    accent_color: Mapped[str] = mapped_column(String(7), default="#4f46e5", nullable=False, server_default="#4f46e5")
    overdue_color: Mapped[str] = mapped_column(String(7), default="#dc2626", nullable=False, server_default="#dc2626")
    recurring_color: Mapped[str] = mapped_column(String(7), default="#0f766e", nullable=False, server_default="#0f766e")
    in_progress_color: Mapped[str] = mapped_column(String(7), default="#d97706", nullable=False, server_default="#d97706")
    unassigned_color: Mapped[str] = mapped_column(String(7), default="#475569", nullable=False, server_default="#475569")
    task_category_button_color_mode: Mapped[str] = mapped_column(
        String(20), default="match", nullable=False, server_default="match"
    )
    task_category_overdue_color: Mapped[str] = mapped_column(
        String(7), default="#dc2626", nullable=False, server_default="#dc2626"
    )
    task_category_up_next_color: Mapped[str] = mapped_column(
        String(7), default="#4f46e5", nullable=False, server_default="#4f46e5"
    )
    task_category_later_color: Mapped[str] = mapped_column(
        String(7), default="#0f766e", nullable=False, server_default="#0f766e"
    )
    task_category_unassigned_color: Mapped[str] = mapped_column(
        String(7), default="#475569", nullable=False, server_default="#475569"
    )
    task_category_in_progress_color: Mapped[str] = mapped_column(
        String(7), default="#d97706", nullable=False, server_default="#d97706"
    )
    task_category_completed_color: Mapped[str] = mapped_column(
        String(7), default="#64748b", nullable=False, server_default="#64748b"
    )
    surface_style: Mapped[str] = mapped_column(String(20), default="clean", nullable=False, server_default="clean")
    density_preference: Mapped[str] = mapped_column(
        String(20), default="comfortable", nullable=False, server_default="comfortable"
    )
    decoration_style: Mapped[str] = mapped_column(String(20), default="none", nullable=False, server_default="none")
    session_timeout_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    created_tasks = relationship("Task", foreign_keys="Task.created_by_id", back_populates="created_by")
    assigned_tasks = relationship("Task", foreign_keys="Task.assignee_id", back_populates="assignee")
    daily_capacity = relationship("UserDailyCapacity", back_populates="user", uselist=False)
    scheduling_preference = relationship("UserSchedulingPreference", back_populates="user", uselist=False)
    away_periods = relationship("UserAwayPeriod", back_populates="user")
