from datetime import date

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from backend.app.models.task import Task
from backend.app.models.user_daily_capacity import UserDailyCapacity
from backend.app.services.scheduling_service import SchedulingService


class WorkloadService:
    def __init__(self, db: Session):
        self.db = db
        self.scheduling = SchedulingService(db)

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
        allow_policy_override: bool = False,
    ) -> dict:
        today = date.today()
        is_past_date = date_value < today
        schedule_block = self.scheduling.get_block_for_date(user_id=user_id, date_value=date_value)
        current_points = self.get_daily_points(user_id=user_id, date_value=date_value, exclude_task_id=exclude_task_id)
        capacity = self.get_user_capacity(user_id)
        projected_points = current_points + task_points
        task_too_large = capacity is not None and task_points > capacity
        blocked_by_policy = schedule_block is not None and not allow_policy_override
        fits_capacity = capacity is not None and projected_points <= capacity
        fits = fits_capacity and not blocked_by_policy and not is_past_date

        suggestion = None
        if not fits and capacity is not None and not task_too_large and not allow_policy_override:
            suggestion = self.suggest_next_available_date(
                user_id=user_id,
                task_points=task_points,
                start_date=today if is_past_date else date_value,
                max_days=30,
                exclude_task_id=exclude_task_id,
            )
        elif not fits and capacity is not None and not task_too_large and allow_policy_override:
            suggestion = self.suggest_next_available_date(
                user_id=user_id,
                task_points=task_points,
                start_date=today if is_past_date else date_value,
                max_days=30,
                exclude_task_id=exclude_task_id,
                allow_policy_override=True,
            )

        message = "Assignment is within capacity."
        if is_past_date:
            message = "Assignment date cannot be in the past."
        elif capacity is None:
            message = "No daily capacity configured for this user."
        elif task_too_large:
            message = "This task is larger than the user's daily capacity, so it cannot be assigned on any day."
        elif blocked_by_policy and schedule_block is not None:
            message = schedule_block["message"]
        elif not fits:
            message = "Assignment exceeds daily capacity."
            if suggestion is None:
                message = "Assignment exceeds daily capacity and no available date was found in the next 30 days."
        elif schedule_block is not None and allow_policy_override:
            message = f"{schedule_block['message']} Admin override is enabled for this assignment."

        return {
            "valid": fits,
            "user_id": user_id,
            "date": date_value.isoformat(),
            "task_points": task_points,
            "current_points": current_points,
            "projected_points": projected_points,
            "capacity": capacity,
            "is_past_date": is_past_date,
            "task_too_large": task_too_large,
            "blocked_by_policy": blocked_by_policy,
            "policy_override_applied": allow_policy_override and schedule_block is not None,
            "blocked_reason": schedule_block["message"] if schedule_block else None,
            "blocked_type": schedule_block.get("type") if schedule_block else None,
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
        allow_policy_override: bool = False,
    ) -> date | None:
        capacity = self.get_user_capacity(user_id)
        if capacity is None or task_points > capacity:
            return None

        search_start = max(start_date, date.today())
        for offset in range(0, max_days + 1):
            candidate = date.fromordinal(search_start.toordinal() + offset)
            if not allow_policy_override and self.scheduling.get_block_for_date(user_id=user_id, date_value=candidate):
                continue
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
