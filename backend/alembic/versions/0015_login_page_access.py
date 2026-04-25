"""add login page access controls

Revision ID: 0015_login_access
Revises: 0014_app_settings
Create Date: 2026-04-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0015_login_access"
down_revision: Union[str, Sequence[str], None] = "0014_app_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column("public_registration_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "app_settings",
        sa.Column("login_theme_preference", sa.String(length=20), nullable=False, server_default="light"),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "login_theme_preference")
    op.drop_column("app_settings", "public_registration_enabled")
