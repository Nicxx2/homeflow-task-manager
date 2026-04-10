"""add user task display preferences

Revision ID: 0010_user_task_display_prefs
Revises: 0009_user_appearance_preferences
Create Date: 2026-04-08
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010_user_task_display_prefs"
down_revision: Union[str, Sequence[str], None] = "0009_user_appearance_preferences"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_task_display_preferences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("highlight_color", sa.String(length=7), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "task_id", name="uq_user_task_display_preferences_user_task"),
    )
    op.create_index(
        op.f("ix_user_task_display_preferences_task_id"),
        "user_task_display_preferences",
        ["task_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_user_task_display_preferences_user_id"),
        "user_task_display_preferences",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_user_task_display_preferences_user_id"), table_name="user_task_display_preferences")
    op.drop_index(op.f("ix_user_task_display_preferences_task_id"), table_name="user_task_display_preferences")
    op.drop_table("user_task_display_preferences")
