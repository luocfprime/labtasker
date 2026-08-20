from __future__ import annotations

import secrets
import time
from collections.abc import Callable
from typing import TypeVar

import httpx
from pydantic import TypeAdapter, ValidationError

from labtasker.config import ResolvedConfig, resolve_config
from labtasker.errors import APIError, TransportError
from labtasker.models import BulkUpdateResult, CountResponse, Queue, ResponseModel, Task, TaskPage
from labtasker.types import JSONValue, TaskOrderField, TaskStatus, TaskUpdate
from labtasker.validation import (
    RequestValidationError,
    validate_filter,
    validate_identifier,
    validate_int64,
    validate_json_object,
    validate_order_field,
    validate_routes,
    validate_status,
    validate_task_id,
    validate_task_name,
    validate_task_update,
)

T = TypeVar("T")
ModelT = TypeVar("ModelT", bound=ResponseModel)
REQUEST_TIMEOUT_SECONDS = 10.0
MAX_RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = (0.05, 0.1)
QUEUE_LIST_ADAPTER = TypeAdapter(list[Queue])


class Client:
    def __init__(
        self,
        url: str | None = None,
        token: str | None = None,
        queue: str | None = None,
    ) -> None:
        self._config = resolve_config(url=url, token=token, queue=queue)
        headers = {}
        if self._config.token is not None:
            headers["Authorization"] = f"Bearer {self._config.token}"
        self._http = httpx.Client(
            base_url=f"{self._config.url}/api/v2/",
            headers=headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        self._closed = False

    def __enter__(self) -> Client:
        self._ensure_open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._http.close()

    @property
    def configuration(self) -> ResolvedConfig:
        return self._config

    def submit_task(
        self,
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
        self._ensure_open()
        normalized_args = validate_json_object({} if args is None else args, field="args")
        normalized_metadata = validate_json_object(
            {} if metadata is None else metadata,
            field="metadata",
        )
        normalized_routes = validate_routes(["default"] if routes is None else routes)
        body: dict[str, object] = {
            "name": validate_task_name(name),
            "args": normalized_args,
            "metadata": normalized_metadata,
            "priority": validate_int64(priority, field="priority"),
            "max_attempts": validate_int64(
                max_attempts,
                field="max_attempts",
                positive=True,
            ),
            "routes": normalized_routes,
        }
        queue_name = self._queue(queue)
        if task_id is not None:
            selected_id = validate_task_id(task_id)
            return self._submit_with_id(queue_name, selected_id, body)

        for _ in range(MAX_RETRY_ATTEMPTS):
            selected_id = _generate_task_id()
            try:
                return self._submit_with_id(queue_name, selected_id, body)
            except APIError as error:
                if error.code != "task_id_conflict":
                    raise
        raise TransportError(
            "Could not allocate a unique Task ID.",
            {"operation": "submit_task", "url": self._config.url},
        )

    def get_task(self, task_id: str, *, queue: str | None = None) -> Task:
        self._ensure_open()
        queue_name = self._queue(queue)
        task_id = validate_task_id(task_id)
        return self._call(
            operation="get_task",
            method="GET",
            path=f"queues/{queue_name}/tasks/{task_id}",
            parser=lambda response: _parse_model(response, Task, {200}),
            retry=True,
        )

    def list_tasks(
        self,
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
        self._ensure_open()
        queue_name = self._queue(queue)
        status = validate_status(status)
        order_by = validate_order_field(order_by)
        filter = validate_filter(filter)
        if not isinstance(descending, bool):
            raise RequestValidationError("descending must be a Boolean.")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise RequestValidationError("limit must be an integer from 1 through 1000.")
        if name is not None and not isinstance(name, str):
            raise RequestValidationError("name selector must be a string or None.")
        if cursor is not None and not isinstance(cursor, str):
            raise RequestValidationError("cursor must be a string or None.")
        params = _without_none(
            {
                "status": status,
                "name": name,
                "filter": filter,
                "order_by": order_by,
                "descending": "true" if descending else "false",
                "limit": limit,
                "cursor": cursor,
            }
        )
        return self._call(
            operation="list_tasks",
            method="GET",
            path=f"queues/{queue_name}/tasks",
            params=params,
            parser=lambda response: _parse_model(response, TaskPage, {200}),
            retry=True,
        )

    def count_tasks(
        self,
        *,
        status: TaskStatus | None = None,
        name: str | None = None,
        filter: str | None = None,
        queue: str | None = None,
    ) -> int:
        self._ensure_open()
        queue_name = self._queue(queue)
        status = validate_status(status)
        filter = validate_filter(filter)
        if name is not None and not isinstance(name, str):
            raise RequestValidationError("name selector must be a string or None.")
        result = self._call(
            operation="count_tasks",
            method="GET",
            path=f"queues/{queue_name}/tasks/count",
            params=_without_none({"status": status, "name": name, "filter": filter}),
            parser=lambda response: _parse_model(response, CountResponse, {200}),
            retry=True,
        )
        return result.count

    def update_task(
        self,
        task_id: str,
        changes: TaskUpdate,
        *,
        queue: str | None = None,
    ) -> Task:
        self._ensure_open()
        queue_name = self._queue(queue)
        task_id = validate_task_id(task_id)
        normalized = validate_task_update(changes)
        return self._call(
            operation="update_task",
            method="PATCH",
            path=f"queues/{queue_name}/tasks/{task_id}",
            json=normalized,
            parser=lambda response: _parse_model(response, Task, {200}),
        )

    def update_tasks(
        self,
        *,
        filter: str,
        changes: TaskUpdate,
        queue: str | None = None,
    ) -> BulkUpdateResult:
        self._ensure_open()
        queue_name = self._queue(queue)
        normalized_filter = validate_filter(filter, required=True)
        normalized_changes = validate_task_update(changes)
        return self._call(
            operation="update_tasks",
            method="PATCH",
            path=f"queues/{queue_name}/tasks",
            json={"filter": normalized_filter, "changes": normalized_changes},
            parser=lambda response: _parse_model(response, BulkUpdateResult, {200}),
        )

    def cancel_task(self, task_id: str, *, queue: str | None = None) -> Task:
        return self._task_action("cancel", task_id, queue=queue)

    def requeue_task(self, task_id: str, *, queue: str | None = None) -> Task:
        return self._task_action("requeue", task_id, queue=queue)

    def delete_task(self, task_id: str, *, queue: str | None = None) -> None:
        self._ensure_open()
        queue_name = self._queue(queue)
        task_id = validate_task_id(task_id)
        self._call(
            operation="delete_task",
            method="DELETE",
            path=f"queues/{queue_name}/tasks/{task_id}",
            parser=lambda response: _parse_none(response, {204}),
        )

    def create_queue(self, name: str) -> Queue:
        self._ensure_open()
        name = validate_identifier(name, field="queue")
        return self._call(
            operation="create_queue",
            method="PUT",
            path=f"queues/{name}",
            parser=lambda response: _parse_model(response, Queue, {200, 201}),
        )

    def list_queues(self) -> list[Queue]:
        self._ensure_open()
        return self._call(
            operation="list_queues",
            method="GET",
            path="queues",
            parser=lambda response: _parse_queue_list(response, {200}),
            retry=True,
        )

    def delete_queue(self, name: str, *, cascade: bool = False) -> None:
        self._ensure_open()
        name = validate_identifier(name, field="queue")
        if not isinstance(cascade, bool):
            raise RequestValidationError("cascade must be a Boolean.")
        self._call(
            operation="delete_queue",
            method="DELETE",
            path=f"queues/{name}",
            params={"cascade": "true" if cascade else "false"},
            parser=lambda response: _parse_none(response, {204}),
        )

    def _submit_with_id(
        self,
        queue: str,
        task_id: str,
        body: dict[str, object],
    ) -> Task:
        return self._call(
            operation="submit_task",
            method="PUT",
            path=f"queues/{queue}/tasks/{task_id}",
            json=body,
            parser=lambda response: _parse_model(response, Task, {200, 201}),
            retry=True,
        )

    def _task_action(self, action: str, task_id: str, *, queue: str | None) -> Task:
        self._ensure_open()
        queue_name = self._queue(queue)
        task_id = validate_task_id(task_id)
        return self._call(
            operation=f"{action}_task",
            method="POST",
            path=f"queues/{queue_name}/tasks/{task_id}/{action}",
            parser=lambda response: _parse_model(response, Task, {200}),
        )

    def _queue(self, queue: str | None) -> str:
        return validate_identifier(self._config.queue if queue is None else queue, field="queue")

    def _call(
        self,
        *,
        operation: str,
        method: str,
        path: str,
        parser: Callable[[httpx.Response], T],
        json: object | None = None,
        params: dict[str, str | int] | None = None,
        retry: bool = False,
    ) -> T:
        self._ensure_open()
        attempts = MAX_RETRY_ATTEMPTS if retry else 1
        last_transport_error: TransportError | None = None
        for attempt in range(attempts):
            try:
                response = self._http.request(method, path, json=json, params=params)
            except httpx.RequestError as error:
                last_transport_error = TransportError(
                    "The Labtasker Server could not be reached.",
                    {"operation": operation, "url": self._config.url},
                )
                if attempt + 1 == attempts:
                    raise last_transport_error from error
            else:
                if response.is_error:
                    try:
                        api_error = _parse_api_error(response)
                    except TransportError as error:
                        last_transport_error = _with_operation(
                            error,
                            operation,
                            self._config.url,
                        )
                        if attempt + 1 == attempts:
                            raise last_transport_error from error
                        _backoff(attempt)
                        continue
                    if retry and api_error.code == "database_busy" and attempt + 1 < attempts:
                        _backoff(attempt)
                        continue
                    raise api_error
                try:
                    return parser(response)
                except TransportError as error:
                    last_transport_error = _with_operation(error, operation, self._config.url)
                    if attempt + 1 == attempts:
                        raise last_transport_error from error
            _backoff(attempt)
        if last_transport_error is None:
            raise AssertionError("Request loop ended without a result or error.")
        raise last_transport_error

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("Client is closed.")


def _parse_model(
    response: httpx.Response,
    model: type[ModelT],
    statuses: set[int],
) -> ModelT:
    _require_status(response, statuses)
    try:
        return model.model_validate_json(response.content, strict=True)
    except (ValidationError, ValueError, TypeError) as error:
        raise TransportError(
            "The Server returned an invalid success response.",
            {"http_status": response.status_code},
        ) from error


def _parse_queue_list(response: httpx.Response, statuses: set[int]) -> list[Queue]:
    _require_status(response, statuses)
    try:
        return QUEUE_LIST_ADAPTER.validate_json(response.content, strict=True)
    except (ValidationError, ValueError, TypeError) as error:
        raise TransportError(
            "The Server returned an invalid Queue list.",
            {"http_status": response.status_code},
        ) from error


def _parse_none(response: httpx.Response, statuses: set[int]) -> None:
    _require_status(response, statuses)
    if response.content:
        raise TransportError(
            "The Server returned an unexpected response body.",
            {"http_status": response.status_code},
        )


def _require_status(response: httpx.Response, statuses: set[int]) -> None:
    if response.status_code not in statuses:
        raise TransportError(
            "The Server returned an unexpected success status.",
            {"http_status": response.status_code},
        )


def _parse_api_error(response: httpx.Response) -> APIError:
    try:
        payload = response.json()
        if not isinstance(payload, dict) or set(payload) != {"error"}:
            raise ValueError
        error = payload["error"]
        if not isinstance(error, dict) or set(error) != {"code", "message", "details"}:
            raise ValueError
        code = error["code"]
        message = error["message"]
        details = error["details"]
        if not isinstance(code, str) or not isinstance(message, str):
            raise ValueError
        normalized_details = validate_json_object(details, field="error.details")
    except (ValueError, TypeError) as error:
        raise TransportError(
            "The Server returned an invalid error response.",
            {"http_status": response.status_code},
        ) from error
    return APIError(response.status_code, code, message, normalized_details)


def _with_operation(error: TransportError, operation: str, url: str) -> TransportError:
    return TransportError(error.message, {**error.details, "operation": operation, "url": url})


def _generate_task_id() -> str:
    return f"t_{secrets.token_urlsafe(9)}"


def _without_none(values: dict[str, str | int | None]) -> dict[str, str | int]:
    return {key: value for key, value in values.items() if value is not None}


def _backoff(attempt: int) -> None:
    if attempt < len(RETRY_BACKOFF_SECONDS):
        time.sleep(RETRY_BACKOFF_SECONDS[attempt])
