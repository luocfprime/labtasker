from __future__ import annotations

from threading import Lock

from labtasker.client import Client
from labtasker.models import BulkUpdateResult, Queue, Task, TaskPage
from labtasker.types import JSONValue, TaskOrderField, TaskStatus, TaskUpdate

_default_client: Client | None = None
_default_client_lock = Lock()


def submit_task(
    args: dict[str, JSONValue] | None = None,
    *,
    name: str | None = None,
    metadata: dict[str, JSONValue] | None = None,
    priority: int = 0,
    max_attempts: int = 3,
    routes: list[str] | None = None,
    task_id: str | None = None,
    queue: str | None = None,
) -> Task:
    return _client().submit_task(
        args,
        name=name,
        metadata=metadata,
        priority=priority,
        max_attempts=max_attempts,
        routes=routes,
        task_id=task_id,
        queue=queue,
    )


def get_task(task_id: str, *, queue: str | None = None) -> Task:
    return _client().get_task(task_id, queue=queue)


def list_tasks(
    *,
    status: TaskStatus | None = None,
    name: str | None = None,
    filter: str | None = None,
    order_by: TaskOrderField = "created_at",
    descending: bool = True,
    limit: int = 100,
    cursor: str | None = None,
    queue: str | None = None,
) -> TaskPage:
    return _client().list_tasks(
        status=status,
        name=name,
        filter=filter,
        order_by=order_by,
        descending=descending,
        limit=limit,
        cursor=cursor,
        queue=queue,
    )


def count_tasks(
    *,
    status: TaskStatus | None = None,
    name: str | None = None,
    filter: str | None = None,
    queue: str | None = None,
) -> int:
    return _client().count_tasks(status=status, name=name, filter=filter, queue=queue)


def update_task(
    task_id: str,
    changes: TaskUpdate,
    *,
    queue: str | None = None,
) -> Task:
    return _client().update_task(task_id, changes, queue=queue)


def update_tasks(
    *,
    filter: str,
    changes: TaskUpdate,
    queue: str | None = None,
) -> BulkUpdateResult:
    return _client().update_tasks(filter=filter, changes=changes, queue=queue)


def cancel_task(task_id: str, *, queue: str | None = None) -> Task:
    return _client().cancel_task(task_id, queue=queue)


def requeue_task(task_id: str, *, queue: str | None = None) -> Task:
    return _client().requeue_task(task_id, queue=queue)


def delete_task(task_id: str, *, queue: str | None = None) -> None:
    _client().delete_task(task_id, queue=queue)


def create_queue(name: str) -> Queue:
    return _client().create_queue(name)


def list_queues() -> list[Queue]:
    return _client().list_queues()


def delete_queue(name: str, *, cascade: bool = False) -> None:
    _client().delete_queue(name, cascade=cascade)


def _client() -> Client:
    global _default_client
    if _default_client is not None:
        return _default_client
    with _default_client_lock:
        if _default_client is None:
            _default_client = Client()
        return _default_client
