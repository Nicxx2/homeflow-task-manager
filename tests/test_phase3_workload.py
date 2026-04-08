from datetime import date, timedelta
from uuid import uuid4

from backend.app.db.base import Base
from backend.app.db.session import SessionLocal, engine
from backend.app.models.enums import EffortLevel, TaskStatus
from backend.app.models.task import Task
from backend.app.models.task_effort_config import TaskEffortConfig
from backend.app.models.user import User
from backend.app.models.user_daily_capacity import UserDailyCapacity
from backend.app.schemas.task import TaskCreate
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


def _create_user(db, email: str, capacity: int) -> User:
    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(email=email, full_name=email.split("@")[0], hashed_password="x")
        db.add(user)
        db.commit()
        db.refresh(user)
    cap = db.get(UserDailyCapacity, user.id)
    if cap:
        cap.daily_capacity_points = capacity
    else:
        db.add(UserDailyCapacity(user_id=user.id, daily_capacity_points=capacity))
    db.commit()
    return user


def _create_task(db, creator: User, level: EffortLevel, title: str, due: date) -> Task:
    payload = TaskCreate(
        title=title,
        description="Task description",
        due_date=due,
        effort_level=level,
        ai_suggested_level=level,
        ai_confidence=0.7,
        ai_reason="test",
        fallback_used=False,
        provider_used="rules",
        model_used="rules-default",
    )
    return TaskService(db).create_unassigned_task(payload, creator)


def test_assignment_within_capacity_succeeds():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        creator = _create_user(db, f"phase3-creator1-{token}@example.com", 10)
        assignee = _create_user(db, f"phase3-assignee1-{token}@example.com", 8)
        day = date.today() + timedelta(days=1)

        task = _create_task(db, creator, EffortLevel.MEDIUM, "Task A", day)
        result = WorkloadService(db).validate_assignment(user_id=assignee.id, date_value=day, task_points=task.points_value)
        assert result["valid"] is True
        TaskService(db).assign_task(task, assignee_id=assignee.id, assignment_date=day)
    finally:
        db.close()


def test_assignment_over_capacity_is_blocked_and_suggests_date():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        creator = _create_user(db, f"phase3-creator2-{token}@example.com", 10)
        assignee = _create_user(db, f"phase3-assignee2-{token}@example.com", 6)
        day = date.today() + timedelta(days=2)

        existing = _create_task(db, creator, EffortLevel.MEDIUM, "Existing load", day)  # 5 points
        TaskService(db).assign_task(existing, assignee_id=assignee.id, assignment_date=day)

        new_task = _create_task(db, creator, EffortLevel.MEDIUM, "New load", day)  # +5 => 10 > 6
        result = WorkloadService(db).validate_assignment(user_id=assignee.id, date_value=day, task_points=new_task.points_value)
        assert result["valid"] is False
        assert result["current_points"] == 5
        assert result["projected_points"] == 10
        assert result["capacity"] == 6
        assert result["next_available_date"] is not None
        ok, _ = TaskService(db).assign_task_with_validation(new_task, assignee_id=assignee.id, assignment_date=day)
        assert ok is False
        assert new_task.assignee_id is None
        assert new_task.assignment_date is None
    finally:
        db.close()


def test_suggest_next_available_date_finds_future_slot():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        creator = _create_user(db, f"phase3-creator3-{token}@example.com", 10)
        assignee = _create_user(db, f"phase3-assignee3-{token}@example.com", 5)
        start = date.today() + timedelta(days=3)

        full_task = _create_task(db, creator, EffortLevel.MEDIUM, "Full day", start)
        TaskService(db).assign_task(full_task, assignee_id=assignee.id, assignment_date=start)

        suggestion = WorkloadService(db).suggest_next_available_date(
            user_id=assignee.id,
            task_points=2,
            start_date=start,
            max_days=30,
        )
        assert suggestion is not None
        assert suggestion > start
    finally:
        db.close()


def test_validate_assignment_exclude_task_id_allows_reassignment_check():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        creator = _create_user(db, f"phase3-creator4-{token}@example.com", 10)
        assignee = _create_user(db, f"phase3-assignee4-{token}@example.com", 5)
        day = date.today() + timedelta(days=4)

        task = _create_task(db, creator, EffortLevel.MEDIUM, "Same task", day)
        TaskService(db).assign_task(task, assignee_id=assignee.id, assignment_date=day)

        result = WorkloadService(db).validate_assignment(
            user_id=assignee.id,
            date_value=day,
            task_points=task.points_value,
            exclude_task_id=task.id,
        )
        assert result["valid"] is True
        assert result["current_points"] == 0
    finally:
        db.close()


def test_get_daily_points_includes_completed_tasks():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        creator = _create_user(db, f"phase3-creator5-{token}@example.com", 10)
        assignee = _create_user(db, f"phase3-assignee5-{token}@example.com", 20)
        day = date.today() + timedelta(days=5)

        active = _create_task(db, creator, EffortLevel.LOW, "Active", day)  # 2
        done = _create_task(db, creator, EffortLevel.MEDIUM, "Done", day)  # 5
        task_service = TaskService(db)
        task_service.assign_task(active, assignee_id=assignee.id, assignment_date=day)
        task_service.assign_task(done, assignee_id=assignee.id, assignment_date=day)
        done.status = TaskStatus.COMPLETED
        db.add(done)
        db.commit()

        points = WorkloadService(db).get_daily_points(user_id=assignee.id, date_value=day)
        assert points == 7
    finally:
        db.close()
