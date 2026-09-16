from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_worker_observability"
down_revision: str | None = "0003_task_progress"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("workers") as batch:
        batch.add_column(sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("telemetry_json", sa.Text()))
        batch.add_column(sa.Column("telemetry_updated_at_us", sa.Integer()))
        batch.create_check_constraint(
            "ck_workers_metadata_json",
            "json_valid(metadata_json) AND json_type(metadata_json) = 'object'",
        )
        batch.create_check_constraint(
            "ck_workers_telemetry_json",
            "telemetry_json IS NULL OR "
            "(json_valid(telemetry_json) AND json_type(telemetry_json) = 'object')",
        )
        batch.create_check_constraint(
            "ck_workers_telemetry_state",
            "(telemetry_json IS NULL AND telemetry_updated_at_us IS NULL) OR "
            "(telemetry_json IS NOT NULL AND telemetry_updated_at_us IS NOT NULL)",
        )


def downgrade() -> None:
    with op.batch_alter_table("workers") as batch:
        batch.drop_constraint("ck_workers_telemetry_state", type_="check")
        batch.drop_constraint("ck_workers_telemetry_json", type_="check")
        batch.drop_constraint("ck_workers_metadata_json", type_="check")
        batch.drop_column("telemetry_updated_at_us")
        batch.drop_column("telemetry_json")
        batch.drop_column("metadata_json")
