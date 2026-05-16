"""add member task status update setting

Revision ID: 0017_member_status_updates
Revises: 0016_reg_capacity
Create Date: 2026-05-16
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0017_member_status_updates"
down_revision: Union[str, Sequence[str], None] = "0016_reg_capacity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column("allow_member_status_updates", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "allow_member_status_updates")
