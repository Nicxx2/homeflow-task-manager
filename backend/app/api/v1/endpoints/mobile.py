from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user
from backend.app.db.session import get_db
from backend.app.models.enums import TaskStatus
from backend.app.models.task import Task
from backend.app.models.user import User
from backend.app.schemas.mobile import (
    MobileTaskNextAvailableResponse,
    MobileTaskRead,
    MobileTaskScheduleFeedback,
    MobileTaskScheduleRequest,
    MobileTaskScheduleUpdateResponse,
    MobileTaskStatusUpdateRequest,
    MobileTaskStatusUpdateResponse,
    MobileTaskWindowResponse,
)
from backend.app.services.recurring_task_service import RecurringTaskService
from backend.app.services.task_service import TaskService
from backend.app.services.workload_service import WorkloadService

router = APIRouter(prefix="/mobile", tags=["Mobile"])


def _server_time() -> datetime:
    return datetime.now(timezone.utc)


def _display_bucket(task: Task, *, today_value: date) -> str:
    if task.status == TaskStatus.COMPLETED:
        return "completed"
    if (task.assignment_date or task.due_date) == today_value:
        return "today"
    if (
        (task.assignment_date is not None and task.assignment_date < today_value)
        or task.due_date < today_value
    ):
        return "overdue"
    return "upcoming"


def _is_overdue(task: Task, *, today_value: date) -> bool:
    return task.status != TaskStatus.COMPLETED and (
        (task.assignment_date is not None and task.assignment_date < today_value)
        or task.due_date < today_value
    )


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
        is_overdue=_is_overdue(task, today_value=today_value),
        is_completed=task.status == TaskStatus.COMPLETED,
        display_bucket=bucket,
        sort_key=_sort_key(task, today_value=today_value),
        recurrence_parent_id=task.recurrence_parent_id,
        recurrence_summary=_recurrence_summary(task),
    )


def _schedule_feedback(validation: dict) -> MobileTaskScheduleFeedback:
    next_available_date = validation.get("next_available_date")
    return MobileTaskScheduleFeedback(
        valid=bool(validation.get("valid", False)),
        message=str(validation.get("message") or "Schedule could not be checked."),
        date=date.fromisoformat(validation["date"]) if validation.get("date") else None,
        task_points=validation.get("task_points"),
        current_points=validation.get("current_points"),
        projected_points=validation.get("projected_points"),
        capacity=validation.get("capacity"),
        is_past_date=bool(validation.get("is_past_date", False)),
        task_too_large=bool(validation.get("task_too_large", False)),
        blocked_by_policy=bool(validation.get("blocked_by_policy", False)),
        next_available_date=date.fromisoformat(next_available_date) if next_available_date else None,
    )


def _can_extend_capacity_for_assignment(validation: dict) -> bool:
    capacity = validation.get("capacity")
    projected_points = validation.get("projected_points")
    return (
        capacity is not None
        and projected_points is not None
        and projected_points > capacity
        and not bool(validation.get("is_past_date", False))
        and not bool(validation.get("blocked_by_policy", False))
    )


def _extend_capacity_for_assignment(
    workload: WorkloadService,
    *,
    user_id: int,
    assignment_date: date,
    validation: dict,
) -> int | None:
    capacity_breakdown = workload.get_capacity_breakdown(user_id=user_id, date_value=assignment_date)
    base_capacity = capacity_breakdown["base_capacity"]
    if base_capacity is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No daily capacity is configured for this user.",
        )

    projected_points = validation.get("projected_points")
    if projected_points is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Schedule could not be saved.",
        )

    required_extra_capacity = max(0, int(projected_points) - int(base_capacity))
    current_extra_capacity = int(capacity_breakdown["extra_capacity"] or 0)
    if required_extra_capacity > current_extra_capacity:
        workload.set_extra_capacity_points(
            user_id=user_id,
            date_value=assignment_date,
            extra_capacity_points=required_extra_capacity,
        )
        return current_extra_capacity
    return None


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


@router.get("/tasks/{task_id}/schedule/check", response_model=MobileTaskScheduleFeedback)
def check_mobile_task_schedule(
    task_id: int,
    assignment_date: date = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    RecurringTaskService(db).sync()
    task = TaskService(db).get_mobile_task_for_user(task_id, user)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")

    validation = WorkloadService(db).validate_assignment(
        user_id=user.id,
        date_value=assignment_date,
        task_points=task.points_value,
        exclude_task_id=task.id,
    )
    return _schedule_feedback(validation)


@router.get("/tasks/{task_id}/schedule/next-available", response_model=MobileTaskNextAvailableResponse)
def mobile_task_next_available_schedule(
    task_id: int,
    start_date: date | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    RecurringTaskService(db).sync()
    task = TaskService(db).get_mobile_task_for_user(task_id, user)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")

    workload = WorkloadService(db)
    if workload.get_base_user_capacity(user.id) is None:
        return MobileTaskNextAvailableResponse(
            ok=False,
            message="No daily capacity is configured for this user.",
        )

    suggested_date = workload.suggest_next_available_date(
        user_id=user.id,
        task_points=task.points_value,
        start_date=start_date or (date.today() + timedelta(days=1)),
        max_days=30,
        exclude_task_id=task.id,
    )
    if suggested_date is None:
        return MobileTaskNextAvailableResponse(
            ok=False,
            message="No suitable future day was found in the next 30 days.",
        )
    return MobileTaskNextAvailableResponse(
        ok=True,
        message=f"Next available day found: {suggested_date.isoformat()}",
        assignment_date=suggested_date,
    )


@router.patch("/tasks/{task_id}/schedule", response_model=MobileTaskScheduleUpdateResponse)
def update_mobile_task_schedule(
    task_id: int,
    payload: MobileTaskScheduleRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    RecurringTaskService(db).sync()
    service = TaskService(db)
    task = service.get_mobile_task_for_user(task_id, user)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")

    success, validation = service.update_task_schedule_with_validation(
        task,
        due_date=payload.due_date,
        assignee_id=user.id,
        assignment_date=payload.assignment_date,
        allow_policy_override=False,
    )
    if not success and payload.extend_capacity and _can_extend_capacity_for_assignment(validation):
        workload = WorkloadService(db)
        previous_extra_capacity = _extend_capacity_for_assignment(
            workload,
            user_id=user.id,
            assignment_date=payload.assignment_date,
            validation=validation,
        )
        success, validation = service.update_task_schedule_with_validation(
            task,
            due_date=payload.due_date,
            assignee_id=user.id,
            assignment_date=payload.assignment_date,
            allow_policy_override=False,
        )
        if not success and previous_extra_capacity is not None:
            workload.set_extra_capacity_points(
                user_id=user.id,
                date_value=payload.assignment_date,
                extra_capacity_points=previous_extra_capacity,
            )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=validation.get("message") or "Schedule could not be saved.",
        )

    return MobileTaskScheduleUpdateResponse(
        server_time=_server_time(),
        task=_serialize_task(task, today_value=date.today()),
        feedback=_schedule_feedback(validation),
    )
