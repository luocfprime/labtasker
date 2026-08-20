from __future__ import annotations

import asyncio
import hmac
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text

from labtasker_server.config import ServerSettings
from labtasker_server.database import Database
from labtasker_server.errors import DomainError
from labtasker_server.middleware import RequestBodyLimitMiddleware
from labtasker_server.schemas import (
    BulkUpdateRequest,
    BulkUpdateResult,
    ClaimRequest,
    ClaimResponse,
    CompleteRequest,
    CountResponse,
    FailRequest,
    HeartbeatResponse,
    Queue,
    RunRequest,
    Task,
    TaskCreate,
    TaskOrderField,
    TaskPage,
    TaskStatus,
    TaskUpdate,
)
from labtasker_server.services.queues import QueueService
from labtasker_server.services.tasks import TaskService, system_now_us
from labtasker_server.validation import MAX_TASK_DATA_BYTES

EXPIRY_SCAN_INTERVAL_SECONDS = 60
logger = logging.getLogger(__name__)


def create_app(
    settings: ServerSettings,
    *,
    now_us: Callable[[], int] = system_now_us,
) -> FastAPI:
    database = Database(settings.database)
    database.initialize()
    queue_service = QueueService(database)
    task_service = TaskService(database, now_us=now_us)
    task_service.expire_leases()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        scanner = asyncio.create_task(_expiry_scanner(task_service))
        try:
            yield
        finally:
            scanner.cancel()
            with suppress(asyncio.CancelledError):
                await scanner
            database.dispose()

    app = FastAPI(docs_url=None, redoc_url=None, lifespan=lifespan)
    app.add_middleware(RequestBodyLimitMiddleware, max_bytes=MAX_TASK_DATA_BYTES)
    app.state.database = database
    app.state.settings = settings
    app.state.task_service = task_service

    @app.exception_handler(DomainError)
    async def handle_domain_error(_: Request, exc: DomainError) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        code, details = _validation_error(request, exc)
        if details is not None:
            return JSONResponse(
                status_code=422,
                content={
                    "error": {
                        "code": code,
                        "message": _specific_validation_message(code),
                        "details": details,
                    }
                },
            )
        errors = []
        for error in exc.errors():
            location = list(error.get("loc", ()))
            if not location:
                location = ["body"]
            errors.append(
                {
                    "location": location,
                    "message": str(error.get("msg", "Invalid value.")),
                }
            )
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": code,
                    "message": "Request validation failed.",
                    "details": {"errors": errors},
                }
            },
        )

    def require_auth(authorization: Annotated[str | None, Header()] = None) -> None:
        token = settings.token
        if token is None:
            return
        if authorization is None:
            raise _unauthorized()
        scheme, separator, credential = authorization.partition(" ")
        if separator != " " or scheme.lower() != "bearer" or not credential:
            raise _unauthorized()
        if not hmac.compare_digest(credential, token):
            raise _unauthorized()

    authenticated = [Depends(require_auth)]

    @app.get("/health")
    def health() -> JSONResponse:
        try:
            with database.read_session() as session:
                session.execute(text("SELECT 1"))
        except Exception:
            return JSONResponse(
                status_code=503,
                content={"status": "error", "api_version": "2", "database": "error"},
            )
        return JSONResponse(
            status_code=200,
            content={"status": "ok", "api_version": "2", "database": "ok"},
        )

    @app.put("/api/v2/queues/{queue}", response_model=Queue, dependencies=authenticated)
    def create_queue(queue: str, response: Response) -> Queue:
        result, created = queue_service.create(queue)
        response.status_code = 201 if created else 200
        return result

    @app.get("/api/v2/queues", response_model=list[Queue], dependencies=authenticated)
    def list_queues() -> list[Queue]:
        return queue_service.list()

    @app.delete("/api/v2/queues/{queue}", status_code=204, dependencies=authenticated)
    def delete_queue(queue: str, cascade: bool = False) -> Response:
        queue_service.delete(queue, cascade=cascade)
        return Response(status_code=204)

    @app.put(
        "/api/v2/queues/{queue}/tasks/{task_id}",
        response_model=Task,
        dependencies=authenticated,
    )
    def create_task(queue: str, task_id: str, request: TaskCreate, response: Response) -> Task:
        result, created = task_service.create(queue, task_id, request)
        response.status_code = 201 if created else 200
        return result

    @app.get(
        "/api/v2/queues/{queue}/tasks",
        response_model=TaskPage,
        dependencies=authenticated,
    )
    def list_tasks(
        queue: str,
        status: TaskStatus | None = None,
        name: str | None = None,
        filter_expression: Annotated[str | None, Query(alias="filter")] = None,
        order_by: TaskOrderField = "created_at",
        descending: bool = True,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
        cursor: str | None = None,
    ) -> TaskPage:
        return task_service.list_tasks(
            queue,
            status=status,
            name=name,
            filter_expression=filter_expression,
            order_by=order_by,
            descending=descending,
            limit=limit,
            cursor=cursor,
        )

    @app.get(
        "/api/v2/queues/{queue}/tasks/count",
        response_model=CountResponse,
        dependencies=authenticated,
    )
    def count_tasks(
        queue: str,
        status: TaskStatus | None = None,
        name: str | None = None,
        filter_expression: Annotated[str | None, Query(alias="filter")] = None,
    ) -> CountResponse:
        return CountResponse(
            count=task_service.count_tasks(
                queue,
                status=status,
                name=name,
                filter_expression=filter_expression,
            )
        )

    @app.get(
        "/api/v2/queues/{queue}/tasks/{task_id}",
        response_model=Task,
        dependencies=authenticated,
    )
    def get_task(queue: str, task_id: str) -> Task:
        return task_service.get(queue, task_id)

    @app.patch(
        "/api/v2/queues/{queue}/tasks/{task_id}",
        response_model=Task,
        dependencies=authenticated,
    )
    def update_task(queue: str, task_id: str, changes: TaskUpdate) -> Task:
        return task_service.update_task(queue, task_id, changes)

    @app.patch(
        "/api/v2/queues/{queue}/tasks",
        response_model=BulkUpdateResult,
        dependencies=authenticated,
    )
    def update_tasks(queue: str, request: BulkUpdateRequest) -> BulkUpdateResult:
        return task_service.update_tasks(
            queue,
            filter_expression=request.filter,
            changes=request.changes,
        )

    @app.post(
        "/api/v2/queues/{queue}/tasks/claim",
        response_model=ClaimResponse,
        dependencies=authenticated,
    )
    def claim_task(queue: str, request: ClaimRequest) -> ClaimResponse | Response:
        claim = task_service.claim(queue, request.route, request.run_id)
        return Response(status_code=204) if claim is None else claim

    @app.post(
        "/api/v2/queues/{queue}/tasks/{task_id}/heartbeat",
        response_model=HeartbeatResponse,
        dependencies=authenticated,
    )
    def heartbeat(queue: str, task_id: str, request: RunRequest) -> HeartbeatResponse:
        return task_service.heartbeat(queue, task_id, request.run_id)

    @app.post(
        "/api/v2/queues/{queue}/tasks/{task_id}/complete",
        status_code=204,
        dependencies=authenticated,
    )
    def complete(queue: str, task_id: str, request: CompleteRequest) -> Response:
        task_service.complete(queue, task_id, request.run_id, request.result)
        return Response(status_code=204)

    @app.post(
        "/api/v2/queues/{queue}/tasks/{task_id}/fail",
        status_code=204,
        dependencies=authenticated,
    )
    def fail(queue: str, task_id: str, request: FailRequest) -> Response:
        task_service.fail(queue, task_id, request.run_id, request.error)
        return Response(status_code=204)

    @app.post(
        "/api/v2/queues/{queue}/tasks/{task_id}/unclaim",
        status_code=204,
        dependencies=authenticated,
    )
    def unclaim(queue: str, task_id: str, request: RunRequest) -> Response:
        task_service.unclaim(queue, task_id, request.run_id)
        return Response(status_code=204)

    @app.post(
        "/api/v2/queues/{queue}/tasks/{task_id}/cancel",
        response_model=Task,
        dependencies=authenticated,
    )
    def cancel_task(queue: str, task_id: str) -> Task:
        return task_service.cancel(queue, task_id)

    @app.post(
        "/api/v2/queues/{queue}/tasks/{task_id}/requeue",
        response_model=Task,
        dependencies=authenticated,
    )
    def requeue_task(queue: str, task_id: str) -> Task:
        return task_service.requeue(queue, task_id)

    @app.delete(
        "/api/v2/queues/{queue}/tasks/{task_id}",
        status_code=204,
        dependencies=authenticated,
    )
    def delete_task(queue: str, task_id: str) -> Response:
        task_service.delete(queue, task_id)
        return Response(status_code=204)

    return app


async def _expiry_scanner(task_service: TaskService) -> None:
    while True:
        await asyncio.sleep(EXPIRY_SCAN_INTERVAL_SECONDS)
        try:
            await asyncio.to_thread(task_service.expire_leases)
        except Exception:
            logger.exception("Heartbeat expiry scan failed; it will retry in 60 seconds.")


def _unauthorized() -> DomainError:
    return DomainError(401, "unauthorized", "Authentication is required.", {})


def _validation_code(request: Request) -> str:
    if request.method == "PUT" and "/tasks/" in request.url.path:
        return "invalid_task"
    if request.method == "PATCH" and "/tasks" in request.url.path:
        return "invalid_update"
    return "invalid_request"


def _validation_error(
    request: Request,
    exc: RequestValidationError,
) -> tuple[str, dict[str, object] | None]:
    for error in exc.errors():
        error_type = str(error.get("type", ""))
        if error_type in {"invalid_task_name", "json_too_deep"}:
            context = error.get("ctx")
            return error_type, dict(context) if isinstance(context, dict) else {}
    if request.method == "PATCH" and request.url.path.endswith("/tasks"):
        for error in exc.errors():
            location = tuple(error.get("loc", ()))
            if location[:2] == ("body", "filter"):
                return "invalid_filter", None
    return _validation_code(request), None


def _specific_validation_message(code: str) -> str:
    if code == "json_too_deep":
        return "JSON value is too deeply nested."
    if code == "invalid_task_name":
        return "Task name is invalid."
    raise AssertionError(f"Unknown specific validation code: {code}")
