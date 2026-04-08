"""add user scheduling preferences and away periods

Revision ID: 0007_user_scheduling_preferences
Revises: 0006_user_approval_visibility
Create Date: 2026-04-08
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007_user_scheduling_preferences"
down_revision: Union[str, Sequence[str], None] = "0006_user_approval_visibility"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_scheduling_preferences",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("allow_monday", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("allow_tuesday", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("allow_wednesday", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("allow_thursday", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("allow_friday", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("allow_saturday", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("allow_sunday", sa.Boolean(), nullable=False, server_default="true"),
        sa.PrimaryKeyConstraint("user_id"),
    )

    op.create_table(
        "user_away_periods",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("end_date >= start_date", name="ck_user_away_periods_date_range"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_away_periods_user_id", "user_away_periods", ["user_id"])
    op.create_index("ix_user_away_periods_start_date", "user_away_periods", ["start_date"])
    op.create_index("ix_user_away_periods_end_date", "user_away_periods", ["end_date"])


def downgrade() -> None:
    op.drop_index("ix_user_away_periods_end_date", table_name="user_away_periods")
    op.drop_index("ix_user_away_periods_start_date", table_name="user_away_periods")
    op.drop_index("ix_user_away_periods_user_id", table_name="user_away_periods")
    op.drop_table("user_away_periods")
    op.drop_table("user_scheduling_preferences")
