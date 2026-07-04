from datetime import date, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app.core.security import create_access_token
from backend.app.db.base import Base
from backend.app.db.session import SessionLocal, engine
from backend.app.main import app
from backend.app.models.enums import EffortLevel, TaskStatus
from backend.app.models.task import Task
from backend.app.models.task_effort_config import TaskEffortConfig
from backend.app.models.user_daily_capacity import UserDailyCapacity
from backend.app.models.user_daily_capacity_override import UserDailyCapacityOverride
from backend.app.schemas.auth import RegisterRequest
from backend.app.schemas.task import TaskCreate
from backend.app.services.auth_service import AuthService
from backend.app.services.planner_service import PlannerService
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


def _create_user(db, *, capacity: int = 10, is_admin: bool = False, show_in_member_lists: bool = True):
    token = uuid4().hex[:8]
    user = AuthService(db).register(
        RegisterRequest(
            email=f"planner-{token}@example.com",
            full_name=f"Planner {token}",
            password="securepass123",
        ),
        require_approval=False,
    )
    user.is_admin = is_admin
    user.show_in_member_lists = show_in_member_lists
    db.add(user)
    db.add(UserDailyCapacity(user_id=user.id, daily_capacity_points=capacity))
    db.commit()
    db.refresh(user)
    return user


def _create_recurring(db, *, creator, due_date: date, interval_weeks: int, late_behavior: str, count: int | None = None):
    return TaskService(db).create_unassigned_task(
        TaskCreate(
            title=f"Recurring {uuid4().hex[:6]}",
            description="Recurring edge-case test",
            due_date=due_date,
            effort_level=EffortLevel.LOW,
            recurrence_pattern="weekly",
            recurrence_interval_weeks=interval_weeks,
            recurrence_count_limit=count,
            recurrence_blocked_behavior="skip",
            recurrence_late_behavior=late_behavior,
        ),
        creator,
    )


def _create_assigned_task(db, *, creator, assignee, title: str, day: date):
    task = TaskService(db).create_unassigned_task(
        TaskCreate(
            title=title,
            description="Planner move test",
            due_date=day + timedelta(days=10),
            effort_level=EffortLevel.LOW,
        ),
        creator,
    )
    return TaskService(db).assign_task(task, assignee_id=assignee.id, assignment_date=day)


def _authed_client(user):
    client = TestClient(app)
    client.cookies.set("access_token", create_access_token(subject=str(user.id)))
    return client


def test_overdue_keep_schedule_skips_directly_to_first_future_slot():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        user = _create_user(db)
        today = date.today()
        anchor = today - timedelta(days=65)
        task = _create_recurring(
            db,
            creator=user,
            due_date=anchor,
            interval_weeks=2,
            late_behavior="keep_schedule",
        )

        TaskService(db).update_status(task, TaskStatus.COMPLETED)
        db.refresh(task)

        expected_index = ((today - anchor).days // 14) + 1
        assert task.status == TaskStatus.PENDING
        assert task.due_date == anchor + timedelta(days=14 * expected_index)
        assert task.due_date > today
        assert task.recurrence_occurrence_index == expected_index
        history = RecurringTaskService(db).get_history(task.id)
        assert len(history) == 1
        assert history[0].due_date == anchor
    finally:
        db.close()


def test_legacy_recurring_task_without_late_behavior_keeps_original_schedule():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        user = _create_user(db)
        today = date.today()
        anchor = today - timedelta(days=65)
        task = _create_recurring(
            db,
            creator=user,
            due_date=anchor,
            interval_weeks=2,
            late_behavior="keep_schedule",
        )
        task.recurrence_late_behavior = None
        db.add(task)
        db.commit()
        db.refresh(task)

        TaskService(db).update_status(task, TaskStatus.COMPLETED)
        db.refresh(task)

        expected_index = ((today - anchor).days // 14) + 1
        assert task.status == TaskStatus.PENDING
        assert task.due_date == anchor + timedelta(days=14 * expected_index)
        assert task.due_date > today
        assert task.recurrence_occurrence_index == expected_index
    finally:
        db.close()

def test_repeat_from_completion_uses_a_full_interval_from_today():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        user = _create_user(db)
        today = date.today()
        task = _create_recurring(
            db,
            creator=user,
            due_date=today - timedelta(days=65),
            interval_weeks=2,
            late_behavior="from_completion",
        )

        TaskService(db).update_status(task, TaskStatus.COMPLETED)
        db.refresh(task)

        assert task.due_date == today + timedelta(weeks=2)
        assert task.recurrence_anchor_date == today
        assert task.recurrence_occurrence_index == 1
    finally:
        db.close()


def test_overdue_keep_schedule_count_limit_can_finish_series():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        user = _create_user(db)
        task = _create_recurring(
            db,
            creator=user,
            due_date=date.today() - timedelta(weeks=8),
            interval_weeks=1,
            late_behavior="keep_schedule",
            count=2,
        )

        TaskService(db).update_status(task, TaskStatus.COMPLETED)
        db.refresh(task)

        assert task.status == TaskStatus.COMPLETED
        assert task.recurrence_occurrence_index == 0
        assert RecurringTaskService(db).get_history(task.id) == []
    finally:
        db.close()


def test_from_completion_count_limit_preserves_remaining_future_occurrence():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        user = _create_user(db)
        today = date.today()
        task = _create_recurring(
            db,
            creator=user,
            due_date=today - timedelta(weeks=8),
            interval_weeks=2,
            late_behavior="from_completion",
            count=2,
        )

        TaskService(db).update_status(task, TaskStatus.COMPLETED)
        db.refresh(task)

        assert task.status == TaskStatus.PENDING
        assert task.due_date == today + timedelta(weeks=2)
        assert task.recurrence_occurrence_index == 1
        assert RecurringTaskService(db).remaining_count_limit_occurrences(task) == 1

        TaskService(db).update_status(task, TaskStatus.COMPLETED)
        db.refresh(task)

        assert task.status == TaskStatus.COMPLETED
        assert task.recurrence_occurrence_index == 1
    finally:
        db.close()

def test_overdue_fixed_count_series_finishes_without_fake_history():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        user = _create_user(db)
        task = _create_recurring(
            db,
            creator=user,
            due_date=date.today() - timedelta(weeks=10),
            interval_weeks=1,
            late_behavior="keep_schedule",
            count=3,
        )

        TaskService(db).update_status(task, TaskStatus.COMPLETED)
        db.refresh(task)

        assert task.status == TaskStatus.COMPLETED
        assert RecurringTaskService(db).get_history(task.id) == []
    finally:
        db.close()


def test_permanently_blocked_unlimited_series_falls_back_unassigned():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        user = _create_user(db)
        today = date.today()
        task = _create_recurring(
            db,
            creator=user,
            due_date=today,
            interval_weeks=1,
            late_behavior="keep_schedule",
        )
        TaskService(db).assign_task(task, assignee_id=user.id, assignment_date=today)
        weekday_key = SchedulingService.WEEKDAY_FIELDS[today.weekday()][0]
        allowed = {key: True for key, _column, _label in SchedulingService.WEEKDAY_FIELDS}
        allowed[weekday_key] = False
        SchedulingService(db).update_preferences(user_id=user.id, allowed_days=allowed)

        preview = RecurringTaskService(db).preview_next_occurrence(task)

        assert preview is not None
        assert preview["due_date"] == today + timedelta(weeks=1)
        assert preview["assignee_id"] is None
        assert preview["assignment_date"] is None
    finally:
        db.close()


def test_planner_batch_capacity_is_combined_not_checked_individually():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        user = _create_user(db, capacity=3)
        today = date.today()
        first = _create_assigned_task(db, creator=user, assignee=user, title="First", day=today)
        second = _create_assigned_task(db, creator=user, assignee=user, title="Second", day=today + timedelta(days=1))

        result = PlannerService(db).preview_move(
            task_ids=[first.id, second.id],
            assignment_date=today + timedelta(days=2),
            viewer=user,
        )

        assert result["ok"] is False
        assert result["members"][0]["projected_points"] == 4
        assert result["members"][0]["capacity"] == 3
        assert any("needs 4 points" in error for error in result["errors"])
    finally:
        db.close()


def test_planner_batch_commit_is_atomic_and_preserves_due_dates():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        user = _create_user(db, capacity=6)
        today = date.today()
        destination = today + timedelta(days=3)
        first = _create_assigned_task(db, creator=user, assignee=user, title="Move first", day=today)
        second = _create_assigned_task(db, creator=user, assignee=user, title="Move second", day=today + timedelta(days=1))
        original_due_dates = {first.id: first.due_date, second.id: second.due_date}
        service = PlannerService(db)

        preview = service.preview_move(
            task_ids=[first.id, second.id],
            assignment_date=destination,
            viewer=user,
        )
        assert preview["ok"] is True
        committed = service.commit_move(
            task_ids=[first.id, second.id],
            assignment_date=destination,
            fingerprint=preview["fingerprint"],
            viewer=user,
        )

        assert committed["ok"] is True
        assert committed["moved_count"] == 2
        for task_id in (first.id, second.id):
            moved = db.get(Task, task_id)
            assert moved.assignment_date == destination
            assert moved.due_date == original_due_dates[task_id]
    finally:
        db.close()


def test_planner_mixed_selection_moves_only_changed_tasks_at_exact_capacity():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        user = _create_user(db, capacity=4)
        today = date.today()
        destination = today + timedelta(days=3)
        existing = _create_assigned_task(
            db,
            creator=user,
            assignee=user,
            title="Already there",
            day=destination,
        )
        moving = _create_assigned_task(db, creator=user, assignee=user, title="Move there", day=today)
        service = PlannerService(db)

        preview = service.preview_move(
            task_ids=[existing.id, moving.id],
            assignment_date=destination,
            viewer=user,
        )

        assert preview["ok"] is True
        assert preview["task_count"] == 1
        assert preview["unchanged_count"] == 1
        assert preview["members"][0]["current_points"] == 2
        assert preview["members"][0]["selected_points"] == 2
        assert preview["members"][0]["projected_points"] == 4
        assert preview["members"][0]["remaining"] == 0

        result = service.commit_move(
            task_ids=[existing.id, moving.id],
            assignment_date=destination,
            fingerprint=preview["fingerprint"],
            viewer=user,
        )
        assert result["moved_count"] == 1
        assert db.get(Task, existing.id).assignment_date == destination
        assert db.get(Task, moving.id).assignment_date == destination
    finally:
        db.close()


def test_planner_rejects_stale_confirmation_without_partial_move():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        user = _create_user(db, capacity=6)
        today = date.today()
        destination = today + timedelta(days=4)
        first = _create_assigned_task(db, creator=user, assignee=user, title="Stale first", day=today)
        second = _create_assigned_task(db, creator=user, assignee=user, title="Stale second", day=today + timedelta(days=1))
        service = PlannerService(db)
        preview = service.preview_move(
            task_ids=[first.id, second.id],
            assignment_date=destination,
            viewer=user,
        )

        capacity = db.get(UserDailyCapacity, user.id)
        capacity.daily_capacity_points = 7
        db.add(capacity)
        db.commit()

        result = service.commit_move(
            task_ids=[first.id, second.id],
            assignment_date=destination,
            fingerprint=preview["fingerprint"],
            viewer=user,
        )

        assert result["ok"] is False
        assert result["conflict"] is True
        assert db.get(Task, first.id).assignment_date == today
        assert db.get(Task, second.id).assignment_date == today + timedelta(days=1)
    finally:
        db.close()


def test_planner_non_admin_cannot_move_another_users_task():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        viewer = _create_user(db)
        assignee = _create_user(db)
        today = date.today()
        destination = today + timedelta(days=2)
        task = _create_assigned_task(db, creator=viewer, assignee=assignee, title="Other user task", day=today)
        service = PlannerService(db)

        preview = service.preview_move(
            task_ids=[task.id],
            assignment_date=destination,
            viewer=viewer,
        )
        result = service.commit_move(
            task_ids=[task.id],
            assignment_date=destination,
            fingerprint=preview["fingerprint"],
            viewer=viewer,
        )

        assert preview["ok"] is False
        assert any("only the assignee or an admin" in error for error in preview["errors"])
        assert result["ok"] is False
        assert db.get(Task, task.id).assignment_date == today
    finally:
        db.close()


def test_planner_admin_can_move_another_users_task_when_capacity_fits():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        admin = _create_user(db, is_admin=True)
        assignee = _create_user(db, capacity=4)
        today = date.today()
        destination = today + timedelta(days=2)
        task = _create_assigned_task(db, creator=admin, assignee=assignee, title="Admin move", day=today)
        service = PlannerService(db)

        preview = service.preview_move(
            task_ids=[task.id],
            assignment_date=destination,
            viewer=admin,
        )
        result = service.commit_move(
            task_ids=[task.id],
            assignment_date=destination,
            fingerprint=preview["fingerprint"],
            viewer=admin,
        )

        assert preview["ok"] is True
        assert result["ok"] is True
        assert db.get(Task, task.id).assignment_date == destination
    finally:
        db.close()


def test_planner_own_over_capacity_move_can_add_extra_capacity():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        user = _create_user(db, capacity=2)
        today = date.today()
        destination = today + timedelta(days=3)
        _create_assigned_task(db, creator=user, assignee=user, title="Already full", day=destination)
        moving = _create_assigned_task(db, creator=user, assignee=user, title="Needs extra", day=today)
        service = PlannerService(db)

        preview = service.preview_move(
            task_ids=[moving.id],
            assignment_date=destination,
            viewer=user,
        )
        result = service.commit_move(
            task_ids=[moving.id],
            assignment_date=destination,
            fingerprint=preview["fingerprint"],
            viewer=user,
            add_extra_capacity=True,
        )
        override = db.get(UserDailyCapacityOverride, {"user_id": user.id, "override_date": destination})

        assert preview["ok"] is False
        assert preview["can_add_extra_capacity"] is True
        assert preview["extra_capacity_required"] == 2
        assert result["ok"] is True
        assert result["extra_capacity_added"] == 2
        assert override is not None
        assert override.extra_capacity_points == 2
        assert db.get(Task, moving.id).assignment_date == destination
    finally:
        db.close()


def test_planner_extra_capacity_override_is_only_for_own_tasks():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        admin = _create_user(db, is_admin=True)
        assignee = _create_user(db, capacity=2)
        today = date.today()
        destination = today + timedelta(days=3)
        _create_assigned_task(db, creator=admin, assignee=assignee, title="Full other day", day=destination)
        moving = _create_assigned_task(db, creator=admin, assignee=assignee, title="Other needs extra", day=today)
        service = PlannerService(db)

        preview = service.preview_move(
            task_ids=[moving.id],
            assignment_date=destination,
            viewer=admin,
        )
        result = service.commit_move(
            task_ids=[moving.id],
            assignment_date=destination,
            fingerprint=preview["fingerprint"],
            viewer=admin,
            add_extra_capacity=True,
        )
        override = db.get(UserDailyCapacityOverride, {"user_id": assignee.id, "override_date": destination})

        assert preview["ok"] is False
        assert preview["can_add_extra_capacity"] is False
        assert result["ok"] is False
        assert override is None
        assert db.get(Task, moving.id).assignment_date == today
    finally:
        db.close()

def test_planner_api_rejects_other_users_task_for_non_admin():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        viewer = _create_user(db)
        assignee = _create_user(db)
        today = date.today()
        destination = today + timedelta(days=2)
        task = _create_assigned_task(db, creator=viewer, assignee=assignee, title="API other user task", day=today)
        client = _authed_client(viewer)

        preview_response = client.post(
            "/planner/move/preview",
            json={"task_ids": [task.id], "assignment_date": destination.isoformat()},
        )
        preview = preview_response.json()
        commit_response = client.post(
            "/planner/move/commit",
            json={
                "task_ids": [task.id],
                "assignment_date": destination.isoformat(),
                "fingerprint": preview["fingerprint"],
                "add_extra_capacity": True,
            },
        )

        assert preview_response.status_code == 400
        assert any("only the assignee or an admin" in error for error in preview["errors"])
        assert commit_response.status_code == 400
        db.expire_all()
        assert db.get(Task, task.id).assignment_date == today
    finally:
        db.close()


def test_planner_extra_capacity_rejects_stale_confirmation_without_extra_override():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        user = _create_user(db, capacity=2)
        today = date.today()
        destination = today + timedelta(days=3)
        _create_assigned_task(db, creator=user, assignee=user, title="Stale full day", day=destination)
        moving = _create_assigned_task(db, creator=user, assignee=user, title="Stale needs extra", day=today)
        service = PlannerService(db)
        preview = service.preview_move(
            task_ids=[moving.id],
            assignment_date=destination,
            viewer=user,
        )
        db.add(
            UserDailyCapacityOverride(
                user_id=user.id,
                override_date=destination,
                extra_capacity_points=1,
            )
        )
        db.commit()

        result = service.commit_move(
            task_ids=[moving.id],
            assignment_date=destination,
            fingerprint=preview["fingerprint"],
            viewer=user,
            add_extra_capacity=True,
        )
        override = db.get(UserDailyCapacityOverride, {"user_id": user.id, "override_date": destination})

        assert preview["ok"] is False
        assert preview["can_add_extra_capacity"] is True
        assert result["ok"] is False
        assert result["conflict"] is True
        assert override.extra_capacity_points == 1
        assert db.get(Task, moving.id).assignment_date == today
    finally:
        db.close()

def test_planner_rejects_destination_when_assignee_is_away():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        user = _create_user(db)
        today = date.today()
        destination = today + timedelta(days=2)
        task = _create_assigned_task(db, creator=user, assignee=user, title="Away move", day=today)
        SchedulingService(db).add_away_period(
            user_id=user.id,
            start_date=destination,
            end_date=destination,
            note="Unavailable",
        )

        result = PlannerService(db).preview_move(
            task_ids=[task.id],
            assignment_date=destination,
            viewer=user,
        )

        assert result["ok"] is False
        assert any("marked away" in error for error in result["errors"])
        assert task.assignment_date == today
    finally:
        db.close()


def test_planner_rejects_completed_tasks_and_past_dates():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        user = _create_user(db)
        today = date.today()
        task = _create_assigned_task(db, creator=user, assignee=user, title="Completed", day=today)
        TaskService(db).update_status(task, TaskStatus.COMPLETED)

        result = PlannerService(db).preview_move(
            task_ids=[task.id],
            assignment_date=today - timedelta(days=1),
            viewer=user,
        )

        assert result["ok"] is False
        assert any("completed tasks cannot be moved" in error for error in result["errors"])
        assert any("past date" in error for error in result["errors"])
    finally:
        db.close()


def test_planner_page_renders_separate_touch_ready_view():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        user = _create_user(db)
        today = date.today()
        task = _create_assigned_task(db, creator=user, assignee=user, title="Planner visible task", day=today)

        response = _authed_client(user).get("/planner")

        assert response.status_code == 200
        assert "Planner visible task" in response.text
        assert 'data-planner-root' in response.text
        assert 'data-planner-mobile-day' in response.text
        assert f'data-task-id="{task.id}"' in response.text
        assert 'data-planner-title-trigger' in response.text
        assert 'data-planner-date-choice' in response.text
        assert 'data-planner-date-strip' in response.text
        assert 'data-planner-date-scroll="1"' in response.text
        assert 'data-planner-date-scroll="-1"' in response.text
        assert 'bottom-3 z-50' in response.text
        assert 'planner-selection-active #assistant-toggle' in response.text
        assert f'data-assignment-date="{(today + timedelta(days=21)).isoformat()}"' in response.text
        assert 'name="member_id"' in response.text
        assert f'href="/planner?view=month&start={today.isoformat()}&scope=mine"' in response.text
        assert 'href="/planner"' in response.text
    finally:
        db.close()


def test_planner_member_filter_shows_only_selected_visible_member():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        viewer = _create_user(db)
        visible_member = _create_user(db, capacity=4)
        hidden_member = _create_user(db, capacity=4, show_in_member_lists=False)
        today = date.today()
        own_task = _create_assigned_task(db, creator=viewer, assignee=viewer, title="Own planner task", day=today)
        visible_task = _create_assigned_task(db, creator=viewer, assignee=visible_member, title="Visible member task", day=today)
        hidden_task = _create_assigned_task(db, creator=viewer, assignee=hidden_member, title="Hidden member task", day=today)

        response = _authed_client(viewer).get(f"/planner?scope=member&member_id={visible_member.id}")

        assert response.status_code == 200
        assert f'data-selected-member-id="{visible_member.id}"' in response.text
        assert f'value="{visible_member.id}" selected' in response.text
        assert "Visible member task" in response.text
        assert "Own planner task" not in response.text
        assert "Hidden member task" not in response.text
        assert f"scope=member&amp;member_id={visible_member.id}" in response.text
        assert "%2Fplanner%3Fscope%3Dmember" in response.text
        assert own_task.id != visible_task.id
        assert hidden_task.id != visible_task.id
    finally:
        db.close()


def test_planner_member_filter_rejects_hidden_member():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        viewer = _create_user(db)
        hidden_member = _create_user(db, show_in_member_lists=False)

        response = _authed_client(viewer).get(f"/planner?scope=member&member_id={hidden_member.id}")

        assert response.status_code == 404
    finally:
        db.close()


def test_repeated_web_completion_with_stale_occurrence_token_is_noop():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        user = _create_user(db)
        today = date.today()
        task = _create_recurring(
            db,
            creator=user,
            due_date=today,
            interval_weeks=1,
            late_behavior="from_completion",
        )
        TaskService(db).assign_task(task, assignee_id=user.id, assignment_date=today)
        client = _authed_client(user)
        payload = {
            "status_value": "completed",
            "redirect_to": f"/tasks/{task.id}",
            "expected_recurrence_index": "0",
        }

        first = client.post(f"/tasks/{task.id}/status", data=payload, follow_redirects=False)
        second = client.post(f"/tasks/{task.id}/status", data=payload, follow_redirects=False)
        db.refresh(task)

        assert first.status_code == 302
        assert second.status_code == 302
        assert task.recurrence_occurrence_index == 1
        assert task.due_date == today + timedelta(weeks=1)
        assert len(RecurringTaskService(db).get_history(task.id)) == 1
    finally:
        db.close()

def test_planner_json_preview_and_commit_move_tasks_together():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        user = _create_user(db, capacity=6)
        today = date.today()
        destination = today + timedelta(days=5)
        first = _create_assigned_task(db, creator=user, assignee=user, title="API first", day=today)
        second = _create_assigned_task(db, creator=user, assignee=user, title="API second", day=today + timedelta(days=1))
        client = _authed_client(user)

        preview_response = client.post(
            "/planner/move/preview",
            json={"task_ids": [first.id, second.id], "assignment_date": destination.isoformat()},
        )
        assert preview_response.status_code == 200
        preview = preview_response.json()
        assert preview["ok"] is True
        assert preview["members"][0]["projected_points"] == 4

        commit_response = client.post(
            "/planner/move/commit",
            json={
                "task_ids": [first.id, second.id],
                "assignment_date": destination.isoformat(),
                "fingerprint": preview["fingerprint"],
            },
        )
        assert commit_response.status_code == 200
        assert commit_response.json()["moved_count"] == 2
        db.expire_all()
        assert db.get(Task, first.id).assignment_date == destination
        assert db.get(Task, second.id).assignment_date == destination
    finally:
        db.close()


def test_recurring_form_help_and_late_behavior_persist_end_to_end():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        user = _create_user(db)
        client = _authed_client(user)
        create_page = client.get("/tasks/new")

        assert create_page.status_code == 200
        assert "After a late completion" in create_page.text
        assert "Keep original schedule" in create_page.text
        assert "Repeat from completion date" in create_page.text
        assert 'data-help-popover' in create_page.text

        title = f"Completion mode {uuid4().hex[:8]}"
        response = client.post(
            "/tasks",
            data={
                "title": title,
                "description": "",
                "due_date": date.today().isoformat(),
                "effort_level": "low",
                "repeat_weekly": "true",
                "recurrence_interval_weeks": "2",
                "recurrence_until": "",
                "recurrence_count_limit": "",
                "recurrence_blocked_behavior": "skip",
                "recurrence_late_behavior": "from_completion",
            },
            follow_redirects=False,
        )

        assert response.status_code == 302
        db.expire_all()
        task = db.query(Task).filter(Task.title == title).one()
        assert task.recurrence_late_behavior == "from_completion"
        assert task.recurrence_interval_weeks == 2
    finally:
        db.close()

def test_delete_current_recurring_occurrence_advances_series():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        user = _create_user(db)
        due_day = date.today() + timedelta(days=1)
        task = _create_recurring(
            db,
            creator=user,
            due_date=due_day,
            interval_weeks=1,
            late_behavior="keep_schedule",
        )
        TaskService(db).assign_task(task, assignee_id=user.id, assignment_date=due_day)
        client = _authed_client(user)
        task_id = task.id
        db.close()

        response = client.post(
            f"/tasks/{task_id}/delete",
            data={"redirect_to": "/tasks", "delete_scope": "single"},
            follow_redirects=False,
        )

        assert response.status_code == 302
        verify_db = SessionLocal()
        try:
            refreshed = verify_db.get(Task, task_id)
            assert refreshed is not None
            assert refreshed.status == TaskStatus.PENDING
            assert refreshed.recurrence_occurrence_index == 1
            assert refreshed.due_date == due_day + timedelta(weeks=1)
            assert refreshed.assignment_date == due_day + timedelta(weeks=1)
        finally:
            verify_db.close()
    finally:
        db.close()


def test_edit_form_completion_advances_recurring_root_once():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        user = _create_user(db)
        today = date.today()
        task = _create_recurring(
            db,
            creator=user,
            due_date=today,
            interval_weeks=1,
            late_behavior="from_completion",
        )
        TaskService(db).assign_task(task, assignee_id=user.id, assignment_date=today)
        client = _authed_client(user)
        task_id = task.id
        payload = {
            "title": task.title,
            "description": task.description,
            "due_date": today.isoformat(),
            "effort_level": "low",
            "status_value": "completed",
            "repeat_weekly": "true",
            "recurrence_interval_weeks": "1",
            "recurrence_series_due_date": (today + timedelta(weeks=1)).isoformat(),
            "recurrence_until": "",
            "recurrence_count_limit": "",
            "recurrence_blocked_behavior": "skip",
            "recurrence_late_behavior": "from_completion",
            "assignee_id_edit": str(user.id),
            "assignment_date_edit": today.isoformat(),
            "expected_recurrence_index": "0",
        }
        db.close()

        day_page = client.get(f"/day-view?day={today.isoformat()}&scope=mine")
        assert day_page.status_code == 200
        assert 'name="expected_recurrence_index" value="0"' in day_page.text

        first = client.post(f"/tasks/{task_id}/edit", data=payload, follow_redirects=False)
        second = client.post(f"/tasks/{task_id}/edit", data=payload, follow_redirects=False)

        assert first.status_code == 302
        assert second.status_code == 302
        verify_db = SessionLocal()
        try:
            refreshed = verify_db.get(Task, task_id)
            assert refreshed.status == TaskStatus.PENDING
            assert refreshed.recurrence_occurrence_index == 1
            assert refreshed.due_date == today + timedelta(weeks=1)
            assert len(RecurringTaskService(verify_db).get_history(task_id)) == 1
        finally:
            verify_db.close()
    finally:
        db.close()

