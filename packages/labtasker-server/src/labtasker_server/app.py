from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from starlette.exceptions import HTTPException

from labtasker_server import __version__
from labtasker_server.config import ServerSettings
from labtasker_server.database import Database
from labtasker_server.errors import DomainError
from labtasker_server.grouping import request_error
from labtasker_server.middleware import (
    RequestBodyLimitMiddleware,
    ServerVersionMiddleware,
    is_authenticated,
)
from labtasker_server.schemas import (
    BulkUpdateRequest,
    BulkUpdateResult,
    ClaimRequest,
    ClaimResponse,
    CompleteRequest,
    CountResponse,
    ErrorEnvelope,
    FailRequest,
    GroupCountPage,
    HealthyResponse,
    HeartbeatResponse,
    ProgressRequest,
    Queue,
    RunRequest,
    Task,
    TaskCreate,
    TaskOrderField,
    TaskPage,
    TaskStatus,
    TaskUpdate,
    UnhealthyResponse,
    WorkerPage,
    WorkerReport,
    WorkerTelemetryReport,
)
from labtasker_server.services.queues import QueueService
from labtasker_server.services.tasks import TaskService, system_now_us
from labtasker_server.services.workers import WorkerService
from labtasker_server.validation import MAX_JSON_DEPTH, MAX_TASK_DATA_BYTES

EXPIRY_SCAN_INTERVAL_SECONDS = 60
logger = logging.getLogger(__name__)
BEARER = HTTPBearer(auto_error=False)
API_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorEnvelope} for status in (401, 404, 409, 413, 422, 503)
}


def create_app(
    settings: ServerSettings,
    *,
    now_us: Callable[[], int] = system_now_us,
) -> FastAPI:
    database = Database(settings.database, ownership_fd=settings.database_fd)
    try:
        database.initialize()
        queue_service = QueueService(database)
        task_service = TaskService(database, now_us=now_us)
        task_service.expire_leases()
        worker_service = WorkerService(database, now_us=now_us)
        worker_service.expire()
    except BaseException:
        database.dispose()
        raise

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        scanner = asyncio.create_task(_expiry_scanner(task_service, worker_service))
        try:
            yield
        finally:
            scanner.cancel()
            with suppress(asyncio.CancelledError):
                await scanner
            database.dispose()

    app = FastAPI(docs_url=None, redoc_url=None, lifespan=lifespan)
    app.add_middleware(RequestBodyLimitMiddleware, max_bytes=MAX_TASK_DATA_BYTES)
    app.add_middleware(ServerVersionMiddleware, version=__version__, token=settings.token)
    app.state.database = database
    app.state.settings = settings
    app.state.task_service = task_service
    app.state.worker_service = worker_service

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
                        "message": (
                            "Request validation failed."
                            if code == "invalid_request"
                            else _specific_validation_message(code)
                        ),
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

    @app.exception_handler(HTTPException)
    async def handle_http_error(request: Request, exc: HTTPException) -> Response:
        # FastAPI wraps decoder limits and invalid byte encodings in HTTP 400
        # before Pydantic sees the body. Keep those in the validation contract.
        if (
            exc.status_code == 400
            and exc.detail == "There was an error parsing the body"
            and isinstance(exc.__cause__, (ValueError, RecursionError))
        ):
            if isinstance(exc.__cause__, RecursionError):
                error = DomainError(
                    422,
                    "json_too_deep",
                    "JSON value is too deeply nested.",
                    {"max_depth": MAX_JSON_DEPTH},
                )
            else:
                error = DomainError(
                    422,
                    "invalid_request",
                    "Request validation failed.",
                    {"errors": [{"location": ["body"], "message": "Malformed JSON body."}]},
                )
            return await handle_domain_error(request, error)
        return await http_exception_handler(request, exc)

    def require_auth(
        request: Request,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(BEARER)],
    ) -> None:
        if not is_authenticated(request.headers.get("authorization"), settings.token):
            raise _unauthorized()

    authenticated = [Depends(require_auth)]

    @app.get(
        "/health",
        response_model=HealthyResponse,
        responses={503: {"model": UnhealthyResponse}},
    )
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

    @app.put(
        "/api/v2/queues/{queue}",
        response_model=Queue,
        dependencies=authenticated,
        responses={**API_ERROR_RESPONSES, 201: {"model": Queue}},
    )
    def create_queue(queue: str, response: Response) -> Queue:
        result, created = queue_service.create(queue)
        response.status_code = 201 if created else 200
        return result

    @app.get(
        "/api/v2/queues",
        response_model=list[Queue],
        dependencies=authenticated,
        responses=API_ERROR_RESPONSES,
    )
    def list_queues() -> list[Queue]:
        return queue_service.list()

    @app.delete(
        "/api/v2/queues/{queue}",
        status_code=204,
        dependencies=authenticated,
        responses=API_ERROR_RESPONSES,
    )
    def delete_queue(queue: str, cascade: bool = False) -> Response:
        queue_service.delete(queue, cascade=cascade)
        return Response(status_code=204)

    @app.put(
        "/api/v2/queues/{queue}/tasks/{task_id}",
        response_model=Task,
        dependencies=authenticated,
        responses={**API_ERROR_RESPONSES, 201: {"model": Task}},
    )
    def create_task(queue: str, task_id: str, request: TaskCreate, response: Response) -> Task:
        result, created = task_service.create(queue, task_id, request)
        response.status_code = 201 if created else 200
        return result

    @app.get(
        "/api/v2/queues/{queue}/tasks",
        response_model=TaskPage,
        dependencies=authenticated,
        responses=API_ERROR_RESPONSES,
    )
    def list_tasks(
        queue: str,
        status: TaskStatus | None = None,
        name: str | None = None,
        name_fuzzy: str | None = None,
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
            name_fuzzy=name_fuzzy,
            filter_expression=filter_expression,
            order_by=order_by,
            descending=descending,
            limit=limit,
            cursor=cursor,
        )

    @app.get(
        "/api/v2/queues/{queue}/tasks/count",
        response_model=CountResponse | GroupCountPage,
        dependencies=authenticated,
        responses=API_ERROR_RESPONSES,
    )
    def count_tasks(
        request: Request,
        queue: str,
        status: TaskStatus | None = None,
        name: str | None = None,
        name_fuzzy: str | None = None,
        filter_expression: Annotated[str | None, Query(alias="filter")] = None,
        group_by: str | None = None,
        limit: Annotated[int | None, Query(ge=1, le=1000)] = None,
        cursor: str | None = None,
    ) -> CountResponse | GroupCountPage:
        _single_grouping(request)
        result = task_service.count_tasks(
            queue,
            status=status,
            name=name,
            name_fuzzy=name_fuzzy,
            filter_expression=filter_expression,
            group_by=group_by,
            limit=limit,
            cursor=cursor,
        )
        return CountResponse(count=result) if isinstance(result, int) else result

    @app.get(
        "/api/v2/queues/{queue}/workers",
        response_model=WorkerPage,
        dependencies=authenticated,
        responses=API_ERROR_RESPONSES,
    )
    def list_workers(
        queue: str,
        filter_expression: Annotated[str | None, Query(alias="filter")] = None,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
        cursor: str | None = None,
    ) -> WorkerPage:
        return worker_service.list(
            queue, filter_expression=filter_expression, limit=limit, cursor=cursor
        )

    @app.get(
        "/api/v2/queues/{queue}/workers/count",
        response_model=CountResponse | GroupCountPage,
        dependencies=authenticated,
        responses=API_ERROR_RESPONSES,
    )
    def count_workers(
        request: Request,
        queue: str,
        filter_expression: Annotated[str | None, Query(alias="filter")] = None,
        group_by: str | None = None,
        limit: Annotated[int | None, Query(ge=1, le=1000)] = None,
        cursor: str | None = None,
    ) -> CountResponse | GroupCountPage:
        _single_grouping(request)
        result = worker_service.count(
            queue,
            filter_expression=filter_expression,
            group_by=group_by,
            limit=limit,
            cursor=cursor,
        )
        return CountResponse(count=result) if isinstance(result, int) else result

    @app.put(
        "/api/v2/queues/{queue}/workers/{id}",
        status_code=204,
        dependencies=authenticated,
        responses=API_ERROR_RESPONSES,
    )
    def report_worker(queue: str, id: str, report: WorkerReport) -> Response:
        worker_service.report(queue, id, report)
        return Response(status_code=204)

    @app.post(
        "/api/v2/queues/{queue}/workers/{id}/telemetry",
        status_code=204,
        dependencies=authenticated,
        responses=API_ERROR_RESPONSES,
    )
    def report_worker_telemetry(queue: str, id: str, report: WorkerTelemetryReport) -> Response:
        worker_service.report_telemetry(queue, id, report)
        return Response(status_code=204)

    @app.delete(
        "/api/v2/queues/{queue}/workers/{id}",
        status_code=204,
        dependencies=authenticated,
        responses=API_ERROR_RESPONSES,
    )
    def withdraw_worker(queue: str, id: str) -> Response:
        worker_service.withdraw(queue, id)
        return Response(status_code=204)

    @app.get(
        "/api/v2/queues/{queue}/tasks/{task_id}",
        response_model=Task,
        dependencies=authenticated,
        responses=API_ERROR_RESPONSES,
    )
    def get_task(queue: str, task_id: str) -> Task:
        return task_service.get(queue, task_id)

    @app.patch(
        "/api/v2/queues/{queue}/tasks/{task_id}",
        response_model=Task,
        dependencies=authenticated,
        responses=API_ERROR_RESPONSES,
    )
    def update_task(queue: str, task_id: str, changes: TaskUpdate) -> Task:
        return task_service.update_task(queue, task_id, changes)

    @app.patch(
        "/api/v2/queues/{queue}/tasks",
        response_model=BulkUpdateResult,
        dependencies=authenticated,
        responses=API_ERROR_RESPONSES,
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
        responses={**API_ERROR_RESPONSES, 204: {"description": "No eligible Task."}},
    )
    def claim_task(queue: str, request: ClaimRequest) -> ClaimResponse | Response:
        claim = task_service.claim(queue, request.route, request.run_id)
        return Response(status_code=204) if claim is None else claim

    @app.post(
        "/api/v2/queues/{queue}/tasks/{task_id}/heartbeat",
        response_model=HeartbeatResponse,
        dependencies=authenticated,
        responses=API_ERROR_RESPONSES,
    )
    def heartbeat(queue: str, task_id: str, request: RunRequest) -> HeartbeatResponse:
        return task_service.heartbeat(queue, task_id, request.run_id)

    @app.post(
        "/api/v2/queues/{queue}/tasks/{task_id}/progress",
        status_code=204,
        dependencies=authenticated,
        responses=API_ERROR_RESPONSES,
    )
    def report_progress(queue: str, task_id: str, request: ProgressRequest) -> Response:
        task_service.report_progress(queue, task_id, request.run_id, request.progress)
        return Response(status_code=204)

    @app.post(
        "/api/v2/queues/{queue}/tasks/{task_id}/complete",
        status_code=204,
        dependencies=authenticated,
        responses=API_ERROR_RESPONSES,
    )
    def complete(queue: str, task_id: str, request: CompleteRequest) -> Response:
        task_service.complete(queue, task_id, request.run_id, request.result)
        return Response(status_code=204)

    @app.post(
        "/api/v2/queues/{queue}/tasks/{task_id}/fail",
        status_code=204,
        dependencies=authenticated,
        responses=API_ERROR_RESPONSES,
    )
    def fail(queue: str, task_id: str, request: FailRequest) -> Response:
        task_service.fail(queue, task_id, request.run_id, request.error)
        return Response(status_code=204)

    @app.post(
        "/api/v2/queues/{queue}/tasks/{task_id}/unclaim",
        status_code=204,
        dependencies=authenticated,
        responses=API_ERROR_RESPONSES,
    )
    def unclaim(queue: str, task_id: str, request: RunRequest) -> Response:
        task_service.unclaim(queue, task_id, request.run_id)
        return Response(status_code=204)

    @app.post(
        "/api/v2/queues/{queue}/tasks/{task_id}/cancel",
        response_model=Task,
        dependencies=authenticated,
        responses=API_ERROR_RESPONSES,
    )
    def cancel_task(queue: str, task_id: str) -> Task:
        return task_service.cancel(queue, task_id)

    @app.post(
        "/api/v2/queues/{queue}/tasks/{task_id}/requeue",
        response_model=Task,
        dependencies=authenticated,
        responses=API_ERROR_RESPONSES,
    )
    def requeue_task(queue: str, task_id: str) -> Task:
        return task_service.requeue(queue, task_id)

    @app.delete(
        "/api/v2/queues/{queue}/tasks/{task_id}",
        status_code=204,
        dependencies=authenticated,
        responses=API_ERROR_RESPONSES,
    )
    def delete_task(queue: str, task_id: str) -> Response:
        task_service.delete(queue, task_id)
        return Response(status_code=204)

    for route in app.routes:
        if isinstance(route, APIRoute) and route.path.startswith("/api/"):
            for status in {route.status_code or 200, *route.responses}:
                if str(status) == "401":
                    continue
                route.responses.setdefault(status, {}).setdefault("headers", {})[
                    "Labtasker-Server-Version"
                ] = {
                    "description": "Server package version; present only with valid credentials "
                    "when authentication is enabled.",
                    "schema": {"type": "string"},
                }
    return app


async def _expiry_scanner(task_service: TaskService, worker_service: WorkerService) -> None:
    while True:
        await asyncio.sleep(EXPIRY_SCAN_INTERVAL_SECONDS)
        scan = asyncio.create_task(asyncio.to_thread(_expire_records, task_service, worker_service))
        try:
            await asyncio.shield(scan)
        except asyncio.CancelledError:
            # Cancelling to_thread cannot stop its database command. Keep the
            # ownership descriptor until that command has actually finished.
            with suppress(Exception):
                await scan
            raise
        except Exception:
            logger.exception("Heartbeat expiry scan failed; it will retry in 60 seconds.")


def _expire_records(task_service: TaskService, worker_service: WorkerService) -> None:
    task_service.expire_leases()
    worker_service.expire()


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
        if error_type == "recursion_loop":
            # A JSON body cannot contain reference cycles. This is Pydantic's
            # own nesting limit, reached before the domain depth validator.
            return "json_too_deep", {"max_depth": MAX_JSON_DEPTH}
        if error_type == "json_invalid":
            return "invalid_request", {
                "errors": [{"location": ["body"], "message": "Malformed JSON body."}]
            }
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


def _single_grouping(request: Request) -> None:
    if len(request.query_params.getlist("group_by")) > 1:
        request_error("group_by", "Specify group_by only once.")
