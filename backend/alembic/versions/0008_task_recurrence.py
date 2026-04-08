"""add recurring task fields

Revision ID: 0008_task_recurrence
Revises: 0007_user_scheduling_preferences
Create Date: 2026-04-08
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008_task_recurrence"
down_revision: Union[str, Sequence[str], None] = "0007_user_scheduling_preferences"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("recurrence_pattern", sa.String(length=20), nullable=True))
    op.add_column("tasks", sa.Column("recurrence_interval_weeks", sa.Integer(), nullable=True))
    op.add_column("tasks", sa.Column("recurrence_until", sa.Date(), nullable=True))
    op.add_column("tasks", sa.Column("recurrence_count_limit", sa.Integer(), nullable=True))
    op.add_column("tasks", sa.Column("recurrence_blocked_behavior", sa.String(length=30), nullable=True))
    op.add_column("tasks", sa.Column("recurrence_parent_id", sa.Integer(), nullable=True))
    op.add_column("tasks", sa.Column("recurrence_anchor_date", sa.Date(), nullable=True))

    op.create_index("ix_tasks_recurrence_pattern", "tasks", ["recurrence_pattern"])
    op.create_index("ix_tasks_recurrence_parent_id", "tasks", ["recurrence_parent_id"])
    op.create_foreign_key(
        "fk_tasks_recurrence_parent_id_tasks",
        "tasks",
        "tasks",
        ["recurrence_parent_id"],
        ["id"],
    )
    op.create_check_constraint(
        "ck_tasks_recurrence_interval_positive",
        "tasks",
        "(recurrence_interval_weeks IS NULL) OR (recurrence_interval_weeks > 0)",
    )
    op.create_check_constraint(
        "ck_tasks_recurrence_count_positive",
        "tasks",
        "(recurrence_count_limit IS NULL) OR (recurrence_count_limit > 0)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_tasks_recurrence_count_positive", "tasks", type_="check")
    op.drop_constraint("ck_tasks_recurrence_interval_positive", "tasks", type_="check")
    op.drop_constraint("fk_tasks_recurrence_parent_id_tasks", "tasks", type_="foreignkey")
    op.drop_index("ix_tasks_recurrence_parent_id", table_name="tasks")
    op.drop_index("ix_tasks_recurrence_pattern", table_name="tasks")
    op.drop_column("tasks", "recurrence_anchor_date")
    op.drop_column("tasks", "recurrence_parent_id")
    op.drop_column("tasks", "recurrence_blocked_behavior")
    op.drop_column("tasks", "recurrence_count_limit")
    op.drop_column("tasks", "recurrence_until")
    op.drop_column("tasks", "recurrence_interval_weeks")
    op.drop_column("tasks", "recurrence_pattern")
