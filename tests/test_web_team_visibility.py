from datetime import date, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app.db.base import Base
from backend.app.db.session import SessionLocal, engine
from backend.app.main import app
from backend.app.core.security import create_access_token
from backend.app.models.enums import EffortLevel, TaskStatus
from backend.app.models.task_effort_config import TaskEffortConfig
from backend.app.models.user_daily_capacity import UserDailyCapacity
from backend.app.schemas.auth import RegisterRequest
from backend.app.schemas.task import TaskCreate
from backend.app.services.auth_service import AuthService
from backend.app.services.task_service import TaskService


def setup_module():
    Base.metadata.create_all(bind=engine)


def _ensure_effort_config(db):
    for level, points in (
        (EffortLevel.LOW, 2),
        (EffortLevel.MEDIUM, 5),
        (EffortLevel.HIGH, 8),
    ):
        if not db.get(TaskEffortConfig, level):
            db.add(TaskEffortConfig(level=level, points_value=points))
    db.commit()


def _create_user(db, *, email: str, full_name: str, capacity: int, is_admin: bool = False, show_in_member_lists: bool | None = None):
    user = AuthService(db).register(
        RegisterRequest(
            email=email,
            full_name=full_name,
            password="securepass123",
        ),
        is_admin=is_admin,
        require_approval=False,
        show_in_member_lists=show_in_member_lists,
    )
    db.add(UserDailyCapacity(user_id=user.id, daily_capacity_points=capacity))
    db.commit()
    db.refresh(user)
    return user


def _create_task(db, *, creator, assignee, title: str, day: date):
    task = TaskService(db).create_unassigned_task(
        TaskCreate(
            title=title,
            description="Task description",
            due_date=day,
            effort_level=EffortLevel.MEDIUM,
            ai_suggested_level=EffortLevel.MEDIUM,
            ai_confidence=0.7,
            ai_reason="test",
            fallback_used=False,
            provider_used="rules",
            model_used="rules-default",
        ),
        creator,
    )
    TaskService(db).assign_task(task, assignee_id=assignee.id, assignment_date=day)
    return task


def _authed_client(user):
    client = TestClient(app)
    token = create_access_token(subject=str(user.id))
    client.cookies.set("access_token", token)
    return client


def test_non_admin_dashboard_shows_team_workload():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(
            db,
            email=f"team-viewer-{token}@example.com",
            full_name="Viewer User",
            capacity=9,
        )
        teammate = _create_user(
            db,
            email=f"team-mate-{token}@example.com",
            full_name="Teammate User",
            capacity=7,
        )
        day = date.today()
        _create_task(db, creator=teammate, assignee=teammate, title=f"Team Task {token}", day=day)

        client = _authed_client(viewer)
        response = client.get("/dashboard")

        assert response.status_code == 200
        assert "Teammate User" in response.text
        assert "2 pts left" in response.text
    finally:
        db.close()


def test_non_admin_day_view_can_toggle_between_team_and_mine():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(
            db,
            email=f"toggle-viewer-{token}@example.com",
            full_name="Toggle Viewer",
            capacity=10,
        )
        teammate = _create_user(
            db,
            email=f"toggle-mate-{token}@example.com",
            full_name="Toggle Mate",
            capacity=8,
        )
        day = date.today() + timedelta(days=1)
        other_task = _create_task(db, creator=teammate, assignee=teammate, title=f"Other Task {token}", day=day)

        client = _authed_client(viewer)

        team_response = client.get(f"/day-view?day={day.isoformat()}")
        assert team_response.status_code == 200
        assert "Toggle Mate" in team_response.text
        assert f"Other Task {token}" in team_response.text
        assert f'href="/tasks/{other_task.id}"' in team_response.text

        mine_response = client.get(f"/day-view?day={day.isoformat()}&scope=mine")
        assert mine_response.status_code == 200
        assert "Toggle Mate" not in mine_response.text
        assert f"Other Task {token}" not in mine_response.text
    finally:
        db.close()


def test_quick_status_update_redirects_back_to_current_view():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(
            db,
            email=f"status-viewer-{token}@example.com",
            full_name="Status Viewer",
            capacity=10,
        )
        day = date.today() + timedelta(days=2)
        task = _create_task(db, creator=viewer, assignee=viewer, title=f"Status Task {token}", day=day)

        client = _authed_client(viewer)
        response = client.post(
            f"/tasks/{task.id}/status",
            data={
                "status_value": TaskStatus.COMPLETED.value,
                "redirect_to": f"/day-view?day={day.isoformat()}&scope=mine",
            },
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert response.headers["location"] == f"/day-view?day={day.isoformat()}&scope=mine"

        db.refresh(task)
        assert task.status == TaskStatus.COMPLETED
    finally:
        db.close()


def test_hidden_admin_is_not_shown_in_member_views():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(
            db,
            email=f"member-viewer-{token}@example.com",
            full_name="Member Viewer",
            capacity=10,
        )
        _create_user(
            db,
            email=f"hidden-admin-{token}@example.com",
            full_name="System Admin Hidden",
            capacity=10,
            is_admin=True,
            show_in_member_lists=False,
        )
        day = date.today()

        client = _authed_client(viewer)

        dashboard_response = client.get("/dashboard")
        assert dashboard_response.status_code == 200
        assert "System Admin Hidden" not in dashboard_response.text

        day_view_response = client.get(f"/day-view?day={day.isoformat()}&scope=team")
        assert day_view_response.status_code == 200
        assert "System Admin Hidden" not in day_view_response.text
    finally:
        db.close()


def test_hidden_assignee_still_displays_name_on_task_detail():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(
            db,
            email=f"hidden-viewer-{token}@example.com",
            full_name="Hidden Viewer",
            capacity=10,
        )
        hidden_admin = _create_user(
            db,
            email=f"hidden-assignee-{token}@example.com",
            full_name="Hidden Admin",
            capacity=10,
            is_admin=True,
            show_in_member_lists=False,
        )
        day = date.today()
        task = _create_task(db, creator=viewer, assignee=hidden_admin, title=f"Hidden Task {token}", day=day)

        client = _authed_client(viewer)
        response = client.get(f"/tasks/{task.id}")

        assert response.status_code == 200
        assert "Hidden Admin" in response.text
        assert "hidden from member lists" in response.text
        assert f'Assignee:</span> {hidden_admin.id}' not in response.text
    finally:
        db.close()


def test_assignee_can_open_task_and_update_status():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        creator = _create_user(
            db,
            email=f"creator-{token}@example.com",
            full_name="Task Creator",
            capacity=10,
        )
        assignee = _create_user(
            db,
            email=f"assignee-{token}@example.com",
            full_name="Task Assignee",
            capacity=10,
        )
        day = date.today() + timedelta(days=3)
        task = _create_task(db, creator=creator, assignee=assignee, title=f"Assigned Task {token}", day=day)

        client = _authed_client(assignee)

        detail_response = client.get(f"/tasks/{task.id}")
        assert detail_response.status_code == 200
        assert 'name="status_value"' in detail_response.text

        tasks_response = client.get("/tasks")
        assert tasks_response.status_code == 200
        assert f"Assigned Task {token}" in tasks_response.text

        status_response = client.post(
            f"/tasks/{task.id}/status",
            data={"status_value": TaskStatus.IN_PROGRESS.value, "redirect_to": f"/tasks/{task.id}"},
            follow_redirects=False,
        )
        assert status_response.status_code == 302

        db.refresh(task)
        assert task.status == TaskStatus.IN_PROGRESS
    finally:
        db.close()


def test_unrelated_user_can_open_task_but_cannot_quick_update_status():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        creator = _create_user(
            db,
            email=f"owner-{token}@example.com",
            full_name="Owner User",
            capacity=10,
        )
        assignee = _create_user(
            db,
            email=f"helper-{token}@example.com",
            full_name="Helper User",
            capacity=10,
        )
        outsider = _create_user(
            db,
            email=f"outsider-{token}@example.com",
            full_name="Outsider User",
            capacity=10,
        )
        day = date.today() + timedelta(days=4)
        task = _create_task(db, creator=creator, assignee=assignee, title=f"Private Task {token}", day=day)

        client = _authed_client(outsider)

        detail_response = client.get(f"/tasks/{task.id}")
        assert detail_response.status_code == 200
        assert 'name="status_value"' not in detail_response.text

        edit_response = client.get(f"/tasks/{task.id}/edit")
        assert edit_response.status_code == 200

        tasks_response = client.get("/tasks")
        assert tasks_response.status_code == 200
        assert f"Private Task {token}" in tasks_response.text

        status_response = client.post(
            f"/tasks/{task.id}/status",
            data={"status_value": TaskStatus.COMPLETED.value, "redirect_to": "/tasks"},
            follow_redirects=False,
        )
        assert status_response.status_code == 403
    finally:
        db.close()
