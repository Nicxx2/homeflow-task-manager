"""add task ai provider metadata

Revision ID: 0004_task_ai_metadata
Revises: 0003_ai_error_logs
Create Date: 2026-04-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_task_ai_metadata"
down_revision: Union[str, Sequence[str], None] = "0003_ai_error_logs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("ai_provider_used", sa.String(length=100), nullable=True))
    op.add_column("tasks", sa.Column("ai_model_used", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "ai_model_used")
    op.drop_column("tasks", "ai_provider_used")
