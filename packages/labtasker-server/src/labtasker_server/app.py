from __future__ import annotations

import hmac
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text

from labtasker_server.config import ServerSettings
from labtasker_server.database import Database
from labtasker_server.errors import DomainError
from labtasker_server.middleware import RequestBodyLimitMiddleware
from labtasker_server.schemas import Queue, Task, TaskCreate
from labtasker_server.services.queues import QueueService
from labtasker_server.services.tasks import TaskService
from labtasker_server.validation import MAX_TASK_DATA_BYTES


def create_app(settings: ServerSettings) -> FastAPI:
    database = Database(settings.database)
    database.initialize()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        database.dispose()

    app = FastAPI(docs_url=None, redoc_url=None, lifespan=lifespan)
    app.add_middleware(RequestBodyLimitMiddleware, max_bytes=MAX_TASK_DATA_BYTES)
    app.state.database = database
    app.state.settings = settings
    queue_service = QueueService(database)
    task_service = TaskService(database)

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
        "/api/v2/queues/{queue}/tasks/{task_id}",
        response_model=Task,
        dependencies=authenticated,
    )
    def get_task(queue: str, task_id: str) -> Task:
        return task_service.get(queue, task_id)

    return app


def _unauthorized() -> DomainError:
    return DomainError(401, "unauthorized", "Authentication is required.", {})


def _validation_code(request: Request) -> str:
    if request.method == "PUT" and "/tasks/" in request.url.path:
        return "invalid_task"
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
    return _validation_code(request), None


def _specific_validation_message(code: str) -> str:
    if code == "json_too_deep":
        return "JSON value is too deeply nested."
    if code == "invalid_task_name":
        return "Task name is invalid."
    raise AssertionError(f"Unknown specific validation code: {code}")
