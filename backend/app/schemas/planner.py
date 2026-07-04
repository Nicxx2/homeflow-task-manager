from datetime import date

from pydantic import BaseModel, Field, field_validator


class PlannerMoveRequest(BaseModel):
    task_ids: list[int] = Field(min_length=1, max_length=50)
    assignment_date: date
    fingerprint: str | None = None
    add_extra_capacity: bool = False

    @field_validator("task_ids")
    @classmethod
    def task_ids_must_be_unique_and_positive(cls, values: list[int]) -> list[int]:
        unique_values = list(dict.fromkeys(values))
        if any(value <= 0 for value in unique_values):
            raise ValueError("Task IDs must be positive.")
        return unique_values
