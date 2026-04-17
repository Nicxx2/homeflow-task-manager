"""add user daily capacity overrides

Revision ID: 0012_daily_cap_overrides
Revises: 0011_task_cat_btn_prefs
Create Date: 2026-04-16
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012_daily_cap_overrides"
down_revision: Union[str, Sequence[str], None] = "0011_task_cat_btn_prefs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_daily_capacity_overrides",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("override_date", sa.Date(), nullable=False),
        sa.Column("extra_capacity_points", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("extra_capacity_points >= 0", name="ck_user_daily_capacity_override_nonnegative"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id", "override_date"),
    )
    op.create_index(
        op.f("ix_user_daily_capacity_overrides_override_date"),
        "user_daily_capacity_overrides",
        ["override_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_user_daily_capacity_overrides_override_date"), table_name="user_daily_capacity_overrides")
    op.drop_table("user_daily_capacity_overrides")
