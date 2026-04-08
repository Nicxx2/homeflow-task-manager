"""phase 2 core models

Revision ID: 0002_phase2_core_models
Revises: 0001_create_users
Create Date: 2026-04-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002_phase2_core_models"
down_revision: Union[str, Sequence[str], None] = "0001_create_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

effort_level_enum = sa.Enum("low", "medium", "high", name="effort_level")
task_status_enum = sa.Enum("pending", "in_progress", "completed", name="task_status")
effort_level_enum_ref = postgresql.ENUM("low", "medium", "high", name="effort_level", create_type=False)
task_status_enum_ref = postgresql.ENUM("pending", "in_progress", "completed", name="task_status", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    effort_level_enum.create(bind, checkfirst=True)
    task_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "task_effort_configs",
        sa.Column("level", effort_level_enum_ref, nullable=False),
        sa.Column("points_value", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("level"),
        sa.CheckConstraint("points_value > 0", name="ck_task_effort_points_positive"),
    )
    op.bulk_insert(
        sa.table(
            "task_effort_configs",
            sa.column("level", effort_level_enum_ref),
            sa.column("points_value", sa.Integer()),
        ),
        [
            {"level": "low", "points_value": 2},
            {"level": "medium", "points_value": 5},
            {"level": "high", "points_value": 8},
        ],
    )

    op.create_table(
        "ai_model_registry",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("provider_name", sa.String(length=100), nullable=False),
        sa.Column("model_identifier", sa.String(length=255), nullable=False),
        sa.Column("available", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("health_status", sa.String(length=50), server_default="unknown", nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_name", "model_identifier", name="uq_provider_model_identifier"),
    )
    op.create_index("ix_ai_model_registry_provider_name", "ai_model_registry", ["provider_name"], unique=False)

    op.create_table(
        "ai_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ai_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("active_provider", sa.String(length=100), server_default="ollama", nullable=False),
        sa.Column("active_model", sa.String(length=255), server_default="qwen2.5:1.5b", nullable=False),
        sa.Column("fallback_provider", sa.String(length=100), server_default="rules", nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), server_default="8", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("timeout_seconds > 0", name="ck_ai_settings_timeout_positive"),
    )
    op.bulk_insert(
        sa.table(
            "ai_settings",
            sa.column("id", sa.Integer()),
            sa.column("ai_enabled", sa.Boolean()),
            sa.column("active_provider", sa.String()),
            sa.column("active_model", sa.String()),
            sa.column("fallback_provider", sa.String()),
            sa.column("timeout_seconds", sa.Integer()),
        ),
        [
            {
                "id": 1,
                "ai_enabled": True,
                "active_provider": "ollama",
                "active_model": "qwen2.5:1.5b",
                "fallback_provider": "rules",
                "timeout_seconds": 8,
            }
        ],
    )

    op.create_table(
        "user_daily_capacities",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("daily_capacity_points", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id"),
        sa.CheckConstraint("daily_capacity_points > 0", name="ck_user_daily_capacity_positive"),
    )

    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("assignment_date", sa.Date(), nullable=True),
        sa.Column("assignee_id", sa.Integer(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column("effort_level", effort_level_enum_ref, nullable=False),
        sa.Column("points_value", sa.Integer(), nullable=False),
        sa.Column("status", task_status_enum_ref, server_default="pending", nullable=False),
        sa.Column("ai_suggested_level", effort_level_enum_ref, nullable=True),
        sa.Column("ai_confidence", sa.Numeric(3, 2), nullable=True),
        sa.Column("ai_reason", sa.Text(), nullable=True),
        sa.Column("fallback_used", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["assignee_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("points_value > 0", name="ck_tasks_points_value_positive"),
        sa.CheckConstraint(
            "(ai_confidence IS NULL) OR (ai_confidence >= 0 AND ai_confidence <= 1)",
            name="ck_tasks_ai_confidence_range",
        ),
        sa.CheckConstraint(
            "(assignee_id IS NULL AND assignment_date IS NULL) OR (assignee_id IS NOT NULL AND assignment_date IS NOT NULL)",
            name="ck_tasks_assignment_pair",
        ),
    )
    op.create_index("ix_tasks_assignment_date", "tasks", ["assignment_date"], unique=False)
    op.create_index("ix_tasks_assignee_id", "tasks", ["assignee_id"], unique=False)
    op.create_index("ix_tasks_created_by_id", "tasks", ["created_by_id"], unique=False)
    op.create_index("ix_tasks_due_date", "tasks", ["due_date"], unique=False)
    op.create_index("ix_tasks_effort_level", "tasks", ["effort_level"], unique=False)
    op.create_index("ix_tasks_status", "tasks", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_tasks_status", table_name="tasks")
    op.drop_index("ix_tasks_effort_level", table_name="tasks")
    op.drop_index("ix_tasks_due_date", table_name="tasks")
    op.drop_index("ix_tasks_assignment_date", table_name="tasks")
    op.drop_index("ix_tasks_created_by_id", table_name="tasks")
    op.drop_index("ix_tasks_assignee_id", table_name="tasks")
    op.drop_table("tasks")

    op.drop_table("user_daily_capacities")
    op.drop_table("ai_settings")

    op.drop_index("ix_ai_model_registry_provider_name", table_name="ai_model_registry")
    op.drop_table("ai_model_registry")

    op.drop_table("task_effort_configs")

    bind = op.get_bind()
    task_status_enum.drop(bind, checkfirst=True)
    effort_level_enum.drop(bind, checkfirst=True)
