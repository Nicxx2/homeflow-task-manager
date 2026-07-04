"""add recurring late-completion behavior

Revision ID: 0019_recurrence_late_behavior
Revises: 0018_remembered_devices
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019_recurrence_late_behavior"
down_revision: Union[str, Sequence[str], None] = "0018_remembered_devices"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("recurrence_late_behavior", sa.String(length=30), nullable=True))
    op.execute(
        "UPDATE tasks SET recurrence_late_behavior = 'keep_schedule' "
        "WHERE recurrence_pattern = 'weekly' AND recurrence_parent_id IS NULL"
    )


def downgrade() -> None:
    op.drop_column("tasks", "recurrence_late_behavior")
