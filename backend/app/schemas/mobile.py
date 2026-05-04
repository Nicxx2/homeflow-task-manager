from datetime import date as Date, datetime

from pydantic import BaseModel

from backend.app.models.enums import EffortLevel, TaskStatus


class MobileTaskRead(BaseModel):
    id: int
    title: str
    description: str
    status: TaskStatus
    due_date: Date
    assignment_date: Date | None
    assignee_id: int | None
    effort_level: EffortLevel
    points_value: int
    updated_at: datetime
    is_overdue: bool
    is_completed: bool
    display_bucket: str
    sort_key: str
    recurrence_parent_id: int | None = None
    recurrence_summary: str | None = None


class MobileTaskWindowResponse(BaseModel):
    server_time: datetime
    window_start: Date
    window_end: Date
    tasks: list[MobileTaskRead]


class MobileTaskStatusUpdateRequest(BaseModel):
    status: TaskStatus


class MobileTaskStatusUpdateResponse(BaseModel):
    server_time: datetime
    refresh_required: bool = False
    task: MobileTaskRead | None = None


class MobileTaskScheduleRequest(BaseModel):
    due_date: Date
    assignment_date: Date
    extend_capacity: bool = False


class MobileTaskScheduleFeedback(BaseModel):
    valid: bool
    message: str
    date: Date | None = None
    task_points: int | None = None
    current_points: int | None = None
    projected_points: int | None = None
    capacity: int | None = None
    is_past_date: bool = False
    task_too_large: bool = False
    blocked_by_policy: bool = False
    next_available_date: Date | None = None


class MobileTaskScheduleUpdateResponse(BaseModel):
    server_time: datetime
    task: MobileTaskRead
    feedback: MobileTaskScheduleFeedback


class MobileTaskNextAvailableResponse(BaseModel):
    ok: bool
    message: str
    assignment_date: Date | None = None
