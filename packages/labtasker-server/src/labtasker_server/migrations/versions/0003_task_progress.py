from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_task_progress"
down_revision: str | None = "0002_worker_observations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SQLite batch migration rebuilds ``tasks``. Preserve child routes explicitly
    # because dropping the old parent applies the configured ON DELETE CASCADE.
    op.execute(
        "CREATE TEMPORARY TABLE labtasker_progress_routes AS "
        "SELECT queue_name, task_id, route FROM task_routes"
    )
    with op.batch_alter_table("tasks") as batch:
        batch.add_column(sa.Column("progress_json", sa.Text()))
        batch.add_column(sa.Column("progress_updated_at_us", sa.Integer()))
        batch.add_column(sa.Column("progress_attempt", sa.Integer()))
        batch.create_check_constraint(
            "ck_progress_json",
            "progress_json IS NULL OR "
            "(json_valid(progress_json) AND json_type(progress_json) = 'object')",
        )
        batch.create_check_constraint(
            "ck_tasks_progress_state",
            "(progress_json IS NULL AND progress_updated_at_us IS NULL "
            "AND progress_attempt IS NULL) OR "
            "(progress_json IS NOT NULL AND progress_updated_at_us IS NOT NULL "
            "AND progress_attempt IS NOT NULL)",
        )
    op.execute(
        "INSERT OR IGNORE INTO task_routes (queue_name, task_id, route) "
        "SELECT queue_name, task_id, route FROM labtasker_progress_routes"
    )
    op.execute("DROP TABLE labtasker_progress_routes")


def downgrade() -> None:
    op.execute(
        "CREATE TEMPORARY TABLE labtasker_progress_routes AS "
        "SELECT queue_name, task_id, route FROM task_routes"
    )
    with op.batch_alter_table("tasks") as batch:
        batch.drop_constraint("ck_tasks_progress_state", type_="check")
        batch.drop_constraint("ck_progress_json", type_="check")
        batch.drop_column("progress_attempt")
        batch.drop_column("progress_updated_at_us")
        batch.drop_column("progress_json")
    op.execute(
        "INSERT OR IGNORE INTO task_routes (queue_name, task_id, route) "
        "SELECT queue_name, task_id, route FROM labtasker_progress_routes"
    )
    op.execute("DROP TABLE labtasker_progress_routes")
