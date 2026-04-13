import json
from datetime import date, timedelta
from urllib.parse import quote, urlparse

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.orm import Session

from backend.app.ai.schemas.classification import TaskClassificationResult
from backend.app.api.deps import get_current_user
from backend.app.db.session import get_db
from backend.app.models.enums import EffortLevel, TaskStatus
from backend.app.models.task import Task
from backend.app.models.user import User
from backend.app.schemas.auth import RegisterRequest
from backend.app.schemas.task import TaskAssignRequest, TaskCreate, TaskUpdate
from backend.app.services.admin_settings_service import AdminSettingsService
from backend.app.services.ai_service import AIService
from backend.app.services.app_assistant_service import AppAssistantService
from backend.app.services.auth_service import AuthService
from backend.app.services.recurring_task_service import RecurringTaskService
from backend.app.services.scheduling_service import SchedulingService
from backend.app.services.task_service import TaskService
from backend.app.services.user_task_display_service import UserTaskDisplayService
from backend.app.services.workload_service import WorkloadService

router = APIRouter()
templates = Jinja2Templates(directory="backend/app/templates")


def _is_history_occurrence(task) -> bool:
    return task.recurrence_parent_id is not None and task.status == TaskStatus.COMPLETED


def _can_access_task_detail(*, viewer: User, task) -> bool:
    return viewer.is_admin or viewer.is_active


def _can_manage_task(*, viewer: User, task) -> bool:
    return viewer.is_admin or viewer.is_active


def _can_delete_task(*, viewer: User, task) -> bool:
    return viewer.is_admin or task.created_by_id == viewer.id


def _can_update_task_status(*, viewer: User, task) -> bool:
    return not _is_history_occurrence(task) and (viewer.is_admin or task.assignee_id == viewer.id)


def _can_override_schedule_for_assignment(*, viewer: User, assignee_id: int | None) -> bool:
    return viewer.is_admin or (assignee_id is not None and viewer.id == assignee_id)


def _member_users(db: Session) -> list[User]:
    return list(
        db.query(User)
        .filter(
            User.is_active.is_(True),
            User.approval_status == AuthService.APPROVAL_APPROVED,
            User.show_in_member_lists.is_(True),
        )
        .order_by(User.full_name.asc())
        .all()
    )


def _assignable_users_for_task(db: Session, task) -> list[User]:
    users = _member_users(db)
    if task.assignee and all(item.id != task.assignee.id for item in users):
        users.append(task.assignee)
    return users


def _current_path_with_query(request: Request, default: str) -> str:
    path = request.url.path or default
    query = request.url.query
    return f"{path}?{query}" if query else path


def _redirect_to_target(*, request: Request, redirect_to: str | None, default: str) -> RedirectResponse:
    target = redirect_to or request.headers.get("referer") or default
    parsed = urlparse(target)
    redirect_path = parsed.path or default
    if parsed.query:
        redirect_path = f"{redirect_path}?{parsed.query}"
    return RedirectResponse(url=redirect_path, status_code=status.HTTP_302_FOUND)


def _task_ai_result_context(db: Session, result: dict):
    try:
        validated = TaskClassificationResult.model_validate(result)
        return {
            "result": validated.model_dump(),
            "levels": [EffortLevel.LOW, EffortLevel.MEDIUM, EffortLevel.HIGH],
        }
    except ValidationError:
        fallback = {
            "suggested_level": EffortLevel.MEDIUM,
            "confidence": 0.55,
            "reason": "AI response was invalid. Manual override is available.",
            "provider_used": "rules",
            "model_used": "rules-default",
            "fallback_used": True,
        }
        AdminSettingsService(db).log_ai_error(
            provider_name="ai-service",
            model_identifier=None,
            error_type="InvalidClassificationPayload",
            message="AI classification payload failed validation.",
            context="task-ai-classify-route",
        )
        return {
            "result": fallback,
            "levels": [EffortLevel.LOW, EffortLevel.MEDIUM, EffortLevel.HIGH],
        }


def _admin_settings_context(
    *,
    request: Request,
    user: User,
    service: AdminSettingsService,
    ai_test_result: dict | None,
) -> dict:
    ai_errors = service.get_recent_ai_errors(limit=25)
    all_users = list(db_user for db_user, _ in service.get_users_with_capacities())
    return {
        "request": request,
        "user": user,
        "effort_configs": service.get_effort_configs(),
        "user_caps": service.get_member_users_with_capacities(),
        "all_users": all_users,
        "pending_users": service.get_pending_users(),
        "ai_settings": service.get_ai_settings(),
        "ai_models": service.get_ai_registry_models(),
        "ai_health": service.get_ai_health(),
        "ai_errors_initial": ai_errors[:3],
        "ai_errors_more": ai_errors[3:],
        "ai_test_result": ai_test_result,
        "user_create_result": None,
    }


def _schedule_page_context(*, request: Request, user: User, db: Session, form_error: str | None = None) -> dict:
    scheduling = SchedulingService(db)
    return {
        "request": request,
        "user": user,
        "form_error": form_error,
        **scheduling.get_schedule_page_context(user_id=user.id),
    }


def _appearance_page_context(*, request: Request, user: User, form_error: str | None = None) -> dict:
    return {
        "request": request,
        "user": user,
        "form_error": form_error,
        "task_category_button_mode_options": [
            {"value": "match", "label": "Match task colours"},
            {"value": "custom", "label": "Use separate button colours"},
        ],
        "surface_style_options": [
            {"value": "clean", "label": "Clean"},
            {"value": "soft", "label": "Soft"},
            {"value": "contrast", "label": "High contrast"},
        ],
        "density_options": [
            {"value": "comfortable", "label": "Comfortable"},
            {"value": "compact", "label": "Compact"},
        ],
        "decoration_options": [
            {"value": "none", "label": "None"},
            {"value": "glow", "label": "Soft glow"},
            {"value": "petals", "label": "Soft petals"},
        ],
    }


def _initial_assignment_date_for_task(task) -> str:
    return (task.assignment_date or date.today()).isoformat()


def _task_delete_contacts(db: Session, *, task) -> dict:
    admin_contacts = list(
        db.query(User)
        .filter(
            User.is_admin.is_(True),
            User.is_active.is_(True),
            User.approval_status == AuthService.APPROVAL_APPROVED,
            User.id != task.created_by_id,
        )
        .order_by(User.full_name.asc())
        .limit(2)
        .all()
    )
    return {"creator": task.created_by, "admins": admin_contacts}


def _task_detail_context(
    *,
    request: Request,
    user: User,
    db: Session,
    task: Task,
    return_to: str | None,
    assignment_feedback: dict | None,
) -> dict:
    _apply_personal_task_highlights(db=db, user=user, tasks=[task])
    is_history_occurrence = _is_history_occurrence(task)
    recurrence_history = []
    if task.recurrence_pattern == "weekly" and task.recurrence_parent_id is None:
        recurrence_history = RecurringTaskService(db).get_history(task.id)
    delete_contacts = _task_delete_contacts(db, task=task)
    current_page_url = return_to or _current_path_with_query(request, f"/tasks/{task.id}")
    return {
        "request": request,
        "user": user,
        "today_iso": date.today().isoformat(),
        "initial_assignment_date": _initial_assignment_date_for_task(task),
        "task": task,
        "recurrence_history": recurrence_history,
        "all_users": _assignable_users_for_task(db, task),
        "statuses": [TaskStatus.PENDING, TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED],
        "assignment_feedback": assignment_feedback,
        "current_page_url": current_page_url,
        "can_manage_task": _can_manage_task(viewer=user, task=task) and not is_history_occurrence,
        "can_delete_task": _can_delete_task(viewer=user, task=task),
        "can_update_status": _can_update_task_status(viewer=user, task=task),
        "is_history_occurrence": is_history_occurrence,
        "personal_highlight_color": getattr(task, "personal_highlight_color", None),
        "personal_highlight_default": getattr(task, "personal_highlight_color", None) or user.accent_color,
        "return_to": return_to,
        "encoded_return_to": _encoded_redirect_target(return_to) if return_to else None,
        "delete_contact_creator": delete_contacts["creator"],
        "delete_contact_admins": delete_contacts["admins"],
        "delete_redirect_to": return_to or "/tasks",
        "show_due_date_shortcut": task.due_date >= date.today(),
    }


def _next_available_assignment_shortcut(
    *,
    db: Session,
    task: Task,
    assignee_id: int,
    allow_policy_override: bool,
) -> dict:
    workload = WorkloadService(db)
    assignee = db.get(User, assignee_id)
    if not assignee or not assignee.is_active:
        return {"ok": False, "message": "Choose a valid user first."}

    capacity = workload.get_user_capacity(assignee_id)
    if capacity is None:
        return {"ok": False, "message": "No daily capacity is configured for this user."}
    if task.points_value > capacity:
        return {
            "ok": False,
            "message": "This task is larger than the user's daily capacity, so no future day can fit it.",
        }

    suggested_date = workload.suggest_next_available_date(
        user_id=assignee_id,
        task_points=task.points_value,
        start_date=date.today() + timedelta(days=1),
        max_days=30,
        exclude_task_id=task.id,
        allow_policy_override=allow_policy_override,
    )
    if suggested_date is None:
        return {"ok": False, "message": "No suitable future day was found in the next 30 days."}
    return {
        "ok": True,
        "assignment_date": suggested_date.isoformat(),
        "message": f"Next available day found: {suggested_date.isoformat()}",
    }


def _apply_personal_task_highlights(*, db: Session, user: User, tasks: list[Task]) -> None:
    UserTaskDisplayService(db).apply_highlights(user_id=user.id, tasks=tasks)


def _encoded_redirect_target(target: str) -> str:
    return quote(target, safe="")


def _open_unassigned_tasks(tasks: list[Task]) -> list[Task]:
    return [task for task in tasks if task.assignee_id is None and task.status != TaskStatus.COMPLETED]


def _task_matches_scope(*, task: Task, user: User, scope: str) -> bool:
    if scope == "mine":
        return task.assignee_id == user.id or (task.assignee_id is None and task.status != TaskStatus.COMPLETED)
    return True


def _parse_recurrence_form(
    *,
    repeat_weekly: str,
    recurrence_interval_weeks: str,
    recurrence_until: str,
    recurrence_count_limit: str,
    recurrence_blocked_behavior: str,
) -> dict:
    enabled = repeat_weekly.lower() in {"true", "on", "1", "yes"}
    if not enabled:
        return {
            "recurrence_pattern": None,
            "recurrence_interval_weeks": None,
            "recurrence_until": None,
            "recurrence_count_limit": None,
            "recurrence_blocked_behavior": None,
        }

    interval_value = int(recurrence_interval_weeks) if recurrence_interval_weeks.strip() else 1
    count_limit_value = int(recurrence_count_limit) if recurrence_count_limit.strip() else None
    until_value = date.fromisoformat(recurrence_until) if recurrence_until.strip() else None
    blocked_behavior = recurrence_blocked_behavior.strip() or "skip"
    if blocked_behavior not in {"skip", "move_same_week"}:
        raise ValueError("Invalid recurring blocked-date behavior.")

    return {
        "recurrence_pattern": "weekly",
        "recurrence_interval_weeks": interval_value,
        "recurrence_until": until_value,
        "recurrence_count_limit": count_limit_value,
        "recurrence_blocked_behavior": blocked_behavior,
    }


def _sync_recurring_tasks(db: Session) -> None:
    RecurringTaskService(db).sync()


@router.get("/", response_class=HTMLResponse)
def root() -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": None, "register_error": None, "register_success": None, "show_nav": False},
    )


@router.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    service = AuthService(db)
    user = service.authenticate(email, password)
    if not user:
        denial_reason = service.get_login_denial_reason(email, password)
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": denial_reason or "Invalid email or password.",
                "register_error": None,
                "register_success": None,
                "show_nav": False,
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    token = service.issue_token(user)
    service.touch_activity(user)
    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    response.set_cookie(key="access_token", value=token, httponly=True, samesite="lax")
    return response


@router.post("/register", response_class=HTMLResponse)
def register_submit(
    request: Request,
    email: str = Form(...),
    full_name: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    service = AuthService(db)
    try:
        service.register(RegisterRequest(email=email, full_name=full_name, password=password))
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": None,
                "register_error": None,
                "register_success": "Registration request sent. An admin must approve your account before you can sign in.",
                "show_nav": False,
            },
            status_code=status.HTTP_201_CREATED,
        )
    except ValueError as exc:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": None,
                "register_error": str(exc),
                "register_success": None,
                "show_nav": False,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _sync_recurring_tasks(db)
    service = TaskService(db)
    workload = WorkloadService(db)
    admin_service = AdminSettingsService(db)
    ai_ui_status = admin_service.get_ai_ui_status()
    users_for_today = _member_users(db)
    all_tasks = service.get_tasks()
    unassigned_tasks = _open_unassigned_tasks(service.get_tasks(only_unassigned=True))
    _apply_personal_task_highlights(db=db, user=user, tasks=all_tasks)
    _apply_personal_task_highlights(db=db, user=user, tasks=unassigned_tasks)

    today = date.today()
    my_active_tasks = [
        task
        for task in all_tasks
        if task.assignee_id == user.id and task.status != TaskStatus.COMPLETED
    ]
    today_workload = []
    for item in users_for_today:
        points = workload.get_daily_points(user_id=item.id, date_value=today)
        capacity = workload.get_user_capacity(item.id)
        remaining_capacity = None if capacity is None else capacity - points
        schedule_block = workload.scheduling.get_block_for_date(user_id=item.id, date_value=today)
        tasks_today = workload.get_tasks_for_user_on_date(user_id=item.id, date_value=today)
        next_task = next((task for task in tasks_today if task.status != TaskStatus.COMPLETED), None)
        _apply_personal_task_highlights(db=db, user=user, tasks=tasks_today)
        status_label = "Capacity unset"
        status_tone = "slate"
        if schedule_block and schedule_block.get("type") == "away":
            status_label = "Away"
            status_tone = "amber"
        elif remaining_capacity is None:
            status_label = "Capacity unset"
            status_tone = "slate"
        elif remaining_capacity < 0:
            status_label = "Over"
            status_tone = "red"
        elif remaining_capacity <= 2:
            status_label = "Nearly full"
            status_tone = "amber"
        else:
            status_label = "Free"
            status_tone = "emerald"
        today_workload.append(
            {
                "user": item,
                "points": points,
                "capacity": capacity,
                "remaining_capacity": remaining_capacity,
                "tasks_today": tasks_today,
                "next_task": next_task,
                "status_label": status_label,
                "status_tone": status_tone,
                "schedule_block": schedule_block,
            }
        )
    status_rank = {"Over": 0, "Nearly full": 1, "Free": 2, "Capacity unset": 3, "Away": 4}
    today_workload.sort(key=lambda row: (status_rank.get(row["status_label"], 5), row["user"].full_name.lower()))
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "unassigned_tasks": unassigned_tasks,
            "my_active_tasks": my_active_tasks,
            "today_workload": today_workload,
            "today": today,
            "ai_ui_status": ai_ui_status,
            "tasks_page_url": "/tasks?scope=mine&view=up_next",
            "encoded_dashboard_return_to": _encoded_redirect_target(_current_path_with_query(request, "/dashboard")),
        },
    )


@router.get("/tasks", response_class=HTMLResponse)
def tasks_page(
    request: Request,
    scope: str = "mine",
    view: str = "up_next",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _sync_recurring_tasks(db)
    service = TaskService(db)
    tasks = service.get_tasks()
    completed_history = list(
        db.query(Task)
        .filter(Task.recurrence_parent_id.is_not(None), Task.status == TaskStatus.COMPLETED)
        .order_by(Task.due_date.desc(), Task.created_at.desc())
        .all()
    )
    _apply_personal_task_highlights(db=db, user=user, tasks=tasks)
    _apply_personal_task_highlights(db=db, user=user, tasks=completed_history)
    today = date.today()
    tomorrow = today + timedelta(days=1)
    selected_scope = "mine" if scope == "mine" else "team"
    scoped_tasks = [task for task in tasks if _task_matches_scope(task=task, user=user, scope=selected_scope)]
    scoped_completed_history = [
        task
        for task in completed_history
        if _task_matches_scope(task=task, user=user, scope=selected_scope)
    ]
    overdue_tasks = [
        task
        for task in scoped_tasks
        if task.status != TaskStatus.COMPLETED and task.due_date < today
    ]
    up_next_tasks = [
        task
        for task in scoped_tasks
        if task.status == TaskStatus.PENDING and task.assignee_id is not None and today <= task.due_date <= tomorrow
    ]
    future_tasks = [
        task
        for task in scoped_tasks
        if task.status == TaskStatus.PENDING and task.assignee_id is not None and task.due_date > tomorrow
    ]
    unassigned_tasks = [
        task
        for task in scoped_tasks
        if task.status != TaskStatus.COMPLETED and task.assignee_id is None and task.due_date >= today
    ]
    in_progress_tasks = [
        task for task in scoped_tasks if task.status == TaskStatus.IN_PROGRESS and task.due_date >= today
    ]
    completed_tasks = sorted(
        [task for task in scoped_tasks if task.status == TaskStatus.COMPLETED] + scoped_completed_history,
        key=lambda task: (task.due_date, task.created_at),
        reverse=True,
    )
    available_views = {
        "overdue": {
            "label": "Overdue",
            "description": "Past-due work that still needs attention.",
            "items": overdue_tasks,
            "empty_message": "No overdue tasks right now.",
        },
        "up_next": {
            "label": "Next Up",
            "description": "Assigned pending work due today or tomorrow.",
            "items": up_next_tasks,
            "empty_message": "Nothing assigned is due today or tomorrow.",
        },
        "later": {
            "label": "Later Queue",
            "description": "Assigned pending work scheduled after tomorrow.",
            "items": future_tasks,
            "empty_message": "Nothing is scheduled beyond tomorrow right now.",
        },
        "unassigned": {
            "label": "Unassigned",
            "description": "Tasks waiting for someone to pick them up and plan them.",
            "items": unassigned_tasks,
            "empty_message": "No unassigned active tasks right now.",
        },
        "in_progress": {
            "label": "In Progress",
            "description": "Active work already underway.",
            "items": in_progress_tasks,
            "empty_message": "Nothing is currently in progress.",
        },
        "completed": {
            "label": "Completed",
            "description": "Finished work when you need to look back.",
            "items": completed_tasks,
            "empty_message": "No completed tasks yet.",
        },
    }
    selected_view = view if view in available_views else "up_next"
    return templates.TemplateResponse(
        "tasks/list.html",
        {
            "request": request,
            "user": user,
            "tasks": scoped_tasks,
            "overdue_tasks": overdue_tasks,
            "up_next_tasks": up_next_tasks,
            "future_tasks": future_tasks,
            "unassigned_tasks": unassigned_tasks,
            "in_progress_tasks": in_progress_tasks,
            "completed_tasks": completed_tasks,
            "statuses": [TaskStatus.PENDING, TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED],
            "current_page_url": _current_path_with_query(request, "/tasks"),
            "today": today,
            "tomorrow": tomorrow,
            "scope": selected_scope,
            "selected_view": selected_view,
            "selected_bucket": available_views[selected_view],
            "task_views": [
                {"key": "overdue", "label": "Overdue", "count": len(overdue_tasks)},
                {"key": "up_next", "label": "Next Up", "count": len(up_next_tasks)},
                {"key": "later", "label": "Later Queue", "count": len(future_tasks)},
                {"key": "unassigned", "label": "Unassigned", "count": len(unassigned_tasks)},
                {"key": "in_progress", "label": "In Progress", "count": len(in_progress_tasks)},
                {"key": "completed", "label": "Completed", "count": len(completed_tasks)},
            ],
            "current_page_return_to": _encoded_redirect_target(_current_path_with_query(request, "/tasks")),
        },
    )


@router.get("/tasks/new", response_class=HTMLResponse)
def task_create_page(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    admin_service = AdminSettingsService(db)
    ai_settings = admin_service.get_ai_settings()
    ai_ui_status = admin_service.get_ai_ui_status()
    return templates.TemplateResponse(
        "tasks/create.html",
        {
            "request": request,
            "user": user,
            "levels": [EffortLevel.LOW, EffortLevel.MEDIUM, EffortLevel.HIGH],
            "today": date.today().isoformat(),
            "ai_settings": ai_settings,
            "ai_ui_status": ai_ui_status,
            "personal_highlight_default": user.accent_color,
        },
    )


@router.post("/tasks/ai-classify", response_class=HTMLResponse)
def task_ai_classify(
    request: Request,
    title: str = Form(""),
    description: str = Form(""),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    if not title.strip() or not description.strip():
        return templates.TemplateResponse("tasks/partials/ai_waiting.html", {"request": request})

    ai_service = AIService(db)
    result = ai_service.classify_task(title, description)
    context = _task_ai_result_context(db, result)
    return templates.TemplateResponse(
        "tasks/partials/ai_result.html",
        {
            "request": request,
            **context,
        },
    )


@router.post("/tasks", response_class=HTMLResponse)
def task_create_submit(
    request: Request,
    title: str = Form(...),
    description: str = Form(...),
    due_date: str = Form(...),
    effort_level: str = Form(...),
    ai_suggested_level: str = Form(""),
    ai_confidence: str = Form(""),
    ai_reason: str = Form(""),
    fallback_used: str = Form("false"),
    provider_used: str = Form(""),
    model_used: str = Form(""),
    repeat_weekly: str = Form("false"),
    recurrence_interval_weeks: str = Form("1"),
    recurrence_until: str = Form(""),
    recurrence_count_limit: str = Form(""),
    recurrence_blocked_behavior: str = Form("skip"),
    use_personal_highlight: str = Form("false"),
    personal_highlight_color: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ai_settings = AdminSettingsService(db).get_ai_settings()
    highlight_enabled = use_personal_highlight.lower() in {"true", "on", "1", "yes"}
    normalized_highlight_color = None
    if highlight_enabled:
        try:
            normalized_highlight_color = AuthService._normalize_hex_color(personal_highlight_color or user.accent_color)
        except ValueError:
            return templates.TemplateResponse(
                "tasks/create.html",
                {
                    "request": request,
                    "user": user,
                    "levels": [EffortLevel.LOW, EffortLevel.MEDIUM, EffortLevel.HIGH],
                    "today": date.today().isoformat(),
                    "ai_settings": ai_settings,
                    "ai_ui_status": AdminSettingsService(db).get_ai_ui_status(),
                    "personal_highlight_default": user.accent_color,
                    "form_error": "Please choose a valid personal task highlight colour.",
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )
    try:
        level = EffortLevel(effort_level)
    except ValueError:
        return templates.TemplateResponse(
            "tasks/create.html",
            {
                "request": request,
                "user": user,
                "levels": [EffortLevel.LOW, EffortLevel.MEDIUM, EffortLevel.HIGH],
                "today": date.today().isoformat(),
                "ai_settings": ai_settings,
                "ai_ui_status": AdminSettingsService(db).get_ai_ui_status(),
                "personal_highlight_default": user.accent_color,
                "form_error": "Please select a valid effort level before saving.",
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    ai_level = None
    if ai_suggested_level:
        try:
            ai_level = EffortLevel(ai_suggested_level)
        except ValueError:
            ai_level = None
    if ai_level is None:
        ai_result = AIService(db).classify_task(title, description)
        try:
            validated_ai = TaskClassificationResult.model_validate(ai_result)
            ai_level = validated_ai.suggested_level
            ai_confidence = str(validated_ai.confidence)
            ai_reason = validated_ai.reason
            fallback_used = "true" if validated_ai.fallback_used else "false"
            provider_used = validated_ai.provider_used
            model_used = validated_ai.model_used
        except ValidationError:
            ai_level = EffortLevel.MEDIUM
            ai_confidence = "0.55"
            ai_reason = "AI attempt failed validation; default fallback classification applied."
            fallback_used = "true"
            provider_used = "rules"
            model_used = "rules-default"
            AdminSettingsService(db).log_ai_error(
                provider_name="ai-service",
                model_identifier=None,
                error_type="InvalidClassificationPayload",
                message="Task create submit AI attempt returned invalid payload.",
                context="task-create-submit",
            )

    try:
        parsed_due_date = date.fromisoformat(due_date)
    except ValueError:
        return templates.TemplateResponse(
            "tasks/create.html",
            {
                "request": request,
                "user": user,
                "levels": [EffortLevel.LOW, EffortLevel.MEDIUM, EffortLevel.HIGH],
                "today": date.today().isoformat(),
                "ai_settings": ai_settings,
                "ai_ui_status": AdminSettingsService(db).get_ai_ui_status(),
                "personal_highlight_default": user.accent_color,
                "form_error": "Please choose a valid due date.",
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        recurrence_values = _parse_recurrence_form(
            repeat_weekly=repeat_weekly,
            recurrence_interval_weeks=recurrence_interval_weeks,
            recurrence_until=recurrence_until,
            recurrence_count_limit=recurrence_count_limit,
            recurrence_blocked_behavior=recurrence_blocked_behavior,
        )
    except ValueError:
        return templates.TemplateResponse(
            "tasks/create.html",
            {
                "request": request,
                "user": user,
                "levels": [EffortLevel.LOW, EffortLevel.MEDIUM, EffortLevel.HIGH],
                "today": date.today().isoformat(),
                "ai_settings": ai_settings,
                "ai_ui_status": AdminSettingsService(db).get_ai_ui_status(),
                "personal_highlight_default": user.accent_color,
                "form_error": "Please provide valid recurring task settings.",
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        payload = TaskCreate(
            title=title,
            description=description,
            due_date=parsed_due_date,
            effort_level=level,
            ai_suggested_level=ai_level,
            ai_confidence=float(ai_confidence) if ai_confidence else None,
            ai_reason=ai_reason or None,
            fallback_used=fallback_used.lower() == "true",
            provider_used=provider_used or None,
            model_used=model_used or None,
            **recurrence_values,
        )
    except ValidationError:
        return templates.TemplateResponse(
            "tasks/create.html",
            {
                "request": request,
                "user": user,
                "levels": [EffortLevel.LOW, EffortLevel.MEDIUM, EffortLevel.HIGH],
                "today": date.today().isoformat(),
                "ai_settings": ai_settings,
                "ai_ui_status": AdminSettingsService(db).get_ai_ui_status(),
                "personal_highlight_default": user.accent_color,
                "form_error": "Please provide title, description, due date, and a valid effort level.",
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    task = TaskService(db).create_unassigned_task(payload, user)
    if highlight_enabled:
        UserTaskDisplayService(db).set_highlight_color(
            user=user,
            task=task,
            highlight_color=normalized_highlight_color,
        )
    return RedirectResponse(url="/tasks", status_code=status.HTTP_302_FOUND)


@router.get("/tasks/{task_id}", response_class=HTMLResponse)
def task_detail_page(
    task_id: int,
    request: Request,
    return_to: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _sync_recurring_tasks(db)
    service = TaskService(db)
    task = service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    if not _can_access_task_detail(viewer=user, task=task):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed.")
    return templates.TemplateResponse(
        "tasks/detail.html",
        _task_detail_context(
            request=request,
            user=user,
            db=db,
            task=task,
            return_to=return_to,
            assignment_feedback=None,
        ),
    )


@router.get("/tasks/{task_id}/edit", response_class=HTMLResponse)
def task_edit_page(
    task_id: int,
    request: Request,
    redirect_to: str = "",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = TaskService(db)
    task = service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    if not _can_manage_task(viewer=user, task=task) or _is_history_occurrence(task):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed.")
    redirect_target = redirect_to or f"/tasks/{task.id}"
    _apply_personal_task_highlights(db=db, user=user, tasks=[task])
    return templates.TemplateResponse(
        "tasks/edit.html",
        {
            "request": request,
            "user": user,
            "task": task,
            "levels": [EffortLevel.LOW, EffortLevel.MEDIUM, EffortLevel.HIGH],
            "statuses": [TaskStatus.PENDING, TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED],
            "form_error": None,
            "personal_highlight_color": getattr(task, "personal_highlight_color", None),
            "personal_highlight_default": getattr(task, "personal_highlight_color", None) or user.accent_color,
            "redirect_to": redirect_target,
        },
    )


@router.post("/tasks/{task_id}/edit", response_class=HTMLResponse)
def task_edit_submit(
    task_id: int,
    request: Request,
    title: str = Form(...),
    description: str = Form(...),
    due_date: str = Form(...),
    effort_level: str = Form(...),
    status_value: str = Form("pending"),
    repeat_weekly: str = Form("false"),
    recurrence_interval_weeks: str = Form("1"),
    recurrence_until: str = Form(""),
    recurrence_count_limit: str = Form(""),
    recurrence_blocked_behavior: str = Form("skip"),
    use_personal_highlight: str = Form("false"),
    personal_highlight_color: str = Form(""),
    redirect_to: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service = TaskService(db)
    task = service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    if not _can_manage_task(viewer=user, task=task) or _is_history_occurrence(task):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed.")
    redirect_target = redirect_to or f"/tasks/{task.id}"
    highlight_enabled = use_personal_highlight.lower() in {"true", "on", "1", "yes"}
    normalized_highlight_color = None
    if highlight_enabled:
        try:
            normalized_highlight_color = AuthService._normalize_hex_color(personal_highlight_color or user.accent_color)
        except ValueError:
            _apply_personal_task_highlights(db=db, user=user, tasks=[task])
            return templates.TemplateResponse(
                "tasks/edit.html",
                {
                    "request": request,
                    "user": user,
                    "task": task,
                    "levels": [EffortLevel.LOW, EffortLevel.MEDIUM, EffortLevel.HIGH],
                    "statuses": [TaskStatus.PENDING, TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED],
                    "form_error": "Please choose a valid personal task highlight colour.",
                    "personal_highlight_color": getattr(task, "personal_highlight_color", None),
                    "personal_highlight_default": getattr(task, "personal_highlight_color", None) or user.accent_color,
                    "redirect_to": redirect_target,
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    try:
        update_level = EffortLevel(effort_level)
        update_status = TaskStatus(status_value)
        update_due_date = date.fromisoformat(due_date)
    except ValueError:
        return templates.TemplateResponse(
            "tasks/edit.html",
            {
                "request": request,
                "user": user,
                "task": task,
                "levels": [EffortLevel.LOW, EffortLevel.MEDIUM, EffortLevel.HIGH],
                "statuses": [TaskStatus.PENDING, TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED],
                "form_error": "Please provide valid task values before saving.",
                "personal_highlight_color": UserTaskDisplayService(db).get_highlight_color(user_id=user.id, task_id=task.id),
                "personal_highlight_default": UserTaskDisplayService(db).get_highlight_color(user_id=user.id, task_id=task.id)
                or user.accent_color,
                "redirect_to": redirect_target,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        recurrence_values = _parse_recurrence_form(
            repeat_weekly=repeat_weekly,
            recurrence_interval_weeks=recurrence_interval_weeks,
            recurrence_until=recurrence_until,
            recurrence_count_limit=recurrence_count_limit,
            recurrence_blocked_behavior=recurrence_blocked_behavior,
        )
    except ValueError:
        return templates.TemplateResponse(
            "tasks/edit.html",
            {
                "request": request,
                "user": user,
                "task": task,
                "levels": [EffortLevel.LOW, EffortLevel.MEDIUM, EffortLevel.HIGH],
                "statuses": [TaskStatus.PENDING, TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED],
                "form_error": "Please provide valid recurring task settings before saving.",
                "personal_highlight_color": UserTaskDisplayService(db).get_highlight_color(user_id=user.id, task_id=task.id),
                "personal_highlight_default": UserTaskDisplayService(db).get_highlight_color(user_id=user.id, task_id=task.id)
                or user.accent_color,
                "redirect_to": redirect_target,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    payload = TaskUpdate(
        title=title,
        description=description,
        due_date=update_due_date,
        effort_level=update_level,
        status=update_status,
        **recurrence_values,
    )
    service.update_task(task, payload)
    UserTaskDisplayService(db).set_highlight_color(
        user=user,
        task=task,
        highlight_color=normalized_highlight_color if highlight_enabled else None,
    )
    return _redirect_to_target(request=request, redirect_to=redirect_target, default=f"/tasks/{task_id}")


@router.post("/tasks/{task_id}/display")
def task_display_submit(
    task_id: int,
    request: Request,
    use_personal_highlight: str = Form("false"),
    personal_highlight_color: str = Form(""),
    redirect_to: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task = TaskService(db).get_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    if not _can_access_task_detail(viewer=user, task=task):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed.")

    highlight_enabled = use_personal_highlight.lower() in {"true", "on", "1", "yes"}
    try:
        UserTaskDisplayService(db).set_highlight_color(
            user=user,
            task=task,
            highlight_color=(personal_highlight_color or user.accent_color) if highlight_enabled else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _redirect_to_target(request=request, redirect_to=redirect_to, default=f"/tasks/{task_id}")


@router.post("/tasks/{task_id}/assign", response_class=HTMLResponse)
def task_assign_submit(
    task_id: int,
    request: Request,
    assignee_id: int = Form(...),
    assignment_date: str = Form(...),
    allow_policy_override: str = Form("false"),
    redirect_to: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task_service = TaskService(db)
    task = task_service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    if not _can_manage_task(viewer=user, task=task):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed.")

    try:
        payload = TaskAssignRequest(assignee_id=assignee_id, assignment_date=date.fromisoformat(assignment_date))
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid assignment payload.") from exc

    success, validation = task_service.assign_task_with_validation(
        task,
        assignee_id=payload.assignee_id,
        assignment_date=payload.assignment_date,
        allow_policy_override=_can_override_schedule_for_assignment(viewer=user, assignee_id=payload.assignee_id)
        and allow_policy_override.lower() in {"true", "on", "1", "yes"},
    )
    if success:
        return _redirect_to_target(request=request, redirect_to=redirect_to, default="/tasks")

    return templates.TemplateResponse(
        "tasks/detail.html",
        _task_detail_context(
            request=request,
            user=user,
            db=db,
            task=task,
            return_to=redirect_to or f"/tasks/{task.id}",
            assignment_feedback={
                **validation,
                "selected_assignee_id": payload.assignee_id,
                "selected_assignment_date": payload.assignment_date.isoformat(),
                "allow_policy_override": _can_override_schedule_for_assignment(viewer=user, assignee_id=payload.assignee_id)
                and allow_policy_override.lower() in {"true", "on", "1", "yes"},
            },
        ),
        status_code=status.HTTP_400_BAD_REQUEST,
    )


@router.post("/tasks/{task_id}/delete")
def task_delete_submit(
    task_id: int,
    request: Request,
    delete_scope: str = Form("single"),
    redirect_to: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service = TaskService(db)
    task = service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    if not _can_delete_task(viewer=user, task=task):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed.")

    is_recurring_root = task.recurrence_pattern == "weekly" and task.recurrence_parent_id is None
    if is_recurring_root and delete_scope != "series":
        RecurringTaskService(db).delete_current_occurrence(task)
    else:
        service.delete_task(task, preserve_completed_history=is_recurring_root and delete_scope == "series")
    return _redirect_to_target(request=request, redirect_to=redirect_to or "/tasks", default="/tasks")


@router.post("/tasks/{task_id}/unassign")
def task_unassign_submit(
    task_id: int,
    request: Request,
    redirect_to: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service = TaskService(db)
    task = service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    if not _can_manage_task(viewer=user, task=task):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed.")
    service.assign_task(task, assignee_id=None, assignment_date=None)
    return _redirect_to_target(request=request, redirect_to=redirect_to, default=f"/tasks/{task_id}")


@router.post("/tasks/{task_id}/status")
def task_status_submit(
    task_id: int,
    request: Request,
    status_value: str = Form(...),
    redirect_to: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service = TaskService(db)
    task = service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    if not _can_update_task_status(viewer=user, task=task):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed.")

    try:
        new_status = TaskStatus(status_value)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid status value.") from exc

    service.update_status(task, new_status)
    return _redirect_to_target(request=request, redirect_to=redirect_to, default=f"/tasks/{task_id}")


@router.get("/tasks/{task_id}/assignment-check", response_class=HTMLResponse)
def task_assignment_check(
    task_id: int,
    request: Request,
    assignee_id: int | None = None,
    assignment_date: str | None = None,
    allow_policy_override: str = "false",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task_service = TaskService(db)
    task = task_service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    if not _can_manage_task(viewer=user, task=task):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed.")

    if not assignee_id or not assignment_date:
        return templates.TemplateResponse(
            "tasks/partials/assignment_feedback.html",
            {"request": request, "feedback": None, "task": task},
        )

    try:
        parsed_date = date.fromisoformat(assignment_date)
    except ValueError:
        return templates.TemplateResponse(
            "tasks/partials/assignment_feedback.html",
            {
                "request": request,
                "task": task,
                "feedback": {"valid": False, "message": "Invalid assignment date."},
            },
        )

    feedback = WorkloadService(db).validate_assignment(
        user_id=assignee_id,
        date_value=parsed_date,
        task_points=task.points_value,
        exclude_task_id=task.id,
        allow_policy_override=_can_override_schedule_for_assignment(viewer=user, assignee_id=assignee_id)
        and allow_policy_override.lower() in {"true", "on", "1", "yes"},
    )
    return templates.TemplateResponse(
        "tasks/partials/assignment_feedback.html",
        {"request": request, "feedback": feedback, "task": task},
    )


@router.get("/tasks/{task_id}/assignment-next-available")
def task_assignment_next_available(
    task_id: int,
    assignee_id: int | None = None,
    allow_policy_override: str = "false",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task_service = TaskService(db)
    task = task_service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    if not _can_manage_task(viewer=user, task=task):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed.")
    if not assignee_id:
        return JSONResponse({"ok": False, "message": "Select a user first."}, status_code=status.HTTP_400_BAD_REQUEST)

    allow_override = _can_override_schedule_for_assignment(viewer=user, assignee_id=assignee_id) and allow_policy_override.lower() in {
        "true",
        "on",
        "1",
        "yes",
    }
    payload = _next_available_assignment_shortcut(
        db=db,
        task=task,
        assignee_id=assignee_id,
        allow_policy_override=allow_override,
    )
    status_code = status.HTTP_200_OK if payload["ok"] else status.HTTP_400_BAD_REQUEST
    return JSONResponse(payload, status_code=status_code)


@router.get("/schedule", response_class=HTMLResponse)
def schedule_page(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return templates.TemplateResponse("schedule.html", _schedule_page_context(request=request, user=user, db=db))


@router.get("/appearance", response_class=HTMLResponse)
def appearance_page(request: Request, user: User = Depends(get_current_user)):
    return templates.TemplateResponse("appearance.html", _appearance_page_context(request=request, user=user))


@router.post("/appearance", response_class=HTMLResponse)
def appearance_submit(
    request: Request,
    theme_preference: str = Form(...),
    accent_color: str = Form(...),
    overdue_color: str = Form(...),
    recurring_color: str = Form(...),
    in_progress_color: str = Form(...),
    unassigned_color: str = Form(...),
    task_category_button_color_mode: str = Form("match"),
    task_category_overdue_color: str = Form(...),
    task_category_up_next_color: str = Form(...),
    task_category_later_color: str = Form(...),
    task_category_unassigned_color: str = Form(...),
    task_category_in_progress_color: str = Form(...),
    task_category_completed_color: str = Form(...),
    surface_style: str = Form(...),
    density_preference: str = Form(...),
    decoration_style: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service = AuthService(db)
    try:
        service.update_appearance_preferences(
            user,
            theme_preference=theme_preference,
            accent_color=accent_color,
            overdue_color=overdue_color,
            recurring_color=recurring_color,
            in_progress_color=in_progress_color,
            unassigned_color=unassigned_color,
            task_category_button_color_mode=task_category_button_color_mode,
            task_category_overdue_color=task_category_overdue_color,
            task_category_up_next_color=task_category_up_next_color,
            task_category_later_color=task_category_later_color,
            task_category_unassigned_color=task_category_unassigned_color,
            task_category_in_progress_color=task_category_in_progress_color,
            task_category_completed_color=task_category_completed_color,
            surface_style=surface_style,
            density_preference=density_preference,
            decoration_style=decoration_style,
        )
    except ValueError as exc:
        return templates.TemplateResponse(
            "appearance.html",
            _appearance_page_context(request=request, user=user, form_error=str(exc)),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    return RedirectResponse(url="/appearance", status_code=status.HTTP_302_FOUND)


@router.post("/schedule/preferences", response_class=HTMLResponse)
async def schedule_preferences_submit(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    form = await request.form()
    allowed_days = {
        key: form.get(f"allow_{key}") in {"true", "on", "1", "yes"}
        for key in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    }
    if not any(allowed_days.values()):
        return templates.TemplateResponse(
            "schedule.html",
            _schedule_page_context(
                request=request,
                user=user,
                db=db,
                form_error="At least one day must stay available for scheduling.",
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    SchedulingService(db).update_preferences(user_id=user.id, allowed_days=allowed_days)
    return RedirectResponse(url="/schedule", status_code=status.HTTP_302_FOUND)


@router.post("/schedule/away", response_class=HTMLResponse)
def schedule_away_submit(
    request: Request,
    start_date: str = Form(...),
    end_date: str = Form(...),
    note: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        parsed_start = date.fromisoformat(start_date)
        parsed_end = date.fromisoformat(end_date)
    except ValueError:
        return templates.TemplateResponse(
            "schedule.html",
            _schedule_page_context(request=request, user=user, db=db, form_error="Please choose valid away dates."),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if parsed_end < parsed_start:
        return templates.TemplateResponse(
            "schedule.html",
            _schedule_page_context(
                request=request,
                user=user,
                db=db,
                form_error="Away end date must be on or after the start date.",
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    SchedulingService(db).add_away_period(user_id=user.id, start_date=parsed_start, end_date=parsed_end, note=note)
    return RedirectResponse(url="/schedule", status_code=status.HTTP_302_FOUND)


@router.post("/schedule/away/{period_id}/delete")
def schedule_away_delete(
    period_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    SchedulingService(db).remove_away_period(user_id=user.id, period_id=period_id)
    return RedirectResponse(url="/schedule", status_code=status.HTTP_302_FOUND)


@router.get("/day-view", response_class=HTMLResponse)
def day_view(
    request: Request,
    day: str | None = None,
    scope: str = "team",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _sync_recurring_tasks(db)
    if day:
        try:
            target_day = date.fromisoformat(day)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid day value.") from exc
    else:
        target_day = date.today()

    selected_scope = "mine" if scope == "mine" else "team"
    users = _member_users(db)
    workload = WorkloadService(db)
    rows = []
    for member in users:
        if selected_scope == "mine" and member.id != user.id:
            continue
        points = workload.get_daily_points(user_id=member.id, date_value=target_day)
        cap = workload.get_user_capacity(member.id)
        tasks = workload.get_tasks_for_user_on_date(user_id=member.id, date_value=target_day)
        _apply_personal_task_highlights(db=db, user=user, tasks=tasks)
        rows.append(
            {
                "member": member,
                "points": points,
                "capacity": cap,
                "remaining_capacity": None if cap is None else cap - points,
                "tasks": [
                    {
                        "task": task,
                        "can_open": _can_access_task_detail(viewer=user, task=task),
                        "can_update_status": _can_update_task_status(viewer=user, task=task),
                    }
                    for task in tasks
                ],
            }
        )

    return templates.TemplateResponse(
        "day_view.html",
        {
            "request": request,
            "user": user,
            "target_day": target_day,
            "rows": rows,
            "scope": selected_scope,
            "statuses": [TaskStatus.PENDING, TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED],
            "current_page_url": _current_path_with_query(request, "/day-view"),
        },
    )


@router.get("/admin/settings", response_class=HTMLResponse)
def admin_settings_page(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required.")
    service = AdminSettingsService(db)
    return templates.TemplateResponse(
        "admin/settings.html",
        _admin_settings_context(request=request, user=user, service=service, ai_test_result=None),
    )


@router.post("/admin/settings/users")
def admin_user_create(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(""),
    role: str = Form("user"),
    daily_capacity_points: str = Form(""),
    session_timeout_minutes: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required.")

    service = AdminSettingsService(db)
    try:
        cap_value = int(daily_capacity_points) if daily_capacity_points.strip() else None
        timeout_value = int(session_timeout_minutes) if session_timeout_minutes.strip() else None
        if timeout_value is not None and timeout_value <= 0:
            raise ValueError("Session timeout override must be a positive number.")

        service.create_user(
            email=email,
            password=password,
            full_name=full_name.strip() or None,
            is_admin=role.strip().lower() == "admin",
            daily_capacity_points=cap_value,
            session_timeout_minutes=timeout_value,
        )
        context = _admin_settings_context(request=request, user=user, service=service, ai_test_result=None)
        context["user_create_result"] = {"ok": True, "message": f"User {email.strip().lower()} created successfully."}
        return templates.TemplateResponse("admin/settings.html", context)
    except ValueError as exc:
        context = _admin_settings_context(request=request, user=user, service=service, ai_test_result=None)
        context["user_create_result"] = {"ok": False, "error": str(exc)}
        return templates.TemplateResponse("admin/settings.html", context, status_code=status.HTTP_400_BAD_REQUEST)


@router.post("/admin/settings/users/{user_id}/approve")
def admin_user_approve(
    user_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required.")
    try:
        AdminSettingsService(db).approve_user(user_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return RedirectResponse(url="/admin/settings", status_code=status.HTTP_302_FOUND)


@router.post("/admin/settings/users/{user_id}/reject")
def admin_user_reject(
    user_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required.")
    try:
        AdminSettingsService(db).reject_user(user_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return RedirectResponse(url="/admin/settings", status_code=status.HTTP_302_FOUND)


@router.post("/admin/settings/users/{user_id}/visibility")
def admin_user_visibility_update(
    user_id: int,
    visible_in_members: str = Form("false"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required.")
    try:
        AdminSettingsService(db).set_user_member_visibility(
            user_id,
            visible=visible_in_members.lower() in {"true", "on", "1", "yes"},
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return RedirectResponse(url="/admin/settings", status_code=status.HTTP_302_FOUND)


@router.post("/admin/settings/effort")
def admin_effort_save(
    request: Request,
    low_points: int = Form(...),
    medium_points: int = Form(...),
    high_points: int = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required.")
    if min(low_points, medium_points, high_points) <= 0:
        service = AdminSettingsService(db)
        return templates.TemplateResponse(
            "admin/settings.html",
            _admin_settings_context(
                request=request,
                user=user,
                service=service,
                ai_test_result={"ok": False, "error": "Effort points must be positive numbers."},
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    AdminSettingsService(db).upsert_effort_config(
        {
            EffortLevel.LOW: low_points,
            EffortLevel.MEDIUM: medium_points,
            EffortLevel.HIGH: high_points,
        }
    )
    return RedirectResponse(url="/admin/settings", status_code=status.HTTP_302_FOUND)


@router.post("/admin/settings/capacity")
async def admin_capacity_save(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required.")

    form = await request.form()
    capacities: dict[int, int] = {}
    try:
        for key, value in form.items():
            if key.startswith("cap_") and value:
                user_id = int(key.replace("cap_", ""))
                parsed = int(value)
                if parsed <= 0:
                    raise ValueError("Capacity values must be positive.")
                capacities[user_id] = parsed
    except ValueError as exc:
        service = AdminSettingsService(db)
        return templates.TemplateResponse(
            "admin/settings.html",
            _admin_settings_context(
                request=request,
                user=user,
                service=service,
                ai_test_result={"ok": False, "error": str(exc)},
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if capacities:
        AdminSettingsService(db).upsert_user_capacities(capacities)
    return RedirectResponse(url="/admin/settings", status_code=status.HTTP_302_FOUND)


@router.post("/admin/settings/ai")
def admin_ai_save(
    request: Request,
    ai_enabled: str = Form("off"),
    active_provider: str = Form(...),
    active_model: str = Form(...),
    fallback_provider: str = Form(...),
    timeout_seconds: int = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required.")
    service = AdminSettingsService(db)
    try:
        service.update_ai_settings(
            ai_enabled=ai_enabled.lower() in {"on", "true", "1"},
            active_provider=active_provider.strip().lower(),
            active_model=active_model.strip(),
            fallback_provider=fallback_provider.strip().lower(),
            timeout_seconds=timeout_seconds,
        )
        return RedirectResponse(url="/admin/settings", status_code=status.HTTP_302_FOUND)
    except ValueError as exc:
        return templates.TemplateResponse(
            "admin/settings.html",
            _admin_settings_context(
                request=request,
                user=user,
                service=service,
                ai_test_result={"ok": False, "error": str(exc)},
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )


@router.post("/admin/settings/ai/refresh")
def admin_ai_refresh(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required.")
    service = AdminSettingsService(db)
    try:
        service.refresh_ai_models()
        return RedirectResponse(url="/admin/settings", status_code=status.HTTP_302_FOUND)
    except Exception as exc:
        return templates.TemplateResponse(
            "admin/settings.html",
            _admin_settings_context(
                request=request,
                user=user,
                service=service,
                ai_test_result={"ok": False, "error": f"Model refresh failed: {exc}"},
            ),
            status_code=status.HTTP_502_BAD_GATEWAY,
        )


@router.post("/admin/settings/ai/test", response_class=HTMLResponse)
def admin_ai_test(
    request: Request,
    test_title: str = Form("Test task"),
    test_description: str = Form("Please classify this sample task effort."),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required.")
    service = AdminSettingsService(db)
    test_result = service.test_ai_provider(sample_title=test_title, sample_description=test_description)
    return templates.TemplateResponse(
        "admin/settings.html",
        _admin_settings_context(request=request, user=user, service=service, ai_test_result=test_result),
    )


@router.get("/admin")
def admin_root(user: User = Depends(get_current_user)):
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required.")
    return RedirectResponse(url="/admin/settings", status_code=status.HTTP_302_FOUND)


@router.post("/logout")
def logout():
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie("access_token")
    return response


@router.post("/preferences/theme")
def update_theme_preference(
    request: Request,
    theme_preference: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service = AuthService(db)
    try:
        service.update_theme_preference(user, theme_preference)
    except ValueError:
        pass

    referer = request.headers.get("referer") or "/dashboard"
    parsed = urlparse(referer)
    redirect_path = parsed.path or "/dashboard"
    if parsed.query:
        redirect_path = f"{redirect_path}?{parsed.query}"
    return RedirectResponse(url=redirect_path, status_code=status.HTTP_302_FOUND)


@router.post("/assistant/chat")
def assistant_chat(
    message: str = Form(...),
    context_json: str = Form("[]"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        parsed_context = json.loads(context_json) if context_json else []
        if not isinstance(parsed_context, list):
            parsed_context = []
    except json.JSONDecodeError:
        parsed_context = []

    result = AppAssistantService(db, user=user).respond(message, context_items=parsed_context)
    return JSONResponse(result)


@router.post("/assistant/actions/assign-self")
def assistant_assign_self(
    task_id: int = Form(...),
    assignment_date: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        parsed_date = date.fromisoformat(assignment_date)
    except ValueError:
        return JSONResponse({"ok": False, "reply": "Invalid assignment date."}, status_code=status.HTTP_400_BAD_REQUEST)

    result = AppAssistantService(db, user=user).assign_self_to_task(task_id=task_id, assignment_date=parsed_date)
    status_code = status.HTTP_200_OK if result.get("ok") else status.HTTP_400_BAD_REQUEST
    return JSONResponse(result, status_code=status_code)
