from sqlalchemy import Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base


class UserSchedulingPreference(Base):
    __tablename__ = "user_scheduling_preferences"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    allow_monday: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    allow_tuesday: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    allow_wednesday: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    allow_thursday: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    allow_friday: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    allow_saturday: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    allow_sunday: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    user = relationship("User", back_populates="scheduling_preference")
