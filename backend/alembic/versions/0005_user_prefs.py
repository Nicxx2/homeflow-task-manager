"""add user session and theme preferences

Revision ID: 0005_user_prefs
Revises: 0004_task_ai_metadata
Create Date: 2026-04-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005_user_prefs"
down_revision: Union[str, Sequence[str], None] = "0004_task_ai_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("theme_preference", sa.String(length=20), server_default="light", nullable=False))
    op.add_column("users", sa.Column("session_timeout_minutes", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "ck_users_session_timeout_positive",
        "users",
        "(session_timeout_minutes IS NULL) OR (session_timeout_minutes > 0)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_session_timeout_positive", "users", type_="check")
    op.drop_column("users", "last_activity_at")
    op.drop_column("users", "session_timeout_minutes")
    op.drop_column("users", "theme_preference")
