from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_task_archive"
down_revision: str | None = "0005_task_dependencies"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column(
            "archived",
            sa.Boolean(),
            sa.CheckConstraint(
                "archived IN (0,1) AND "
                "(archived = 0 OR status IN ('succeeded','failed','cancelled'))",
                name="ck_tasks_archived_state",
            ),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("tasks", "archived")
