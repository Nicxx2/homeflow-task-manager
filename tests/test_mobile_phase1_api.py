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
            "Today in progress",
            "Today pending",
            "Today completed",
        ]
        assert [item["display_bucket"] for item in today_payload["tasks"]] == [
            "overdue",
            "overdue",
            "today",
            "today",
            "completed",
        ]

        window_response = client.get(
            f"/api/v1/mobile/tasks/window?start={(today - timedelta(days=1)).isoformat()}&end={(today + timedelta(days=3)).isoformat()}",
            headers=headers,
        )
        assert window_response.status_code == 200
        window_payload = window_response.json()
        assert [item["title"] for item in window_payload["tasks"]] == [
            "Overdue in progress",
            "Overdue pending",
            "Today in progress",
            "Today pending",
            "Future pending",
            "Today completed",
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
