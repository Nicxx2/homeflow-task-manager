from datetime import date

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from backend.app.models.task import Task
from backend.app.models.user_daily_capacity import UserDailyCapacity


class WorkloadService:
    def __init__(self, db: Session):
        self.db = db

    def _assigned_points_stmt(self, *, user_id: int, date_value: date, exclude_task_id: int | None = None) -> Select:
        stmt = select(func.coalesce(func.sum(Task.points_value), 0)).where(
            Task.assignee_id == user_id,
            Task.assignment_date == date_value,
        )
        if exclude_task_id is not None:
            stmt = stmt.where(Task.id != exclude_task_id)
        return stmt

    def get_daily_points(self, *, user_id: int, date_value: date, exclude_task_id: int | None = None) -> int:
        """
        Counts all assigned task points for the given user/date.
        Completed tasks still count because daily capacity reflects energy spent on that day.
        """
        value = self.db.scalar(self._assigned_points_stmt(user_id=user_id, date_value=date_value, exclude_task_id=exclude_task_id))
        return int(value or 0)

    def get_user_capacity(self, user_id: int) -> int | None:
        capacity = self.db.get(UserDailyCapacity, user_id)
        return capacity.daily_capacity_points if capacity else None

    def validate_assignment(
        self,
        *,
        user_id: int,
        date_value: date,
        task_points: int,
        exclude_task_id: int | None = None,
    ) -> dict:
        current_points = self.get_daily_points(user_id=user_id, date_value=date_value, exclude_task_id=exclude_task_id)
        capacity = self.get_user_capacity(user_id)
        projected_points = current_points + task_points
        fits = capacity is not None and projected_points <= capacity

        suggestion = None
        if not fits and capacity is not None:
            suggestion = self.suggest_next_available_date(
                user_id=user_id,
                task_points=task_points,
                start_date=date_value,
                max_days=30,
                exclude_task_id=exclude_task_id,
            )

        message = "Assignment is within capacity."
        if capacity is None:
            message = "No daily capacity configured for this user."
        elif not fits:
            message = "Assignment exceeds daily capacity."
            if suggestion is None:
                message = "Assignment exceeds daily capacity and no available date was found in the next 30 days."

        return {
            "valid": fits,
            "user_id": user_id,
            "date": date_value.isoformat(),
            "task_points": task_points,
            "current_points": current_points,
            "projected_points": projected_points,
            "capacity": capacity,
            "next_available_date": suggestion.isoformat() if suggestion else None,
            "message": message,
        }

    def suggest_next_available_date(
        self,
        *,
        user_id: int,
        task_points: int,
        start_date: date,
        max_days: int = 30,
        exclude_task_id: int | None = None,
    ) -> date | None:
        capacity = self.get_user_capacity(user_id)
        if capacity is None:
            return None

        for offset in range(0, max_days + 1):
            candidate = date.fromordinal(start_date.toordinal() + offset)
            current = self.get_daily_points(user_id=user_id, date_value=candidate, exclude_task_id=exclude_task_id)
            if current + task_points <= capacity:
                return candidate
        return None

    def get_tasks_for_user_on_date(self, *, user_id: int, date_value: date) -> list[Task]:
        stmt = (
            select(Task)
            .where(Task.assignee_id == user_id, Task.assignment_date == date_value)
            .order_by(Task.due_date.asc(), Task.created_at.desc())
        )
        return list(self.db.scalars(stmt).all())
