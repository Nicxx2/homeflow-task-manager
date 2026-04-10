from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user
from backend.app.db.session import get_db
from backend.app.models.enums import TaskStatus
from backend.app.models.task import Task
from backend.app.models.user import User
from backend.app.schemas.mobile import (
    MobileTaskRead,
    MobileTaskStatusUpdateRequest,
    MobileTaskStatusUpdateResponse,
    MobileTaskWindowResponse,
)
from backend.app.services.recurring_task_service import RecurringTaskService
from backend.app.services.task_service import TaskService

router = APIRouter(prefix="/mobile", tags=["Mobile"])


def _server_time() -> datetime:
    return datetime.now(timezone.utc)


def _display_bucket(task: Task, *, today_value: date) -> str:
    if task.status == TaskStatus.COMPLETED:
        return "completed"
    if (
        (task.assignment_date is not None and task.assignment_date < today_value)
        or task.due_date < today_value
    ):
        return "overdue"
    if (task.assignment_date or task.due_date) == today_value:
        return "today"
    return "upcoming"


def _recurrence_summary(task: Task) -> str | None:
    if not task.recurrence_pattern:
        return None
    if task.recurrence_pattern == "weekly":
        interval = task.recurrence_interval_weeks or 1
        if interval == 1:
            return "Weekly recurring task"
        return f"Every {interval} weeks"
    return task.recurrence_pattern.replace("_", " ").capitalize()


def _sort_key(task: Task, *, today_value: date) -> str:
    bucket_order = {
        "overdue": "00",
        "today": "10",
        "upcoming": "20",
        "completed": "30",
    }
    status_order = {
        TaskStatus.IN_PROGRESS: "00",
        TaskStatus.PENDING: "10",
        TaskStatus.COMPLETED: "20",
    }
    bucket = _display_bucket(task, today_value=today_value)
    primary_date = task.assignment_date or task.due_date
    return ":".join(
        [
            bucket_order.get(bucket, "99"),
            status_order.get(task.status, "99"),
            primary_date.isoformat(),
            task.due_date.isoformat(),
            task.updated_at.isoformat(),
            f"{task.id:010d}",
        ]
    )


def _serialize_task(task: Task, *, today_value: date) -> MobileTaskRead:
    bucket = _display_bucket(task, today_value=today_value)
    return MobileTaskRead(
        id=task.id,
        title=task.title,
        description=task.description,
        status=task.status,
        due_date=task.due_date,
        assignment_date=task.assignment_date,
        assignee_id=task.assignee_id,
        effort_level=task.effort_level,
        points_value=task.points_value,
        updated_at=task.updated_at,
        is_overdue=bucket == "overdue",
        is_completed=task.status == TaskStatus.COMPLETED,
        display_bucket=bucket,
        sort_key=_sort_key(task, today_value=today_value),
        recurrence_parent_id=task.recurrence_parent_id,
        recurrence_summary=_recurrence_summary(task),
    )


@router.get("/tasks/today", response_model=MobileTaskWindowResponse)
def get_today_tasks(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    RecurringTaskService(db).sync()
    today_value = date.today()
    tasks = TaskService(db).get_mobile_tasks_for_today(user, today_value=today_value)
    return MobileTaskWindowResponse(
        server_time=_server_time(),
        window_start=today_value,
        window_end=today_value,
        tasks=[_serialize_task(task, today_value=today_value) for task in tasks],
    )


@router.get("/tasks/window", response_model=MobileTaskWindowResponse)
def get_task_window(
    start: date = Query(...),
    end: date = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if end < start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="End date must be on or after start date.",
        )
    RecurringTaskService(db).sync()
    today_value = date.today()
    tasks = TaskService(db).get_mobile_tasks_for_window(
        user,
        start_date=start,
        end_date=end,
        include_overdue=start <= today_value,
    )
    return MobileTaskWindowResponse(
        server_time=_server_time(),
        window_start=start,
        window_end=end,
        tasks=[_serialize_task(task, today_value=today_value) for task in tasks],
    )


@router.get("/tasks/{task_id}", response_model=MobileTaskRead)
def get_mobile_task(
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    RecurringTaskService(db).sync()
    task = TaskService(db).get_mobile_task_for_user(task_id, user)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    return _serialize_task(task, today_value=date.today())


@router.patch("/tasks/{task_id}/status", response_model=MobileTaskStatusUpdateResponse)
def update_mobile_task_status(
    task_id: int,
    payload: MobileTaskStatusUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    RecurringTaskService(db).sync()
    service = TaskService(db)
    task = service.get_mobile_task_for_user(task_id, user)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")

    updated = service.update_status(task, payload.status)
    refresh_required = updated.status != payload.status
    serialized = None if refresh_required else _serialize_task(updated, today_value=date.today())
    return MobileTaskStatusUpdateResponse(
        server_time=_server_time(),
        refresh_required=refresh_required,
        task=serialized,
    )
