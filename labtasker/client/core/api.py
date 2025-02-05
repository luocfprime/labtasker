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
from labtasker.client.core.config import ClientConfig, get_client_config
from labtasker.security import get_auth_headers

_httpx_client = httpx.Client()


def get_httpx_client() -> httpx.Client:
    return _httpx_client


def health_check(
    client: Optional[httpx.Client] = None, config: Optional[ClientConfig] = None
) -> HealthCheckResponse:
    """Check the health of the server."""
    if client is None:
        client = get_httpx_client()
    if config is None:
        config = get_client_config()
    headers = get_auth_headers(config.queue_name, config.password)
    response = client.get(f"{config.api_base_url}/health", headers=headers)
    response.raise_for_status()
    return HealthCheckResponse(**response.json())


def create_queue(
    queue_name: str,
    password: str,
    metadata: Optional[Dict[str, Any]] = None,
    client: Optional[httpx.Client] = None,
    config: Optional[ClientConfig] = None,
) -> QueueCreateResponse:
    """Create a new queue."""
    if client is None:
        client = get_httpx_client()
    if config is None:
        config = get_client_config()
    headers = get_auth_headers(config.queue_name, config.password)
    payload = {
        "queue_name": queue_name,
        "password": password,
        "metadata": metadata or {},
    }
    response = client.post(
        f"{config.api_base_url}/api/v1/queues", headers=headers, json=payload
    )
    response.raise_for_status()
    return QueueCreateResponse(**response.json())


def get_queue(
    client: Optional[httpx.Client] = None, config: Optional[ClientConfig] = None
) -> QueueGetResponse:
    """Get queue information."""
    if client is None:
        client = get_httpx_client()
    if config is None:
        config = get_client_config()
    headers = get_auth_headers(config.queue_name, config.password)
    response = client.get(f"{config.api_base_url}/api/v1/queues/me", headers=headers)
    response.raise_for_status()
    return QueueGetResponse(**response.json())


def delete_queue(
    cascade_delete: bool = False,
    client: Optional[httpx.Client] = None,
    config: Optional[ClientConfig] = None,
) -> None:
    """Delete a queue."""
    if client is None:
        client = get_httpx_client()
    if config is None:
        config = get_client_config()
    headers = get_auth_headers(config.queue_name, config.password)
    params = {"cascade_delete": cascade_delete}
    response = client.delete(
        f"{config.api_base_url}/api/v1/queues/me", headers=headers, params=params
    )
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
    config: Optional[ClientConfig] = None,
) -> TaskSubmitResponse:
    """Submit a task to the queue."""
    if client is None:
        client = get_httpx_client()
    if config is None:
        config = get_client_config()
    headers = get_auth_headers(config.queue_name, config.password)
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
    response = client.post(
        f"{config.api_base_url}/api/v1/queues/me/tasks", headers=headers, json=payload
    )
    response.raise_for_status()
    return TaskSubmitResponse(**response.json())


def fetch_task(
    worker_id: Optional[str],
    eta_max: Optional[str],
    start_heartbeat: bool,
    required_fields: Optional[Dict[str, Any]],
    extra_filter: Optional[Dict[str, Any]],
    client: Optional[httpx.Client] = None,
    config: Optional[ClientConfig] = None,
) -> TaskFetchResponse:
    """Fetch the next available task from the queue."""
    if client is None:
        client = get_httpx_client()
    if config is None:
        config = get_client_config()
    headers = get_auth_headers(config.queue_name, config.password)
    payload = {
        "worker_id": worker_id,
        "eta_max": eta_max,
        "start_heartbeat": start_heartbeat,
        "required_fields": required_fields,
        "extra_filter": extra_filter,
    }
    response = client.post(
        f"{config.api_base_url}/api/v1/queues/me/tasks/next",
        headers=headers,
        json=payload,
    )
    response.raise_for_status()
    return TaskFetchResponse(**response.json())


def report_task_status(
    task_id: str,
    status: str,
    summary: Optional[Dict[str, Any]],
    client: Optional[httpx.Client] = None,
    config: Optional[ClientConfig] = None,
) -> None:
    """Report the status of a task."""
    if client is None:
        client = get_httpx_client()
    if config is None:
        config = get_client_config()
    headers = get_auth_headers(config.queue_name, config.password)
    payload = {
        "status": status,
        "summary": summary,
    }
    response = client.post(
        f"{config.api_base_url}/api/v1/queues/me/tasks/{task_id}/status",
        headers=headers,
        json=payload,
    )
    response.raise_for_status()


def refresh_task_heartbeat(
    task_id: str,
    client: Optional[httpx.Client] = None,
    config: Optional[ClientConfig] = None,
) -> None:
    """Refresh the heartbeat of a task."""
    if client is None:
        client = get_httpx_client()
    if config is None:
        config = get_client_config()
    headers = get_auth_headers(config.queue_name, config.password)
    response = client.post(
        f"{config.api_base_url}/api/v1/queues/me/tasks/{task_id}/heartbeat",
        headers=headers,
    )
    response.raise_for_status()


def create_worker(
    worker_name: Optional[str],
    metadata: Optional[Dict[str, Any]],
    max_retries: Optional[int],
    client: Optional[httpx.Client] = None,
    config: Optional[ClientConfig] = None,
) -> str:
    """Create a new worker."""
    if client is None:
        client = get_httpx_client()
    if config is None:
        config = get_client_config()
    headers = get_auth_headers(config.queue_name, config.password)
    payload = {
        "worker_name": worker_name,
        "metadata": metadata,
        "max_retries": max_retries,
    }
    response = client.post(
        f"{config.api_base_url}/api/v1/queues/me/workers", headers=headers, json=payload
    )
    response.raise_for_status()
    return response.json()["worker_id"]


def ls_worker(
    worker_id: Optional[str] = None,
    worker_name: Optional[str] = None,
    extra_filter: Optional[Dict[str, Any]] = None,
    limit: int = 100,
    offset: int = 0,
    client: Optional[httpx.Client] = None,
    config: Optional[ClientConfig] = None,
) -> WorkerLsResponse:
    """List workers."""
    if client is None:
        client = get_httpx_client()
    if config is None:
        config = get_client_config()
    headers = get_auth_headers(config.queue_name, config.password)
    payload = {
        "worker_id": worker_id,
        "worker_name": worker_name,
        "extra_filter": extra_filter,
        "limit": limit,
        "offset": offset,
    }
    response = client.get(
        f"{config.api_base_url}/api/v1/queues/me/workers",
        headers=headers,
        params=payload,
    )
    response.raise_for_status()
    return WorkerLsResponse(**response.json())


def report_worker_status(
    worker_id: str,
    status: str,
    client: Optional[httpx.Client] = None,
    config: Optional[ClientConfig] = None,
) -> None:
    """Report the status of a worker."""
    if client is None:
        client = get_httpx_client()
    if config is None:
        config = get_client_config()
    headers = get_auth_headers(config.queue_name, config.password)
    payload = {
        "status": status,
    }
    response = client.post(
        f"{config.api_base_url}/api/v1/queues/me/workers/{worker_id}/status",
        headers=headers,
        json=payload,
    )
    response.raise_for_status()


def ls_tasks(
    task_id: Optional[str] = None,
    task_name: Optional[str] = None,
    extra_filter: Optional[Dict[str, Any]] = None,
    limit: int = 100,
    offset: int = 0,
    client: Optional[httpx.Client] = None,
    config: Optional[ClientConfig] = None,
) -> TaskLsResponse:
    """List tasks in a queue."""
    if client is None:
        client = get_httpx_client()
    if config is None:
        config = get_client_config()
    headers = get_auth_headers(config.queue_name, config.password)
    payload = {
        "task_id": task_id,
        "task_name": task_name,
        "extra_filter": extra_filter,
        "limit": limit,
        "offset": offset,
    }
    response = client.get(
        f"{config.api_base_url}/api/v1/queues/me/tasks", headers=headers, params=payload
    )
    response.raise_for_status()
    return TaskLsResponse(**response.json())


def delete_task(
    task_id: str,
    client: Optional[httpx.Client] = None,
    config: Optional[ClientConfig] = None,
) -> None:
    """Delete a specific task."""
    if client is None:
        client = get_httpx_client()
    if config is None:
        config = get_client_config()
    headers = get_auth_headers(config.queue_name, config.password)
    response = client.delete(
        f"{config.api_base_url}/api/v1/queues/me/tasks/{task_id}", headers=headers
    )
    response.raise_for_status()


def update_queue(
    queue_id: str,
    metadata: Optional[Dict[str, Any]] = None,
    client: Optional[httpx.Client] = None,
    config: Optional[ClientConfig] = None,
) -> None:
    """Update queue details."""
    if client is None:
        client = get_httpx_client()
    if config is None:
        config = get_client_config()
    headers = get_auth_headers(config.queue_name, config.password)
    payload = {"metadata": metadata or {}}
    response = client.put(
        f"{config.api_base_url}/api/v1/queues/{queue_id}", headers=headers, json=payload
    )
    response.raise_for_status()


def delete_worker(
    worker_id: str,
    client: Optional[httpx.Client] = None,
    config: Optional[ClientConfig] = None,
) -> None:
    """Delete a specific worker."""
    if client is None:
        client = get_httpx_client()
    if config is None:
        config = get_client_config()
    headers = get_auth_headers(config.queue_name, config.password)
    response = client.delete(
        f"{config.api_base_url}/api/v1/queues/me/workers/{worker_id}", headers=headers
    )
    response.raise_for_status()
