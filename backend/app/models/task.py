from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base
from backend.app.models.enums import EffortLevel, TaskStatus, effort_level_sa_enum, task_status_sa_enum


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint("points_value > 0", name="ck_tasks_points_value_positive"),
        CheckConstraint(
            "(ai_confidence IS NULL) OR (ai_confidence >= 0 AND ai_confidence <= 1)",
            name="ck_tasks_ai_confidence_range",
        ),
        CheckConstraint(
            "(assignee_id IS NULL AND assignment_date IS NULL) OR (assignee_id IS NOT NULL AND assignment_date IS NOT NULL)",
            name="ck_tasks_assignment_pair",
        ),
        CheckConstraint(
            "(recurrence_interval_weeks IS NULL) OR (recurrence_interval_weeks > 0)",
            name="ck_tasks_recurrence_interval_positive",
        ),
        CheckConstraint(
            "(recurrence_count_limit IS NULL) OR (recurrence_count_limit > 0)",
            name="ck_tasks_recurrence_count_positive",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    assignment_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    effort_level: Mapped[EffortLevel] = mapped_column(effort_level_sa_enum, nullable=False, index=True)
    points_value: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[TaskStatus] = mapped_column(
        task_status_sa_enum,
        nullable=False,
        default=TaskStatus.PENDING,
        server_default=TaskStatus.PENDING.value,
        index=True,
    )
    ai_suggested_level: Mapped[EffortLevel | None] = mapped_column(
        effort_level_sa_enum,
        nullable=True,
    )
    ai_confidence: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)
    ai_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_provider_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ai_model_used: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fallback_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    recurrence_pattern: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    recurrence_interval_weeks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recurrence_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    recurrence_count_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recurrence_blocked_behavior: Mapped[str | None] = mapped_column(String(30), nullable=True)
    recurrence_late_behavior: Mapped[str | None] = mapped_column(String(30), nullable=True)
    recurrence_parent_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    recurrence_anchor_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    recurrence_occurrence_index: Mapped[int | None] = mapped_column(Integer, nullable=True, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    assignee = relationship("User", foreign_keys=[assignee_id], back_populates="assigned_tasks")
    created_by = relationship("User", foreign_keys=[created_by_id], back_populates="created_tasks")
    recurrence_parent = relationship("Task", remote_side=[id])
