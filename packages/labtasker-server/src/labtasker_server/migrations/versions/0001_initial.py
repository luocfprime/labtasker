from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table("queues", sa.Column("name", sa.String(length=128), primary_key=True))
    op.create_table(
        "tasks",
        sa.Column("queue_name", sa.String(length=128), nullable=False),
        sa.Column("task_id", sa.String(length=14), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=256)),
        sa.Column("args_json", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("created_at_us", sa.Integer(), nullable=False),
        sa.Column("updated_at_us", sa.Integer(), nullable=False),
        sa.Column("last_route", sa.String(length=128)),
        sa.Column("started_at_us", sa.Integer()),
        sa.Column("finished_at_us", sa.Integer()),
        sa.Column("last_error_json", sa.Text()),
        sa.Column("creation_hash", sa.String(length=64), nullable=False),
        sa.Column("active_run_id", sa.String(length=14)),
        sa.Column("lease_expires_at_us", sa.Integer()),
        sa.Column("last_terminal_run_id", sa.String(length=14)),
        sa.Column("last_terminal_action", sa.String(length=32)),
        sa.Column("pending_at_us", sa.Integer()),
        sa.CheckConstraint(
            "status IN ('pending','running','succeeded','failed','cancelled')",
            name="ck_tasks_status",
        ),
        sa.CheckConstraint("attempt >= 0", name="ck_tasks_attempt_nonnegative"),
        sa.CheckConstraint("max_attempts > 0", name="ck_tasks_max_attempts_positive"),
        sa.CheckConstraint(
            "json_valid(args_json) AND json_type(args_json) = 'object'",
            name="ck_args_json",
        ),
        sa.CheckConstraint(
            "json_valid(metadata_json) AND json_type(metadata_json) = 'object'",
            name="ck_metadata_json",
        ),
        sa.CheckConstraint(
            "json_valid(result_json) AND json_type(result_json) = 'object'",
            name="ck_result_json",
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND pending_at_us IS NOT NULL "
            "AND active_run_id IS NULL AND lease_expires_at_us IS NULL "
            "AND attempt < max_attempts) OR status != 'pending'",
            name="ck_tasks_pending_state",
        ),
        sa.CheckConstraint(
            "(status = 'running' AND pending_at_us IS NULL "
            "AND active_run_id IS NOT NULL AND lease_expires_at_us IS NOT NULL) "
            "OR status != 'running'",
            name="ck_tasks_running_state",
        ),
        sa.CheckConstraint(
            "(status IN ('succeeded','failed','cancelled') AND pending_at_us IS NULL "
            "AND active_run_id IS NULL AND lease_expires_at_us IS NULL) "
            "OR status NOT IN ('succeeded','failed','cancelled')",
            name="ck_tasks_terminal_state",
        ),
        sa.ForeignKeyConstraint(["queue_name"], ["queues.name"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("queue_name", "task_id"),
    )
    op.create_index(
        "ix_tasks_claim",
        "tasks",
        ["queue_name", "status", sa.text("priority DESC"), "pending_at_us", "task_id"],
    )
    op.create_index("ix_tasks_expiry", "tasks", ["status", "lease_expires_at_us"])
    op.create_index(
        "ix_tasks_default_list",
        "tasks",
        ["queue_name", sa.text("created_at_us DESC"), sa.text("task_id DESC")],
    )
    op.create_index(
        "ix_tasks_status_list",
        "tasks",
        ["queue_name", "status", sa.text("created_at_us DESC"), sa.text("task_id DESC")],
    )
    op.create_index(
        "uq_tasks_active_run_id",
        "tasks",
        ["active_run_id"],
        unique=True,
        sqlite_where=sa.text("active_run_id IS NOT NULL"),
    )
    op.create_index(
        "ix_tasks_terminal_run_id",
        "tasks",
        ["last_terminal_run_id"],
        sqlite_where=sa.text("last_terminal_run_id IS NOT NULL"),
    )
    op.create_table(
        "task_routes",
        sa.Column("queue_name", sa.String(length=128), nullable=False),
        sa.Column("task_id", sa.String(length=14), nullable=False),
        sa.Column("route", sa.String(length=128), nullable=False),
        sa.ForeignKeyConstraint(
            ["queue_name", "task_id"],
            ["tasks.queue_name", "tasks.task_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("queue_name", "task_id", "route"),
    )
    op.create_index(
        "ix_task_routes_route",
        "task_routes",
        ["queue_name", "route", "task_id"],
    )


def downgrade() -> None:
    op.drop_table("task_routes")
    op.drop_table("tasks")
    op.drop_table("queues")
