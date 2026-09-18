from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any, Literal, cast

from sqlalchemy import delete, func, select

from labtasker_server.database import Database, OperationKind
from labtasker_server.errors import conflict, invalid, not_found
from labtasker_server.filtering import compile_filter
from labtasker_server.grouping import (
    decode_position,
    encode_position,
    grouped_page,
    grouping_fields,
    page_limit,
)
from labtasker_server.models import QueueRow, WorkerRow
from labtasker_server.schemas import (
    GroupCountPage,
    WorkerObservation,
    WorkerPage,
    WorkerReport,
    WorkerTelemetryReport,
)
from labtasker_server.services.tasks import canonical_json, datetime_from_us, system_now_us
from labtasker_server.validation import validate_identifier

WORKER_TTL_US = 300_000_000


def validate_worker_id(value: str) -> str:
    if not re.fullmatch(r"w_[A-Za-z0-9_-]{12}", value):
        raise invalid(
            "invalid_request",
            "Request validation failed.",
            errors=[
                {
                    "location": ["path", "id"],
                    "message": "Expected a Worker instance ID (w_ plus 12 URL-safe characters).",
                }
            ],
        )
    return value


def worker_from_row(row: WorkerRow) -> WorkerObservation:
    return WorkerObservation(
        id=row.worker_id,
        queue=row.queue_name,
        route=row.route,
        status=cast(Literal["idle", "busy"], row.status),
        task_id=row.task_id,
        metadata=json.loads(row.metadata_json),
        telemetry=None if row.telemetry_json is None else json.loads(row.telemetry_json),
        telemetry_updated_at=(
            None
            if row.telemetry_updated_at_us is None
            else datetime_from_us(row.telemetry_updated_at_us)
        ),
        last_seen_at=datetime_from_us(row.last_seen_at_us),
        expires_at=datetime_from_us(row.expires_at_us),
    )


class WorkerService:
    def __init__(self, database: Database, *, now_us: Callable[[], int] = system_now_us):
        self.database = database
        self.now_us = now_us

    def report(self, queue: str, worker_id: str, report: WorkerReport) -> None:
        queue = validate_identifier(queue, kind="Queue")
        worker_id = validate_worker_id(worker_id)
        with self.database.write_session() as session:
            if session.get(QueueRow, queue) is None:
                raise not_found("queue_not_found", "Queue does not exist.", queue=queue)
            row = session.get(WorkerRow, (queue, worker_id))
            if row is not None and row.route != report.route:
                raise conflict(
                    "worker_route_conflict",
                    "A Worker instance cannot change route.",
                    worker_id=worker_id,
                )
            now = self.now_us()
            if row is None:
                row = WorkerRow(
                    queue_name=queue,
                    worker_id=worker_id,
                    route=report.route,
                    metadata_json=canonical_json(report.metadata),
                )
                session.add(row)
            row.status = report.status
            row.task_id = report.task_id
            row.metadata_json = canonical_json(report.metadata)
            row.last_seen_at_us = now
            row.expires_at_us = now + WORKER_TTL_US

    def report_telemetry(self, queue: str, worker_id: str, report: WorkerTelemetryReport) -> None:
        queue = validate_identifier(queue, kind="Queue")
        worker_id = validate_worker_id(worker_id)
        with self.database.write_session() as session:
            if session.get(QueueRow, queue) is None:
                raise not_found("queue_not_found", "Queue does not exist.", queue=queue)
            row = session.get(WorkerRow, (queue, worker_id))
            now = self.now_us()
            if row is None or row.expires_at_us <= now:
                raise not_found(
                    "worker_not_found",
                    "Online Worker observation does not exist.",
                    worker_id=worker_id,
                )
            row.telemetry_json = canonical_json(report.telemetry)
            row.telemetry_updated_at_us = now

    def withdraw(self, queue: str, worker_id: str) -> None:
        queue = validate_identifier(queue, kind="Queue")
        worker_id = validate_worker_id(worker_id)
        with self.database.write_session() as session:
            if session.get(QueueRow, queue) is None:
                raise not_found("queue_not_found", "Queue does not exist.", queue=queue)
            session.execute(
                delete(WorkerRow).where(
                    WorkerRow.queue_name == queue, WorkerRow.worker_id == worker_id
                )
            )

    def _conditions(self, queue: str, filter_expression: str | None) -> list[Any]:
        conditions = [WorkerRow.queue_name == queue, WorkerRow.expires_at_us > self.now_us()]
        if filter_expression is not None:
            conditions.append(compile_filter(filter_expression, worker=True))
        return conditions

    def list(
        self,
        queue: str,
        *,
        filter_expression: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> WorkerPage:
        queue = validate_identifier(queue, kind="Queue")
        size = page_limit(limit)
        selection = {"operation": "workers.list", "queue": queue, "filter": filter_expression}
        position = decode_position(cursor, selection, 1)
        conditions = self._conditions(queue, filter_expression)
        if position is not None:
            conditions.append(WorkerRow.worker_id > position[0])
        with self.database.read_session() as session:
            if session.get(QueueRow, queue) is None:
                raise not_found("queue_not_found", "Queue does not exist.", queue=queue)
            rows = session.scalars(
                select(WorkerRow).where(*conditions).order_by(WorkerRow.worker_id).limit(size + 1)
            ).all()
            return WorkerPage(
                items=[worker_from_row(row) for row in rows[:size]],
                next_cursor=encode_position(selection, [rows[size - 1].worker_id])
                if len(rows) > size
                else None,
            )

    def count(
        self,
        queue: str,
        *,
        filter_expression: str | None = None,
        group_by: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> int | GroupCountPage:
        queue = validate_identifier(queue, kind="Queue")
        fields = grouping_fields(group_by, {"route", "status"}, limit, cursor)
        conditions = self._conditions(queue, filter_expression)
        with self.database.read_session() as session:
            if session.get(QueueRow, queue) is None:
                raise not_found("queue_not_found", "Queue does not exist.", queue=queue)
            count = (
                session.scalar(select(func.count()).select_from(WorkerRow).where(*conditions)) or 0
            )
            if fields is None:
                return count
            selection = {
                "operation": "workers.count",
                "queue": queue,
                "filter": filter_expression,
                "group_by": fields,
            }
            return grouped_page(
                session,
                select(WorkerRow).where(*conditions),
                {"route": WorkerRow.route, "status": WorkerRow.status},
                fields,
                selection,
                count,
                limit,
                cursor,
            )

    def expire(self, *, operation: OperationKind = "write") -> None:
        with self.database.write_session(operation=operation) as session:
            session.execute(delete(WorkerRow).where(WorkerRow.expires_at_us <= self.now_us()))
