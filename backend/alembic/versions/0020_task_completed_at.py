"""add task completion timestamp

Revision ID: 0020_task_completed_at
Revises: 0019_recurrence_late_behavior
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020_task_completed_at"
down_revision: Union[str, Sequence[str], None] = "0019_recurrence_late_behavior"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_tasks_completed_at", "tasks", ["completed_at"], unique=False)
    op.execute("UPDATE tasks SET completed_at = updated_at WHERE status = 'completed' AND completed_at IS NULL")


def downgrade() -> None:
    op.drop_index("ix_tasks_completed_at", table_name="tasks")
    op.drop_column("tasks", "completed_at")