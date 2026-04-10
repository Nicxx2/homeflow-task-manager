"""add ai error logs

Revision ID: 0003_ai_error_logs
Revises: 0002_phase2_core_models
Create Date: 2026-04-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_ai_error_logs"
down_revision: Union[str, Sequence[str], None] = "0002_phase2_core_models"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_error_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_name", sa.String(length=100), nullable=False),
        sa.Column("model_identifier", sa.String(length=255), nullable=True),
        sa.Column("error_type", sa.String(length=100), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_error_logs_provider_name", "ai_error_logs", ["provider_name"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_ai_error_logs_provider_name", table_name="ai_error_logs")
    op.drop_table("ai_error_logs")
