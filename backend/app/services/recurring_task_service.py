from datetime import date, timedelta
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.enums import TaskStatus
from backend.app.models.task import Task
from backend.app.models.user_task_display_preference import UserTaskDisplayPreference
from backend.app.services.workload_service import WorkloadService


class RecurringTaskService:
    def __init__(self, db: Session):
        self.db = db
        self.workload = WorkloadService(db)

    def preview_next_occurrence(self, root: Task) -> dict | None:
        return self._next_occurrence_after_current(root)

    def current_occurrence_index(self, root: Task) -> int:
        return self._current_occurrence_index(root)

    def remaining_count_limit_occurrences(self, root: Task) -> int | None:
        if not root.recurrence_count_limit:
            return None
        return max(root.recurrence_count_limit - self.current_occurrence_index(root), 0)

    def remaining_occurrence_count(self, root: Task) -> int | None:
        if not root.recurrence_count_limit and not root.recurrence_until:
            return None

        cursor = SimpleNamespace(
            due_date=root.due_date,
            assignment_date=root.assignment_date,
            assignee_id=root.assignee_id,
            points_value=root.points_value,
            recurrence_interval_weeks=root.recurrence_interval_weeks,
            recurrence_count_limit=root.recurrence_count_limit,
            recurrence_until=root.recurrence_until,
            recurrence_blocked_behavior=root.recurrence_blocked_behavior,
            recurrence_anchor_date=root.recurrence_anchor_date,
            recurrence_occurrence_index=self.current_occurrence_index(root),
        )

        remaining = 0
        while True:
            next_occurrence = self._next_occurrence_after_current(cursor)
            if next_occurrence is None:
                return remaining
            remaining += 1
            cursor.due_date = next_occurrence["due_date"]
            cursor.assignment_date = next_occurrence["assignment_date"]
            cursor.assignee_id = next_occurrence["assignee_id"]
            cursor.recurrence_occurrence_index = next_occurrence["occurrence_index"]

    def sync(self) -> int:
        legacy_occurrences = list(
            self.db.scalars(
                select(Task).where(
                    Task.recurrence_parent_id.is_not(None),
                    Task.status != TaskStatus.COMPLETED,
                )
            ).all()
        )
        if not legacy_occurrences:
            return 0

        removed_count = len(legacy_occurrences)
        for item in legacy_occurrences:
            self.db.delete(item)
        self.db.commit()
        return removed_count

    def complete_occurrence(self, root: Task) -> Task:
        self.sync()
        next_occurrence = self._next_occurrence_after_current(root)
        if next_occurrence is None:
            root.status = TaskStatus.COMPLETED
            self.db.add(root)
            self.db.commit()
            self.db.refresh(root)
            return root

        self._create_completed_snapshot(root)
        root.status = TaskStatus.PENDING
        root.due_date = next_occurrence["due_date"]
        root.assignment_date = next_occurrence["assignment_date"]
        root.assignee_id = next_occurrence["assignee_id"]
        root.recurrence_occurrence_index = next_occurrence["occurrence_index"]
        self.db.add(root)
        self.db.commit()
        self.db.refresh(root)
        return root

    def delete_current_occurrence(self, root: Task) -> Task | None:
        self.sync()
        next_occurrence = self._next_occurrence_after_current(root)
        if next_occurrence is None:
            history_items = list(
                self.db.scalars(
                    select(Task).where(
                        Task.recurrence_parent_id == root.id,
                        Task.status == TaskStatus.COMPLETED,
                    )
                ).all()
            )
            for history_item in history_items:
                history_item.recurrence_parent_id = None
                self.db.add(history_item)

            display_preferences = list(
                self.db.scalars(
                    select(UserTaskDisplayPreference).where(UserTaskDisplayPreference.task_id == root.id)
                ).all()
            )
            for preference in display_preferences:
                self.db.delete(preference)

            self.db.delete(root)
            self.db.commit()
            return None

        root.status = TaskStatus.PENDING
        root.due_date = next_occurrence["due_date"]
        root.assignment_date = next_occurrence["assignment_date"]
        root.assignee_id = next_occurrence["assignee_id"]
        root.recurrence_occurrence_index = next_occurrence["occurrence_index"]
        self.db.add(root)
        self.db.commit()
        self.db.refresh(root)
        return root

    def _current_occurrence_index(self, root: Task) -> int:
        stored_index = getattr(root, "recurrence_occurrence_index", None)
        if stored_index is not None:
            return max(stored_index, 0)
        anchor = root.recurrence_anchor_date or root.due_date
        interval_days = max((root.recurrence_interval_weeks or 1) * 7, 1)
        delta_days = max((root.due_date - anchor).days, 0)
        return delta_days // interval_days

    def _resolve_occurrence_date(self, root: Task, scheduled_date: date) -> date | None:
        if root.assignee_id is None:
            return scheduled_date

        block = self.workload.scheduling.get_block_for_date(user_id=root.assignee_id, date_value=scheduled_date)
        if block is None:
            return scheduled_date

        if root.recurrence_blocked_behavior == "move_same_week":
            for offset in range(1, 7):
                candidate = scheduled_date + timedelta(days=offset)
                if candidate.weekday() <= scheduled_date.weekday():
                    break
                if self.workload.scheduling.get_block_for_date(user_id=root.assignee_id, date_value=candidate) is None:
                    return candidate
            return None

        return None

    def _next_occurrence_after_current(self, root: Task) -> dict | None:
        anchor = root.recurrence_anchor_date or root.due_date
        interval_weeks = root.recurrence_interval_weeks or 1
        next_index = self.current_occurrence_index(root) + 1

        while True:
            if root.recurrence_count_limit and next_index >= root.recurrence_count_limit:
                return None

            scheduled_date = anchor + timedelta(weeks=interval_weeks * next_index)
            if root.recurrence_until and scheduled_date > root.recurrence_until:
                return None

            resolved_due_date = self._resolve_occurrence_date(root, scheduled_date)
            if resolved_due_date is None:
                next_index += 1
                continue

            assignee_id = root.assignee_id
            assignment_date = None
            if assignee_id is not None:
                validation = self.workload.validate_assignment(
                    user_id=assignee_id,
                    date_value=resolved_due_date,
                    task_points=root.points_value,
                )
                if validation["valid"]:
                    assignment_date = resolved_due_date
                elif validation.get("next_available_date"):
                    assignment_date = date.fromisoformat(validation["next_available_date"])
                else:
                    assignee_id = None

            return {
                "occurrence_index": next_index,
                "due_date": resolved_due_date,
                "assignment_date": assignment_date,
                "assignee_id": assignee_id if assignment_date is not None else None,
            }

    def _create_completed_snapshot(self, root: Task) -> Task:
        history = Task(
            title=root.title,
            description=root.description,
            due_date=root.due_date,
            assignment_date=root.assignment_date,
            assignee_id=root.assignee_id,
            created_by_id=root.created_by_id,
            effort_level=root.effort_level,
            points_value=root.points_value,
            status=TaskStatus.COMPLETED,
            ai_suggested_level=root.ai_suggested_level,
            ai_confidence=root.ai_confidence,
            ai_reason=root.ai_reason,
            ai_provider_used=root.ai_provider_used,
            ai_model_used=root.ai_model_used,
            fallback_used=root.fallback_used,
            recurrence_parent_id=root.id,
        )
        self.db.add(history)
        self.db.flush()
        return history

    def get_history(self, root_id: int, *, limit: int = 12) -> list[Task]:
        return list(
            self.db.scalars(
                select(Task)
                .where(
                    Task.recurrence_parent_id == root_id,
                    Task.status == TaskStatus.COMPLETED,
                )
                .order_by(Task.due_date.desc(), Task.id.desc())
                .limit(limit)
            ).all()
        )
