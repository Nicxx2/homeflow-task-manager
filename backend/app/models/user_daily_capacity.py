from sqlalchemy import CheckConstraint, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base


class UserDailyCapacity(Base):
    __tablename__ = "user_daily_capacities"
    __table_args__ = (CheckConstraint("daily_capacity_points > 0", name="ck_user_daily_capacity_positive"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    daily_capacity_points: Mapped[int] = mapped_column(Integer, nullable=False)

    user = relationship("User", back_populates="daily_capacity")
