from datetime import date, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app.core.security import get_password_hash
from backend.app.db.base import Base
from backend.app.db.session import SessionLocal, engine
from backend.app.main import app
from backend.app.models.enums import EffortLevel, TaskStatus
from backend.app.models.task import Task
from backend.app.models.user import User
from backend.app.models.user_daily_capacity import UserDailyCapacity
from backend.app.models.user_daily_capacity_override import UserDailyCapacityOverride


def setup_module():
    Base.metadata.create_all(bind=engine)


def _create_user(db, *, label: str) -> tuple[User, str]:
    suffix = uuid4().hex[:8]
    password = "securepass123"
    user = User(
        email=f"{label}-{suffix}@example.com",
        full_name=f"{label.title()} User",
        hashed_password=get_password_hash(password),
        approval_status="approved",
        is_active=True,
        show_in_member_lists=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user, password


def _login_headers(client: TestClient, *, email: str, password: str) -> tuple[dict[str, str], dict]:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    payload = response.json()
    return {"Authorization": f"Bearer {payload['access_token']}"}, payload


def _create_task(
    db,
    *,
    title: str,
    created_by_id: int,
    assignee_id: int | None,
    assignment_date: date | None,
    due_date: date,
    status: TaskStatus,
    effort_level: EffortLevel = EffortLevel.MEDIUM,
    recurrence_pattern: str | None = None,
    recurrence_interval_weeks: int | None = None,
    recurrence_anchor_date: date | None = None,
    recurrence_parent_id: int | None = None,
) -> Task:
    points_lookup = {
        EffortLevel.LOW: 2,
        EffortLevel.MEDIUM: 5,
        EffortLevel.HIGH: 8,
    }
    task = Task(
        title=title,
        description=f"{title} description",
        due_date=due_date,
        assignment_date=assignment_date,
        assignee_id=assignee_id,
        created_by_id=created_by_id,
        effort_level=effort_level,
        points_value=points_lookup[effort_level],
        status=status,
        recurrence_pattern=recurrence_pattern,
        recurrence_interval_weeks=recurrence_interval_weeks,
        recurrence_anchor_date=recurrence_anchor_date,
        recurrence_parent_id=recurrence_parent_id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def test_login_response_includes_user_and_expiry():
    client = TestClient(app)
    db = SessionLocal()
    try:
        user, password = _create_user(db, label="mobile-login")
        _headers, payload = _login_headers(client, email=user.email, password=password)
        assert payload["token_type"] == "bearer"
        assert payload["expires_at"]
        assert payload["user"]["email"] == user.email
        assert payload["user"]["approval_status"] == "approved"
    finally:
        db.close()


def test_mobile_today_window_detail_and_assigned_scope():
    client = TestClient(app)
    db = SessionLocal()
    try:
        owner, _owner_password = _create_user(db, label="mobile-owner")
        mobile_user, mobile_password = _create_user(db, label="mobile-member")
        other_user, _other_password = _create_user(db, label="mobile-other")
        headers, _payload = _login_headers(client, email=mobile_user.email, password=mobile_password)

        today = date.today()
        overdue_in_progress = _create_task(
            db,
            title="Overdue in progress",
            created_by_id=owner.id,
            assignee_id=mobile_user.id,
            assignment_date=today - timedelta(days=2),
            due_date=today - timedelta(days=2),
            status=TaskStatus.IN_PROGRESS,
        )
        overdue_pending = _create_task(
            db,
            title="Overdue pending",
            created_by_id=owner.id,
            assignee_id=mobile_user.id,
            assignment_date=today - timedelta(days=1),
            due_date=today - timedelta(days=1),
            status=TaskStatus.PENDING,
        )
        today_in_progress = _create_task(
            db,
            title="Today in progress",
            created_by_id=owner.id,
            assignee_id=mobile_user.id,
            assignment_date=today,
            due_date=today,
            status=TaskStatus.IN_PROGRESS,
        )
        today_pending = _create_task(
            db,
            title="Today pending",
            created_by_id=owner.id,
            assignee_id=mobile_user.id,
            assignment_date=today,
            due_date=today + timedelta(days=1),
            status=TaskStatus.PENDING,
        )
        today_assigned_due_past = _create_task(
            db,
            title="Today assigned due past",
            created_by_id=owner.id,
            assignee_id=mobile_user.id,
            assignment_date=today,
            due_date=today - timedelta(days=1),
            status=TaskStatus.PENDING,
        )
        future_assigned_due_past = _create_task(
            db,
            title="Future assigned due past",
            created_by_id=owner.id,
            assignee_id=mobile_user.id,
            assignment_date=today + timedelta(days=10),
            due_date=today - timedelta(days=1),
            status=TaskStatus.PENDING,
        )
        today_completed = _create_task(
            db,
            title="Today completed",
            created_by_id=owner.id,
            assignee_id=mobile_user.id,
            assignment_date=today,
            due_date=today,
            status=TaskStatus.COMPLETED,
        )
        future_pending = _create_task(
            db,
            title="Future pending",
            created_by_id=owner.id,
            assignee_id=mobile_user.id,
            assignment_date=today + timedelta(days=2),
            due_date=today + timedelta(days=2),
            status=TaskStatus.PENDING,
        )
        other_task = _create_task(
            db,
            title="Other user's task",
            created_by_id=owner.id,
            assignee_id=other_user.id,
            assignment_date=today,
            due_date=today,
            status=TaskStatus.PENDING,
        )
        _create_task(
            db,
            title="Unassigned task",
            created_by_id=mobile_user.id,
            assignee_id=None,
            assignment_date=None,
            due_date=today,
            status=TaskStatus.PENDING,
        )

        today_response = client.get("/api/v1/mobile/tasks/today", headers=headers)
        assert today_response.status_code == 200
        today_payload = today_response.json()
        assert [item["title"] for item in today_payload["tasks"]] == [
            "Overdue in progress",
            "Overdue pending",
            "Future assigned due past",
            "Today in progress",
            "Today assigned due past",
            "Today pending",
            "Today completed",
        ]
        assert [item["display_bucket"] for item in today_payload["tasks"]] == [
            "overdue",
            "overdue",
            "overdue",
            "today",
            "today",
            "today",
            "completed",
        ]
        today_due_past_payload = next(
            item for item in today_payload["tasks"] if item["id"] == today_assigned_due_past.id
        )
        assert today_due_past_payload["display_bucket"] == "today"
        assert today_due_past_payload["is_overdue"] is True
        assert [item["id"] for item in today_payload["tasks"]].count(today_assigned_due_past.id) == 1
        assert [item["id"] for item in today_payload["tasks"]].count(future_assigned_due_past.id) == 1

        window_response = client.get(
            f"/api/v1/mobile/tasks/window?start={(today - timedelta(days=1)).isoformat()}&end={(today + timedelta(days=3)).isoformat()}",
            headers=headers,
        )
        assert window_response.status_code == 200
        window_payload = window_response.json()
        assert [item["title"] for item in window_payload["tasks"]] == [
            "Overdue in progress",
            "Overdue pending",
            "Future assigned due past",
            "Today in progress",
            "Today assigned due past",
            "Today pending",
            "Today completed",
            "Future pending",
        ]

        detail_response = client.get(f"/api/v1/mobile/tasks/{today_pending.id}", headers=headers)
        assert detail_response.status_code == 200
        detail_payload = detail_response.json()
        assert detail_payload["id"] == today_pending.id
        assert detail_payload["title"] == "Today pending"

        hidden_response = client.get(f"/api/v1/mobile/tasks/{other_task.id}", headers=headers)
        assert hidden_response.status_code == 404
    finally:
        db.close()


def test_mobile_status_update_and_error_payloads():
    client = TestClient(app)
    db = SessionLocal()
    try:
        owner, _owner_password = _create_user(db, label="mobile-status-owner")
        mobile_user, mobile_password = _create_user(db, label="mobile-status-member")
        headers, _payload = _login_headers(client, email=mobile_user.email, password=mobile_password)

        today = date.today()
        task = _create_task(
            db,
            title="Patch me",
            created_by_id=owner.id,
            assignee_id=mobile_user.id,
            assignment_date=today,
            due_date=today,
            status=TaskStatus.PENDING,
        )

        patch_response = client.patch(
            f"/api/v1/mobile/tasks/{task.id}/status",
            headers=headers,
            json={"status": "completed"},
        )
        assert patch_response.status_code == 200
        patch_payload = patch_response.json()
        assert patch_payload["refresh_required"] is False
        assert patch_payload["task"]["status"] == "completed"
        assert patch_payload["task"]["is_completed"] is True

        invalid_status = client.patch(
            f"/api/v1/mobile/tasks/{task.id}/status",
            headers=headers,
            json={"status": "not-a-real-status"},
        )
        assert invalid_status.status_code == 422
        invalid_payload = invalid_status.json()
        assert invalid_payload["code"] == "validation_error"
        assert invalid_payload["retryable"] is False
        assert invalid_payload["detail"] == "Validation failed."

        unauthenticated = client.get("/api/v1/mobile/tasks/today")
        assert unauthenticated.status_code == 401
        unauthenticated_payload = unauthenticated.json()
        assert unauthenticated_payload["code"] == "not_authenticated"
        assert unauthenticated_payload["retryable"] is False

        bad_window = client.get(
            f"/api/v1/mobile/tasks/window?start={(today + timedelta(days=2)).isoformat()}&end={today.isoformat()}",
            headers=headers,
        )
        assert bad_window.status_code == 400
        bad_window_payload = bad_window.json()
        assert bad_window_payload["code"] == "invalid_request"
        assert bad_window_payload["detail"] == "End date must be on or after start date."
    finally:
        db.close()


def test_mobile_schedule_update_uses_capacity_and_assignment_date_rules():
    client = TestClient(app)
    db = SessionLocal()
    try:
        owner, _owner_password = _create_user(db, label="mobile-schedule-owner")
        mobile_user, mobile_password = _create_user(db, label="mobile-schedule-member")
        other_user, _other_password = _create_user(db, label="mobile-schedule-other")
        db.add(UserDailyCapacity(user_id=mobile_user.id, daily_capacity_points=6))
        db.commit()
        headers, _payload = _login_headers(client, email=mobile_user.email, password=mobile_password)

        today = date.today()
        existing = _create_task(
            db,
            title="Existing load",
            created_by_id=owner.id,
            assignee_id=mobile_user.id,
            assignment_date=today + timedelta(days=1),
            due_date=today + timedelta(days=1),
            status=TaskStatus.PENDING,
            effort_level=EffortLevel.LOW,
        )
        task = _create_task(
            db,
            title="Schedule me",
            created_by_id=owner.id,
            assignee_id=mobile_user.id,
            assignment_date=today,
            due_date=today,
            status=TaskStatus.PENDING,
            effort_level=EffortLevel.MEDIUM,
        )
        other_task = _create_task(
            db,
            title="Other schedule",
            created_by_id=owner.id,
            assignee_id=other_user.id,
            assignment_date=today,
            due_date=today,
            status=TaskStatus.PENDING,
        )

        blocked_response = client.patch(
            f"/api/v1/mobile/tasks/{task.id}/schedule",
            headers=headers,
            json={
                "due_date": (today + timedelta(days=1)).isoformat(),
                "assignment_date": (today + timedelta(days=1)).isoformat(),
            },
        )
        assert blocked_response.status_code == 400
        assert blocked_response.json()["detail"] == "Assignment exceeds daily capacity."

        next_response = client.get(
            f"/api/v1/mobile/tasks/{task.id}/schedule/next-available?start_date={(today + timedelta(days=1)).isoformat()}",
            headers=headers,
        )
        assert next_response.status_code == 200
        assert next_response.json()["assignment_date"] == (today + timedelta(days=2)).isoformat()

        check_response = client.get(
            f"/api/v1/mobile/tasks/{task.id}/schedule/check?assignment_date={(today + timedelta(days=2)).isoformat()}",
            headers=headers,
        )
        assert check_response.status_code == 200
        assert check_response.json()["valid"] is True

        update_response = client.patch(
            f"/api/v1/mobile/tasks/{task.id}/schedule",
            headers=headers,
            json={
                "due_date": (today + timedelta(days=3)).isoformat(),
                "assignment_date": (today + timedelta(days=2)).isoformat(),
            },
        )
        assert update_response.status_code == 200
        payload = update_response.json()
        assert payload["task"]["due_date"] == (today + timedelta(days=3)).isoformat()
        assert payload["task"]["assignment_date"] == (today + timedelta(days=2)).isoformat()
        assert payload["feedback"]["valid"] is True

        db.refresh(task)
        db.refresh(existing)
        assert task.assignment_date == today + timedelta(days=2)
        assert existing.assignment_date == today + timedelta(days=1)

        past_response = client.patch(
            f"/api/v1/mobile/tasks/{task.id}/schedule",
            headers=headers,
            json={
                "due_date": today.isoformat(),
                "assignment_date": (today - timedelta(days=1)).isoformat(),
            },
        )
        assert past_response.status_code == 400
        assert past_response.json()["detail"] == "Assignment date cannot be in the past."

        hidden_response = client.patch(
            f"/api/v1/mobile/tasks/{other_task.id}/schedule",
            headers=headers,
            json={
                "due_date": today.isoformat(),
                "assignment_date": today.isoformat(),
            },
        )
        assert hidden_response.status_code == 404

        extend_response = client.patch(
            f"/api/v1/mobile/tasks/{task.id}/schedule",
            headers=headers,
            json={
                "due_date": (today + timedelta(days=1)).isoformat(),
                "assignment_date": (today + timedelta(days=1)).isoformat(),
                "extend_capacity": True,
            },
        )
        assert extend_response.status_code == 200
        extend_payload = extend_response.json()
        assert extend_payload["task"]["assignment_date"] == (today + timedelta(days=1)).isoformat()
        assert extend_payload["feedback"]["valid"] is True
        assert extend_payload["feedback"]["capacity"] == 7

        override = db.get(
            UserDailyCapacityOverride,
            {"user_id": mobile_user.id, "override_date": today + timedelta(days=1)},
        )
        assert override is not None
        assert override.extra_capacity_points == 1

        db.refresh(task)
        assert task.assignment_date == today + timedelta(days=1)
    finally:
        db.close()


def test_mobile_schedule_update_allows_due_date_only_change_for_existing_past_assignment():
    client = TestClient(app)
    db = SessionLocal()
    try:
        owner, _owner_password = _create_user(db, label="mobile-due-only-owner")
        mobile_user, mobile_password = _create_user(db, label="mobile-due-only-member")
        headers, _payload = _login_headers(client, email=mobile_user.email, password=mobile_password)

        today = date.today()
        task = _create_task(
            db,
            title="Due only change",
            created_by_id=owner.id,
            assignee_id=mobile_user.id,
            assignment_date=today - timedelta(days=3),
            due_date=today - timedelta(days=1),
            status=TaskStatus.PENDING,
            effort_level=EffortLevel.MEDIUM,
        )

        response = client.patch(
            f"/api/v1/mobile/tasks/{task.id}/schedule",
            headers=headers,
            json={
                "due_date": (today + timedelta(days=5)).isoformat(),
                "assignment_date": (today - timedelta(days=3)).isoformat(),
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["task"]["due_date"] == (today + timedelta(days=5)).isoformat()
        assert payload["task"]["assignment_date"] == (today - timedelta(days=3)).isoformat()
        assert payload["feedback"]["valid"] is True

        db.refresh(task)
        assert task.due_date == today + timedelta(days=5)
        assert task.assignment_date == today - timedelta(days=3)
    finally:
        db.close()


def test_recurring_completion_returns_refresh_required_and_creates_completed_snapshot():
    client = TestClient(app)
    db = SessionLocal()
    try:
        owner, _owner_password = _create_user(db, label="mobile-recurring-owner")
        mobile_user, mobile_password = _create_user(db, label="mobile-recurring-member")
        db.add(UserDailyCapacity(user_id=mobile_user.id, daily_capacity_points=10))
        db.commit()

        headers, _payload = _login_headers(client, email=mobile_user.email, password=mobile_password)
        today = date.today()
        recurring = _create_task(
            db,
            title="Recurring chore",
            created_by_id=owner.id,
            assignee_id=mobile_user.id,
            assignment_date=today,
            due_date=today,
            status=TaskStatus.PENDING,
            recurrence_pattern="weekly",
            recurrence_interval_weeks=1,
            recurrence_anchor_date=today,
        )

        patch_response = client.patch(
            f"/api/v1/mobile/tasks/{recurring.id}/status",
            headers=headers,
            json={"status": "completed"},
        )
        assert patch_response.status_code == 200
        patch_payload = patch_response.json()
        assert patch_payload["refresh_required"] is True
        assert patch_payload["task"] is None

        today_response = client.get("/api/v1/mobile/tasks/today", headers=headers)
        assert today_response.status_code == 200
        today_titles = [item["title"] for item in today_response.json()["tasks"]]
        assert "Recurring chore" in today_titles

        next_window = client.get(
            f"/api/v1/mobile/tasks/window?start={today.isoformat()}&end={(today + timedelta(days=8)).isoformat()}",
            headers=headers,
        )
        assert next_window.status_code == 200
        window_payload = next_window.json()
        recurring_items = [item for item in window_payload["tasks"] if item["title"] == "Recurring chore"]
        assert any(item["display_bucket"] == "completed" for item in recurring_items)
        assert any(item["status"] == "pending" for item in recurring_items)
    finally:
        db.close()


def test_mobile_reopens_completed_recurring_snapshot_as_one_off_task():
    client = TestClient(app)
    db = SessionLocal()
    try:
        owner, _owner_password = _create_user(db, label="mobile-recurring-reopen-owner")
        mobile_user, mobile_password = _create_user(db, label="mobile-recurring-reopen-member")
        headers, _payload = _login_headers(client, email=mobile_user.email, password=mobile_password)
        today = date.today()
        recurring = _create_task(
            db,
            title="Recurring reopen",
            created_by_id=owner.id,
            assignee_id=mobile_user.id,
            assignment_date=today,
            due_date=today,
            status=TaskStatus.PENDING,
            recurrence_pattern="weekly",
            recurrence_interval_weeks=1,
            recurrence_anchor_date=today,
        )

        complete_response = client.patch(
            f"/api/v1/mobile/tasks/{recurring.id}/status",
            headers=headers,
            json={"status": "completed"},
        )
        assert complete_response.status_code == 200
        db.refresh(recurring)
        next_due_date = recurring.due_date
        snapshot = (
            db.query(Task)
            .filter(Task.recurrence_parent_id == recurring.id, Task.status == TaskStatus.COMPLETED)
            .one()
        )

        reopen_response = client.patch(
            f"/api/v1/mobile/tasks/{snapshot.id}/status",
            headers=headers,
            json={"status": "pending"},
        )

        assert reopen_response.status_code == 200
        reopen_payload = reopen_response.json()
        assert reopen_payload["refresh_required"] is False
        assert reopen_payload["task"]["status"] == "pending"
        assert reopen_payload["task"]["recurrence_parent_id"] is None
        assert reopen_payload["task"]["recurrence_summary"] is None

        db.refresh(snapshot)
        db.refresh(recurring)
        assert snapshot.status == TaskStatus.PENDING
        assert snapshot.recurrence_parent_id is None
        assert snapshot.recurrence_pattern is None
        assert recurring.status == TaskStatus.PENDING
        assert recurring.due_date == next_due_date
        assert recurring.recurrence_pattern == "weekly"
    finally:
        db.close()
