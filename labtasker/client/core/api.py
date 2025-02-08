from typing import Any, Dict, List, Optional, Union

import httpx

from labtasker.api_models import (
    HealthCheckResponse,
    QueueCreateResponse,
    QueueGetResponse,
    TaskFetchResponse,
    TaskLsResponse,
    TaskSubmitResponse,
    WorkerLsResponse,
)
from labtasker.client.core.config import get_client_config
from labtasker.security import get_auth_headers

_httpx_client = None


def get_httpx_client() -> httpx.Client:
    """Lazily initialize httpx client."""
    global _httpx_client
    if _httpx_client is None:
        config = get_client_config()
        auth_headers = get_auth_headers(config.queue_name, config.password)
        _httpx_client = httpx.Client(
            base_url=str(config.api_base_url),
            headers={**auth_headers, "Content-Type": "application/json"},
        )
    return _httpx_client


def close_httpx_client():
    """Close the httpx client."""
    global _httpx_client
    if _httpx_client is not None:
        _httpx_client.close()
        _httpx_client = None


def health_check(client: Optional[httpx.Client] = None) -> HealthCheckResponse:
    """Check the health of the server."""
    if client is None:
        client = get_httpx_client()
    response = client.get("/health")
    response.raise_for_status()
    return HealthCheckResponse(**response.json())


def create_queue(
    queue_name: str,
    password: str,
    metadata: Optional[Dict[str, Any]] = None,
    client: Optional[httpx.Client] = None,
) -> QueueCreateResponse:
    """Create a new queue."""
    if client is None:
        client = get_httpx_client()
    payload = {
        "queue_name": queue_name,
        "password": password,
        "metadata": metadata or {},
    }
    response = client.post("/api/v1/queues", json=payload)
    response.raise_for_status()
    return QueueCreateResponse(**response.json())


def get_queue(client: Optional[httpx.Client] = None) -> QueueGetResponse:
    """Get queue information."""
    if client is None:
        client = get_httpx_client()
    response = client.get("/api/v1/queues/me")
    response.raise_for_status()
    return QueueGetResponse(**response.json())


def delete_queue(
    cascade_delete: bool = False,
    client: Optional[httpx.Client] = None,
) -> None:
    """Delete a queue."""
    if client is None:
        client = get_httpx_client()
    params = {"cascade_delete": cascade_delete}
    response = client.delete("/api/v1/queues/me", params=params)
    response.raise_for_status()


def submit_task(
    task_name: Optional[str],
    args: Optional[Dict[str, Any]],
    metadata: Optional[Dict[str, Any]],
    cmd: Optional[Union[str, List[str]]],
    heartbeat_timeout: Optional[int],
    task_timeout: Optional[int],
    max_retries: Optional[int],
    priority: Optional[int],
    client: Optional[httpx.Client] = None,
) -> TaskSubmitResponse:
    """Submit a task to the queue."""
    if client is None:
        client = get_httpx_client()
    payload = {
        "task_name": task_name,
        "args": args,
        "metadata": metadata,
        "cmd": cmd,
        "heartbeat_timeout": heartbeat_timeout,
        "task_timeout": task_timeout,
        "max_retries": max_retries,
        "priority": priority,
    }
    response = client.post("/api/v1/queues/me/tasks", json=payload)
    response.raise_for_status()
    return TaskSubmitResponse(**response.json())


def fetch_task(
    worker_id: Optional[str],
    eta_max: Optional[str],
    start_heartbeat: bool,
    required_fields: Optional[Dict[str, Any]],
    extra_filter: Optional[Dict[str, Any]],
    client: Optional[httpx.Client] = None,
) -> TaskFetchResponse:
    """Fetch the next available task from the queue."""
    if client is None:
        client = get_httpx_client()
    payload = {
        "worker_id": worker_id,
        "eta_max": eta_max,
        "start_heartbeat": start_heartbeat,
        "required_fields": required_fields,
        "extra_filter": extra_filter,
    }
    response = client.post("/api/v1/queues/me/tasks/next", json=payload)
    response.raise_for_status()
    return TaskFetchResponse(**response.json())


def report_task_status(
    task_id: str,
    status: str,
    summary: Optional[Dict[str, Any]],
    client: Optional[httpx.Client] = None,
) -> None:
    """Report the status of a task."""
    if client is None:
        client = get_httpx_client()
    payload = {
        "status": status,
        "summary": summary,
    }
    response = client.post(f"/api/v1/queues/me/tasks/{task_id}/status", json=payload)
    response.raise_for_status()


def refresh_task_heartbeat(
    task_id: str,
    client: Optional[httpx.Client] = None,
) -> None:
    """Refresh the heartbeat of a task."""
    if client is None:
        client = get_httpx_client()
    response = client.post(f"/api/v1/queues/me/tasks/{task_id}/heartbeat")
    response.raise_for_status()


def create_worker(
    worker_name: Optional[str],
    metadata: Optional[Dict[str, Any]],
    max_retries: Optional[int],
    client: Optional[httpx.Client] = None,
) -> str:
    """Create a new worker."""
    if client is None:
        client = get_httpx_client()
    payload = {
        "worker_name": worker_name,
        "metadata": metadata,
        "max_retries": max_retries,
    }
    response = client.post("/api/v1/queues/me/workers", json=payload)
    response.raise_for_status()
    return response.json()["worker_id"]


def ls_worker(
    worker_id: Optional[str] = None,
    worker_name: Optional[str] = None,
    extra_filter: Optional[Dict[str, Any]] = None,
    limit: int = 100,
    offset: int = 0,
    client: Optional[httpx.Client] = None,
) -> WorkerLsResponse:
    """List workers."""
    if client is None:
        client = get_httpx_client()
    payload = {
        "worker_id": worker_id,
        "worker_name": worker_name,
        "extra_filter": extra_filter,
        "limit": limit,
        "offset": offset,
    }
    response = client.get("/api/v1/queues/me/workers", params=payload)
    response.raise_for_status()
    return WorkerLsResponse(**response.json())


def report_worker_status(
    worker_id: str,
    status: str,
    client: Optional[httpx.Client] = None,
) -> None:
    """Report the status of a worker."""
    if client is None:
        client = get_httpx_client()
    payload = {
        "status": status,
    }
    response = client.post(
        f"/api/v1/queues/me/workers/{worker_id}/status", json=payload
    )
    response.raise_for_status()


def ls_tasks(
    task_id: Optional[str] = None,
    task_name: Optional[str] = None,
    extra_filter: Optional[Dict[str, Any]] = None,
    limit: int = 100,
    offset: int = 0,
    client: Optional[httpx.Client] = None,
) -> TaskLsResponse:
    """List tasks in a queue."""
    if client is None:
        client = get_httpx_client()
    payload = {
        "task_id": task_id,
        "task_name": task_name,
        "extra_filter": extra_filter,
        "limit": limit,
        "offset": offset,
    }
    response = client.get("/api/v1/queues/me/tasks", params=payload)
    response.raise_for_status()
    return TaskLsResponse(**response.json())


def delete_task(
    task_id: str,
    client: Optional[httpx.Client] = None,
) -> None:
    """Delete a specific task."""
    if client is None:
        client = get_httpx_client()
    response = client.delete(f"/api/v1/queues/me/tasks/{task_id}")
    response.raise_for_status()


def update_queue(
    queue_id: str,
    metadata: Optional[Dict[str, Any]] = None,
    client: Optional[httpx.Client] = None,
) -> None:
    """Update queue details."""
    if client is None:
        client = get_httpx_client()
    payload = {"metadata": metadata or {}}
    response = client.put(f"/api/v1/queues/{queue_id}", json=payload)
    response.raise_for_status()


def delete_worker(
    worker_id: str,
    client: Optional[httpx.Client] = None,
) -> None:
    """Delete a specific worker."""
    if client is None:
        client = get_httpx_client()
    response = client.delete(f"/api/v1/queues/me/workers/{worker_id}")
    response.raise_for_status()
