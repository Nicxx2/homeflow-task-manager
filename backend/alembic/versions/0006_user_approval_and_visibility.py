"""add user approval status and member visibility

Revision ID: 0006_user_approval_visibility
Revises: 0005_user_prefs
Create Date: 2026-04-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006_user_approval_visibility"
down_revision: Union[str, Sequence[str], None] = "0005_user_prefs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("approval_status", sa.String(length=20), server_default="approved", nullable=False))
    op.add_column("users", sa.Column("show_in_member_lists", sa.Boolean(), server_default=sa.true(), nullable=False))
    op.create_check_constraint(
        "ck_users_approval_status_valid",
        "users",
        "approval_status IN ('pending', 'approved', 'rejected')",
    )
    op.execute("UPDATE users SET approval_status = 'approved'")
    op.execute("UPDATE users SET show_in_member_lists = CASE WHEN is_admin THEN false ELSE true END")


def downgrade() -> None:
    op.drop_constraint("ck_users_approval_status_valid", "users", type_="check")
    op.drop_column("users", "show_in_member_lists")
    op.drop_column("users", "approval_status")
