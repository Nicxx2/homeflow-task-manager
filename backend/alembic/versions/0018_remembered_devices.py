"""add remembered devices for easy logon

Revision ID: 0018_remembered_devices
Revises: 0017_member_status_updates
Create Date: 2026-06-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0018_remembered_devices"
down_revision: Union[str, Sequence[str], None] = "0017_member_status_updates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "remembered_devices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_remembered_devices_expires_at", "remembered_devices", ["expires_at"], unique=False)
    op.create_index("ix_remembered_devices_id", "remembered_devices", ["id"], unique=False)
    op.create_index("ix_remembered_devices_revoked_at", "remembered_devices", ["revoked_at"], unique=False)
    op.create_index("ix_remembered_devices_token_hash", "remembered_devices", ["token_hash"], unique=True)
    op.create_index("ix_remembered_devices_user_id", "remembered_devices", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_remembered_devices_user_id", table_name="remembered_devices")
    op.drop_index("ix_remembered_devices_token_hash", table_name="remembered_devices")
    op.drop_index("ix_remembered_devices_revoked_at", table_name="remembered_devices")
    op.drop_index("ix_remembered_devices_id", table_name="remembered_devices")
    op.drop_index("ix_remembered_devices_expires_at", table_name="remembered_devices")
    op.drop_table("remembered_devices")
