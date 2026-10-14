from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_task_dependencies"
down_revision: str | None = "0004_worker_observability"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column(
            "dependencies_json",
            sa.Text(),
            sa.CheckConstraint(
                "json_valid(dependencies_json) AND json_type(dependencies_json) = 'array'",
                name="ck_dependencies_json",
            ),
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    # The column-local CHECK is removed with the column. Avoid rebuilding tasks:
    # deleting the old table would cascade into its route rows with foreign keys enabled.
    op.drop_column("tasks", "dependencies_json")
