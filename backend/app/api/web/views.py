import json
from datetime import date
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.orm import Session

from backend.app.ai.schemas.classification import TaskClassificationResult
from backend.app.api.deps import get_current_user
from backend.app.db.session import get_db
from backend.app.models.enums import EffortLevel, TaskStatus
from backend.app.models.user import User
from backend.app.schemas.auth import RegisterRequest
from backend.app.schemas.task import TaskAssignRequest, TaskCreate, TaskUpdate
from backend.app.services.admin_settings_service import AdminSettingsService
from backend.app.services.ai_service import AIService
from backend.app.services.app_assistant_service import AppAssistantService
from backend.app.services.auth_service import AuthService
from backend.app.services.task_service import TaskService
from backend.app.services.workload_service import WorkloadService

router = APIRouter()
templates = Jinja2Templates(directory="backend/app/templates")


def _can_access_task_detail(*, viewer: User, task) -> bool:
    return viewer.is_admin or viewer.is_active


def _can_manage_task(*, viewer: User, task) -> bool:
    return viewer.is_admin or viewer.is_active


def _can_update_task_status(*, viewer: User, task) -> bool:
    return viewer.is_admin or task.assignee_id == viewer.id


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
    service = TaskService(db)
    workload = WorkloadService(db)
    admin_service = AdminSettingsService(db)
    ai_ui_status = admin_service.get_ai_ui_status()
    users_for_today = _member_users(db)
    all_tasks = service.get_tasks()
    unassigned_tasks = service.get_tasks(only_unassigned=True)

    today = date.today()
    today_workload = []
    for item in users_for_today:
        points = workload.get_daily_points(user_id=item.id, date_value=today)
        capacity = workload.get_user_capacity(item.id)
        today_workload.append(
            {
                "user": item,
                "points": points,
                "capacity": capacity,
                "remaining_capacity": None if capacity is None else capacity - points,
            }
        )
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "unassigned_tasks": unassigned_tasks,
            "all_tasks": all_tasks,
            "today_workload": today_workload,
            "ai_ui_status": ai_ui_status,
        },
    )


@router.get("/tasks", response_class=HTMLResponse)
def tasks_page(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    service = TaskService(db)
    tasks = service.get_tasks()
    return templates.TemplateResponse(
        "tasks/list.html",
        {
            "request": request,
            "user": user,
            "tasks": tasks,
            "statuses": [TaskStatus.PENDING, TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED],
            "current_page_url": _current_path_with_query(request, "/tasks"),
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
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ai_settings = AdminSettingsService(db).get_ai_settings()
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
                "form_error": "Please choose a valid due date.",
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
                "form_error": "Please provide title, description, due date, and a valid effort level.",
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    TaskService(db).create_unassigned_task(payload, user)
    return RedirectResponse(url="/tasks", status_code=status.HTTP_302_FOUND)


@router.get("/tasks/{task_id}", response_class=HTMLResponse)
def task_detail_page(task_id: int, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    service = TaskService(db)
    task = service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    if not _can_access_task_detail(viewer=user, task=task):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed.")
    all_users = _assignable_users_for_task(db, task)
    return templates.TemplateResponse(
        "tasks/detail.html",
        {
            "request": request,
            "user": user,
            "task": task,
            "all_users": all_users,
            "statuses": [TaskStatus.PENDING, TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED],
            "assignment_feedback": None,
            "current_page_url": _current_path_with_query(request, f"/tasks/{task.id}"),
            "can_manage_task": _can_manage_task(viewer=user, task=task),
            "can_update_status": _can_update_task_status(viewer=user, task=task),
        },
    )


@router.get("/tasks/{task_id}/edit", response_class=HTMLResponse)
def task_edit_page(task_id: int, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    service = TaskService(db)
    task = service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    if not _can_manage_task(viewer=user, task=task):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed.")
    return templates.TemplateResponse(
        "tasks/edit.html",
        {
            "request": request,
            "user": user,
            "task": task,
            "levels": [EffortLevel.LOW, EffortLevel.MEDIUM, EffortLevel.HIGH],
            "statuses": [TaskStatus.PENDING, TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED],
            "form_error": None,
        },
    )


@router.post("/tasks/{task_id}/edit", response_class=HTMLResponse)
def task_edit_submit(
    task_id: int,
    title: str = Form(...),
    description: str = Form(...),
    due_date: str = Form(...),
    effort_level: str = Form(...),
    status_value: str = Form("pending"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service = TaskService(db)
    task = service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    if not _can_manage_task(viewer=user, task=task):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed.")

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
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    payload = TaskUpdate(
        title=title,
        description=description,
        due_date=update_due_date,
        effort_level=update_level,
        status=update_status,
    )
    service.update_task(task, payload)
    return RedirectResponse(url=f"/tasks/{task_id}", status_code=status.HTTP_302_FOUND)


@router.post("/tasks/{task_id}/assign", response_class=HTMLResponse)
def task_assign_submit(
    task_id: int,
    request: Request,
    assignee_id: int = Form(...),
    assignment_date: str = Form(...),
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
    )
    if success:
        return RedirectResponse(url=f"/tasks/{task_id}", status_code=status.HTTP_302_FOUND)

    all_users = _assignable_users_for_task(db, task)
    return templates.TemplateResponse(
        "tasks/detail.html",
        {
            "request": request,
            "user": user,
            "task": task,
            "all_users": all_users,
            "statuses": [TaskStatus.PENDING, TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED],
            "assignment_feedback": {
                **validation,
                "selected_assignee_id": payload.assignee_id,
                "selected_assignment_date": payload.assignment_date.isoformat(),
            },
            "current_page_url": f"/tasks/{task.id}",
            "can_manage_task": _can_manage_task(viewer=user, task=task),
            "can_update_status": _can_update_task_status(viewer=user, task=task),
        },
        status_code=status.HTTP_400_BAD_REQUEST,
    )


@router.post("/tasks/{task_id}/unassign")
def task_unassign_submit(
    task_id: int,
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
    return RedirectResponse(url=f"/tasks/{task_id}", status_code=status.HTTP_302_FOUND)


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
    )
    return templates.TemplateResponse(
        "tasks/partials/assignment_feedback.html",
        {"request": request, "feedback": feedback, "task": task},
    )


@router.get("/day-view", response_class=HTMLResponse)
def day_view(
    request: Request,
    day: str | None = None,
    scope: str = "team",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
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
