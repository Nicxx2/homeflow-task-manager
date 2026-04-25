from datetime import date

from pydantic import BaseModel, Field, field_validator

from backend.app.models.enums import EffortLevel, TaskStatus


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    due_date: date
    effort_level: EffortLevel
    ai_suggested_level: EffortLevel | None = None
    ai_confidence: float | None = None
    ai_reason: str | None = None
    fallback_used: bool = False
    provider_used: str | None = None
    model_used: str | None = None
    recurrence_pattern: str | None = None
    recurrence_interval_weeks: int | None = None
    recurrence_until: date | None = None
    recurrence_count_limit: int | None = None
    recurrence_blocked_behavior: str | None = None

    @field_validator("recurrence_interval_weeks", "recurrence_count_limit")
    @classmethod
    def recurrence_values_must_be_positive(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("Recurring task values must be positive.")
        return value

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        selected = value.strip()
        if not selected:
            raise ValueError("Title is required.")
        return selected

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value: str | None) -> str:
        return (value or "").strip()


class TaskUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    due_date: date
    effort_level: EffortLevel
    status: TaskStatus = TaskStatus.PENDING
    recurrence_pattern: str | None = None
    recurrence_interval_weeks: int | None = None
    recurrence_until: date | None = None
    recurrence_count_limit: int | None = None
    recurrence_blocked_behavior: str | None = None

    @field_validator("recurrence_interval_weeks", "recurrence_count_limit")
    @classmethod
    def recurrence_values_must_be_positive(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("Recurring task values must be positive.")
        return value

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        selected = value.strip()
        if not selected:
            raise ValueError("Title is required.")
        return selected

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value: str | None) -> str:
        return (value or "").strip()


class TaskAssignRequest(BaseModel):
    assignee_id: int
    assignment_date: date

    @field_validator("assignee_id")
    @classmethod
    def assignee_id_must_be_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("assignee_id must be positive.")
        return value


class TaskRead(BaseModel):
    id: int
    title: str
    description: str
    due_date: date
    assignment_date: date | None
    assignee_id: int | None
    created_by_id: int
    effort_level: EffortLevel
    points_value: int
    status: TaskStatus
    ai_suggested_level: EffortLevel | None
    ai_confidence: float | None
    ai_reason: str | None
    ai_provider_used: str | None = None
    ai_model_used: str | None = None
    fallback_used: bool
    recurrence_pattern: str | None = None
    recurrence_interval_weeks: int | None = None
    recurrence_until: date | None = None
    recurrence_count_limit: int | None = None
    recurrence_blocked_behavior: str | None = None
    recurrence_parent_id: int | None = None
    recurrence_anchor_date: date | None = None

    model_config = {"from_attributes": True}
