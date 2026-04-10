"""add task category button appearance preferences

Revision ID: 0011_task_cat_btn_prefs
Revises: 0010_user_task_display_prefs
Create Date: 2026-04-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011_task_cat_btn_prefs"
down_revision: Union[str, Sequence[str], None] = "0010_user_task_display_prefs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("task_category_button_color_mode", sa.String(length=20), server_default="match", nullable=False),
    )
    op.add_column(
        "users",
        sa.Column("task_category_overdue_color", sa.String(length=7), server_default="#dc2626", nullable=False),
    )
    op.add_column(
        "users",
        sa.Column("task_category_up_next_color", sa.String(length=7), server_default="#4f46e5", nullable=False),
    )
    op.add_column(
        "users",
        sa.Column("task_category_later_color", sa.String(length=7), server_default="#0f766e", nullable=False),
    )
    op.add_column(
        "users",
        sa.Column("task_category_unassigned_color", sa.String(length=7), server_default="#475569", nullable=False),
    )
    op.add_column(
        "users",
        sa.Column("task_category_in_progress_color", sa.String(length=7), server_default="#d97706", nullable=False),
    )
    op.add_column(
        "users",
        sa.Column("task_category_completed_color", sa.String(length=7), server_default="#64748b", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("users", "task_category_completed_color")
    op.drop_column("users", "task_category_in_progress_color")
    op.drop_column("users", "task_category_unassigned_color")
    op.drop_column("users", "task_category_later_color")
    op.drop_column("users", "task_category_up_next_color")
    op.drop_column("users", "task_category_overdue_color")
    op.drop_column("users", "task_category_button_color_mode")
