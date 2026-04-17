from datetime import date

from sqlalchemy import CheckConstraint, Date, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class UserDailyCapacityOverride(Base):
    __tablename__ = "user_daily_capacity_overrides"
    __table_args__ = (
        CheckConstraint("extra_capacity_points >= 0", name="ck_user_daily_capacity_override_nonnegative"),
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    override_date: Mapped[date] = mapped_column(Date, primary_key=True, index=True)
    extra_capacity_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
