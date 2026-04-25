"""add default capacity for public registrations

Revision ID: 0016_reg_capacity
Revises: 0015_login_access
Create Date: 2026-04-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0016_reg_capacity"
down_revision: Union[str, Sequence[str], None] = "0015_login_access"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column("registration_default_capacity_points", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "registration_default_capacity_points")
