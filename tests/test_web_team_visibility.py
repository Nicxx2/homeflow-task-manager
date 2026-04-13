from datetime import date, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

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
from backend.app.services.auth_service import AuthService
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
