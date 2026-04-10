from datetime import date, datetime

from pydantic import BaseModel

from backend.app.models.enums import EffortLevel, TaskStatus


class MobileTaskRead(BaseModel):
    id: int
    title: str
    description: str
    status: TaskStatus
    due_date: date
    assignment_date: date | None
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
    window_start: date
    window_end: date
    tasks: list[MobileTaskRead]


class MobileTaskStatusUpdateRequest(BaseModel):
    status: TaskStatus


class MobileTaskStatusUpdateResponse(BaseModel):
    server_time: datetime
    refresh_required: bool = False
    task: MobileTaskRead | None = None
