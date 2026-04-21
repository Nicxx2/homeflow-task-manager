from datetime import date

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from backend.app.models.task import Task
from backend.app.models.user_daily_capacity import UserDailyCapacity
from backend.app.models.user_daily_capacity_override import UserDailyCapacityOverride
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

    def get_base_user_capacity(self, user_id: int) -> int | None:
        capacity = self.db.get(UserDailyCapacity, user_id)
        return capacity.daily_capacity_points if capacity else None

    def get_extra_capacity_points(self, *, user_id: int, date_value: date) -> int:
        override = self.db.get(UserDailyCapacityOverride, {"user_id": user_id, "override_date": date_value})
        return override.extra_capacity_points if override else 0

    def get_user_capacity(self, user_id: int, *, date_value: date | None = None) -> int | None:
        base_capacity = self.get_base_user_capacity(user_id)
        if base_capacity is None or date_value is None:
            return base_capacity
        return base_capacity + self.get_extra_capacity_points(user_id=user_id, date_value=date_value)

    def get_capacity_breakdown(self, *, user_id: int, date_value: date) -> dict[str, int | None]:
        base_capacity = self.get_base_user_capacity(user_id)
        extra_capacity = self.get_extra_capacity_points(user_id=user_id, date_value=date_value) if base_capacity is not None else 0
        total_capacity = None if base_capacity is None else base_capacity + extra_capacity
        return {
            "base_capacity": base_capacity,
            "extra_capacity": extra_capacity,
            "total_capacity": total_capacity,
        }

    def set_extra_capacity_points(self, *, user_id: int, date_value: date, extra_capacity_points: int) -> None:
        base_capacity = self.get_base_user_capacity(user_id)
        if base_capacity is None:
            raise ValueError("This user does not have a base daily capacity yet.")
        if extra_capacity_points < 0:
            raise ValueError("Extra capacity cannot be negative.")

        existing = self.db.get(UserDailyCapacityOverride, {"user_id": user_id, "override_date": date_value})
        if extra_capacity_points == 0:
            if existing:
                self.db.delete(existing)
                self.db.commit()
            return

        if existing:
            existing.extra_capacity_points = extra_capacity_points
            self.db.add(existing)
        else:
            self.db.add(
                UserDailyCapacityOverride(
                    user_id=user_id,
                    override_date=date_value,
                    extra_capacity_points=extra_capacity_points,
                )
            )
        self.db.commit()

    def set_extra_capacity_points_range(
        self,
        *,
        user_id: int,
        start_date: date,
        end_date: date,
        extra_capacity_points: int,
    ) -> None:
        base_capacity = self.get_base_user_capacity(user_id)
        if base_capacity is None:
            raise ValueError("This user does not have a base daily capacity yet.")
        if extra_capacity_points < 0:
            raise ValueError("Extra capacity cannot be negative.")
        if end_date < start_date:
            raise ValueError("End date must be on or after the start date.")

        existing_rows = {
            row.override_date: row
            for row in self.db.scalars(
                select(UserDailyCapacityOverride).where(
                    UserDailyCapacityOverride.user_id == user_id,
                    UserDailyCapacityOverride.override_date >= start_date,
                    UserDailyCapacityOverride.override_date <= end_date,
                )
            ).all()
        }

        for ordinal in range(start_date.toordinal(), end_date.toordinal() + 1):
            candidate_date = date.fromordinal(ordinal)
            existing = existing_rows.get(candidate_date)
            if extra_capacity_points == 0:
                if existing:
                    self.db.delete(existing)
                continue

            if existing:
                existing.extra_capacity_points = extra_capacity_points
                self.db.add(existing)
            else:
                self.db.add(
                    UserDailyCapacityOverride(
                        user_id=user_id,
                        override_date=candidate_date,
                        extra_capacity_points=extra_capacity_points,
                    )
                )

        self.db.commit()

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
        base_capacity = self.get_base_user_capacity(user_id)
        capacity = self.get_user_capacity(user_id, date_value=date_value)
        projected_points = current_points + task_points
        blocked_by_policy = schedule_block is not None and not allow_policy_override
        fits_capacity = capacity is not None and projected_points <= capacity
        fits = fits_capacity and not blocked_by_policy and not is_past_date

        suggestion = None
        suggestion_start = today if is_past_date else date.fromordinal(date_value.toordinal() + 1)
        if not fits and capacity is not None and not allow_policy_override:
            suggestion = self.suggest_next_available_date(
                user_id=user_id,
                task_points=task_points,
                start_date=suggestion_start,
                max_days=30,
                exclude_task_id=exclude_task_id,
            )
        elif not fits and capacity is not None and allow_policy_override:
            suggestion = self.suggest_next_available_date(
                user_id=user_id,
                task_points=task_points,
                start_date=suggestion_start,
                max_days=30,
                exclude_task_id=exclude_task_id,
                allow_policy_override=True,
            )

        # A task is "too large" only when it exceeds the user's baseline daily capacity
        # and there is no future date in the search window where configured capacity would fit it.
        task_too_large = (
            base_capacity is not None
            and task_points > base_capacity
            and suggestion is None
        )

        message = "Assignment is within capacity."
        if is_past_date:
            message = "Assignment date cannot be in the past."
        elif capacity is None:
            message = "No daily capacity configured for this user."
        elif blocked_by_policy and schedule_block is not None:
            message = schedule_block["message"]
        elif task_too_large:
            message = "Task exceeds this user's daily capacity and cannot be assigned on any day unless their capacity changes."
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
        base_capacity = self.get_base_user_capacity(user_id)
        if base_capacity is None:
            return None

        search_start = max(start_date, date.today())
        for offset in range(0, max_days + 1):
            candidate = date.fromordinal(search_start.toordinal() + offset)
            candidate_capacity = self.get_user_capacity(user_id, date_value=candidate)
            if candidate_capacity is None or task_points > candidate_capacity:
                continue
            if not allow_policy_override and self.scheduling.get_block_for_date(user_id=user_id, date_value=candidate):
                continue
            current = self.get_daily_points(user_id=user_id, date_value=candidate, exclude_task_id=exclude_task_id)
            if current + task_points <= candidate_capacity:
                return candidate
        return None

    def get_tasks_for_user_on_date(self, *, user_id: int, date_value: date) -> list[Task]:
        stmt = (
            select(Task)
            .where(Task.assignee_id == user_id, Task.assignment_date == date_value)
            .order_by(Task.due_date.asc(), Task.created_at.desc())
        )
        return list(self.db.scalars(stmt).all())
