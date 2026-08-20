from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast, overload

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from labtasker_server.database import Database
from labtasker_server.errors import conflict, invalid, not_found
from labtasker_server.models import QueueRow, TaskRouteRow, TaskRow
from labtasker_server.schemas import LastError, Task, TaskCreate, TaskStatus
from labtasker_server.validation import (
    MAX_TASK_DATA_BYTES,
    validate_identifier,
    validate_task_id,
)


def system_now_us() -> int:
    return int(datetime.now(UTC).timestamp() * 1_000_000)


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


@overload
def datetime_from_us(value: int) -> datetime: ...


@overload
def datetime_from_us(value: None) -> None: ...


def datetime_from_us(value: int | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1_000_000, UTC)


class TaskService:
    def __init__(self, database: Database, *, now_us: Callable[[], int] = system_now_us) -> None:
        self.database = database
        self.now_us = now_us

    def create(self, queue: str, task_id: str, request: TaskCreate) -> tuple[Task, bool]:
        queue = validate_identifier(queue, kind="Queue")
        task_id = validate_task_id(task_id)
        normalized = request.model_dump(mode="json")
        normalized["routes"] = sorted(request.routes)
        creation_hash = hashlib.sha256(canonical_json(normalized).encode()).hexdigest()

        with self.database.write_session() as session:
            if session.get(QueueRow, queue) is None:
                raise not_found("queue_not_found", "Queue does not exist.", queue=queue)

            existing = session.scalar(
                select(TaskRow)
                .options(selectinload(TaskRow.routes))
                .where(TaskRow.queue_name == queue, TaskRow.task_id == task_id)
            )
            if existing is not None:
                if existing.creation_hash != creation_hash:
                    raise conflict(
                        "task_id_conflict",
                        "Task ID is already associated with a different creation request.",
                        task_id=task_id,
                        queue=queue,
                    )
                return task_from_row(existing), False

            _validate_stored_size(normalized, result={})
            now = self.now_us()
            row = TaskRow(
                queue_name=queue,
                task_id=task_id,
                status="pending",
                name=request.name,
                args_json=canonical_json(request.args),
                metadata_json=canonical_json(request.metadata),
                result_json="{}",
                priority=request.priority,
                attempt=0,
                max_attempts=request.max_attempts,
                created_at_us=now,
                updated_at_us=now,
                last_route=None,
                started_at_us=None,
                finished_at_us=None,
                last_error_json=None,
                creation_hash=creation_hash,
                active_run_id=None,
                lease_expires_at_us=None,
                last_terminal_run_id=None,
                last_terminal_action=None,
                pending_at_us=now,
            )
            row.routes = [
                TaskRouteRow(queue_name=queue, task_id=task_id, route=route)
                for route in request.routes
            ]
            session.add(row)
            session.flush()
            return task_from_row(row), True

    def get(self, queue: str, task_id: str) -> Task:
        queue = validate_identifier(queue, kind="Queue")
        task_id = validate_task_id(task_id)
        with self.database.read_session() as session:
            row = session.scalar(
                select(TaskRow)
                .options(selectinload(TaskRow.routes))
                .where(TaskRow.queue_name == queue, TaskRow.task_id == task_id)
            )
            if row is None:
                raise not_found(
                    "task_not_found",
                    "Task does not exist.",
                    queue=queue,
                    task_id=task_id,
                )
            return task_from_row(row)


def task_from_row(row: TaskRow) -> Task:
    last_error = None
    if row.last_error_json is not None:
        raw_error = json.loads(row.last_error_json)
        raw_error["occurred_at"] = datetime_from_us(raw_error["occurred_at_us"])
        del raw_error["occurred_at_us"]
        last_error = LastError.model_validate(raw_error)
    return Task(
        id=row.task_id,
        queue=row.queue_name,
        status=cast(TaskStatus, row.status),
        name=row.name,
        args=json.loads(row.args_json),
        metadata=json.loads(row.metadata_json),
        priority=row.priority,
        attempt=row.attempt,
        max_attempts=row.max_attempts,
        routes=sorted(route.route for route in row.routes),
        result=json.loads(row.result_json),
        last_error=last_error,
        last_route=row.last_route,
        created_at=datetime_from_us(row.created_at_us),
        updated_at=datetime_from_us(row.updated_at_us),
        started_at=datetime_from_us(row.started_at_us),
        finished_at=datetime_from_us(row.finished_at_us),
    )


def _validate_stored_size(normalized: dict[str, object], *, result: dict[str, object]) -> None:
    stored = {
        "name": normalized["name"],
        "args": normalized["args"],
        "metadata": normalized["metadata"],
        "priority": normalized["priority"],
        "max_attempts": normalized["max_attempts"],
        "routes": normalized["routes"],
        "result": result,
    }
    if len(canonical_json(stored).encode("utf-8")) > MAX_TASK_DATA_BYTES:
        raise invalid(
            "task_data_too_large",
            "Stored Task data exceeds the 1 MiB limit.",
            max_bytes=MAX_TASK_DATA_BYTES,
        )
