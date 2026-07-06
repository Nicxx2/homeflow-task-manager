from datetime import date

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.app.models.enums import EffortLevel


class PlannerMoveOutRequest(BaseModel):
    task_id: int
    assignment_date: date

    @field_validator("task_id")
    @classmethod
    def task_id_must_be_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("Task ID must be positive.")
        return value


class PlannerMoveRequest(BaseModel):
    task_ids: list[int] = Field(min_length=1, max_length=50)
    assignment_date: date
    fingerprint: str | None = None
    add_extra_capacity: bool = False
    move_out: list[PlannerMoveOutRequest] = Field(default_factory=list, max_length=50)

    @field_validator("task_ids")
    @classmethod
    def task_ids_must_be_unique_and_positive(cls, values: list[int]) -> list[int]:
        unique_values = list(dict.fromkeys(values))
        if any(value <= 0 for value in unique_values):
            raise ValueError("Task IDs must be positive.")
        return unique_values

    @field_validator("move_out")
    @classmethod
    def move_out_tasks_must_be_unique(cls, values: list[PlannerMoveOutRequest]) -> list[PlannerMoveOutRequest]:
        seen = set()
        unique_values = []
        for item in values:
            if item.task_id in seen:
                continue
            seen.add(item.task_id)
            unique_values.append(item)
        return unique_values


class PlannerTaskCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=5000)
    due_date: date | None = None
    assignment_date: date
    effort_level: EffortLevel
    assignee_id: int | None = None
    add_extra_capacity: bool = False
    repeat_weekly: bool = False
    recurrence_interval_weeks: int = 1
    recurrence_until: date | None = None
    recurrence_count_limit: int | None = None
    recurrence_blocked_behavior: str = "skip"
    recurrence_late_behavior: str = "keep_schedule"

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Task title is required.")
        return stripped

    @field_validator("assignee_id")
    @classmethod
    def assignee_must_be_positive(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("Assignee ID must be positive.")
        return value

    @field_validator("recurrence_interval_weeks", "recurrence_count_limit")
    @classmethod
    def recurrence_numbers_must_be_positive(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("Recurring task values must be positive.")
        return value

    @field_validator("recurrence_blocked_behavior")
    @classmethod
    def recurrence_blocked_behavior_must_be_supported(cls, value: str) -> str:
        if value not in {"skip", "move_same_week"}:
            raise ValueError("Invalid recurring blocked-date behavior.")
        return value

    @field_validator("recurrence_late_behavior")
    @classmethod
    def recurrence_late_behavior_must_be_supported(cls, value: str) -> str:
        if value not in {"keep_schedule", "from_completion"}:
            raise ValueError("Invalid late-completion behavior.")
        return value

    @model_validator(mode="after")
    def recurring_end_must_not_precede_start(self) -> "PlannerTaskCreateRequest":
        due_date = self.assignment_date
        if self.repeat_weekly and self.recurrence_until is not None and self.recurrence_until < due_date:
            raise ValueError("Recurring end date cannot be before the first task date.")
        return self