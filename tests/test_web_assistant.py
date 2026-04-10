import json
from datetime import date
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app.core.security import create_access_token
from backend.app.db.base import Base
from backend.app.db.session import SessionLocal, engine
from backend.app.main import app
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


def _create_user(db, *, email: str, full_name: str, capacity: int):
    user = AuthService(db).register(
        RegisterRequest(email=email, full_name=full_name, password="securepass123"),
        require_approval=False,
    )
    db.add(UserDailyCapacity(user_id=user.id, daily_capacity_points=capacity))
    db.commit()
    db.refresh(user)
    return user


def _create_unassigned_task(db, *, creator, title: str, due_date: date, effort_level: EffortLevel):
    return TaskService(db).create_unassigned_task(
        TaskCreate(
            title=title,
            description="Assistant task",
            due_date=due_date,
            effort_level=effort_level,
            ai_suggested_level=effort_level,
            ai_confidence=0.8,
            ai_reason="assistant test",
            fallback_used=False,
            provider_used="rules",
            model_used="rules-default",
        ),
        creator,
    )


def _authed_client(user):
    client = TestClient(app)
    token = create_access_token(subject=str(user.id))
    client.cookies.set("access_token", token)
    return client


def _create_assigned_task(db, *, creator, assignee, title: str, due_date: date, assignment_date: date, effort_level: EffortLevel):
    task = _create_unassigned_task(
        db,
        creator=creator,
        title=title,
        due_date=due_date,
        effort_level=effort_level,
    )
    TaskService(db).assign_task(task, assignee_id=assignee.id, assignment_date=assignment_date)
    return task


def test_assistant_lists_low_tasks_with_action():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(db, email=f"assistant-viewer-{token}@example.com", full_name="Assistant Viewer", capacity=8)
        task = _create_unassigned_task(
            db,
            creator=viewer,
            title=f"Low Task {token}",
            due_date=date.today(),
            effort_level=EffortLevel.LOW,
        )

        client = _authed_client(viewer)
        response = client.post("/assistant/chat", data={"message": "list low tasks"})

        assert response.status_code == 200
        payload = response.json()
        assert payload["items"][0]["title"] == task.title
        assert payload["items"][0]["action"]["type"] == "assign_self"
    finally:
        db.close()


def test_assistant_reports_who_has_most_capacity_left():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(db, email=f"cap-viewer-{token}@example.com", full_name="Cap Viewer", capacity=6)
        teammate = _create_user(db, email=f"cap-mate-{token}@example.com", full_name="Cap Mate", capacity=10)
        task = _create_unassigned_task(
            db,
            creator=viewer,
            title=f"Taken Task {token}",
            due_date=date.today(),
            effort_level=EffortLevel.LOW,
        )
        TaskService(db).assign_task(task, assignee_id=viewer.id, assignment_date=date.today())

        client = _authed_client(viewer)
        response = client.post("/assistant/chat", data={"message": "who has the most capacity left?"})

        assert response.status_code == 200
        payload = response.json()
        assert payload["items"][0]["title"] == "Cap Mate"
    finally:
        db.close()


def test_assistant_can_assign_current_user_to_suggested_task():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(db, email=f"assign-viewer-{token}@example.com", full_name="Assign Viewer", capacity=10)
        task = _create_unassigned_task(
            db,
            creator=viewer,
            title=f"Assignable Task {token}",
            due_date=date.today(),
            effort_level=EffortLevel.LOW,
        )

        client = _authed_client(viewer)
        initial = client.post("/assistant/chat", data={"message": "add me to any low task available"})
        assert initial.status_code == 200
        action = initial.json()["items"][0]["action"]

        confirm = client.post(
            "/assistant/actions/assign-self",
            data={"task_id": action["task_id"], "assignment_date": action["assignment_date"]},
        )
        assert confirm.status_code == 200
        assert confirm.json()["ok"] is True

        db.refresh(task)
        assert task.assignee_id == viewer.id
    finally:
        db.close()


def test_assistant_understands_add_me_to_low_unassigned_for_today():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(db, email=f"phrase-viewer-{token}@example.com", full_name="Phrase Viewer", capacity=10)
        due_today = _create_unassigned_task(
            db,
            creator=viewer,
            title=f"Today Low {token}",
            due_date=date.today(),
            effort_level=EffortLevel.LOW,
        )
        _create_unassigned_task(
            db,
            creator=viewer,
            title=f"Tomorrow Low {token}",
            due_date=date.fromordinal(date.today().toordinal() + 1),
            effort_level=EffortLevel.LOW,
        )

        client = _authed_client(viewer)
        response = client.post("/assistant/chat", data={"message": "add me to a low task unassigned for today"})

        assert response.status_code == 200
        payload = response.json()
        assert payload["items"][0]["title"] == due_today.title
        assert payload["items"][0]["action"]["type"] == "assign_self"
    finally:
        db.close()


def test_assistant_can_use_context_for_follow_up_assignment():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(db, email=f"context-viewer-{token}@example.com", full_name="Context Viewer", capacity=10)
        first_task = _create_unassigned_task(
            db,
            creator=viewer,
            title=f"First Low {token}",
            due_date=date.today(),
            effort_level=EffortLevel.LOW,
        )
        _create_unassigned_task(
            db,
            creator=viewer,
            title=f"Second Low {token}",
            due_date=date.today(),
            effort_level=EffortLevel.LOW,
        )

        client = _authed_client(viewer)
        initial = client.post("/assistant/chat", data={"message": "list low tasks"})
        assert initial.status_code == 200
        context_items = initial.json()["items"]

        follow_up = client.post(
            "/assistant/chat",
            data={
                "message": "assign me to the first one",
                "context_json": json.dumps(context_items),
            },
        )
        assert follow_up.status_code == 200
        payload = follow_up.json()
        assert payload["items"][0]["title"] == first_task.title
        assert payload["items"][0]["action"]["type"] == "assign_self"
    finally:
        db.close()


def test_assistant_lists_unassigned_tasks_due_today():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(db, email=f"today-viewer-{token}@example.com", full_name="Today Viewer", capacity=10)
        due_today = _create_unassigned_task(
            db,
            creator=viewer,
            title=f"Due Today {token}",
            due_date=date.today(),
            effort_level=EffortLevel.MEDIUM,
        )
        _create_unassigned_task(
            db,
            creator=viewer,
            title=f"Tomorrow {token}",
            due_date=date.fromordinal(date.today().toordinal() + 1),
            effort_level=EffortLevel.MEDIUM,
        )

        client = _authed_client(viewer)
        response = client.post("/assistant/chat", data={"message": "what unassigned tasks are due today?"})

        assert response.status_code == 200
        payload = response.json()
        assert payload["items"][0]["title"] == due_today.title
        assert all("Tomorrow" not in item["title"] for item in payload["items"])
    finally:
        db.close()


def test_assistant_lists_tasks_assigned_to_current_user_today():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(db, email=f"mine-viewer-{token}@example.com", full_name="Mine Viewer", capacity=10)
        teammate = _create_user(db, email=f"mine-mate-{token}@example.com", full_name="Mine Mate", capacity=10)
        assigned_today = _create_assigned_task(
            db,
            creator=teammate,
            assignee=viewer,
            title=f"My Today Task {token}",
            due_date=date.today(),
            assignment_date=date.today(),
            effort_level=EffortLevel.LOW,
        )
        _create_assigned_task(
            db,
            creator=teammate,
            assignee=teammate,
            title=f"Teammate Task {token}",
            due_date=date.today(),
            assignment_date=date.today(),
            effort_level=EffortLevel.LOW,
        )

        client = _authed_client(viewer)
        response = client.post("/assistant/chat", data={"message": "what tasks are assigned to me today?"})

        assert response.status_code == 200
        payload = response.json()
        assert payload["items"][0]["title"] == assigned_today.title
        assert all("Teammate Task" not in item["title"] for item in payload["items"])
    finally:
        db.close()


def test_assistant_filters_today_tasks_by_effort_and_status():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(db, email=f"filter-viewer-{token}@example.com", full_name="Filter Viewer", capacity=10)
        matching = _create_unassigned_task(
            db,
            creator=viewer,
            title=f"Medium Pending Today {token}",
            due_date=date.today(),
            effort_level=EffortLevel.MEDIUM,
        )
        non_matching_status = _create_unassigned_task(
            db,
            creator=viewer,
            title=f"Medium Completed Today {token}",
            due_date=date.today(),
            effort_level=EffortLevel.MEDIUM,
        )
        non_matching_status.status = TaskStatus.COMPLETED
        db.add(non_matching_status)
        db.commit()

        client = _authed_client(viewer)
        response = client.post("/assistant/chat", data={"message": "show today's medium pending tasks"})

        assert response.status_code == 200
        payload = response.json()
        assert payload["items"][0]["title"] == matching.title
        assert all("Completed" not in item["title"] for item in payload["items"])
    finally:
        db.close()
