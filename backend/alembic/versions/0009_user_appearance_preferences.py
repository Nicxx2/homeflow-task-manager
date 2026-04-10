"""add user appearance preferences

Revision ID: 0009_user_appearance_preferences
Revises: 0008_task_recurrence
Create Date: 2026-04-08
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009_user_appearance_preferences"
down_revision: Union[str, Sequence[str], None] = "0008_task_recurrence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("accent_color", sa.String(length=7), server_default="#4f46e5", nullable=False))
    op.add_column("users", sa.Column("overdue_color", sa.String(length=7), server_default="#dc2626", nullable=False))
    op.add_column("users", sa.Column("recurring_color", sa.String(length=7), server_default="#0f766e", nullable=False))
    op.add_column(
        "users",
        sa.Column("in_progress_color", sa.String(length=7), server_default="#d97706", nullable=False),
    )
    op.add_column("users", sa.Column("unassigned_color", sa.String(length=7), server_default="#475569", nullable=False))
    op.add_column("users", sa.Column("surface_style", sa.String(length=20), server_default="clean", nullable=False))
    op.add_column(
        "users",
        sa.Column("density_preference", sa.String(length=20), server_default="comfortable", nullable=False),
    )
    op.add_column("users", sa.Column("decoration_style", sa.String(length=20), server_default="none", nullable=False))


def downgrade() -> None:
    op.drop_column("users", "decoration_style")
    op.drop_column("users", "density_preference")
    op.drop_column("users", "surface_style")
    op.drop_column("users", "unassigned_color")
    op.drop_column("users", "in_progress_color")
    op.drop_column("users", "recurring_color")
    op.drop_column("users", "overdue_color")
    op.drop_column("users", "accent_color")
