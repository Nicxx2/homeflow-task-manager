from datetime import date, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from backend.app.models.enums import EffortLevel, TaskStatus
from backend.app.models.task import Task
from backend.app.models.task_effort_config import TaskEffortConfig
from backend.app.models.user import User
from backend.app.models.user_task_display_preference import UserTaskDisplayPreference
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

    def get_points_for_level(self, effort_level: EffortLevel) -> int:
        return self._points_for_level(effort_level)

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
            recurrence_occurrence_index=0 if payload.recurrence_pattern else None,
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

    def get_mobile_tasks_for_today(self, user: User, *, today_value: date) -> list[Task]:
        stmt = (
            select(Task)
            .where(
                Task.assignee_id == user.id,
                or_(Task.recurrence_parent_id.is_(None), Task.status == TaskStatus.COMPLETED),
                or_(
                    Task.assignment_date == today_value,
                    and_(
                        Task.due_date < today_value,
                        Task.status != TaskStatus.COMPLETED,
                    ),
                    and_(
                        Task.assignment_date.is_not(None),
                        Task.assignment_date < today_value,
                        Task.status != TaskStatus.COMPLETED,
                    ),
                ),
            )
        )
        return self._sort_mobile_tasks(list(self.db.scalars(stmt).unique().all()), today_value=today_value)

    def get_mobile_tasks_for_window(
        self,
        user: User,
        *,
        start_date: date,
        end_date: date,
        include_overdue: bool = True,
    ) -> list[Task]:
        date_filters = [Task.assignment_date.between(start_date, end_date)]
        if include_overdue:
            today_value = date.today()
            date_filters.append(
                and_(
                    Task.assignment_date.is_not(None),
                    Task.assignment_date < today_value,
                    Task.status != TaskStatus.COMPLETED,
                )
            )
            date_filters.append(
                and_(
                    Task.due_date < today_value,
                    Task.status != TaskStatus.COMPLETED,
                )
            )

        stmt = (
            select(Task)
            .where(
                Task.assignee_id == user.id,
                or_(Task.recurrence_parent_id.is_(None), Task.status == TaskStatus.COMPLETED),
                or_(*date_filters),
            )
        )
        return self._sort_mobile_tasks(list(self.db.scalars(stmt).unique().all()), today_value=date.today())

    def get_mobile_task_for_user(self, task_id: int, user: User) -> Task | None:
        stmt = select(Task).where(
            Task.id == task_id,
            Task.assignee_id == user.id,
            or_(Task.recurrence_parent_id.is_(None), Task.status == TaskStatus.COMPLETED),
        )
        return self.db.scalar(stmt)

    def get_task(self, task_id: int) -> Task | None:
        return self.db.get(Task, task_id)

    @staticmethod
    def _clear_recurrence_metadata(task: Task) -> None:
        task.recurrence_parent_id = None
        task.recurrence_pattern = None
        task.recurrence_interval_weeks = None
        task.recurrence_until = None
        task.recurrence_count_limit = None
        task.recurrence_blocked_behavior = None
        task.recurrence_anchor_date = None
        task.recurrence_occurrence_index = None

    @staticmethod
    def _is_recurring_occurrence_copy(task: Task) -> bool:
        return task.recurrence_parent_id is not None

    def _updated_recurrence_anchor_date(
        self,
        *,
        task: Task,
        payload: TaskUpdate,
        recurrence_series_due_date: date | None,
    ) -> date | None:
        if not payload.recurrence_pattern:
            return None
        if task.recurrence_pattern == "weekly" and task.recurrence_parent_id is None and recurrence_series_due_date is not None:
            current_index = RecurringTaskService(self.db).current_occurrence_index(task)
            interval_weeks = payload.recurrence_interval_weeks or 1
            return recurrence_series_due_date - timedelta(weeks=interval_weeks * (current_index + 1))
        if task.recurrence_pattern == "weekly" and task.recurrence_parent_id is None:
            return task.recurrence_anchor_date or payload.due_date
        return payload.due_date

    def update_task(self, task: Task, payload: TaskUpdate, *, recurrence_series_due_date: date | None = None) -> Task:
        was_recurring_occurrence_copy = self._is_recurring_occurrence_copy(task)
        should_detach_occurrence_copy = (
            was_recurring_occurrence_copy
            and (payload.status != TaskStatus.COMPLETED or payload.due_date != task.due_date)
        )
        if should_detach_occurrence_copy:
            self._clear_recurrence_metadata(task)

        task.title = payload.title.strip()
        task.description = payload.description.strip()
        task.due_date = payload.due_date
        task.effort_level = payload.effort_level
        task.points_value = self._points_for_level(payload.effort_level)
        task.status = payload.status
        if not was_recurring_occurrence_copy:
            task.recurrence_pattern = payload.recurrence_pattern
            task.recurrence_interval_weeks = payload.recurrence_interval_weeks
            task.recurrence_until = payload.recurrence_until
            task.recurrence_count_limit = payload.recurrence_count_limit
            task.recurrence_blocked_behavior = payload.recurrence_blocked_behavior
            task.recurrence_anchor_date = self._updated_recurrence_anchor_date(
                task=task,
                payload=payload,
                recurrence_series_due_date=recurrence_series_due_date,
            )
            if payload.recurrence_pattern:
                task.recurrence_occurrence_index = (
                    task.recurrence_occurrence_index
                    if task.recurrence_pattern == "weekly" and task.recurrence_occurrence_index is not None
                    else 0
                )
            else:
                task.recurrence_occurrence_index = None
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
        if self._is_recurring_occurrence_copy(task) and status != TaskStatus.COMPLETED:
            self._clear_recurrence_metadata(task)
        task.status = status
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)
        return task

    def assign_task(self, task: Task, *, assignee_id: int | None, assignment_date: date | None) -> Task:
        if self._is_recurring_occurrence_copy(task) and (
            task.status != TaskStatus.COMPLETED or assignment_date != task.assignment_date
        ):
            self._clear_recurrence_metadata(task)
        task.assignee_id = assignee_id
        task.assignment_date = assignment_date
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)
        return task

    def update_task_schedule(
        self,
        task: Task,
        *,
        due_date: date,
        assignee_id: int | None,
        assignment_date: date | None,
    ) -> Task:
        if self._is_recurring_occurrence_copy(task) and (
            task.status != TaskStatus.COMPLETED
            or due_date != task.due_date
            or assignment_date != task.assignment_date
        ):
            self._clear_recurrence_metadata(task)
        task.due_date = due_date
        task.assignee_id = assignee_id
        task.assignment_date = assignment_date
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)
        return task

    def delete_task(self, task: Task, *, preserve_completed_history: bool = False) -> None:
        related_history = list(self.db.scalars(select(Task).where(Task.recurrence_parent_id == task.id)).all())
        history_to_delete = [] if preserve_completed_history else related_history
        cleanup_task_ids = [task.id, *[item.id for item in history_to_delete]]

        related_preferences = list(
            self.db.scalars(
                select(UserTaskDisplayPreference).where(UserTaskDisplayPreference.task_id.in_(cleanup_task_ids))
            ).all()
        )
        for preference in related_preferences:
            self.db.delete(preference)

        if preserve_completed_history:
            for history_item in related_history:
                history_item.recurrence_parent_id = None
                self.db.add(history_item)

        for history_item in history_to_delete:
            self.db.delete(history_item)

        self.db.delete(task)
        self.db.commit()

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

    def update_task_schedule_with_validation(
        self,
        task: Task,
        *,
        due_date: date,
        assignee_id: int | None,
        assignment_date: date | None,
        allow_policy_override: bool = False,
        task_points: int | None = None,
    ) -> tuple[bool, dict]:
        if assignee_id is not None:
            if assignment_date is None:
                return False, {
                    "valid": False,
                    "message": "Choose an assignment date for the selected assignee.",
                }
            assignment_changed = (
                task.assignee_id != assignee_id
                or task.assignment_date != assignment_date
            )
            points_value = task_points if task_points is not None else task.points_value
            points_changed = task_points is not None and task_points != task.points_value
            if assignment_changed or points_changed:
                validation = WorkloadService(self.db).validate_assignment(
                    user_id=assignee_id,
                    date_value=assignment_date,
                    task_points=points_value,
                    exclude_task_id=task.id,
                    allow_policy_override=allow_policy_override,
                )
                if not validation["valid"]:
                    return False, validation
            else:
                validation = {
                    "valid": True,
                    "date": assignment_date.isoformat(),
                    "task_points": points_value,
                    "message": "Schedule saved.",
                }
        else:
            validation = {"valid": True}
            assignment_date = None

        self.update_task_schedule(task, due_date=due_date, assignee_id=assignee_id, assignment_date=assignment_date)
        return True, validation

    @staticmethod
    def _sort_mobile_tasks(tasks: list[Task], *, today_value: date) -> list[Task]:
        def bucket_rank(task: Task) -> tuple[int, int]:
            assignment = task.assignment_date or task.due_date
            is_overdue = (
                task.status != TaskStatus.COMPLETED
                and (
                    (
                        task.assignment_date is not None
                        and task.assignment_date < today_value
                    )
                    or task.due_date < today_value
                )
            )
            if assignment == today_value:
                status_order = {
                    TaskStatus.IN_PROGRESS: 0,
                    TaskStatus.PENDING: 1,
                    TaskStatus.COMPLETED: 2,
                }
                return (1, status_order.get(task.status, 9))
            if is_overdue:
                return (0, 0 if task.status == TaskStatus.IN_PROGRESS else 1)
            if assignment > today_value:
                status_order = {
                    TaskStatus.IN_PROGRESS: 0,
                    TaskStatus.PENDING: 1,
                    TaskStatus.COMPLETED: 2,
                }
                return (2, status_order.get(task.status, 9))
            return (3, 0)

        return sorted(
            tasks,
            key=lambda task: (
                bucket_rank(task),
                task.assignment_date or task.due_date,
                task.due_date,
                task.updated_at,
                task.id,
            ),
        )
