from __future__ import annotations

from sqlalchemy import func, select

from labtasker_server.database import Database
from labtasker_server.errors import conflict, not_found
from labtasker_server.models import QueueRow, TaskRow
from labtasker_server.schemas import Queue
from labtasker_server.validation import validate_identifier


class QueueService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create(self, name: str) -> tuple[Queue, bool]:
        name = validate_identifier(name, kind="Queue")
        with self.database.write_session() as session:
            existing = session.get(QueueRow, name)
            if existing is not None:
                return Queue(name=existing.name), False
            row = QueueRow(name=name)
            session.add(row)
            session.flush()
            return Queue(name=row.name), True

    def list(self) -> list[Queue]:
        with self.database.read_session() as session:
            names = session.scalars(select(QueueRow.name).order_by(QueueRow.name)).all()
            return [Queue(name=name) for name in names]

    def require_exists(self, name: str) -> None:
        name = validate_identifier(name, kind="Queue")
        with self.database.read_session() as session:
            if session.get(QueueRow, name) is None:
                raise not_found("queue_not_found", "Queue does not exist.", queue=name)

    def delete(self, name: str, *, cascade: bool) -> None:
        name = validate_identifier(name, kind="Queue")
        with self.database.write_session() as session:
            row = session.get(QueueRow, name)
            if row is None:
                raise not_found("queue_not_found", "Queue does not exist.", queue=name)
            running = session.scalar(
                select(func.count())
                .select_from(TaskRow)
                .where(TaskRow.queue_name == name, TaskRow.status == "running")
            )
            if running:
                raise conflict(
                    "queue_has_running_tasks",
                    "Queue contains running Tasks; cancel them before deletion.",
                    queue=name,
                    running=running,
                )
            task_count = session.scalar(
                select(func.count()).select_from(TaskRow).where(TaskRow.queue_name == name)
            )
            if task_count and not cascade:
                raise conflict(
                    "queue_not_empty",
                    "Queue is not empty; use cascade to delete its Tasks.",
                    queue=name,
                    tasks=task_count,
                )
            session.delete(row)
