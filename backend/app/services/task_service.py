from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.models.enums import EffortLevel, TaskStatus
from backend.app.models.task import Task
from backend.app.models.task_effort_config import TaskEffortConfig
from backend.app.models.user import User
from backend.app.schemas.task import TaskCreate, TaskUpdate
from backend.app.services.recurring_task_service import RecurringTaskService
from backend.app.services.workload_service import WorkloadService


class TaskService:
    def __init__(self, db: Session):
        self.db = db

    def _points_for_level(self, effort_level: EffortLevel) -> int:
        config = self.db.get(TaskEffortConfig, effort_level)
        if not config:
            raise ValueError(f"No points configured for level '{effort_level.value}'.")
        return config.points_value

    def create_unassigned_task(self, payload: TaskCreate, created_by: User) -> Task:
        task = Task(
            title=payload.title.strip(),
            description=payload.description.strip(),
            due_date=payload.due_date,
            assignee_id=None,
            created_by_id=created_by.id,
            effort_level=payload.effort_level,
            points_value=self._points_for_level(payload.effort_level),
            ai_suggested_level=payload.ai_suggested_level,
            ai_confidence=payload.ai_confidence,
            ai_reason=payload.ai_reason,
            ai_provider_used=payload.provider_used,
            ai_model_used=payload.model_used,
            fallback_used=payload.fallback_used,
            recurrence_pattern=payload.recurrence_pattern,
            recurrence_interval_weeks=payload.recurrence_interval_weeks,
            recurrence_until=payload.recurrence_until,
            recurrence_count_limit=payload.recurrence_count_limit,
            recurrence_blocked_behavior=payload.recurrence_blocked_behavior,
            recurrence_anchor_date=payload.due_date if payload.recurrence_pattern else None,
        )
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)
        return task

    def get_tasks(self, *, only_unassigned: bool | None = None, include_history: bool = False) -> list[Task]:
        stmt = select(Task).order_by(Task.due_date.asc(), Task.created_at.desc())
        if not include_history:
            stmt = stmt.where(Task.recurrence_parent_id.is_(None))
        if only_unassigned is True:
            stmt = stmt.where(Task.assignee_id.is_(None))
        if only_unassigned is False:
            stmt = stmt.where(Task.assignee_id.is_not(None))
        return list(self.db.scalars(stmt).all())

    def get_tasks_for_user(self, user: User) -> list[Task]:
        stmt = select(Task).where(Task.created_by_id == user.id).order_by(Task.due_date.asc(), Task.created_at.desc())
        return list(self.db.scalars(stmt).all())

    def get_tasks_visible_to_user(self, user: User) -> list[Task]:
        stmt = (
            select(Task)
            .where(or_(Task.created_by_id == user.id, Task.assignee_id == user.id))
            .order_by(Task.due_date.asc(), Task.created_at.desc())
        )
        return list(self.db.scalars(stmt).unique().all())

    def get_task(self, task_id: int) -> Task | None:
        return self.db.get(Task, task_id)

    def update_task(self, task: Task, payload: TaskUpdate) -> Task:
        task.title = payload.title.strip()
        task.description = payload.description.strip()
        task.due_date = payload.due_date
        task.effort_level = payload.effort_level
        task.points_value = self._points_for_level(payload.effort_level)
        task.status = payload.status
        task.recurrence_pattern = payload.recurrence_pattern
        task.recurrence_interval_weeks = payload.recurrence_interval_weeks
        task.recurrence_until = payload.recurrence_until
        task.recurrence_count_limit = payload.recurrence_count_limit
        task.recurrence_blocked_behavior = payload.recurrence_blocked_behavior
        task.recurrence_anchor_date = payload.due_date if payload.recurrence_pattern else None
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)
        return task

    def update_status(self, task: Task, status: TaskStatus) -> Task:
        if (
            task.recurrence_pattern == "weekly"
            and task.recurrence_parent_id is None
            and status == TaskStatus.COMPLETED
        ):
            return RecurringTaskService(self.db).complete_occurrence(task)
        task.status = status
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)
        return task

    def assign_task(self, task: Task, *, assignee_id: int | None, assignment_date: date | None) -> Task:
        task.assignee_id = assignee_id
        task.assignment_date = assignment_date
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)
        return task

    def assign_task_with_validation(
        self,
        task: Task,
        *,
        assignee_id: int,
        assignment_date: date,
        allow_policy_override: bool = False,
    ) -> tuple[bool, dict]:
        validation = WorkloadService(self.db).validate_assignment(
            user_id=assignee_id,
            date_value=assignment_date,
            task_points=task.points_value,
            exclude_task_id=task.id,
            allow_policy_override=allow_policy_override,
        )
        if not validation["valid"]:
            return False, validation
        self.assign_task(task, assignee_id=assignee_id, assignment_date=assignment_date)
        return True, validation
