from datetime import date

from pydantic import BaseModel, Field, field_validator

from backend.app.models.enums import EffortLevel, TaskStatus


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    due_date: date
    effort_level: EffortLevel
    ai_suggested_level: EffortLevel | None = None
    ai_confidence: float | None = None
    ai_reason: str | None = None
    fallback_used: bool = False
    provider_used: str | None = None
    model_used: str | None = None


class TaskUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    due_date: date
    effort_level: EffortLevel
    status: TaskStatus = TaskStatus.PENDING


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

    model_config = {"from_attributes": True}
