from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast, overload

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session, selectinload

from labtasker_server.database import Database
from labtasker_server.errors import conflict, invalid, not_found
from labtasker_server.filtering import compile_filter
from labtasker_server.models import QueueRow, TaskRouteRow, TaskRow
from labtasker_server.pagination import (
    CursorPosition,
    TaskSelection,
    decode_cursor,
    encode_cursor,
)
from labtasker_server.schemas import (
    BulkUpdateResult,
    ClaimResponse,
    FailureReport,
    HeartbeatResponse,
    LastError,
    Task,
    TaskCreate,
    TaskOrderField,
    TaskPage,
    TaskStatus,
    TaskUpdate,
)
from labtasker_server.validation import (
    MAX_TASK_DATA_BYTES,
    JSONValue,
    validate_identifier,
    validate_run_id,
    validate_task_id,
)

HEARTBEAT_TIMEOUT_US = 300_000_000
TerminalAction = Literal["complete", "fail", "unclaim"]
TASK_ORDER_COLUMNS = {
    "id": TaskRow.task_id,
    "name": TaskRow.name,
    "status": TaskRow.status,
    "priority": TaskRow.priority,
    "attempt": TaskRow.attempt,
    "max_attempts": TaskRow.max_attempts,
    "last_route": TaskRow.last_route,
    "created_at": TaskRow.created_at_us,
    "updated_at": TaskRow.updated_at_us,
    "started_at": TaskRow.started_at_us,
    "finished_at": TaskRow.finished_at_us,
}
NULLABLE_ORDER_FIELDS = {"name", "last_route", "started_at", "finished_at"}


@dataclass(frozen=True, slots=True)
class PreparedUpdate:
    name: str | None
    args_json: str
    metadata_json: str
    priority: int
    max_attempts: int
    routes: tuple[str, ...]
    result_json: str
    changed: bool


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

    def list_tasks(
        self,
        queue: str,
        *,
        status: TaskStatus | None = None,
        name: str | None = None,
        filter_expression: str | None = None,
        order_by: TaskOrderField = "created_at",
        descending: bool = True,
        limit: int = 100,
        cursor: str | None = None,
    ) -> TaskPage:
        queue = validate_identifier(queue, kind="Queue")
        _validate_list_inputs(status, order_by, descending, limit)
        selection = TaskSelection(
            queue=queue,
            status=status,
            name=name,
            filter=filter_expression,
            order_by=order_by,
            descending=descending,
        )
        position = decode_cursor(cursor, selection) if cursor is not None else None
        conditions = _selection_conditions(
            queue,
            status=status,
            name=name,
            filter_expression=filter_expression,
        )
        if position is not None:
            conditions.append(_after_cursor(order_by, descending, position))

        column = TASK_ORDER_COLUMNS[order_by]
        direction = column.desc if descending else column.asc
        ordering: list[Any] = []
        if order_by in NULLABLE_ORDER_FIELDS:
            ordering.append(column.is_(None).asc())
        ordering.append(direction())
        if order_by != "id":
            ordering.append(TaskRow.task_id.desc() if descending else TaskRow.task_id.asc())

        with self.database.read_session() as session:
            if session.get(QueueRow, queue) is None:
                raise not_found("queue_not_found", "Queue does not exist.", queue=queue)
            rows = session.scalars(
                select(TaskRow)
                .options(selectinload(TaskRow.routes))
                .where(*conditions)
                .order_by(*ordering)
                .limit(limit + 1)
            ).all()
            has_more = len(rows) > limit
            page_rows = rows[:limit]
            next_cursor = None
            if has_more and page_rows:
                last = page_rows[-1]
                next_cursor = encode_cursor(
                    selection,
                    CursorPosition(
                        value=_order_value(last, order_by),
                        task_id=last.task_id,
                    ),
                )
            return TaskPage(
                items=[task_from_row(row) for row in page_rows],
                next_cursor=next_cursor,
            )

    def count_tasks(
        self,
        queue: str,
        *,
        status: TaskStatus | None = None,
        name: str | None = None,
        filter_expression: str | None = None,
    ) -> int:
        queue = validate_identifier(queue, kind="Queue")
        conditions = _selection_conditions(
            queue,
            status=status,
            name=name,
            filter_expression=filter_expression,
        )
        with self.database.read_session() as session:
            if session.get(QueueRow, queue) is None:
                raise not_found("queue_not_found", "Queue does not exist.", queue=queue)
            value = session.scalar(select(func.count()).select_from(TaskRow).where(*conditions))
            return 0 if value is None else value

    def update_task(self, queue: str, task_id: str, changes: TaskUpdate) -> Task:
        queue = validate_identifier(queue, kind="Queue")
        task_id = validate_task_id(task_id)
        with self.database.write_session() as session:
            row = _require_task_row(session, queue, task_id)
            if row.status == "running":
                raise conflict(
                    "task_running",
                    "Running Tasks cannot be updated.",
                    task_id=task_id,
                )
            prepared = _prepare_update(row, changes)
            if prepared.changed:
                _apply_prepared_update(row, prepared)
                row.updated_at_us = self.now_us()
                session.flush()
            return task_from_row(row)

    def update_tasks(
        self,
        queue: str,
        *,
        filter_expression: str,
        changes: TaskUpdate,
    ) -> BulkUpdateResult:
        queue = validate_identifier(queue, kind="Queue")
        if not filter_expression.strip():
            raise invalid("invalid_filter", "Batch update filter must not be empty.")
        predicate = compile_filter(filter_expression)
        with self.database.write_session() as session:
            if session.get(QueueRow, queue) is None:
                raise not_found("queue_not_found", "Queue does not exist.", queue=queue)
            rows = session.scalars(
                select(TaskRow)
                .options(selectinload(TaskRow.routes))
                .where(
                    TaskRow.queue_name == queue,
                    TaskRow.status != "running",
                    predicate,
                )
            ).all()
            prepared = [(row, _prepare_update(row, changes)) for row in rows]
            now = self.now_us()
            updated_count = 0
            for row, update_values in prepared:
                if not update_values.changed:
                    continue
                _apply_prepared_update(row, update_values)
                row.updated_at_us = now
                updated_count += 1
            return BulkUpdateResult(matched=len(rows), updated=updated_count)

    def claim(self, queue: str, route: str, run_id: str) -> ClaimResponse | None:
        queue = validate_identifier(queue, kind="Queue")
        route = validate_identifier(route, kind="Route")
        run_id = validate_run_id(run_id)

        with self.database.write_session() as session:
            if session.get(QueueRow, queue) is None:
                raise not_found("queue_not_found", "Queue does not exist.", queue=queue)

            active = session.scalar(
                select(TaskRow)
                .options(selectinload(TaskRow.routes))
                .where(TaskRow.active_run_id == run_id)
            )
            now = self.now_us()
            if active is not None:
                if active.queue_name != queue or active.last_route != route:
                    raise conflict(
                        "run_id_conflict",
                        "Run ID is already active for a different claim request.",
                        run_id=run_id,
                    )
                if active.lease_expires_at_us is None or active.lease_expires_at_us <= now:
                    raise conflict("stale_run", "This run is no longer active.", run_id=run_id)
                return _claim_response(active, run_id)

            finalized = session.scalar(
                select(TaskRow.task_id).where(TaskRow.last_terminal_run_id == run_id).limit(1)
            )
            if finalized is not None:
                raise conflict("stale_run", "This run is no longer active.", run_id=run_id)

            candidate = (
                select(TaskRow.task_id)
                .join(
                    TaskRouteRow,
                    (TaskRouteRow.queue_name == TaskRow.queue_name)
                    & (TaskRouteRow.task_id == TaskRow.task_id),
                )
                .where(
                    TaskRow.queue_name == queue,
                    TaskRow.status == "pending",
                    TaskRow.attempt < TaskRow.max_attempts,
                    TaskRouteRow.route == route,
                )
                .order_by(TaskRow.priority.desc(), TaskRow.pending_at_us, TaskRow.task_id)
                .limit(1)
                .scalar_subquery()
            )
            lease_expires_at_us = now + HEARTBEAT_TIMEOUT_US
            claimed_id = session.scalar(
                update(TaskRow)
                .where(
                    TaskRow.queue_name == queue,
                    TaskRow.task_id == candidate,
                    TaskRow.status == "pending",
                    TaskRow.attempt < TaskRow.max_attempts,
                )
                .values(
                    status="running",
                    attempt=TaskRow.attempt + 1,
                    updated_at_us=now,
                    last_route=route,
                    started_at_us=now,
                    finished_at_us=None,
                    active_run_id=run_id,
                    lease_expires_at_us=lease_expires_at_us,
                    pending_at_us=None,
                )
                .returning(TaskRow.task_id)
            )
            if claimed_id is None:
                return None
            row = _require_task_row(session, queue, claimed_id)
            return _claim_response(row, run_id)

    def heartbeat(self, queue: str, task_id: str, run_id: str) -> HeartbeatResponse:
        queue, task_id, run_id = _validated_execution_ids(queue, task_id, run_id)
        finalized_action: str | None = None
        response: HeartbeatResponse | None = None
        with self.database.write_session() as session:
            row = _require_task_row(session, queue, task_id)
            now = self.now_us()
            if row.status == "running" and row.active_run_id == run_id:
                if row.lease_expires_at_us is None or row.lease_expires_at_us <= now:
                    _expire_row(row, now)
                    finalized_action = "heartbeat_expired"
                else:
                    row.lease_expires_at_us = now + HEARTBEAT_TIMEOUT_US
                    response = HeartbeatResponse(
                        lease_expires_at=datetime_from_us(row.lease_expires_at_us)
                    )
            elif row.last_terminal_run_id == run_id:
                finalized_action = row.last_terminal_action
            else:
                raise _stale_run(run_id)

        if finalized_action is not None:
            raise _run_finalized(finalized_action)
        if response is None:
            raise AssertionError("Heartbeat produced neither a response nor a conflict.")
        return response

    def complete(
        self,
        queue: str,
        task_id: str,
        run_id: str,
        result: dict[str, JSONValue],
    ) -> None:
        queue, task_id, run_id = _validated_execution_ids(queue, task_id, run_id)
        finalized_action: str | None = None
        with self.database.write_session() as session:
            row = _require_task_row(session, queue, task_id)
            now = self.now_us()
            guard = _terminal_guard(row, run_id, "complete", now)
            if guard == "expired":
                finalized_action = "heartbeat_expired"
            elif guard == "duplicate":
                return
            else:
                _validate_row_stored_size(row, result=result)
                row.status = "succeeded"
                row.result_json = canonical_json(result)
                _finish_run(row, run_id, "complete", now)
        if finalized_action is not None:
            raise _run_finalized(finalized_action)

    def fail(
        self,
        queue: str,
        task_id: str,
        run_id: str,
        error: FailureReport,
    ) -> None:
        queue, task_id, run_id = _validated_execution_ids(queue, task_id, run_id)
        finalized_action: str | None = None
        with self.database.write_session() as session:
            row = _require_task_row(session, queue, task_id)
            now = self.now_us()
            guard = _terminal_guard(row, run_id, "fail", now)
            if guard == "expired":
                finalized_action = "heartbeat_expired"
            elif guard == "duplicate":
                return
            else:
                row.last_error_json = canonical_json(
                    {
                        **error.model_dump(mode="json"),
                        "occurred_at_us": now,
                        "attempt": row.attempt,
                        "run_id": run_id,
                    }
                )
                row.status = "pending" if row.attempt < row.max_attempts else "failed"
                row.pending_at_us = now if row.status == "pending" else None
                _finish_run(row, run_id, "fail", now)
        if finalized_action is not None:
            raise _run_finalized(finalized_action)

    def unclaim(self, queue: str, task_id: str, run_id: str) -> None:
        queue, task_id, run_id = _validated_execution_ids(queue, task_id, run_id)
        finalized_action: str | None = None
        with self.database.write_session() as session:
            row = _require_task_row(session, queue, task_id)
            now = self.now_us()
            guard = _terminal_guard(row, run_id, "unclaim", now)
            if guard == "expired":
                finalized_action = "heartbeat_expired"
            elif guard == "duplicate":
                return
            else:
                row.status = "pending"
                row.attempt -= 1
                row.pending_at_us = now
                _finish_run(row, run_id, "unclaim", now)
        if finalized_action is not None:
            raise _run_finalized(finalized_action)

    def cancel(self, queue: str, task_id: str) -> Task:
        queue = validate_identifier(queue, kind="Queue")
        task_id = validate_task_id(task_id)
        with self.database.write_session() as session:
            row = _require_task_row(session, queue, task_id)
            if row.status == "cancelled":
                return task_from_row(row)
            if row.status not in {"pending", "running"}:
                raise conflict(
                    "task_state_conflict",
                    "Only pending or running Tasks can be cancelled.",
                    task_id=task_id,
                    status=row.status,
                )
            now = self.now_us()
            if row.status == "running":
                if row.active_run_id is None:
                    raise AssertionError("Running Task has no active run ID.")
                _finish_run(row, row.active_run_id, "cancel", now)
            else:
                row.updated_at_us = now
                row.pending_at_us = None
            row.status = "cancelled"
            session.flush()
            return task_from_row(row)

    def requeue(self, queue: str, task_id: str) -> Task:
        queue = validate_identifier(queue, kind="Queue")
        task_id = validate_task_id(task_id)
        with self.database.write_session() as session:
            row = _require_task_row(session, queue, task_id)
            if row.status not in {"pending", "failed", "cancelled"}:
                raise conflict(
                    "task_state_conflict",
                    "Only pending, failed or cancelled Tasks can be requeued.",
                    task_id=task_id,
                    status=row.status,
                )
            now = self.now_us()
            row.status = "pending"
            row.attempt = 0
            row.last_error_json = None
            row.updated_at_us = now
            row.pending_at_us = now
            session.flush()
            return task_from_row(row)

    def delete(self, queue: str, task_id: str) -> None:
        queue = validate_identifier(queue, kind="Queue")
        task_id = validate_task_id(task_id)
        with self.database.write_session() as session:
            if session.get(QueueRow, queue) is None:
                raise not_found("queue_not_found", "Queue does not exist.", queue=queue)
            row = session.get(TaskRow, (queue, task_id))
            if row is None:
                return
            if row.status == "running":
                raise conflict(
                    "task_running",
                    "Running Tasks must be cancelled before deletion.",
                    task_id=task_id,
                )
            session.delete(row)

    def expire_leases(self) -> int:
        now = self.now_us()
        with self.database.write_session() as session:
            rows = session.scalars(
                select(TaskRow).where(
                    TaskRow.status == "running",
                    TaskRow.lease_expires_at_us <= now,
                )
            ).all()
            for row in rows:
                _expire_row(row, now)
            return len(rows)


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


def _claim_response(row: TaskRow, run_id: str) -> ClaimResponse:
    if row.lease_expires_at_us is None:
        raise AssertionError("Claimed Task has no lease deadline.")
    return ClaimResponse(
        task=task_from_row(row),
        run_id=run_id,
        lease_expires_at=datetime_from_us(row.lease_expires_at_us),
    )


def _selection_conditions(
    queue: str,
    *,
    status: TaskStatus | None,
    name: str | None,
    filter_expression: str | None,
) -> list[Any]:
    conditions: list[Any] = [TaskRow.queue_name == queue]
    if status is not None:
        conditions.append(TaskRow.status == status)
    if name is not None:
        conditions.append(TaskRow.name == name)
    if filter_expression is not None:
        conditions.append(compile_filter(filter_expression))
    return conditions


def _validate_list_inputs(
    status: str | None,
    order_by: str,
    descending: bool,
    limit: int,
) -> None:
    if status is not None and status not in {
        "pending",
        "running",
        "succeeded",
        "failed",
        "cancelled",
    }:
        raise invalid("invalid_request", "Status is not a valid Task status.", field="status")
    if order_by not in TASK_ORDER_COLUMNS:
        raise invalid("invalid_request", "Order field is not supported.", field="order_by")
    if not isinstance(descending, bool):
        raise invalid("invalid_request", "Descending must be a Boolean.", field="descending")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise invalid("invalid_request", "Limit must be an integer from 1 through 1000.")


def _after_cursor(
    order_by: TaskOrderField,
    descending: bool,
    position: CursorPosition,
) -> Any:
    column = TASK_ORDER_COLUMNS[order_by]
    id_after = (
        TaskRow.task_id < position.task_id if descending else TaskRow.task_id > position.task_id
    )
    if order_by == "id":
        return id_after
    if position.value is None:
        return and_(column.is_(None), id_after)
    value_after = column < position.value if descending else column > position.value
    same_value_after = and_(column == position.value, id_after)
    if order_by in NULLABLE_ORDER_FIELDS:
        return or_(value_after, same_value_after, column.is_(None))
    return or_(value_after, same_value_after)


def _order_value(row: TaskRow, order_by: TaskOrderField) -> str | int | None:
    values: dict[str, str | int | None] = {
        "id": row.task_id,
        "name": row.name,
        "status": row.status,
        "priority": row.priority,
        "attempt": row.attempt,
        "max_attempts": row.max_attempts,
        "last_route": row.last_route,
        "created_at": row.created_at_us,
        "updated_at": row.updated_at_us,
        "started_at": row.started_at_us,
        "finished_at": row.finished_at_us,
    }
    return values[order_by]


def _prepare_update(row: TaskRow, changes: TaskUpdate) -> PreparedUpdate:
    supplied = changes.model_dump(mode="python", exclude_unset=True)
    current = {
        "name": row.name,
        "args": json.loads(row.args_json),
        "metadata": json.loads(row.metadata_json),
        "priority": row.priority,
        "max_attempts": row.max_attempts,
        "routes": sorted(route.route for route in row.routes),
        "result": json.loads(row.result_json),
    }
    resulting = {**current, **supplied}
    max_attempts = cast(int, resulting["max_attempts"])
    if row.status == "pending" and max_attempts <= row.attempt:
        raise conflict(
            "update_conflict",
            "Pending Task must retain at least one remaining attempt.",
            task_id=row.task_id,
            field="max_attempts",
            attempt=row.attempt,
        )
    _validate_stored_size(resulting, result=resulting["result"])
    return PreparedUpdate(
        name=cast(str | None, resulting["name"]),
        args_json=canonical_json(resulting["args"]),
        metadata_json=canonical_json(resulting["metadata"]),
        priority=cast(int, resulting["priority"]),
        max_attempts=max_attempts,
        routes=tuple(cast(list[str], resulting["routes"])),
        result_json=canonical_json(resulting["result"]),
        changed=canonical_json(current) != canonical_json(resulting),
    )


def _apply_prepared_update(row: TaskRow, prepared: PreparedUpdate) -> None:
    row.name = prepared.name
    row.args_json = prepared.args_json
    row.metadata_json = prepared.metadata_json
    row.priority = prepared.priority
    row.max_attempts = prepared.max_attempts
    row.result_json = prepared.result_json
    existing_routes = {route.route: route for route in row.routes}
    current_routes = tuple(sorted(existing_routes))
    if current_routes != prepared.routes:
        row.routes = [
            existing_routes.get(route)
            or TaskRouteRow(queue_name=row.queue_name, task_id=row.task_id, route=route)
            for route in prepared.routes
        ]


def _require_task_row(session: Session, queue: str, task_id: str) -> TaskRow:
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
    return row


def _validated_execution_ids(queue: str, task_id: str, run_id: str) -> tuple[str, str, str]:
    return (
        validate_identifier(queue, kind="Queue"),
        validate_task_id(task_id),
        validate_run_id(run_id),
    )


def _terminal_guard(
    row: TaskRow,
    run_id: str,
    action: TerminalAction,
    now: int,
) -> Literal["active", "duplicate", "expired"]:
    if row.status == "running" and row.active_run_id == run_id:
        if row.lease_expires_at_us is None or row.lease_expires_at_us <= now:
            _expire_row(row, now)
            return "expired"
        return "active"
    if row.last_terminal_run_id == run_id:
        if row.last_terminal_action == action:
            return "duplicate"
        raise _run_finalized(row.last_terminal_action)
    raise _stale_run(run_id)


def _finish_run(row: TaskRow, run_id: str, action: str, now: int) -> None:
    row.updated_at_us = now
    row.finished_at_us = now
    row.active_run_id = None
    row.lease_expires_at_us = None
    row.last_terminal_run_id = run_id
    row.last_terminal_action = action


def _expire_row(row: TaskRow, now: int) -> None:
    if row.active_run_id is None:
        raise AssertionError("Cannot expire a Task without an active run ID.")
    run_id = row.active_run_id
    row.last_error_json = canonical_json(
        {
            "type": "HeartbeatTimeout",
            "message": "Heartbeat lease expired.",
            "traceback": None,
            "occurred_at_us": now,
            "attempt": row.attempt,
            "run_id": run_id,
        }
    )
    row.status = "pending" if row.attempt < row.max_attempts else "failed"
    row.pending_at_us = now if row.status == "pending" else None
    _finish_run(row, run_id, "heartbeat_expired", now)


def _run_finalized(action: str | None) -> Exception:
    return conflict(
        "run_finalized",
        "This run has already been finalized.",
        action=action,
    )


def _stale_run(run_id: str) -> Exception:
    return conflict("stale_run", "This run is no longer active.", run_id=run_id)


def _validate_row_stored_size(row: TaskRow, *, result: dict[str, JSONValue]) -> None:
    _validate_stored_size(
        {
            "name": row.name,
            "args": json.loads(row.args_json),
            "metadata": json.loads(row.metadata_json),
            "priority": row.priority,
            "max_attempts": row.max_attempts,
            "routes": sorted(route.route for route in row.routes),
        },
        result=result,
    )


def _validate_stored_size(normalized: dict[str, object], *, result: object) -> None:
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
