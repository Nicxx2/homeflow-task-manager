import re
from datetime import date, timedelta
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app.api.web.views import _dashboard_workload_status
from backend.app.db.base import Base
from backend.app.db.session import SessionLocal, engine
from backend.app.main import app
from backend.app.core.security import create_access_token
from backend.app.models.enums import EffortLevel, TaskStatus
from backend.app.models.task import Task
from backend.app.models.task_effort_config import TaskEffortConfig
from backend.app.models.user_daily_capacity import UserDailyCapacity
from backend.app.schemas.auth import RegisterRequest
from backend.app.schemas.task import TaskCreate
from backend.app.services.admin_settings_service import AdminSettingsService
from backend.app.services.auth_service import AuthService
from backend.app.services.recurring_task_service import RecurringTaskService
from backend.app.services.scheduling_service import SchedulingService
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


def _create_task(
    db,
    *,
    creator,
    assignee,
    title: str,
    day: date | None = None,
    due_date: date | None = None,
    assignment_date: date | None = None,
    effort_level: EffortLevel = EffortLevel.MEDIUM,
):
    due_value = due_date or day
    assignment_value = assignment_date or day or due_value
    if due_value is None or assignment_value is None:
        raise ValueError("Task creation requires a due date and assignment date.")

    task = TaskService(db).create_unassigned_task(
        TaskCreate(
            title=title,
            description="Task description",
            due_date=due_value,
            effort_level=effort_level,
            ai_suggested_level=effort_level,
            ai_confidence=0.7,
            ai_reason="test",
            fallback_used=False,
            provider_used="rules",
            model_used="rules-default",
        ),
        creator,
    )
    TaskService(db).assign_task(task, assignee_id=assignee.id, assignment_date=assignment_value)
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


def test_dashboard_renders_unassigned_overdue_tasks():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(
            db,
            email=f"dashboard-overdue-{token}@example.com",
            full_name="Dashboard Overdue",
            capacity=8,
        )
        overdue_day = date.fromordinal(date.today().toordinal() - 1)
        TaskService(db).create_unassigned_task(
            TaskCreate(
                title=f"Overdue Unassigned {token}",
                description="Regression coverage",
                due_date=overdue_day,
                effort_level=EffortLevel.LOW,
                ai_suggested_level=EffortLevel.LOW,
                ai_confidence=0.7,
                ai_reason="test",
                fallback_used=False,
                provider_used="rules",
                model_used="rules-default",
            ),
            viewer,
        )

        client = _authed_client(viewer)
        response = client.get("/dashboard")

        assert response.status_code == 200
        assert f"Overdue Unassigned {token}" in response.text
    finally:
        db.close()


def test_dashboard_next_task_skips_completed_tasks():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(
            db,
            email=f"dashboard-skip-completed-viewer-{token}@example.com",
            full_name="Dashboard Skip Completed Viewer",
            capacity=8,
            show_in_member_lists=False,
        )
        teammate = _create_user(
            db,
            email=f"dashboard-skip-completed-mate-{token}@example.com",
            full_name="Dashboard Skip Completed Mate",
            capacity=8,
        )
        day = date.today()
        first_task = _create_task(db, creator=viewer, assignee=teammate, title=f"Done First {token}", day=day)
        second_task = _create_task(db, creator=viewer, assignee=teammate, title=f"Still Open {token}", day=day)
        TaskService(db).update_status(first_task, TaskStatus.COMPLETED)

        client = _authed_client(viewer)
        response = client.get("/dashboard")

        assert response.status_code == 200
        assert f"Next task: Still Open {token}" in response.text
        assert f"Next task: Done First {token}" not in response.text
    finally:
        db.close()


def test_dashboard_workload_status_boundaries():
    assert _dashboard_workload_status(remaining_capacity=None, schedule_block=None) == ("Capacity unset", "slate")
    assert _dashboard_workload_status(remaining_capacity=-1, schedule_block=None) == ("Over", "red")
    assert _dashboard_workload_status(remaining_capacity=0, schedule_block=None) == ("Full", "amber")
    assert _dashboard_workload_status(remaining_capacity=1, schedule_block=None) == ("Nearly full", "amber")
    assert _dashboard_workload_status(remaining_capacity=2, schedule_block=None) == ("Nearly full", "amber")
    assert _dashboard_workload_status(remaining_capacity=3, schedule_block=None) == ("Free", "emerald")


def test_dashboard_workload_status_away_takes_precedence():
    schedule_block = {"type": "away", "message": "Away today"}
    assert _dashboard_workload_status(remaining_capacity=0, schedule_block=schedule_block) == ("Away", "amber")
    assert _dashboard_workload_status(remaining_capacity=-5, schedule_block=schedule_block) == ("Away", "amber")


def test_dashboard_marks_exact_capacity_as_full():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(
            db,
            email=f"dashboard-full-viewer-{token}@example.com",
            full_name="Dashboard Full Viewer",
            capacity=8,
            show_in_member_lists=False,
        )
        teammate = _create_user(
            db,
            email=f"dashboard-full-mate-{token}@example.com",
            full_name="Dashboard Full Mate",
            capacity=8,
        )
        day = date.today()
        _create_task(
            db,
            creator=viewer,
            assignee=teammate,
            title=f"Exactly Full {token}",
            day=day,
            effort_level=EffortLevel.HIGH,
        )

        client = _authed_client(viewer)
        response = client.get("/dashboard")

        assert response.status_code == 200
        assert "Dashboard Full Mate" in response.text
        assert "Full" in response.text
        assert "Nearly full" not in response.text
        assert "Remaining: 0 pts left" in response.text
    finally:
        db.close()


def test_dashboard_hides_next_task_when_all_tasks_for_today_are_completed():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(
            db,
            email=f"dashboard-all-complete-viewer-{token}@example.com",
            full_name="Dashboard All Complete Viewer",
            capacity=8,
            show_in_member_lists=False,
        )
        teammate = _create_user(
            db,
            email=f"dashboard-all-complete-mate-{token}@example.com",
            full_name="Dashboard All Complete Mate",
            capacity=8,
        )
        day = date.today()
        completed_task = _create_task(db, creator=viewer, assignee=teammate, title=f"Finished {token}", day=day)
        TaskService(db).update_status(completed_task, TaskStatus.COMPLETED)

        client = _authed_client(viewer)
        response = client.get("/dashboard")

        assert response.status_code == 200
        assert f"Finished {token}" in response.text
        assert "Next task:" not in response.text
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


def test_tasks_next_up_uses_assignment_date_for_mine_scope():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(
            db,
            email=f"next-up-mine-{token}@example.com",
            full_name="Next Up Mine",
            capacity=10,
        )
        tomorrow = date.today() + timedelta(days=1)
        later_day = date.today() + timedelta(days=5)

        planned_next = _create_task(
            db,
            creator=viewer,
            assignee=viewer,
            title=f"Planned Soon {token}",
            due_date=date.today() + timedelta(days=7),
            assignment_date=tomorrow,
        )
        _create_task(
            db,
            creator=viewer,
            assignee=viewer,
            title=f"Due Soon But Planned Later {token}",
            due_date=tomorrow,
            assignment_date=later_day,
        )

        client = _authed_client(viewer)
        response = client.get("/tasks?scope=mine&view=up_next")

        assert response.status_code == 200
        assert planned_next.title in response.text
        assert f"Due Soon But Planned Later {token}" not in response.text
        assert "planned for today or tomorrow" in response.text
    finally:
        db.close()


def test_tasks_next_up_uses_assignment_date_for_team_scope():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(
            db,
            email=f"next-up-team-viewer-{token}@example.com",
            full_name="Next Up Team Viewer",
            capacity=10,
        )
        teammate = _create_user(
            db,
            email=f"next-up-team-mate-{token}@example.com",
            full_name="Next Up Team Mate",
            capacity=10,
        )
        tomorrow = date.today() + timedelta(days=1)
        later_day = date.today() + timedelta(days=6)

        planned_next = _create_task(
            db,
            creator=viewer,
            assignee=teammate,
            title=f"Team Planned Soon {token}",
            due_date=date.today() + timedelta(days=8),
            assignment_date=tomorrow,
        )
        _create_task(
            db,
            creator=viewer,
            assignee=teammate,
            title=f"Team Due Soon But Planned Later {token}",
            due_date=tomorrow,
            assignment_date=later_day,
        )

        client = _authed_client(viewer)
        response = client.get("/tasks?scope=team&view=up_next")

        assert response.status_code == 200
        assert planned_next.title in response.text
        assert f"Team Due Soon But Planned Later {token}" not in response.text
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


def test_member_status_update_setting_controls_cross_user_status_changes():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(
            db,
            email=f"status-toggle-viewer-{token}@example.com",
            full_name="Status Toggle Viewer",
            capacity=10,
        )
        teammate = _create_user(
            db,
            email=f"status-toggle-mate-{token}@example.com",
            full_name="Status Toggle Mate",
            capacity=10,
        )
        task = _create_task(
            db,
            creator=teammate,
            assignee=teammate,
            title=f"Shared Status Task {token}",
            day=date.today() + timedelta(days=2),
        )

        service = AdminSettingsService(db)
        settings = service.get_app_settings()
        original_member_status_updates = settings.allow_member_status_updates
        try:
            service.update_task_collaboration_settings(allow_member_status_updates=False)

            client = _authed_client(viewer)
            blocked = client.post(
                f"/tasks/{task.id}/status",
                data={"status_value": TaskStatus.COMPLETED.value},
                follow_redirects=False,
            )
            assert blocked.status_code == 403

            assignee_response = _authed_client(teammate).post(
                f"/tasks/{task.id}/status",
                data={"status_value": TaskStatus.IN_PROGRESS.value},
                follow_redirects=False,
            )
            assert assignee_response.status_code == 302
            db.refresh(task)
            assert task.status == TaskStatus.IN_PROGRESS

            service.update_task_collaboration_settings(allow_member_status_updates=True)
            allowed = client.post(
                f"/tasks/{task.id}/status",
                data={"status_value": TaskStatus.COMPLETED.value},
                follow_redirects=False,
            )
            assert allowed.status_code == 302
            db.refresh(task)
            assert task.status == TaskStatus.COMPLETED

            delete_response = client.post(f"/tasks/{task.id}/delete", follow_redirects=False)
            assert delete_response.status_code == 403
        finally:
            service.update_task_collaboration_settings(
                allow_member_status_updates=original_member_status_updates,
            )
    finally:
        db.close()


def test_assignment_success_redirects_to_tasks_list():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(
            db,
            email=f"assign-redirect-{token}@example.com",
            full_name="Assign Redirect",
            capacity=10,
        )
        day = date.today() + timedelta(days=5)
        task = TaskService(db).create_unassigned_task(
            TaskCreate(
                title=f"Assign Redirect Task {token}",
                description="Redirect test",
                due_date=day,
                effort_level=EffortLevel.LOW,
                ai_suggested_level=EffortLevel.LOW,
                ai_confidence=0.7,
                ai_reason="test",
                fallback_used=False,
                provider_used="rules",
                model_used="rules-default",
            ),
            viewer,
        )

        client = _authed_client(viewer)
        response = client.post(
            f"/tasks/{task.id}/assign",
            data={"assignee_id": viewer.id, "assignment_date": day.isoformat()},
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert response.headers["location"] == "/tasks"
    finally:
        db.close()


def test_assignment_feedback_shows_suggested_date_action():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(
            db,
            email=f"assign-feedback-{token}@example.com",
            full_name="Assign Feedback",
            capacity=6,
        )
        day = date.today() + timedelta(days=6)
        existing = _create_task(db, creator=viewer, assignee=viewer, title=f"Existing Load {token}", day=day)
        task = TaskService(db).create_unassigned_task(
            TaskCreate(
                title=f"Needs Suggestion {token}",
                description="Suggestion test",
                due_date=day,
                effort_level=EffortLevel.MEDIUM,
                ai_suggested_level=EffortLevel.MEDIUM,
                ai_confidence=0.7,
                ai_reason="test",
                fallback_used=False,
                provider_used="rules",
                model_used="rules-default",
            ),
            viewer,
        )

        assert existing.points_value == 5
        assert task.points_value == 5

        client = _authed_client(viewer)
        response = client.get(
            f"/tasks/{task.id}/assignment-check?assignee_id={viewer.id}&assignment_date={day.isoformat()}"
        )

        assert response.status_code == 200
        assert "Use suggested date" in response.text
    finally:
        db.close()


def test_task_detail_defaults_assignment_date_to_today_for_unassigned_tasks():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(
            db,
            email=f"detail-default-date-{token}@example.com",
            full_name="Detail Default Date",
            capacity=8,
        )
        due_day = date.today() + timedelta(days=9)
        task = TaskService(db).create_unassigned_task(
            TaskCreate(
                title=f"Default Date Task {token}",
                description="Check task detail default date",
                due_date=due_day,
                effort_level=EffortLevel.LOW,
                ai_suggested_level=EffortLevel.LOW,
                ai_confidence=0.7,
                ai_reason="test",
                fallback_used=False,
                provider_used="rules",
                model_used="rules-default",
            ),
            viewer,
        )

        client = _authed_client(viewer)
        response = client.get(f"/tasks/{task.id}")

        assert response.status_code == 200
        assert f'id="assignment_date"' in response.text
        assert f'value="{date.today().isoformat()}"' in response.text
    finally:
        db.close()


def test_task_detail_uses_existing_assignment_date_when_task_is_already_assigned():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(
            db,
            email=f"detail-assigned-default-date-{token}@example.com",
            full_name="Detail Assigned Default Date",
            capacity=8,
        )
        assigned_day = date.today() + timedelta(days=6)
        task = _create_task(
            db,
            creator=viewer,
            assignee=viewer,
            title=f"Assigned Default Date Task {token}",
            day=assigned_day,
        )

        client = _authed_client(viewer)
        response = client.get(f"/tasks/{task.id}")

        assert response.status_code == 200
        assert f'id="assignment_date"' in response.text
        assert f'value="{assigned_day.isoformat()}"' in response.text
    finally:
        db.close()


def test_assignment_next_available_shortcut_starts_from_tomorrow():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(
            db,
            email=f"next-available-shortcut-{token}@example.com",
            full_name="Next Available Shortcut",
            capacity=10,
        )
        SchedulingService(db).update_preferences(
            user_id=viewer.id,
            allowed_days={
                "monday": True,
                "tuesday": True,
                "wednesday": True,
                "thursday": True,
                "friday": True,
                "saturday": True,
                "sunday": True,
            },
        )
        due_day = date.today() + timedelta(days=3)
        task = TaskService(db).create_unassigned_task(
            TaskCreate(
                title=f"Shortcut Task {token}",
                description="Check next available shortcut",
                due_date=due_day,
                effort_level=EffortLevel.LOW,
                ai_suggested_level=EffortLevel.LOW,
                ai_confidence=0.7,
                ai_reason="test",
                fallback_used=False,
                provider_used="rules",
                model_used="rules-default",
            ),
            viewer,
        )

        client = _authed_client(viewer)
        response = client.get(f"/tasks/{task.id}/assignment-next-available?assignee_id={viewer.id}")

        assert response.status_code == 200
        assert response.json()["assignment_date"] == (date.today() + timedelta(days=1)).isoformat()
    finally:
        db.close()


def test_assignment_in_past_is_blocked_in_web_flow():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(
            db,
            email=f"assign-past-{token}@example.com",
            full_name="Assign Past",
            capacity=10,
        )
        day = date.today()
        task = TaskService(db).create_unassigned_task(
            TaskCreate(
                title=f"Past Block Task {token}",
                description="Past date test",
                due_date=day,
                effort_level=EffortLevel.LOW,
                ai_suggested_level=EffortLevel.LOW,
                ai_confidence=0.7,
                ai_reason="test",
                fallback_used=False,
                provider_used="rules",
                model_used="rules-default",
            ),
            viewer,
        )

        past_day = date.fromordinal(date.today().toordinal() - 1)
        client = _authed_client(viewer)
        response = client.post(
            f"/tasks/{task.id}/assign",
            data={"assignee_id": viewer.id, "assignment_date": past_day.isoformat()},
            follow_redirects=False,
        )

        assert response.status_code == 400
        assert "Assignment date cannot be in the past." in response.text
    finally:
        db.close()


def test_delete_controls_only_show_for_creator_and_admin():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        creator = _create_user(
            db,
            email=f"delete-creator-{token}@example.com",
            full_name="Delete Creator",
            capacity=10,
        )
        admin = _create_user(
            db,
            email=f"delete-admin-{token}@example.com",
            full_name="Delete Admin",
            capacity=10,
            is_admin=True,
            show_in_member_lists=False,
        )
        outsider = _create_user(
            db,
            email=f"delete-outsider-{token}@example.com",
            full_name="Delete Outsider",
            capacity=10,
        )
        task = TaskService(db).create_unassigned_task(
            TaskCreate(
                title=f"Delete Control Task {token}",
                description="Delete controls",
                due_date=date.today() + timedelta(days=2),
                effort_level=EffortLevel.LOW,
                ai_suggested_level=EffortLevel.LOW,
                ai_confidence=0.7,
                ai_reason="test",
                fallback_used=False,
                provider_used="rules",
                model_used="rules-default",
            ),
            creator,
        )

        creator_response = _authed_client(creator).get(f"/tasks/{task.id}")
        admin_response = _authed_client(admin).get(f"/tasks/{task.id}")
        outsider_response = _authed_client(outsider).get(f"/tasks/{task.id}")

        assert creator_response.status_code == 200
        assert admin_response.status_code == 200
        assert outsider_response.status_code == 200
        assert 'onclick="openDeleteTaskModal()"' in creator_response.text
        assert 'onclick="openDeleteTaskModal()"' in outsider_response.text
        assert f'action="/tasks/{task.id}/delete"' in creator_response.text
        assert f'action="/tasks/{task.id}/delete"' in admin_response.text
        assert f'action="/tasks/{task.id}/delete"' not in outsider_response.text
        assert "Only the task creator and admins can delete this task." in outsider_response.text
    finally:
        db.close()


def test_non_creator_non_admin_cannot_delete_task():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        creator = _create_user(
            db,
            email=f"delete-owner-{token}@example.com",
            full_name="Delete Owner",
            capacity=10,
        )
        outsider = _create_user(
            db,
            email=f"delete-blocked-{token}@example.com",
            full_name="Delete Blocked",
            capacity=10,
        )
        task = TaskService(db).create_unassigned_task(
            TaskCreate(
                title=f"Delete Block Task {token}",
                description="Delete permissions",
                due_date=date.today() + timedelta(days=2),
                effort_level=EffortLevel.LOW,
                ai_suggested_level=EffortLevel.LOW,
                ai_confidence=0.7,
                ai_reason="test",
                fallback_used=False,
                provider_used="rules",
                model_used="rules-default",
            ),
            creator,
        )

        response = _authed_client(outsider).post(
            f"/tasks/{task.id}/delete",
            data={"redirect_to": "/tasks"},
            follow_redirects=False,
        )

        assert response.status_code == 403
        assert db.get(Task, task.id) is not None
    finally:
        db.close()


def test_creator_can_delete_recurring_task_and_history_snapshots():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        creator = _create_user(
            db,
            email=f"delete-recurring-{token}@example.com",
            full_name="Delete Recurring",
            capacity=10,
        )
        due_day = date.today() + timedelta(days=1)
        task = TaskService(db).create_unassigned_task(
            TaskCreate(
                title=f"Recurring Delete Task {token}",
                description="Recurring delete coverage",
                due_date=due_day,
                effort_level=EffortLevel.LOW,
                ai_suggested_level=EffortLevel.LOW,
                ai_confidence=0.7,
                ai_reason="test",
                fallback_used=False,
                provider_used="rules",
                model_used="rules-default",
                recurrence_pattern="weekly",
                recurrence_interval_weeks=1,
                recurrence_until=None,
                recurrence_count_limit=None,
                recurrence_blocked_behavior="skip",
            ),
            creator,
        )
        TaskService(db).assign_task(task, assignee_id=creator.id, assignment_date=due_day)
        TaskService(db).update_status(task, TaskStatus.COMPLETED)

        history_count = db.query(Task).filter(Task.recurrence_parent_id == task.id).count()
        assert history_count == 1

        response = _authed_client(creator).post(
            f"/tasks/{task.id}/delete",
            data={"redirect_to": "/tasks", "delete_scope": "series"},
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert response.headers["location"] == "/tasks"
        assert db.get(Task, task.id) is None
        preserved_history = (
            db.query(Task)
            .filter(
                Task.title == f"Recurring Delete Task {token}",
                Task.status == TaskStatus.COMPLETED,
                Task.due_date == due_day,
            )
            .all()
        )
        assert len(preserved_history) == 1
        assert preserved_history[0].recurrence_parent_id is None
    finally:
        db.close()


def test_creator_can_delete_only_current_recurring_occurrence_and_keep_series():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        creator = _create_user(
            db,
            email=f"delete-recurring-single-{token}@example.com",
            full_name="Delete Recurring Single",
            capacity=10,
        )
        due_day = date.today() + timedelta(days=1)
        task = TaskService(db).create_unassigned_task(
            TaskCreate(
                title=f"Recurring Single Delete Task {token}",
                description="Delete one recurring occurrence",
                due_date=due_day,
                effort_level=EffortLevel.LOW,
                ai_suggested_level=EffortLevel.LOW,
                ai_confidence=0.7,
                ai_reason="test",
                fallback_used=False,
                provider_used="rules",
                model_used="rules-default",
                recurrence_pattern="weekly",
                recurrence_interval_weeks=1,
                recurrence_until=None,
                recurrence_count_limit=None,
                recurrence_blocked_behavior="skip",
            ),
            creator,
        )
        TaskService(db).assign_task(task, assignee_id=creator.id, assignment_date=due_day)
        original_id = task.id

        response = _authed_client(creator).post(
            f"/tasks/{task.id}/delete",
            data={"redirect_to": "/tasks", "delete_scope": "single"},
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert response.headers["location"] == "/tasks"

        updated_task = db.get(Task, original_id)
        assert updated_task is not None
        assert updated_task.due_date == due_day + timedelta(weeks=1)
        assert updated_task.assignment_date == due_day + timedelta(weeks=1)
        assert updated_task.assignee_id == creator.id
        assert db.query(Task).filter(Task.recurrence_parent_id == original_id).count() == 0
    finally:
        db.close()


def test_creator_can_delete_final_recurring_occurrence_and_keep_completed_history():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        creator = _create_user(
            db,
            email=f"delete-recurring-final-{token}@example.com",
            full_name="Delete Recurring Final",
            capacity=10,
        )
        due_day = date.today() + timedelta(days=1)
        task = TaskService(db).create_unassigned_task(
            TaskCreate(
                title=f"Recurring Final Delete Task {token}",
                description="Delete final recurring occurrence",
                due_date=due_day,
                effort_level=EffortLevel.LOW,
                ai_suggested_level=EffortLevel.LOW,
                ai_confidence=0.7,
                ai_reason="test",
                fallback_used=False,
                provider_used="rules",
                model_used="rules-default",
                recurrence_pattern="weekly",
                recurrence_interval_weeks=1,
                recurrence_until=None,
                recurrence_count_limit=2,
                recurrence_blocked_behavior="skip",
            ),
            creator,
        )
        TaskService(db).assign_task(task, assignee_id=creator.id, assignment_date=due_day)
        TaskService(db).update_status(task, TaskStatus.COMPLETED)
        root_id = task.id

        db.refresh(task)
        assert task.due_date == due_day + timedelta(weeks=1)
        assert db.query(Task).filter(Task.recurrence_parent_id == root_id).count() == 1

        response = _authed_client(creator).post(
            f"/tasks/{task.id}/delete",
            data={"redirect_to": "/tasks", "delete_scope": "single"},
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert response.headers["location"] == "/tasks"
        assert db.get(Task, root_id) is None

        preserved_history = (
            db.query(Task)
            .filter(
                Task.title == f"Recurring Final Delete Task {token}",
                Task.status == TaskStatus.COMPLETED,
                Task.due_date == due_day,
            )
            .all()
        )
        assert len(preserved_history) == 1
        assert preserved_history[0].recurrence_parent_id is None
    finally:
        db.close()


def test_user_can_save_schedule_preferences_and_away_periods():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(
            db,
            email=f"schedule-viewer-{token}@example.com",
            full_name="Schedule Viewer",
            capacity=10,
        )

        client = _authed_client(viewer)
        pref_response = client.post(
            "/schedule/preferences",
            data={
                "allow_monday": "true",
                "allow_tuesday": "true",
                "allow_wednesday": "true",
                "allow_thursday": "true",
                "allow_friday": "true",
            },
            follow_redirects=False,
        )
        away_response = client.post(
            "/schedule/away",
            data={
                "start_date": "2026-04-20",
                "end_date": "2026-04-22",
                "note": "Trip",
            },
            follow_redirects=False,
        )

        assert pref_response.status_code == 302
        assert away_response.status_code == 302

        scheduling = SchedulingService(db)
        preferences = scheduling.get_preferences_map(viewer.id)
        assert preferences["saturday"] is False
        assert preferences["sunday"] is False
        periods = scheduling.list_away_periods(viewer.id)
        assert periods[0].note == "Trip"
    finally:
        db.close()


def test_user_can_save_personal_appearance_without_affecting_others():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(
            db,
            email=f"appearance-viewer-{token}@example.com",
            full_name="Appearance Viewer",
            capacity=10,
        )
        other = _create_user(
            db,
            email=f"appearance-other-{token}@example.com",
            full_name="Appearance Other",
            capacity=10,
        )

        client = _authed_client(viewer)
        response = client.post(
            "/appearance",
            data={
                "theme_preference": "dark",
                "accent_color": "#123abc",
                "overdue_color": "#aa2211",
                "recurring_color": "#117766",
                "in_progress_color": "#bb7700",
                "unassigned_color": "#334455",
                "surface_style": "soft",
                "density_preference": "compact",
                "decoration_style": "glow",
            },
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert response.headers["location"] == "/appearance"

        db.refresh(viewer)
        db.refresh(other)
        assert viewer.accent_color == "#123abc"
        assert viewer.surface_style == "soft"
        assert viewer.density_preference == "compact"
        assert viewer.decoration_style == "glow"
        assert other.accent_color == "#4f46e5"
        assert other.surface_style == "clean"

        viewer_dashboard = client.get("/dashboard")
        other_dashboard = _authed_client(other).get("/dashboard")
        assert "#123abc" in viewer_dashboard.text
        assert "#123abc" not in other_dashboard.text
    finally:
        db.close()


def test_invalid_appearance_color_is_rejected():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(
            db,
            email=f"appearance-invalid-{token}@example.com",
            full_name="Appearance Invalid",
            capacity=10,
        )

        client = _authed_client(viewer)
        response = client.post(
            "/appearance",
            data={
                "theme_preference": "light",
                "accent_color": "red",
                "overdue_color": "#dc2626",
                "recurring_color": "#0f766e",
                "in_progress_color": "#d97706",
                "unassigned_color": "#475569",
                "surface_style": "clean",
                "density_preference": "comfortable",
                "decoration_style": "none",
            },
            follow_redirects=False,
        )

        assert response.status_code == 400
        assert "#RRGGBB" in response.text
    finally:
        db.close()


def test_user_can_create_task_with_personal_highlight():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(
            db,
            email=f"task-highlight-create-{token}@example.com",
            full_name="Task Highlight Create",
            capacity=10,
        )

        client = _authed_client(viewer)
        due_day = (date.today() + timedelta(days=3)).isoformat()
        response = client.post(
            "/tasks",
            data={
                "title": f"Highlighted Task {token}",
                "description": "Personal highlight test",
                "due_date": due_day,
                "effort_level": EffortLevel.LOW.value,
                "ai_suggested_level": EffortLevel.LOW.value,
                "ai_confidence": "0.7",
                "ai_reason": "test",
                "fallback_used": "false",
                "provider_used": "rules",
                "model_used": "rules-default",
                "use_personal_highlight": "true",
                "personal_highlight_color": "#2255aa",
            },
            follow_redirects=False,
        )

        assert response.status_code == 302
        task = db.query(Task).filter(Task.title == f"Highlighted Task {token}").first()
        assert task is not None

        detail = client.get(f"/tasks/{task.id}")
        assert detail.status_code == 200
        assert "#2255aa" in detail.text
    finally:
        db.close()


def test_task_highlight_is_personal_only():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(
            db,
            email=f"task-highlight-viewer-{token}@example.com",
            full_name="Task Highlight Viewer",
            capacity=10,
        )
        other = _create_user(
            db,
            email=f"task-highlight-other-{token}@example.com",
            full_name="Task Highlight Other",
            capacity=10,
        )
        task = TaskService(db).create_unassigned_task(
            TaskCreate(
                title=f"Personal Color Task {token}",
                description="Highlight test",
                due_date=date.today() + timedelta(days=4),
                effort_level=EffortLevel.LOW,
                ai_suggested_level=EffortLevel.LOW,
                ai_confidence=0.7,
                ai_reason="test",
                fallback_used=False,
                provider_used="rules",
                model_used="rules-default",
            ),
            viewer,
        )

        viewer_client = _authed_client(viewer)
        save_response = viewer_client.post(
            f"/tasks/{task.id}/display",
            data={
                "use_personal_highlight": "true",
                "personal_highlight_color": "#993366",
            },
            follow_redirects=False,
        )
        assert save_response.status_code == 302

        viewer_tasks = viewer_client.get("/tasks")
        other_tasks = _authed_client(other).get("/tasks")

        assert viewer_tasks.status_code == 200
        assert other_tasks.status_code == 200
        assert "#993366" in viewer_tasks.text
        assert "#993366" not in other_tasks.text
    finally:
        db.close()


def test_past_away_periods_are_removed_automatically():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(
            db,
            email=f"schedule-cleanup-{token}@example.com",
            full_name="Schedule Cleanup",
            capacity=10,
        )
        scheduling = SchedulingService(db)
        scheduling.add_away_period(
            user_id=viewer.id,
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 2),
            note="Past trip",
        )
        scheduling.add_away_period(
            user_id=viewer.id,
            start_date=date(2026, 4, 20),
            end_date=date(2026, 4, 22),
            note="Upcoming trip",
        )

        removed = scheduling.purge_expired_away_periods(user_id=viewer.id, reference_date=date(2026, 4, 10))
        periods = scheduling.list_away_periods(viewer.id)

        assert removed == 1
        assert len(periods) == 1
        assert periods[0].note == "Upcoming trip"
    finally:
        db.close()


def test_admin_can_override_blocked_schedule_date():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        admin = _create_user(
            db,
            email=f"schedule-admin-{token}@example.com",
            full_name="Schedule Admin",
            capacity=10,
            is_admin=True,
            show_in_member_lists=False,
        )
        member = _create_user(
            db,
            email=f"schedule-member-{token}@example.com",
            full_name="Schedule Member",
            capacity=10,
        )
        scheduling = SchedulingService(db)
        scheduling.add_away_period(
            user_id=member.id,
            start_date=date(2026, 4, 18),
            end_date=date(2026, 4, 18),
            note="Away day",
        )
        task = TaskService(db).create_unassigned_task(
            TaskCreate(
                title=f"Override Task {token}",
                description="Admin override test",
                due_date=date(2026, 4, 18),
                effort_level=EffortLevel.LOW,
                ai_suggested_level=EffortLevel.LOW,
                ai_confidence=0.7,
                ai_reason="test",
                fallback_used=False,
                provider_used="rules",
                model_used="rules-default",
            ),
            admin,
        )

        client = _authed_client(admin)
        blocked = client.post(
            f"/tasks/{task.id}/assign",
            data={"assignee_id": member.id, "assignment_date": "2026-04-18"},
            follow_redirects=False,
        )
        allowed = client.post(
            f"/tasks/{task.id}/assign",
            data={
                "assignee_id": member.id,
                "assignment_date": "2026-04-18",
                "allow_policy_override": "true",
            },
            follow_redirects=False,
        )

        assert blocked.status_code == 400
        assert "blocked by the user's schedule" in blocked.text
        assert allowed.status_code == 302
        assert allowed.headers["location"] == "/tasks"

        db.refresh(task)
        assert task.assignee_id == member.id
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


def test_assignee_can_reopen_completed_recurring_occurrence_as_one_off_task():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        creator = _create_user(
            db,
            email=f"recurring-history-owner-{token}@example.com",
            full_name="Recurring History Owner",
            capacity=10,
        )
        assignee = _create_user(
            db,
            email=f"recurring-history-assignee-{token}@example.com",
            full_name="Recurring History Assignee",
            capacity=10,
        )
        first_due_date = date.today()
        root = TaskService(db).create_unassigned_task(
            TaskCreate(
                title=f"Recurring History Task {token}",
                description="Recurring history status coverage",
                due_date=first_due_date,
                effort_level=EffortLevel.LOW,
                ai_suggested_level=EffortLevel.LOW,
                ai_confidence=0.7,
                ai_reason="test",
                fallback_used=False,
                provider_used="rules",
                model_used="rules-default",
                recurrence_pattern="weekly",
                recurrence_interval_weeks=1,
                recurrence_count_limit=4,
                recurrence_blocked_behavior="skip",
            ),
            creator,
        )
        TaskService(db).assign_task(root, assignee_id=assignee.id, assignment_date=first_due_date)
        TaskService(db).update_status(root, TaskStatus.COMPLETED)
        db.refresh(root)
        next_due_date = root.due_date
        history = RecurringTaskService(db).get_history(root.id)
        assert len(history) == 1
        occurrence = history[0]

        client = _authed_client(assignee)
        tasks_response = client.get("/tasks?scope=mine&view=completed")
        assert tasks_response.status_code == 200
        assert f'action="/tasks/{occurrence.id}/status"' in tasks_response.text
        assert f'hx-post="/tasks/{occurrence.id}/quick-schedule"' in tasks_response.text

        status_response = client.post(
            f"/tasks/{occurrence.id}/status",
            data={"status_value": TaskStatus.IN_PROGRESS.value, "redirect_to": "/tasks?scope=mine&view=completed"},
            follow_redirects=False,
        )

        assert status_response.status_code == 302
        db.refresh(root)
        db.refresh(occurrence)
        assert occurrence.status == TaskStatus.IN_PROGRESS
        assert occurrence.recurrence_parent_id is None
        assert occurrence.recurrence_pattern is None
        assert root.status == TaskStatus.PENDING
        assert root.due_date == next_due_date
        assert root.recurrence_pattern == "weekly"

        assert RecurringTaskService(db).sync() == 0
        assert db.get(Task, occurrence.id) is not None
    finally:
        db.close()


def test_completed_recurring_occurrence_edit_is_one_off_and_hides_recurring_controls():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(
            db,
            email=f"recurring-history-edit-{token}@example.com",
            full_name="Recurring History Edit",
            capacity=10,
        )
        first_due_date = date.today()
        root = TaskService(db).create_unassigned_task(
            TaskCreate(
                title=f"Recurring History Edit Task {token}",
                description="Recurring history edit coverage",
                due_date=first_due_date,
                effort_level=EffortLevel.LOW,
                ai_suggested_level=EffortLevel.LOW,
                ai_confidence=0.7,
                ai_reason="test",
                fallback_used=False,
                provider_used="rules",
                model_used="rules-default",
                recurrence_pattern="weekly",
                recurrence_interval_weeks=1,
                recurrence_count_limit=4,
                recurrence_blocked_behavior="skip",
            ),
            viewer,
        )
        TaskService(db).assign_task(root, assignee_id=viewer.id, assignment_date=first_due_date)
        TaskService(db).update_status(root, TaskStatus.COMPLETED)
        db.refresh(root)
        occurrence = RecurringTaskService(db).get_history(root.id)[0]

        client = _authed_client(viewer)
        edit_response = client.get(f"/tasks/{occurrence.id}/edit")
        assert edit_response.status_code == 200
        assert "Recurring task options" not in edit_response.text

        edited_due_date = first_due_date + timedelta(days=1)
        save_response = client.post(
            f"/tasks/{occurrence.id}/edit",
            data={
                "title": f"Edited History Task {token}",
                "description": "Edited recurring history copy",
                "due_date": edited_due_date.isoformat(),
                "effort_level": EffortLevel.MEDIUM.value,
                "status_value": TaskStatus.COMPLETED.value,
                "assignee_id_edit": str(viewer.id),
                "assignment_date_edit": edited_due_date.isoformat(),
                "redirect_to": f"/tasks/{occurrence.id}",
            },
            follow_redirects=False,
        )

        assert save_response.status_code == 302
        db.refresh(root)
        db.refresh(occurrence)
        assert occurrence.title == f"Edited History Task {token}"
        assert occurrence.due_date == edited_due_date
        assert occurrence.assignment_date == edited_due_date
        assert occurrence.recurrence_parent_id is None
        assert occurrence.recurrence_pattern is None
        assert root.status == TaskStatus.PENDING
        assert root.recurrence_pattern == "weekly"
    finally:
        db.close()


def test_completed_recurring_occurrence_metadata_edit_keeps_history_link():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(
            db,
            email=f"recurring-history-meta-{token}@example.com",
            full_name="Recurring History Meta",
            capacity=10,
        )
        replacement_assignee = _create_user(
            db,
            email=f"recurring-history-meta-assignee-{token}@example.com",
            full_name="Recurring History Meta Assignee",
            capacity=10,
        )
        first_due_date = date.today()
        root = TaskService(db).create_unassigned_task(
            TaskCreate(
                title=f"Recurring History Meta Task {token}",
                description="Recurring history metadata coverage",
                due_date=first_due_date,
                effort_level=EffortLevel.LOW,
                ai_suggested_level=EffortLevel.LOW,
                ai_confidence=0.7,
                ai_reason="test",
                fallback_used=False,
                provider_used="rules",
                model_used="rules-default",
                recurrence_pattern="weekly",
                recurrence_interval_weeks=1,
                recurrence_count_limit=4,
                recurrence_blocked_behavior="skip",
            ),
            viewer,
        )
        TaskService(db).assign_task(root, assignee_id=viewer.id, assignment_date=first_due_date)
        TaskService(db).update_status(root, TaskStatus.COMPLETED)
        db.refresh(root)
        occurrence = RecurringTaskService(db).get_history(root.id)[0]

        response = _authed_client(viewer).post(
            f"/tasks/{occurrence.id}/edit",
            data={
                "title": f"Corrected History Task {token}",
                "description": "Corrected completed occurrence notes",
                "due_date": first_due_date.isoformat(),
                "effort_level": EffortLevel.MEDIUM.value,
                "status_value": TaskStatus.COMPLETED.value,
                "assignee_id_edit": str(replacement_assignee.id),
                "assignment_date_edit": first_due_date.isoformat(),
                "redirect_to": f"/tasks/{occurrence.id}",
            },
            follow_redirects=False,
        )

        assert response.status_code == 302
        db.refresh(root)
        db.refresh(occurrence)
        assert occurrence.title == f"Corrected History Task {token}"
        assert occurrence.description == "Corrected completed occurrence notes"
        assert occurrence.effort_level == EffortLevel.MEDIUM
        assert occurrence.assignee_id == replacement_assignee.id
        assert occurrence.assignment_date == first_due_date
        assert occurrence.status == TaskStatus.COMPLETED
        assert occurrence.recurrence_parent_id == root.id
        assert root.status == TaskStatus.PENDING
        assert root.recurrence_pattern == "weekly"
    finally:
        db.close()


def test_task_edit_invalid_submission_returns_form_error():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(
            db,
            email=f"edit-error-{token}@example.com",
            full_name="Edit Error User",
            capacity=10,
        )
        day = date.today() + timedelta(days=2)
        task = _create_task(db, creator=viewer, assignee=viewer, title=f"Editable Task {token}", day=day)

        client = _authed_client(viewer)
        response = client.post(
            f"/tasks/{task.id}/edit",
            data={
                "title": task.title,
                "description": task.description,
                "due_date": "not-a-date",
                "effort_level": task.effort_level.value,
                "status_value": task.status.value,
            },
        )

        assert response.status_code == 400
        assert "Please provide valid task values before saving." in response.text
    finally:
        db.close()


def test_task_create_page_allows_past_due_dates():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(
            db,
            email=f"create-past-due-{token}@example.com",
            full_name="Create Past Due",
            capacity=8,
        )

        client = _authed_client(viewer)
        response = client.get("/tasks/create")

        assert response.status_code == 200
        due_input = re.search(r'<input id="task_due_date"[^>]+>', response.text)
        assert due_input is not None
        assert 'min="' not in due_input.group(0)
    finally:
        db.close()


def test_task_create_allows_empty_description():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(
            db,
            email=f"create-empty-desc-{token}@example.com",
            full_name="Create Empty Description",
            capacity=8,
        )

        client = _authed_client(viewer)
        due_day = (date.today() + timedelta(days=2)).isoformat()
        response = client.post(
            "/tasks",
            data={
                "title": f"Empty Description {token}",
                "description": "",
                "due_date": due_day,
                "effort_level": EffortLevel.LOW.value,
                "ai_suggested_level": EffortLevel.LOW.value,
                "ai_confidence": "0.6",
                "ai_reason": "title only",
                "fallback_used": "true",
                "provider_used": "rules",
                "model_used": "rules-default",
            },
            follow_redirects=False,
        )

        assert response.status_code == 302
        task = db.query(Task).filter(Task.title == f"Empty Description {token}").first()
        assert task is not None
        assert task.description == ""

        detail_response = client.get(f"/tasks/{task.id}")
        assert detail_response.status_code == 200
        assert "No description." in detail_response.text
    finally:
        db.close()


def test_quick_schedule_uses_today_for_past_assignment_dates():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(
            db,
            email=f"quick-schedule-past-{token}@example.com",
            full_name="Quick Schedule Past",
            capacity=8,
        )
        past_day = date.today() - timedelta(days=2)
        task = _create_task(
            db,
            creator=viewer,
            assignee=viewer,
            title=f"Past Assignment {token}",
            due_date=past_day,
            assignment_date=past_day,
        )

        client = _authed_client(viewer)
        response = client.get("/tasks?scope=mine&view=overdue")

        assert response.status_code == 200
        assignment_input = re.search(
            rf'<input[^>]+id="quick-assignment-date-{task.id}"[^>]+value="([^"]+)"',
            response.text,
        )
        assert assignment_input is not None
        assert assignment_input.group(1) == date.today().isoformat()
    finally:
        db.close()


def test_task_edit_page_prefills_assign_now_section():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(
            db,
            email=f"edit-assign-prefill-{token}@example.com",
            full_name="Edit Assign Prefill",
            capacity=10,
        )
        teammate = _create_user(
            db,
            email=f"edit-assign-prefill-mate-{token}@example.com",
            full_name="Edit Assign Teammate",
            capacity=10,
        )
        assignment_day = date.today() + timedelta(days=3)
        task = _create_task(
            db,
            creator=viewer,
            assignee=teammate,
            title=f"Editable Assigned Task {token}",
            day=assignment_day,
            effort_level=EffortLevel.LOW,
        )

        client = _authed_client(viewer)
        response = client.get(f"/tasks/{task.id}/edit")

        assert response.status_code == 200
        assert "Assign now" in response.text
        assert "Keep assignment changes in the same save flow" not in response.text
        assign_heading_index = response.text.index("Assign now")
        assign_details_start = response.text.rfind("<details", 0, assign_heading_index)
        assign_details_tag = response.text[assign_details_start: response.text.index(">", assign_details_start) + 1]
        assert "open" in assign_details_tag
        assert re.search(
            rf'name="assignment_date_edit"\s+value="{assignment_day.isoformat()}"',
            response.text,
        )
        assert re.search(rf'<option value="{teammate.id}"[^>]*selected>', response.text)
    finally:
        db.close()


def test_task_edit_revalidates_existing_assignment_when_effort_changes():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(
            db,
            email=f"edit-effort-viewer-{token}@example.com",
            full_name="Edit Effort Viewer",
            capacity=10,
        )
        teammate = _create_user(
            db,
            email=f"edit-effort-mate-{token}@example.com",
            full_name="Edit Effort Mate",
            capacity=8,
        )
        assignment_day = date.today() + timedelta(days=2)
        task = _create_task(
            db,
            creator=viewer,
            assignee=teammate,
            title=f"Edit Revalidation Task {token}",
            day=assignment_day,
            effort_level=EffortLevel.LOW,
        )
        _create_task(
            db,
            creator=viewer,
            assignee=teammate,
            title=f"Existing Load {token}",
            day=assignment_day,
            effort_level=EffortLevel.LOW,
        )

        client = _authed_client(viewer)
        response = client.post(
            f"/tasks/{task.id}/edit",
            data={
                "title": task.title,
                "description": task.description,
                "due_date": task.due_date.isoformat(),
                "effort_level": EffortLevel.HIGH.value,
                "status_value": task.status.value,
                "assignee_id_edit": str(teammate.id),
                "assignment_date_edit": assignment_day.isoformat(),
            },
        )

        assert response.status_code == 400
        assert "Assignment exceeds daily capacity." in response.text

        db.refresh(task)
        assert task.effort_level == EffortLevel.LOW
        assert task.assignee_id == teammate.id
        assert task.assignment_date == assignment_day
    finally:
        db.close()


def test_task_edit_can_clear_assignment_without_extra_steps():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(
            db,
            email=f"edit-unassign-viewer-{token}@example.com",
            full_name="Edit Unassign Viewer",
            capacity=10,
        )
        teammate = _create_user(
            db,
            email=f"edit-unassign-mate-{token}@example.com",
            full_name="Edit Unassign Mate",
            capacity=10,
        )
        assignment_day = date.today() + timedelta(days=4)
        task = _create_task(
            db,
            creator=viewer,
            assignee=teammate,
            title=f"Edit Unassign Task {token}",
            day=assignment_day,
            effort_level=EffortLevel.MEDIUM,
        )

        client = _authed_client(viewer)
        response = client.post(
            f"/tasks/{task.id}/edit",
            data={
                "title": task.title,
                "description": task.description,
                "due_date": task.due_date.isoformat(),
                "effort_level": task.effort_level.value,
                "status_value": task.status.value,
                "assignee_id_edit": "",
                "assignment_date_edit": "",
            },
            follow_redirects=False,
        )

        assert response.status_code == 302

        db.refresh(task)
        assert task.assignee_id is None
        assert task.assignment_date is None
    finally:
        db.close()


def test_task_edit_page_shows_current_recurring_summary_and_next_due_date():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(
            db,
            email=f"edit-recurring-{token}@example.com",
            full_name="Edit Recurring User",
            capacity=10,
        )
        due_day = date.today() + timedelta(days=3)
        task = _create_task(db, creator=viewer, assignee=viewer, title=f"Recurring Edit Task {token}", day=due_day)
        task.recurrence_pattern = "weekly"
        task.recurrence_interval_weeks = 2
        task.recurrence_count_limit = 10
        task.recurrence_anchor_date = due_day
        task.recurrence_occurrence_index = 0
        task.recurrence_blocked_behavior = "skip"
        db.add(task)
        db.commit()
        db.refresh(task)

        client = _authed_client(viewer)
        response = client.get(f"/tasks/{task.id}/edit")

        next_due = due_day + timedelta(weeks=2)
        recurring_heading_index = response.text.index("Recurring task options")
        recurring_details_start = response.text.rfind("<details", 0, recurring_heading_index)
        recurring_details_tag = response.text[recurring_details_start: response.text.index(">", recurring_details_start) + 1]

        assert response.status_code == 200
        assert "open" not in recurring_details_tag
        assert "Due date for this task" in response.text
        assert "Use the recurring section below to change future repeats." in response.text
        assert "Future repeat due date" in response.text
        assert 'value="10"' in response.text
        assert f'value="{next_due.isoformat()}"' in response.text
        assert "This current task plus 9 more future repeats are left in the series." in response.text
        assert "Occurrences left including this task:" not in response.text
        assert "These changes start after this task and leave the current occurrence as-is." in response.text
    finally:
        db.close()


def test_task_edit_page_shows_occurrences_left_from_current_series_position():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(
            db,
            email=f"edit-recurring-left-{token}@example.com",
            full_name="Edit Recurring Left User",
            capacity=10,
        )
        anchor_day = date.today() - timedelta(days=28)
        current_day = anchor_day + timedelta(weeks=4)
        task = _create_task(db, creator=viewer, assignee=viewer, title=f"Recurring Left Task {token}", day=current_day)
        task.recurrence_pattern = "weekly"
        task.recurrence_interval_weeks = 1
        task.recurrence_count_limit = 10
        task.recurrence_anchor_date = anchor_day
        task.recurrence_occurrence_index = 4
        task.recurrence_blocked_behavior = "skip"
        db.add(task)
        db.commit()

        client = _authed_client(viewer)
        response = client.get(f"/tasks/{task.id}/edit")

        assert response.status_code == 200
        assert 'value="6"' in response.text
        assert "This current task plus 5 more future repeats are left in the series." in response.text
        assert "Occurrences left including this task:" not in response.text
        assert 'name="recurrence_series_due_date"' in response.text
    finally:
        db.close()


def test_task_edit_page_shows_final_occurrence_message_when_one_is_left():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(
            db,
            email=f"edit-recurring-final-left-{token}@example.com",
            full_name="Edit Recurring Final Left User",
            capacity=10,
        )
        current_day = date.today() + timedelta(days=3)
        task = _create_task(db, creator=viewer, assignee=viewer, title=f"Recurring Final Left Task {token}", day=current_day)
        task.recurrence_pattern = "weekly"
        task.recurrence_interval_weeks = 1
        task.recurrence_count_limit = 1
        task.recurrence_anchor_date = current_day
        task.recurrence_occurrence_index = 0
        task.recurrence_blocked_behavior = "skip"
        db.add(task)
        db.commit()

        client = _authed_client(viewer)
        response = client.get(f"/tasks/{task.id}/edit")

        assert response.status_code == 200
        assert 'value="1"' in response.text
        assert "This current task is the final occurrence in the series." in response.text
    finally:
        db.close()


def test_admin_can_remove_user_and_cleanup_assigned_work():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        admin = _create_user(
            db,
            email=f"remove-admin-{token}@example.com",
            full_name="Remove Admin",
            capacity=10,
            is_admin=True,
            show_in_member_lists=False,
        )
        teammate = _create_user(
            db,
            email=f"remove-target-{token}@example.com",
            full_name="Remove Target",
            capacity=7,
        )
        assignment_day = date.today() + timedelta(days=2)
        task = _create_task(
            db,
            creator=teammate,
            assignee=teammate,
            title=f"Removal Task {token}",
            day=assignment_day,
            effort_level=EffortLevel.MEDIUM,
        )

        client = _authed_client(admin)
        response = client.post(
            f"/admin/settings/users/{teammate.id}/delete",
            follow_redirects=False,
        )

        assert response.status_code == 302

        db.expire_all()
        remaining_user = AuthService(db).get_by_email(teammate.email)
        assert remaining_user is None

        updated_task = db.get(Task, task.id)
        assert updated_task is not None
        assert updated_task.assignee_id is None
        assert updated_task.assignment_date is None
        assert updated_task.created_by_id == admin.id
        assert db.get(UserDailyCapacity, teammate.id) is None
    finally:
        db.close()


def test_admin_cannot_remove_own_account():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        only_admin = _create_user(
            db,
            email=f"last-admin-{token}@example.com",
            full_name="Last Admin",
            capacity=10,
            is_admin=True,
            show_in_member_lists=False,
        )
        member = _create_user(
            db,
            email=f"last-admin-member-{token}@example.com",
            full_name="Last Admin Member",
            capacity=10,
        )

        client = _authed_client(member)
        forbidden_response = client.get("/admin/settings")
        assert forbidden_response.status_code == 403

        admin_client = _authed_client(only_admin)
        response = admin_client.post(f"/admin/settings/users/{only_admin.id}/delete")

        assert response.status_code == 400
        assert "You cannot remove your own account." in response.text
    finally:
        db.close()


def test_admin_registration_toggle_updates_login_message():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        admin = _create_user(
            db,
            email=f"toggle-admin-{token}@example.com",
            full_name="Toggle Admin",
            capacity=10,
            is_admin=True,
            show_in_member_lists=False,
        )

        client = _authed_client(admin)
        response = client.post(
            "/admin/settings/login-access",
            data={
                "public_registration_enabled": "true",
                "auto_approve_registrations": "true",
                "registration_default_capacity_points": "6",
                "login_theme_preference": "light",
            },
            follow_redirects=False,
        )
        assert response.status_code == 302
    finally:
        db.close()

    public_client = TestClient(app)
    login_page = public_client.get("/login")
    assert login_page.status_code == 200
    assert "auto-approved and can sign in straight away" in login_page.text

    db = SessionLocal()
    try:
        assert AdminSettingsService(db).get_app_settings().registration_default_capacity_points == 6
        AdminSettingsService(db).update_login_access_settings(
            public_registration_enabled=True,
            auto_approve_registrations=False,
            login_theme_preference="light",
            registration_default_capacity_points=None,
        )
    finally:
        db.close()


def test_login_page_hides_registration_when_disabled():
    db = SessionLocal()
    try:
        AdminSettingsService(db).update_login_access_settings(
            public_registration_enabled=False,
            auto_approve_registrations=False,
            login_theme_preference="light",
            registration_default_capacity_points=None,
        )
    finally:
        db.close()

    public_client = TestClient(app)
    response = public_client.get("/login")

    assert response.status_code == 200
    assert "Create an account" not in response.text
    assert 'action="/register"' not in response.text
    assert "Welcome back" in response.text

    db = SessionLocal()
    try:
        AdminSettingsService(db).update_login_access_settings(
            public_registration_enabled=True,
            auto_approve_registrations=False,
            login_theme_preference="light",
            registration_default_capacity_points=None,
        )
    finally:
        db.close()


def test_login_page_uses_configured_theme_preference():
    db = SessionLocal()
    try:
        AdminSettingsService(db).update_login_access_settings(
            public_registration_enabled=True,
            auto_approve_registrations=False,
            login_theme_preference="dark",
            registration_default_capacity_points=None,
        )
    finally:
        db.close()

    public_client = TestClient(app)
    response = public_client.get("/login")

    assert response.status_code == 200
    assert 'const pref = "dark";' in response.text

    db = SessionLocal()
    try:
        AdminSettingsService(db).update_login_access_settings(
            public_registration_enabled=True,
            auto_approve_registrations=False,
            login_theme_preference="light",
            registration_default_capacity_points=None,
        )
    finally:
        db.close()


def test_login_access_settings_reject_invalid_default_capacity():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        admin = _create_user(
            db,
            email=f"login-capacity-admin-{token}@example.com",
            full_name="Login Capacity Admin",
            capacity=10,
            is_admin=True,
            show_in_member_lists=False,
        )

        client = _authed_client(admin)
        response = client.post(
            "/admin/settings/login-access",
            data={
                "public_registration_enabled": "true",
                "auto_approve_registrations": "true",
                "registration_default_capacity_points": "abc",
                "login_theme_preference": "light",
            },
        )

        assert response.status_code == 400
        assert "Default capacity for new registrations must be a whole number." in response.text
    finally:
        db.close()


def test_task_collaboration_settings_update_status_toggle_only():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        admin = _create_user(
            db,
            email=f"task-collab-admin-{token}@example.com",
            full_name="Task Collaboration Admin",
            capacity=10,
            is_admin=True,
            show_in_member_lists=False,
        )
        service = AdminSettingsService(db)
        service.update_login_access_settings(
            public_registration_enabled=False,
            auto_approve_registrations=True,
            login_theme_preference="dark",
            registration_default_capacity_points=7,
        )
        service.update_task_collaboration_settings(allow_member_status_updates=False)

        client = _authed_client(admin)
        response = client.post(
            "/admin/settings/task-collaboration",
            data={"allow_member_status_updates": "true"},
            follow_redirects=False,
        )

        assert response.status_code == 302
        db.expire_all()
        settings = service.get_app_settings()
        assert settings.allow_member_status_updates is True
        assert settings.public_registration_enabled is False
        assert settings.auto_approve_registrations is True
        assert settings.login_theme_preference == "dark"
        assert settings.registration_default_capacity_points == 7

        response = client.post(
            "/admin/settings/task-collaboration",
            data={"allow_member_status_updates": "false"},
            follow_redirects=False,
        )
        assert response.status_code == 302
        db.expire_all()
        assert service.get_app_settings().allow_member_status_updates is False
    finally:
        AdminSettingsService(db).update_login_access_settings(
            public_registration_enabled=True,
            auto_approve_registrations=False,
            login_theme_preference="light",
            registration_default_capacity_points=None,
        )
        AdminSettingsService(db).update_task_collaboration_settings(allow_member_status_updates=False)
        db.close()


def test_admin_service_auto_refreshes_ai_models_only_when_registry_is_empty(monkeypatch):
    db = SessionLocal()
    try:
        service = AdminSettingsService(db)
        discovered_models = [SimpleNamespace(provider_name="ollama", model_identifier="llama3.2")]
        refresh_calls: list[str] = []

        monkeypatch.setattr(service.ai, "list_registry_models", lambda: [])

        def _fake_refresh():
            refresh_calls.append("called")
            return discovered_models

        monkeypatch.setattr(service.ai, "refresh_model_registry", _fake_refresh)

        models = service.get_ai_registry_models(auto_refresh_if_empty=True)

        assert models == discovered_models
        assert refresh_calls == ["called"]
    finally:
        db.close()


def test_admin_service_skips_ai_model_refresh_when_registry_already_has_models(monkeypatch):
    db = SessionLocal()
    try:
        service = AdminSettingsService(db)
        existing_models = [SimpleNamespace(provider_name="ollama", model_identifier="llama3.2")]

        monkeypatch.setattr(service.ai, "list_registry_models", lambda: existing_models)

        def _unexpected_refresh():
            raise AssertionError("refresh_model_registry should not run when models already exist")

        monkeypatch.setattr(service.ai, "refresh_model_registry", _unexpected_refresh)

        models = service.get_ai_registry_models(auto_refresh_if_empty=True)

        assert models == existing_models
    finally:
        db.close()


def test_admin_can_disable_ai_even_when_selected_ollama_model_is_unavailable(monkeypatch):
    db = SessionLocal()
    try:
        service = AdminSettingsService(db)
        unavailable_model = SimpleNamespace(
            provider_name="ollama",
            model_identifier="qwen2.5:1.5b",
            available=False,
        )
        captured = {}

        monkeypatch.setattr(service.ai, "list_registry_models", lambda: [unavailable_model])

        def _fake_update_settings(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(**kwargs)

        monkeypatch.setattr(service.ai, "update_settings", _fake_update_settings)

        service.update_ai_settings(
            ai_enabled=False,
            active_provider="ollama",
            active_model="qwen2.5:1.5b",
            fallback_provider="ollama",
            timeout_seconds=8,
        )

        assert captured["ai_enabled"] is False
        assert captured["fallback_provider"] == "rules"
    finally:
        db.close()


def test_admin_ai_registry_does_not_auto_refresh_when_ai_is_disabled(monkeypatch):
    db = SessionLocal()
    try:
        service = AdminSettingsService(db)
        monkeypatch.setattr(service, "get_ai_settings", lambda: SimpleNamespace(ai_enabled=False))
        monkeypatch.setattr(service.ai, "list_registry_models", lambda: [])

        def _unexpected_refresh():
            raise AssertionError("refresh_model_registry should not run when AI is disabled")

        monkeypatch.setattr(service.ai, "refresh_model_registry", _unexpected_refresh)

        assert service.get_ai_registry_models(auto_refresh_if_empty=True) == []
    finally:
        db.close()
