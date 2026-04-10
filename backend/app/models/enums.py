from enum import StrEnum

from sqlalchemy import Enum as SAEnum


class EffortLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TaskStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


def _enum_values(enum_cls) -> list[str]:
    return [member.value for member in enum_cls]


effort_level_sa_enum = SAEnum(
    EffortLevel,
    name="effort_level",
    values_callable=_enum_values,
    native_enum=True,
    create_constraint=False,
)

task_status_sa_enum = SAEnum(
    TaskStatus,
    name="task_status",
    values_callable=_enum_values,
    native_enum=True,
    create_constraint=False,
)
