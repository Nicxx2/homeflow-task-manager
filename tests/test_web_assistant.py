import json
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete, update

from backend.app.ai.services.orchestrator import AIOrchestratorService
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
from backend.app.services.task_service import TaskService
from backend.app.services.workload_service import WorkloadService


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


def _clear_today_capacity_overrides(db):
    db.execute(delete(UserDailyCapacityOverride).where(UserDailyCapacityOverride.override_date == date.today()))
    db.commit()


def _complete_existing_active_tasks(db):
    db.execute(update(Task).where(Task.status != TaskStatus.COMPLETED).values(status=TaskStatus.COMPLETED))
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


def _complete_task_on(db, task: Task, completed_on: date) -> Task:
    TaskService(db).update_status(task, TaskStatus.COMPLETED)
    db.refresh(task)
    task.completed_at = datetime(
        completed_on.year,
        completed_on.month,
        completed_on.day,
        12,
        0,
        tzinfo=timezone.utc,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
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
        completed = _create_unassigned_task(
            db,
            creator=viewer,
            title=f"Completed Low Task {token}",
            due_date=date.fromordinal(date.today().toordinal() - 60),
            effort_level=EffortLevel.LOW,
        )
        _complete_task_on(db, completed, date.today())

        client = _authed_client(viewer)
        response = client.post("/assistant/chat", data={"message": "list low tasks"})

        assert response.status_code == 200
        payload = response.json()
        titles = [item["title"] for item in payload["items"]]
        assert task.title in titles
        assert completed.title not in titles
        assert payload["items"][0]["action"]["type"] == "assign_self"
    finally:
        db.close()


def test_assistant_explicit_completed_tasks_can_be_listed():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(db, email=f"completed-viewer-{token}@example.com", full_name="Completed Viewer", capacity=8)
        completed = _create_unassigned_task(
            db,
            creator=viewer,
            title=f"Explicit Completed Low {token}",
            due_date=date.today(),
            effort_level=EffortLevel.LOW,
        )
        _complete_task_on(db, completed, date.today())

        client = _authed_client(viewer)
        response = client.post("/assistant/chat", data={"message": "show completed low tasks today"})

        assert response.status_code == 200
        payload = response.json()
        assert payload["items"][0]["title"] == completed.title
        assert "action" not in payload["items"][0]

    finally:
        db.close()


def test_assistant_filters_by_visible_member_and_planned_date():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(db, email=f"plan-viewer-{token}@example.com", full_name="Plan Viewer", capacity=10)
        teammate = _create_user(db, email=f"plan-mate-{token}@example.com", full_name=f"Plan Mate {token}", capacity=10)
        other = _create_user(db, email=f"plan-other-{token}@example.com", full_name=f"Plan Other {token}", capacity=10)
        target_day = date.fromordinal(date.today().toordinal() + 3)
        matching = _create_assigned_task(
            db,
            creator=viewer,
            assignee=teammate,
            title=f"Mate Planned {token}",
            due_date=target_day,
            assignment_date=target_day,
            effort_level=EffortLevel.MEDIUM,
        )
        _create_assigned_task(
            db,
            creator=viewer,
            assignee=other,
            title=f"Other Planned {token}",
            due_date=target_day,
            assignment_date=target_day,
            effort_level=EffortLevel.MEDIUM,
        )

        client = _authed_client(viewer)
        response = client.post(
            "/assistant/chat",
            data={"message": f"show tasks for {teammate.full_name} planned on {target_day.isoformat()}"},
        )

        assert response.status_code == 200
        payload = response.json()
        titles = [item["title"] for item in payload["items"]]
        assert titles == [matching.title]
    finally:
        db.close()


def test_assistant_understands_partial_member_name_for_today_tasks():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(db, email=f"partial-viewer-{token}@example.com", full_name="Partial Viewer", capacity=10)
        teammate = _create_user(db, email=f"bethan-{token}@example.com", full_name=f"Bethan{token} Smith", capacity=10)
        matching = _create_assigned_task(
            db,
            creator=viewer,
            assignee=teammate,
            title=f"Bethan Today {token}",
            due_date=date.today(),
            assignment_date=date.today(),
            effort_level=EffortLevel.LOW,
        )
        mine = _create_assigned_task(
            db,
            creator=viewer,
            assignee=viewer,
            title=f"Viewer Today {token}",
            due_date=date.today(),
            assignment_date=date.today(),
            effort_level=EffortLevel.LOW,
        )

        response = _authed_client(viewer).post(
            "/assistant/chat",
            data={"message": f"does Bethan{token} have any tasks today?"},
        )

        assert response.status_code == 200
        titles = [item["title"] for item in response.json()["items"]]
        assert matching.title in titles
        assert mine.title not in titles
    finally:
        db.close()


def test_assistant_member_name_containing_effort_word_does_not_filter_effort():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(db, email=f"marlow-viewer-{token}@example.com", full_name="Effort Viewer", capacity=10)
        teammate = _create_user(db, email=f"marlow-mate-{token}@example.com", full_name=f"Marlow{token} Lane", capacity=10)
        matching = _create_assigned_task(
            db,
            creator=viewer,
            assignee=teammate,
            title=f"Marlow High Today {token}",
            due_date=date.today(),
            assignment_date=date.today(),
            effort_level=EffortLevel.HIGH,
        )

        response = _authed_client(viewer).post(
            "/assistant/chat",
            data={"message": f"does Marlow{token} have any tasks today?"},
        )

        assert response.status_code == 200
        titles = [item["title"] for item in response.json()["items"]]
        assert matching.title in titles
    finally:
        db.close()


def test_assistant_completed_today_uses_completion_date_not_due_date():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(db, email=f"complete-date-viewer-{token}@example.com", full_name="Complete Date Viewer", capacity=10)
        completed_today = _create_assigned_task(
            db,
            creator=viewer,
            assignee=viewer,
            title=f"Completed Today {token}",
            due_date=date.today() + timedelta(days=4),
            assignment_date=date.today() - timedelta(days=1),
            effort_level=EffortLevel.LOW,
        )
        due_today_completed_yesterday = _create_assigned_task(
            db,
            creator=viewer,
            assignee=viewer,
            title=f"Due Today Completed Yesterday {token}",
            due_date=date.today(),
            assignment_date=date.today(),
            effort_level=EffortLevel.LOW,
        )
        teammate = _create_user(db, email=f"complete-mate-{token}@example.com", full_name="Complete Mate", capacity=10)
        teammate_completed_today = _create_assigned_task(
            db,
            creator=viewer,
            assignee=teammate,
            title=f"Teammate Completed Today {token}",
            due_date=date.today() + timedelta(days=2),
            assignment_date=date.today(),
            effort_level=EffortLevel.LOW,
        )
        _complete_task_on(db, completed_today, date.today())
        _complete_task_on(db, due_today_completed_yesterday, date.today() - timedelta(days=1))
        _complete_task_on(db, teammate_completed_today, date.today())

        response = _authed_client(viewer).post(
            "/assistant/chat",
            data={"message": "show completed tasks from today"},
        )

        assert response.status_code == 200
        titles = [item["title"] for item in response.json()["items"]]
        assert completed_today.title in titles
        assert due_today_completed_yesterday.title not in titles

        finish_response = _authed_client(viewer).post(
            "/assistant/chat",
            data={"message": "what tasks did I finish today"},
        )

        assert finish_response.status_code == 200
        finish_titles = [item["title"] for item in finish_response.json()["items"]]
        assert completed_today.title in finish_titles
        assert due_today_completed_yesterday.title not in finish_titles

        team_response = _authed_client(viewer).post(
            "/assistant/chat",
            data={"message": "who completed tasks today"},
        )

        assert team_response.status_code == 200
        team_titles = [item["title"] for item in team_response.json()["items"]]
        assert teammate_completed_today.title in team_titles
        assert due_today_completed_yesterday.title not in team_titles
    finally:
        db.close()


def test_assistant_historical_have_tasks_uses_assignment_date_and_includes_completed():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(db, email=f"history-viewer-{token}@example.com", full_name="History Viewer", capacity=10)
        target_day = date.today() - timedelta(days=28)
        matching = _create_assigned_task(
            db,
            creator=viewer,
            assignee=viewer,
            title=f"Historical Assigned {token}",
            due_date=target_day + timedelta(days=3),
            assignment_date=target_day,
            effort_level=EffortLevel.MEDIUM,
        )
        due_only = _create_assigned_task(
            db,
            creator=viewer,
            assignee=viewer,
            title=f"Historical Due Only {token}",
            due_date=target_day,
            assignment_date=target_day + timedelta(days=1),
            effort_level=EffortLevel.MEDIUM,
        )
        _complete_task_on(db, matching, target_day + timedelta(days=1))

        response = _authed_client(viewer).post(
            "/assistant/chat",
            data={"message": f"what tasks did I have on {target_day.isoformat()}"},
        )

        assert response.status_code == 200
        titles = [item["title"] for item in response.json()["items"]]
        assert matching.title in titles
        assert due_only.title not in titles
    finally:
        db.close()


def test_assistant_completed_on_spoken_date_uses_completed_at():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(db, email=f"spoken-complete-viewer-{token}@example.com", full_name="Spoken Complete Viewer", capacity=10)
        completed_on = date.today() - timedelta(days=14)
        matching = _create_assigned_task(
            db,
            creator=viewer,
            assignee=viewer,
            title=f"Spoken Completed {token}",
            due_date=completed_on - timedelta(days=2),
            assignment_date=completed_on - timedelta(days=2),
            effort_level=EffortLevel.HIGH,
        )
        _complete_task_on(db, matching, completed_on)

        response = _authed_client(viewer).post(
            "/assistant/chat",
            data={"message": f"what did I complete on {completed_on.day}th of {completed_on.strftime('%B')}"},
        )

        assert response.status_code == 200
        assert response.json()["items"][0]["title"] == matching.title
    finally:
        db.close()


def test_assistant_task_search_is_personal_unless_team_requested():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        _complete_existing_active_tasks(db)
        token = uuid4().hex[:8]
        viewer = _create_user(db, email=f"personal-viewer-{token}@example.com", full_name="Personal Viewer", capacity=8)
        teammate = _create_user(db, email=f"personal-mate-{token}@example.com", full_name="Personal Mate", capacity=8)
        mine = _create_unassigned_task(
            db,
            creator=viewer,
            title=f"My Low {token}",
            due_date=date.today(),
            effort_level=EffortLevel.LOW,
        )
        teammate_task = _create_unassigned_task(
            db,
            creator=teammate,
            title=f"Team Low {token}",
            due_date=date.today(),
            effort_level=EffortLevel.LOW,
        )

        client = _authed_client(viewer)
        personal = client.post("/assistant/chat", data={"message": "list low tasks"})
        team = client.post("/assistant/chat", data={"message": "list team low tasks"})

        assert personal.status_code == 200
        personal_titles = [item["title"] for item in personal.json()["items"]]
        assert mine.title in personal_titles
        assert teammate_task.title not in personal_titles

        assert team.status_code == 200
        team_titles = [item["title"] for item in team.json()["items"]]
        assert mine.title in team_titles
        assert teammate_task.title in team_titles
    finally:
        db.close()


def test_assistant_unsupported_write_requests_stay_read_only():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(db, email=f"readonly-viewer-{token}@example.com", full_name="Readonly Viewer", capacity=8)

        response = _authed_client(viewer).post("/assistant/chat", data={"message": "create a task to clean the oven tomorrow"})

        assert response.status_code == 200
        payload = response.json()
        assert payload["items"] == []
        assert "Use Planner or the task form" in payload["reply"]

        broad_response = _authed_client(viewer).post("/assistant/chat", data={"message": "add cleaning chore tomorrow"})

        assert broad_response.status_code == 200
        broad_payload = broad_response.json()
        assert broad_payload["items"] == []
        assert "Use Planner or the task form" in broad_payload["reply"]

        complete_response = _authed_client(viewer).post("/assistant/chat", data={"message": "mark this task done"})

        assert complete_response.status_code == 200
        complete_payload = complete_response.json()
        assert complete_payload["items"] == []
        assert "Use Planner or the task form" in complete_payload["reply"]

        finish_response = _authed_client(viewer).post("/assistant/chat", data={"message": "complete the task"})

        assert finish_response.status_code == 200
        finish_payload = finish_response.json()
        assert finish_payload["items"] == []
        assert "Use Planner or the task form" in finish_payload["reply"]

        finish_tasks_response = _authed_client(viewer).post("/assistant/chat", data={"message": "finish tasks"})

        assert finish_tasks_response.status_code == 200
        finish_tasks_payload = finish_tasks_response.json()
        assert finish_tasks_payload["items"] == []
        assert "Use Planner or the task form" in finish_tasks_payload["reply"]

        mark_it_response = _authed_client(viewer).post("/assistant/chat", data={"message": "mark it done"})

        assert mark_it_response.status_code == 200
        mark_it_payload = mark_it_response.json()
        assert mark_it_payload["items"] == []
        assert "Use Planner or the task form" in mark_it_payload["reply"]
    finally:
        db.close()


def test_assistant_can_use_safe_ai_read_intent(monkeypatch):
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(db, email=f"ai-intent-viewer-{token}@example.com", full_name="AI Intent Viewer", capacity=8)
        low = _create_unassigned_task(
            db,
            creator=viewer,
            title=f"AI Parsed Low {token}",
            due_date=date.today(),
            effort_level=EffortLevel.LOW,
        )
        _create_unassigned_task(
            db,
            creator=viewer,
            title=f"AI Parsed High {token}",
            due_date=date.today(),
            effort_level=EffortLevel.HIGH,
        )

        def fake_parse(self, *, message, visible_members, today):
            _ = (self, message, visible_members, today)
            return {
                "intent": "list_tasks",
                "effort": "low",
                "status": "active",
                "date": None,
                "date_field": "either",
                "assignee": None,
                "confidence": 0.91,
            }

        monkeypatch.setattr(AIOrchestratorService, "parse_assistant_intent", fake_parse)

        response = _authed_client(viewer).post("/assistant/chat", data={"message": "which chores are tiny enough"})

        assert response.status_code == 200
        payload = response.json()
        titles = [item["title"] for item in payload["items"]]
        assert titles[0] == low.title
        assert all("High" not in title for title in titles)
    finally:
        db.close()


def test_assistant_ai_read_intent_can_filter_completed_date_and_partial_member(monkeypatch):
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(db, email=f"ai-completed-viewer-{token}@example.com", full_name="AI Completed Viewer", capacity=8)
        teammate = _create_user(db, email=f"ai-bethan-{token}@example.com", full_name=f"BethanAI{token} Smith", capacity=8)
        completed_day = date.today() - timedelta(days=2)
        matching = _create_assigned_task(
            db,
            creator=viewer,
            assignee=teammate,
            title=f"AI Completed Member {token}",
            due_date=completed_day + timedelta(days=5),
            assignment_date=completed_day - timedelta(days=1),
            effort_level=EffortLevel.LOW,
        )
        _complete_task_on(db, matching, completed_day)
        other = _create_assigned_task(
            db,
            creator=viewer,
            assignee=viewer,
            title=f"AI Completed Viewer {token}",
            due_date=completed_day,
            assignment_date=completed_day,
            effort_level=EffortLevel.LOW,
        )
        _complete_task_on(db, other, completed_day)

        def fake_parse(self, *, message, visible_members, today):
            _ = (self, message, visible_members, today)
            return {
                "intent": "list_tasks",
                "effort": None,
                "status": None,
                "date": completed_day.isoformat(),
                "date_field": "completed",
                "assignee": f"BethanAI{token}",
                "confidence": 0.92,
            }

        monkeypatch.setattr(AIOrchestratorService, "parse_assistant_intent", fake_parse)

        response = _authed_client(viewer).post("/assistant/chat", data={"message": "which chores got wrapped then"})

        assert response.status_code == 200
        titles = [item["title"] for item in response.json()["items"]]
        assert matching.title in titles
        assert other.title not in titles
    finally:
        db.close()


def test_assistant_reports_who_has_most_capacity_left():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        _clear_today_capacity_overrides(db)
        token = uuid4().hex[:8]
        viewer = _create_user(db, email=f"cap-viewer-{token}@example.com", full_name="Cap Viewer", capacity=6)
        teammate = _create_user(db, email=f"cap-mate-{token}@example.com", full_name="Cap Mate", capacity=30)
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


def test_assistant_capacity_query_uses_today_extra_capacity_override():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(db, email=f"cap-override-viewer-{token}@example.com", full_name="Override Viewer", capacity=6)
        teammate = _create_user(db, email=f"cap-override-mate-{token}@example.com", full_name="Override Mate", capacity=5)
        taken = _create_unassigned_task(
            db,
            creator=viewer,
            title=f"Override Load {token}",
            due_date=date.today(),
            effort_level=EffortLevel.LOW,
        )
        TaskService(db).assign_task(taken, assignee_id=teammate.id, assignment_date=date.today())
        WorkloadService(db).set_extra_capacity_points_range(
            user_id=teammate.id,
            start_date=date.today(),
            end_date=date.today(),
            extra_capacity_points=3,
        )

        client = _authed_client(viewer)
        response = client.post("/assistant/chat", data={"message": "who has enough capacity for one medium task?"})

        assert response.status_code == 200
        payload = response.json()
        assert any(item["title"] == "Override Mate" for item in payload["items"])
    finally:
        db.close()


def test_assistant_most_capacity_uses_today_extra_capacity_override():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        viewer = _create_user(db, email=f"most-cap-override-viewer-{token}@example.com", full_name="Most Cap Viewer", capacity=8)
        teammate = _create_user(db, email=f"most-cap-override-mate-{token}@example.com", full_name="Most Cap Mate", capacity=5)
        WorkloadService(db).set_extra_capacity_points(
            user_id=teammate.id,
            date_value=date.today(),
            extra_capacity_points=40,
        )

        client = _authed_client(viewer)
        response = client.post("/assistant/chat", data={"message": "who has the most capacity left?"})

        assert response.status_code == 200
        payload = response.json()
        assert payload["items"][0]["title"] == "Most Cap Mate"
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
        _complete_task_on(db, non_matching_status, date.today())

        client = _authed_client(viewer)
        response = client.post("/assistant/chat", data={"message": "show today's medium pending tasks"})

        assert response.status_code == 200
        payload = response.json()
        assert payload["items"][0]["title"] == matching.title
        assert all("Completed" not in item["title"] for item in payload["items"])

        not_completed_response = client.post("/assistant/chat", data={"message": "show not completed medium tasks today"})

        assert not_completed_response.status_code == 200
        not_completed_payload = not_completed_response.json()
        assert not_completed_payload["items"][0]["title"] == matching.title
        assert all("Completed" not in item["title"] for item in not_completed_payload["items"])
    finally:
        db.close()
