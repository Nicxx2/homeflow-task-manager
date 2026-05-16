from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from backend.app.db.base import Base
from backend.app.db.session import SessionLocal, engine
from backend.app.models.enums import EffortLevel
from backend.app.models.task_effort_config import TaskEffortConfig
from backend.app.models.user import User
from backend.app.schemas.task import TaskCreate, TaskUpdate
from backend.app.services.ai_service import AIService
from backend.app.services.task_service import TaskService


def setup_module():
    Base.metadata.create_all(bind=engine)


def test_task_create_requires_effort_level():
    with pytest.raises(ValidationError):
        TaskCreate(
            title="Task",
            description="Desc",
            due_date=date.today() + timedelta(days=1),
            # effort_level intentionally missing
        )


def test_task_create_rejects_unsupported_recurrence_values():
    with pytest.raises(ValidationError):
        TaskCreate(
            title="Task",
            description="Desc",
            due_date=date.today() + timedelta(days=1),
            effort_level=EffortLevel.LOW,
            recurrence_pattern="monthly",
        )

    with pytest.raises(ValidationError):
        TaskCreate(
            title="Task",
            description="Desc",
            due_date=date.today() + timedelta(days=1),
            effort_level=EffortLevel.LOW,
            recurrence_pattern="weekly",
            recurrence_blocked_behavior="next_best_day",
        )


def test_task_update_rejects_unsupported_recurrence_values():
    with pytest.raises(ValidationError):
        TaskUpdate(
            title="Task",
            description="Desc",
            due_date=date.today() + timedelta(days=1),
            effort_level=EffortLevel.LOW,
            recurrence_pattern="daily",
        )


def test_create_unassigned_task_with_points_from_config():
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "phase2-user@example.com").first()
        if not user:
            user = User(email="phase2-user@example.com", full_name="Phase2 User", hashed_password="x")
            db.add(user)
        for level, points in (
            (EffortLevel.LOW, 2),
            (EffortLevel.MEDIUM, 5),
            (EffortLevel.HIGH, 8),
        ):
            item = db.get(TaskEffortConfig, level)
            if not item:
                db.add(TaskEffortConfig(level=level, points_value=points))
        db.commit()
        db.refresh(user)

        service = TaskService(db)
        payload = TaskCreate(
            title="Prepare weekly groceries",
            description="Create a list and organize pickup.",
            due_date=date.today() + timedelta(days=2),
            effort_level=EffortLevel.MEDIUM,
            ai_suggested_level=EffortLevel.MEDIUM,
            ai_confidence=0.74,
            ai_reason="Simulated",
            fallback_used=False,
            provider_used="rules",
            model_used="rules-default",
        )
        task = service.create_unassigned_task(payload, user)
        assert task.assignee_id is None
        assert task.points_value == 5
        assert task.effort_level == EffortLevel.MEDIUM
    finally:
        db.close()


def test_ai_service_simulation_returns_required_shape():
    result = AIService().classify_task("Quick cleanup", "Wipe kitchen counters and floor.")
    assert result["suggested_level"] in {EffortLevel.LOW, EffortLevel.MEDIUM, EffortLevel.HIGH}
    assert isinstance(result["confidence"], float)
    assert isinstance(result["reason"], str)
    assert result["simulated"] is True
