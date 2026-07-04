from datetime import date, timedelta
from uuid import uuid4

from backend.app.db.base import Base
from backend.app.db.session import SessionLocal, engine
from backend.app.models.enums import EffortLevel, TaskStatus
from backend.app.models.task import Task
from backend.app.models.task_effort_config import TaskEffortConfig
from backend.app.models.user import User
from backend.app.models.user_daily_capacity import UserDailyCapacity
from backend.app.schemas.task import TaskCreate, TaskUpdate
from backend.app.services.recurring_task_service import RecurringTaskService
from backend.app.services.scheduling_service import SchedulingService
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


def test_assignment_larger_than_capacity_is_marked_impossible():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        creator = _create_user(db, f"phase3-creator6-{token}@example.com", 10)
        assignee = _create_user(db, f"phase3-assignee6-{token}@example.com", 6)
        day = date.today() + timedelta(days=6)

        task = _create_task(db, creator, EffortLevel.HIGH, "Oversized task", day)
        result = WorkloadService(db).validate_assignment(
            user_id=assignee.id,
            date_value=day,
            task_points=task.points_value,
        )

        assert result["valid"] is False
        assert result["task_too_large"] is True
        assert result["next_available_date"] is None
        assert "cannot be assigned on any day" in result["message"]
    finally:
        db.close()


def test_assignment_larger_than_base_capacity_can_still_fit_with_future_override():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        creator = _create_user(db, f"phase3-creator6b-{token}@example.com", 10)
        assignee = _create_user(db, f"phase3-assignee6b-{token}@example.com", 6)
        day = date.today() + timedelta(days=2)
        override_day = day + timedelta(days=3)

        WorkloadService(db).set_extra_capacity_points(
            user_id=assignee.id,
            date_value=override_day,
            extra_capacity_points=2,
        )

        task = _create_task(db, creator, EffortLevel.HIGH, "Oversized but override-capable task", day)
        result = WorkloadService(db).validate_assignment(
            user_id=assignee.id,
            date_value=day,
            task_points=task.points_value,
        )

        assert result["valid"] is False
        assert result["task_too_large"] is False
        assert result["next_available_date"] == override_day.isoformat()
    finally:
        db.close()


def test_assignment_in_past_is_rejected_and_suggests_current_slot():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        creator = _create_user(db, f"phase3-creator10-{token}@example.com", 10)
        assignee = _create_user(db, f"phase3-assignee10-{token}@example.com", 8)
        task = _create_task(db, creator, EffortLevel.LOW, "Past assignment", date.today())
        past_day = date.fromordinal(date.today().toordinal() - 1)

        result = WorkloadService(db).validate_assignment(
            user_id=assignee.id,
            date_value=past_day,
            task_points=task.points_value,
        )

        assert result["valid"] is False
        assert result["is_past_date"] is True
        assert result["message"] == "Assignment date cannot be in the past."
        assert result["next_available_date"] is not None
        assert date.fromisoformat(result["next_available_date"]) >= date.today()
    finally:
        db.close()


def test_suggest_next_available_date_skips_blocked_weekdays_and_away_periods():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        creator = _create_user(db, f"phase3-creator7-{token}@example.com", 10)
        assignee = _create_user(db, f"phase3-assignee7-{token}@example.com", 8)
        scheduling = SchedulingService(db)
        scheduling.update_preferences(
            user_id=assignee.id,
            allowed_days={
                "monday": True,
                "tuesday": True,
                "wednesday": True,
                "thursday": True,
                "friday": True,
                "saturday": False,
                "sunday": False,
            },
        )

        days_until_saturday = (5 - date.today().weekday()) % 7
        start = date.today() + timedelta(days=days_until_saturday)
        monday = start + timedelta(days=2)
        tuesday = start + timedelta(days=3)
        wednesday = start + timedelta(days=4)
        scheduling.add_away_period(
            user_id=assignee.id,
            start_date=tuesday,
            end_date=tuesday,
            note="Away Tuesday",
        )

        monday_full = _create_task(db, creator, EffortLevel.HIGH, "Monday full", monday)
        TaskService(db).assign_task(monday_full, assignee_id=assignee.id, assignment_date=monday)

        task = _create_task(db, creator, EffortLevel.LOW, "Blocked start", start)
        suggestion = WorkloadService(db).suggest_next_available_date(
            user_id=assignee.id,
            task_points=task.points_value,
            start_date=start,
            max_days=7,
        )

        assert suggestion == wednesday
    finally:
        db.close()

def test_future_lookup_does_not_delete_upcoming_away_period():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        assignee = _create_user(db, f"phase3-assignee-away-{token}@example.com", 8)
        scheduling = SchedulingService(db)
        start = date.today() + timedelta(days=2)
        end = start + timedelta(days=1)

        scheduling.add_away_period(
            user_id=assignee.id,
            start_date=start,
            end_date=end,
            note="Upcoming trip",
        )

        future_check = end + timedelta(days=7)
        assert scheduling.get_block_for_date(user_id=assignee.id, date_value=future_check) is None

        periods = scheduling.list_away_periods(assignee.id)
        assert len(periods) == 1
        assert periods[0].start_date == start
        assert periods[0].end_date == end

        block = scheduling.get_block_for_date(user_id=assignee.id, date_value=start)
        assert block is not None
        assert block["type"] == "away"
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


def test_weekly_recurring_task_rolls_forward_with_single_active_task():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        creator = _create_user(db, f"phase3-creator8-{token}@example.com", 10)
        assignee = _create_user(db, f"phase3-assignee8-{token}@example.com", 10)
        first_due = date.today() + timedelta(days=7)
        blocked_due = first_due + timedelta(weeks=1)
        scheduling = SchedulingService(db)
        scheduling.add_away_period(
            user_id=assignee.id,
            start_date=blocked_due,
            end_date=blocked_due,
            note="Away on recurring day",
        )

        payload = TaskCreate(
            title="Weekly bins",
            description="Take bins out",
            due_date=first_due,
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
            recurrence_blocked_behavior="move_same_week",
        )
        root = TaskService(db).create_unassigned_task(payload, creator)
        TaskService(db).assign_task(root, assignee_id=assignee.id, assignment_date=root.due_date)

        service = TaskService(db)
        service.update_status(root, TaskStatus.COMPLETED)
        db.refresh(root)

        assert root.status == TaskStatus.PENDING
        assert root.due_date == blocked_due + timedelta(days=1)
        assert root.assignment_date == blocked_due + timedelta(days=1)

        history = RecurringTaskService(db).get_history(root.id)
        assert len(history) == 1
        assert history[0].due_date == first_due

        service.update_status(root, TaskStatus.COMPLETED)
        db.refresh(root)

        assert root.status == TaskStatus.PENDING
        assert root.due_date == first_due + timedelta(weeks=2)
        assert root.assignment_date == first_due + timedelta(weeks=2)

        history = RecurringTaskService(db).get_history(root.id)
        assert [item.due_date for item in reversed(history)] == [
            first_due,
            blocked_due + timedelta(days=1),
        ]
    finally:
        db.close()

def test_weekly_recurring_task_skip_blocked_day_counts_skipped_occurrence_once():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        creator = _create_user(db, f"phase3-creator8b-{token}@example.com", 10)
        assignee = _create_user(db, f"phase3-assignee8b-{token}@example.com", 10)
        first_due = date.today() + timedelta(days=7)
        blocked_due = first_due + timedelta(weeks=1)
        scheduling = SchedulingService(db)
        scheduling.add_away_period(
            user_id=assignee.id,
            start_date=blocked_due,
            end_date=blocked_due,
            note="Away on recurring day",
        )

        payload = TaskCreate(
            title="Weekly recycling",
            description="Put recycling out",
            due_date=first_due,
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
        )
        root = TaskService(db).create_unassigned_task(payload, creator)
        TaskService(db).assign_task(root, assignee_id=assignee.id, assignment_date=root.due_date)

        service = TaskService(db)
        service.update_status(root, TaskStatus.COMPLETED)
        db.refresh(root)

        recurring = RecurringTaskService(db)
        assert root.status == TaskStatus.PENDING
        assert root.due_date == first_due + timedelta(weeks=2)
        assert root.assignment_date == first_due + timedelta(weeks=2)
        assert root.recurrence_occurrence_index == 2
        assert recurring.remaining_count_limit_occurrences(root) == 2
        assert recurring.preview_next_occurrence(root)["due_date"] == first_due + timedelta(weeks=3)
    finally:
        db.close()

def test_recurring_sync_removes_legacy_future_occurrences():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        creator = _create_user(db, f"phase3-creator9-{token}@example.com", 10)
        root = _create_task(db, creator, EffortLevel.LOW, "Legacy recurring", date(2026, 4, 8))
        root.recurrence_pattern = "weekly"
        root.recurrence_interval_weeks = 1
        root.recurrence_anchor_date = date(2026, 4, 8)
        db.add(root)
        db.commit()

        legacy_child = Task(
            title=root.title,
            description=root.description,
            due_date=date(2026, 4, 15),
            assignment_date=None,
            assignee_id=None,
            created_by_id=root.created_by_id,
            effort_level=root.effort_level,
            points_value=root.points_value,
            status=TaskStatus.PENDING,
            recurrence_parent_id=root.id,
        )
        db.add(legacy_child)
        db.commit()

        removed = RecurringTaskService(db).sync()
        remaining = db.query(Task).filter(Task.recurrence_parent_id == root.id).all()

        assert removed == 1
        assert remaining == []
    finally:
        db.close()


def test_editing_recurring_task_preserves_progress_and_remaining_count_limit():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        creator = _create_user(db, f"phase3-creator10-{token}@example.com", 10)
        initial_due = date.today() + timedelta(days=7)
        current_due = initial_due + timedelta(weeks=4)
        edited_due = current_due + timedelta(days=3)
        next_due = edited_due + timedelta(weeks=1)

        payload = TaskCreate(
            title="Shift recurring weekday",
            description="Recurring edit coverage",
            due_date=initial_due,
            effort_level=EffortLevel.LOW,
            ai_suggested_level=EffortLevel.LOW,
            ai_confidence=0.7,
            ai_reason="test",
            fallback_used=False,
            provider_used="rules",
            model_used="rules-default",
            recurrence_pattern="weekly",
            recurrence_interval_weeks=1,
            recurrence_count_limit=10,
            recurrence_blocked_behavior="skip",
        )
        root = TaskService(db).create_unassigned_task(payload, creator)

        root.due_date = current_due
        root.recurrence_occurrence_index = 4
        db.add(root)
        db.commit()
        db.refresh(root)

        service = TaskService(db)
        service.update_task(
            root,
            TaskUpdate(
                title=root.title,
                description=root.description,
                due_date=edited_due,
                effort_level=root.effort_level,
                status=root.status,
                recurrence_pattern="weekly",
                recurrence_interval_weeks=1,
                recurrence_count_limit=10,
                recurrence_blocked_behavior="skip",
            ),
            recurrence_series_due_date=next_due,
        )
        db.refresh(root)

        recurring = RecurringTaskService(db)
        assert root.due_date == edited_due
        assert root.recurrence_anchor_date == edited_due - timedelta(weeks=4)
        assert recurring.current_occurrence_index(root) == 4
        assert recurring.remaining_count_limit_occurrences(root) == 6
        assert recurring.preview_next_occurrence(root)["due_date"] == next_due
    finally:
        db.close()

def test_rescheduling_current_recurring_occurrence_does_not_move_future_series():
    db = SessionLocal()
    try:
        _ensure_effort_config(db)
        token = uuid4().hex[:8]
        creator = _create_user(db, f"phase3-creator11-{token}@example.com", 10)
        initial_due = date.today() + timedelta(days=7)
        current_due = initial_due + timedelta(weeks=4)

        payload = TaskCreate(
            title="Recurring one-off move",
            description="Current occurrence scheduling coverage",
            due_date=initial_due,
            effort_level=EffortLevel.LOW,
            ai_suggested_level=EffortLevel.LOW,
            ai_confidence=0.7,
            ai_reason="test",
            fallback_used=False,
            provider_used="rules",
            model_used="rules-default",
            recurrence_pattern="weekly",
            recurrence_interval_weeks=1,
            recurrence_count_limit=10,
            recurrence_blocked_behavior="skip",
        )
        root = TaskService(db).create_unassigned_task(payload, creator)
        root.due_date = current_due
        root.recurrence_occurrence_index = 4
        db.add(root)
        db.commit()
        db.refresh(root)

        service = TaskService(db)
        service.update_task_schedule(
            root,
            due_date=current_due + timedelta(days=2),
            assignee_id=None,
            assignment_date=None,
        )
        db.refresh(root)

        recurring = RecurringTaskService(db)
        assert root.due_date == current_due + timedelta(days=2)
        assert recurring.current_occurrence_index(root) == 4
        assert recurring.preview_next_occurrence(root)["due_date"] == initial_due + timedelta(weeks=5)
    finally:
        db.close()
