from functools import wraps
from typing import Any, Dict, List, Optional, Tuple, Union

import httpx
import stamina
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_403_FORBIDDEN, HTTP_409_CONFLICT

from labtasker.api_models import (
    HealthCheckResponse,
    QueueCreateRequest,
    QueueCreateResponse,
    QueueGetResponse,
    QueueUpdateRequest,
    TaskFetchRequest,
    TaskFetchResponse,
    TaskLsRequest,
    TaskLsResponse,
    TaskStatusUpdateRequest,
    TaskSubmitRequest,
    TaskSubmitResponse,
    TaskUpdateRequest,
    WorkerCreateRequest,
    WorkerCreateResponse,
    WorkerLsRequest,
    WorkerLsResponse,
    WorkerStatusUpdateRequest,
)
from labtasker.client.core.config import get_client_config
from labtasker.client.core.exceptions import (
    LabtaskerRuntimeError,
    LabtaskerValueError,
    WorkerSuspended,
)
from labtasker.client.core.utils import (
    cast_http_error,
    display_server_notifications,
    raise_for_status,
    transpile_query_safe,
)
from labtasker.constants import Priority
from labtasker.security import SecretStr, get_auth_headers

_httpx_client: Optional[httpx.Client] = None

__all__ = [
    "get_httpx_client",
    "close_httpx_client",
    "health_check",
    "create_queue",
    "get_queue",
    "delete_queue",
    "submit_task",
    "fetch_task",
    "report_task_status",
    "refresh_task_heartbeat",
    "create_worker",
    "ls_workers",
    "report_worker_status",
    "ls_tasks",
    "update_tasks",
    "delete_task",
    "update_queue",
    "delete_worker",
]


def _network_err_retry(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        return stamina.retry(
            on=httpx.TransportError,
            attempts=10,
            timeout=100.0,
            wait_initial=0.5,
            wait_max=16.0,
            wait_jitter=1.0,
            wait_exp_base=2.0,
        )(func)(*args, **kwargs)

    return wrapper


def get_httpx_client() -> httpx.Client:
    """Lazily initialize httpx client."""
    global _httpx_client
    if _httpx_client is None:
        config = get_client_config()
        auth_headers = get_auth_headers(config.queue.queue_name, config.queue.password)
        _httpx_client = httpx.Client(
            base_url=str(config.endpoint.api_base_url),
            headers={**auth_headers, "Content-Type": "application/json"},
        )
    return _httpx_client


def close_httpx_client():
    """Close the httpx client."""
    global _httpx_client
    if _httpx_client is not None:
        _httpx_client.close()
        _httpx_client = None


@display_server_notifications
@cast_http_error
def health_check(client: Optional[httpx.Client] = None) -> HealthCheckResponse:
    """Check the health of the server."""
    if client is None:
        client = get_httpx_client()
    response = client.get("/health/full")
    raise_for_status(response)
    return HealthCheckResponse(**response.json())


@display_server_notifications
@cast_http_error
def create_queue(
    queue_name: str,
    password: str,
    metadata: Optional[Dict[str, Any]] = None,
    client: Optional[httpx.Client] = None,
) -> QueueCreateResponse:
    """Create a new queue."""
    if client is None:
        client = get_httpx_client()
    payload = QueueCreateRequest(
        queue_name=queue_name,
        password=SecretStr(password),
        metadata=metadata,
    ).to_request_dict()  # Convert to dict for JSON serialization
    response = client.post("/api/v1/queues", json=payload)
    raise_for_status(response)
    return QueueCreateResponse(**response.json())


@display_server_notifications
@cast_http_error
def get_queue(client: Optional[httpx.Client] = None) -> QueueGetResponse:
    """Get queue information."""
    if client is None:
        client = get_httpx_client()
    response = client.get("/api/v1/queues/me")
    raise_for_status(response)
    return QueueGetResponse(**response.json())


@cast_http_error
def delete_queue(
    cascade_delete: bool = True,
    client: Optional[httpx.Client] = None,
) -> None:
    """Delete a queue."""
    if client is None:
        client = get_httpx_client()
    params = {"cascade_delete": cascade_delete}
    response = client.delete("/api/v1/queues/me", params=params)
    raise_for_status(response)


@display_server_notifications
@cast_http_error
def submit_task(
    task_name: Optional[str] = None,
    args: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    cmd: Optional[Union[str, List[str]]] = None,
    heartbeat_timeout: Optional[float] = None,
    task_timeout: Optional[int] = None,
    max_retries: int = 3,
    priority: int = Priority.MEDIUM,
    client: Optional[httpx.Client] = None,
) -> TaskSubmitResponse:
    """Submit a task to the queue."""
    if client is None:
        client = get_httpx_client()

    if not cmd and not args:
        raise LabtaskerValueError("Either cmd or args must be specified.")

    payload = TaskSubmitRequest(
        task_name=task_name,
        args=args,
        metadata=metadata,
        cmd=cmd,
        heartbeat_timeout=heartbeat_timeout,
        task_timeout=task_timeout,
        max_retries=max_retries,
        priority=priority,
    ).model_dump(mode="json")
    response = client.post("/api/v1/queues/me/tasks", json=payload)
    raise_for_status(response)
    return TaskSubmitResponse(**response.json())


@display_server_notifications
@cast_http_error
def fetch_task(
    worker_id: Optional[str] = None,
    eta_max: Optional[str] = None,
    heartbeat_timeout: Optional[float] = None,
    start_heartbeat: bool = True,
    required_fields: Optional[List[str]] = None,
    extra_filter: Optional[Union[str, Dict[str, Any]]] = None,
    client: Optional[httpx.Client] = None,
    cmd: Optional[Union[str, List[str]]] = None,
) -> TaskFetchResponse:
    """Fetch the next available task from the queue."""
    if client is None:
        client = get_httpx_client()

    if not eta_max and not start_heartbeat:
        raise LabtaskerValueError(
            "Either eta_max or start_heartbeat must be specified."
        )

    if isinstance(extra_filter, str):  # transpile to mongodb query
        extra_filter = transpile_query_safe(query_str=extra_filter)

    payload = TaskFetchRequest(
        worker_id=worker_id,
        eta_max=eta_max,
        heartbeat_timeout=heartbeat_timeout,
        start_heartbeat=start_heartbeat,
        required_fields=required_fields,
        extra_filter=extra_filter,
        cmd=cmd,
    ).dump_to_json_dict()  # make sure datetime is correctly serialized
    response = client.post("/api/v1/queues/me/tasks/next", json=payload)
    if response.status_code == HTTP_403_FORBIDDEN:
        raise WorkerSuspended(
            "Current worker could be halted due to exceeding max failure counts."
        )
    raise_for_status(response)
    return TaskFetchResponse(**response.json())


@cast_http_error
@_network_err_retry
def report_task_status(
    task_id: str,
    status: str,
    summary: Optional[Dict[str, Any]] = None,
    worker_id: Optional[str] = None,
    client: Optional[httpx.Client] = None,
) -> None:
    """Report the status of a task.

    Args:
        task_id:
        status:
        summary: The summary update.
            1. If summary is None, no changes to summary will be made.
            2. If summary is set to {}, it will set the entire summary to a empty dict.
            3. If summary is like {"foo": "bar"},
        worker_id:
        client:

    Returns:

    """
    if client is None:
        client = get_httpx_client()
    payload = TaskStatusUpdateRequest(
        status=status,
        worker_id=worker_id,
        summary=summary,
    ).model_dump(mode="json")
    response = client.post(f"/api/v1/queues/me/tasks/{task_id}/status", json=payload)
    if response.status_code == HTTP_409_CONFLICT:
        raise LabtaskerRuntimeError(
            "Current task is assigned to a different worker.\n"
            f"Detail: {response.text}"
        )
    raise_for_status(response)


@cast_http_error
@_network_err_retry
def refresh_task_heartbeat(
    task_id: str,
    client: Optional[httpx.Client] = None,
) -> None:
    """Refresh the heartbeat of a task."""
    if client is None:
        client = get_httpx_client()
    response = client.post(f"/api/v1/queues/me/tasks/{task_id}/heartbeat")
    raise_for_status(response)


@cast_http_error
def create_worker(
    worker_name: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    max_retries: Optional[int] = 3,
    client: Optional[httpx.Client] = None,
) -> str:
    """Create a new worker."""
    if client is None:
        client = get_httpx_client()
    payload = WorkerCreateRequest(
        worker_name=worker_name,
        metadata=metadata,
        max_retries=max_retries,
    ).model_dump(mode="json")
    response = client.post("/api/v1/queues/me/workers", json=payload)
    raise_for_status(response)
    return WorkerCreateResponse(**response.json()).worker_id


@display_server_notifications
@cast_http_error
def ls_workers(
    worker_id: Optional[str] = None,
    worker_name: Optional[str] = None,
    status: Optional[str] = None,
    extra_filter: Optional[Union[str, Dict[str, Any]]] = None,
    limit: int = 100,
    offset: int = 0,
    sort: Optional[List[Tuple[str, int]]] = None,
    client: Optional[httpx.Client] = None,
) -> WorkerLsResponse:
    """List workers."""
    if client is None:
        client = get_httpx_client()

    if isinstance(extra_filter, str):  # transpile to mongodb query
        extra_filter = transpile_query_safe(query_str=extra_filter)

    payload = WorkerLsRequest(
        worker_id=worker_id,
        worker_name=worker_name,
        status=status,
        extra_filter=extra_filter,
        limit=limit,
        offset=offset,
        sort=sort,
    ).dump_to_json_dict()  # make sure datetime is correctly serialized
    response = client.post("/api/v1/queues/me/workers/search", json=payload)
    raise_for_status(response)
    return WorkerLsResponse(**response.json())


@cast_http_error
@_network_err_retry
def report_worker_status(
    worker_id: str,
    status: str,
    client: Optional[httpx.Client] = None,
) -> None:
    """Report the status of a worker."""
    assert status in [
        "active",
        "suspended",
        "crashed",
    ], f"Invalid status {status}, should be one of ['active', 'suspended', 'crashed']"

    if client is None:
        client = get_httpx_client()
    payload = WorkerStatusUpdateRequest(status=status).model_dump(mode="json")
    response = client.post(
        f"/api/v1/queues/me/workers/{worker_id}/status", json=payload
    )

    if (
        response.status_code == HTTP_400_BAD_REQUEST
        and "InvalidStateTransition" in response.text
    ):
        raise LabtaskerRuntimeError(
            f"FSM invalid transition: \n" f"Detail: {response.text}"
        )

    raise_for_status(response)


@display_server_notifications
@cast_http_error
def ls_tasks(
    task_id: Optional[str] = None,
    task_name: Optional[str] = None,
    status: Optional[str] = None,
    extra_filter: Optional[Union[str, Dict[str, Any]]] = None,
    limit: int = 100,
    offset: int = 0,
    sort: Optional[List[Tuple[str, int]]] = None,
    client: Optional[httpx.Client] = None,
) -> TaskLsResponse:
    """List tasks in a queue."""
    if client is None:
        client = get_httpx_client()

    if isinstance(extra_filter, str):  # transpile to mongodb query
        extra_filter = transpile_query_safe(query_str=extra_filter)

    payload = TaskLsRequest(
        task_id=task_id,
        task_name=task_name,
        status=status,
        extra_filter=extra_filter,
        limit=limit,
        offset=offset,
        sort=sort,
    ).dump_to_json_dict()  # make sure datetime is correctly serialized
    response = client.post("/api/v1/queues/me/tasks/search", json=payload)
    raise_for_status(response)
    return TaskLsResponse(**response.json())


@display_server_notifications
@cast_http_error
def update_tasks(
    task_updates: List[TaskUpdateRequest],
    reset_pending: bool = False,
    client: Optional[httpx.Client] = None,
) -> TaskLsResponse:
    if client is None:
        client = get_httpx_client()
    payload = [
        task.model_dump(exclude_unset=True, mode="json") for task in task_updates
    ]
    response = client.put(
        "/api/v1/queues/me/tasks", json=payload, params={"reset_pending": reset_pending}
    )
    raise_for_status(response)
    return TaskLsResponse(**response.json())


@cast_http_error
def delete_task(
    task_id: str,
    client: Optional[httpx.Client] = None,
) -> None:
    """Delete a specific task."""
    if client is None:
        client = get_httpx_client()
    response = client.delete(f"/api/v1/queues/me/tasks/{task_id}")
    raise_for_status(response)


@display_server_notifications
@cast_http_error
def update_queue(
    new_queue_name: Optional[str] = None,
    new_password: Optional[str] = None,
    metadata_update: Optional[Dict[str, Any]] = None,
    client: Optional[httpx.Client] = None,
) -> QueueGetResponse:
    """Update queue details."""
    if client is None:
        client = get_httpx_client()

    update_request = QueueUpdateRequest(
        new_queue_name=new_queue_name,
        new_password=SecretStr(new_password) if new_password else None,
        metadata_update=metadata_update,
    )

    response = client.put("/api/v1/queues/me", json=update_request.to_request_dict())
    raise_for_status(response)
    return QueueGetResponse(**response.json())


@cast_http_error
def delete_worker(
    worker_id: str,
    cascade_update: bool = True,
    client: Optional[httpx.Client] = None,
) -> None:
    """Delete a specific worker."""
    if client is None:
        client = get_httpx_client()
    params = {"cascade_update": cascade_update}
    response = client.delete(f"/api/v1/queues/me/workers/{worker_id}", params=params)
    raise_for_status(response)
