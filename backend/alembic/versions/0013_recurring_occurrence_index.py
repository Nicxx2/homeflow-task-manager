"""track recurring task occurrence position

Revision ID: 0013_recurring_occurrence_index
Revises: 0012_daily_cap_overrides
Create Date: 2026-04-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013_recurring_occurrence_index"
down_revision: Union[str, Sequence[str], None] = "0012_daily_cap_overrides"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("recurrence_occurrence_index", sa.Integer(), nullable=True, server_default="0"))
    op.execute(
        """
        UPDATE tasks
        SET recurrence_occurrence_index = CASE
            WHEN recurrence_pattern = 'weekly' AND recurrence_parent_id IS NULL THEN
                GREATEST(
                    ((due_date - COALESCE(recurrence_anchor_date, due_date)) / GREATEST(COALESCE(recurrence_interval_weeks, 1) * 7, 1)),
                    0
                )
            ELSE NULL
        END
        """
    )


def downgrade() -> None:
    op.drop_column("tasks", "recurrence_occurrence_index")
