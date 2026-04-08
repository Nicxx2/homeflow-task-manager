from sqlalchemy import CheckConstraint, Integer
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base
from backend.app.models.enums import EffortLevel, effort_level_sa_enum


class TaskEffortConfig(Base):
    __tablename__ = "task_effort_configs"
    __table_args__ = (CheckConstraint("points_value > 0", name="ck_task_effort_points_positive"),)

    level: Mapped[EffortLevel] = mapped_column(
        effort_level_sa_enum,
        primary_key=True,
    )
    points_value: Mapped[int] = mapped_column(Integer, nullable=False)
