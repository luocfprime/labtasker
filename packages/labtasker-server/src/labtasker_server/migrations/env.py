from __future__ import annotations

from alembic import context

from labtasker_server.models import Base

config = context.config
target_metadata = Base.metadata


def run_migrations() -> None:
    connection = config.attributes.get("connection")
    if connection is None:
        raise RuntimeError("Labtasker migrations require an existing Server connection.")
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=False)
    with context.begin_transaction():
        context.run_migrations()


run_migrations()
