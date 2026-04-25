"""add app settings for registration controls

Revision ID: 0014_app_settings
Revises: 0013_recurring_occurrence_index
Create Date: 2026-04-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014_app_settings"
down_revision: Union[str, Sequence[str], None] = "0013_recurring_occurrence_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("auto_approve_registrations", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute("INSERT INTO app_settings (id, auto_approve_registrations) VALUES (1, false)")


def downgrade() -> None:
    op.drop_table("app_settings")
