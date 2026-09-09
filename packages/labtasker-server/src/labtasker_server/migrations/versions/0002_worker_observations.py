from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_worker_observations"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workers",
        sa.Column("queue_name", sa.String(128), nullable=False),
        sa.Column("worker_id", sa.String(14), nullable=False),
        sa.Column("route", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("task_id", sa.String(14)),
        sa.Column("last_seen_at_us", sa.Integer(), nullable=False),
        sa.Column("expires_at_us", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("queue_name", "worker_id"),
        sa.ForeignKeyConstraint(["queue_name"], ["queues.name"], ondelete="CASCADE"),
        sa.CheckConstraint("status IN ('idle','busy')", name="ck_workers_status"),
    )
    op.create_index("ix_workers_expiry", "workers", ["expires_at_us"])
    op.create_index("ix_workers_route", "workers", ["queue_name", "route", "status"])


def downgrade() -> None:
    op.drop_table("workers")
