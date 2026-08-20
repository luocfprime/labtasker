from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator
from pydantic_core import PydanticCustomError

from labtasker_server.errors import DomainError
from labtasker_server.validation import (
    INT64_MAX,
    INT64_MIN,
    JSONValue,
    canonical_routes,
    validate_identifier,
    validate_json_object,
    validate_run_id,
    validate_task_name,
    validate_unicode_scalar,
)

TaskStatus = Literal["pending", "running", "succeeded", "failed", "cancelled"]
TaskOrderField = Literal[
    "id",
    "name",
    "status",
    "priority",
    "attempt",
    "max_attempts",
    "last_route",
    "created_at",
    "updated_at",
    "started_at",
    "finished_at",
]
Int64 = Annotated[StrictInt, Field(ge=INT64_MIN, le=INT64_MAX)]
PositiveInt64 = Annotated[StrictInt, Field(ge=1, le=INT64_MAX)]
T = TypeVar("T")
OMITTED: Any = None


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Queue(StrictModel):
    name: str


class LastError(StrictModel):
    type: str
    message: str
    traceback: str | None
    occurred_at: datetime
    attempt: int
    run_id: str


class Task(StrictModel):
    id: str
    queue: str
    status: TaskStatus
    name: str | None
    args: dict[str, JSONValue]
    metadata: dict[str, JSONValue]
    priority: int
    attempt: int
    max_attempts: int
    routes: list[str]
    result: dict[str, JSONValue]
    last_error: LastError | None
    last_route: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class TaskCreate(StrictModel):
    name: str | None = None
    args: dict[str, JSONValue] = Field(default_factory=dict)
    metadata: dict[str, JSONValue] = Field(default_factory=dict)
    priority: Int64 = 0
    max_attempts: PositiveInt64 = 3
    routes: list[str] = Field(default_factory=lambda: ["default"])

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        try:
            return validate_task_name(value)
        except DomainError as error:
            raise _pydantic_error(error) from error

    @field_validator("args", "metadata")
    @classmethod
    def validate_objects(cls, value: dict[str, JSONValue], info: object) -> dict[str, JSONValue]:
        field_name = getattr(info, "field_name", "value")
        try:
            return validate_json_object(value, field=field_name)
        except DomainError as error:
            raise _pydantic_error(error) from error

    @field_validator("routes")
    @classmethod
    def validate_routes(cls, value: list[str]) -> list[str]:
        try:
            return canonical_routes(value)
        except DomainError as error:
            raise _pydantic_error(error) from error


class TaskUpdate(StrictModel):
    name: str | None = None
    args: dict[str, JSONValue] = OMITTED
    metadata: dict[str, JSONValue] = OMITTED
    priority: Int64 = OMITTED
    max_attempts: PositiveInt64 = OMITTED
    routes: list[str] = OMITTED
    result: dict[str, JSONValue] = OMITTED

    @model_validator(mode="after")
    def validate_nonempty(self) -> TaskUpdate:
        if not self.model_fields_set:
            raise PydanticCustomError("invalid_update", "Update must contain at least one field.")
        return self

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        return _validated(lambda: validate_task_name(value))

    @field_validator("args", "metadata", "result")
    @classmethod
    def validate_objects(
        cls,
        value: dict[str, JSONValue],
        info: object,
    ) -> dict[str, JSONValue]:
        field_name = getattr(info, "field_name", "value")
        return _validated(lambda: validate_json_object(value, field=field_name))

    @field_validator("routes")
    @classmethod
    def validate_routes(cls, value: list[str]) -> list[str]:
        return _validated(lambda: canonical_routes(value))


class BulkUpdateRequest(StrictModel):
    filter: str
    changes: TaskUpdate


class BulkUpdateResult(StrictModel):
    matched: int
    updated: int


class TaskPage(StrictModel):
    items: list[Task]
    next_cursor: str | None


class CountResponse(StrictModel):
    count: int


class ClaimRequest(StrictModel):
    route: str
    run_id: str

    @field_validator("route")
    @classmethod
    def validate_route(cls, value: str) -> str:
        return _validated(lambda: validate_identifier(value, kind="Route"))

    @field_validator("run_id")
    @classmethod
    def validate_run(cls, value: str) -> str:
        return _validated(lambda: validate_run_id(value))


class ClaimResponse(StrictModel):
    task: Task
    run_id: str
    lease_expires_at: datetime


class RunRequest(StrictModel):
    run_id: str

    @field_validator("run_id")
    @classmethod
    def validate_run(cls, value: str) -> str:
        return _validated(lambda: validate_run_id(value))


class HeartbeatResponse(StrictModel):
    lease_expires_at: datetime


class CompleteRequest(RunRequest):
    result: dict[str, JSONValue]

    @field_validator("result")
    @classmethod
    def validate_result(cls, value: dict[str, JSONValue]) -> dict[str, JSONValue]:
        return _validated(lambda: validate_json_object(value, field="result"))


class FailureReport(StrictModel):
    type: str
    message: str
    traceback: str | None

    @field_validator("type", "message", "traceback")
    @classmethod
    def validate_strings(cls, value: str | None, info: object) -> str | None:
        if value is None:
            return None
        field_name = getattr(info, "field_name", "error")
        return _validated(lambda: validate_unicode_scalar(value, field=field_name))


class FailRequest(RunRequest):
    error: FailureReport


class ErrorItem(StrictModel):
    location: list[str | int]
    message: str


class ErrorBody(StrictModel):
    code: str
    message: str
    details: dict[str, JSONValue]


class ErrorEnvelope(StrictModel):
    error: ErrorBody


class HealthyResponse(StrictModel):
    status: Literal["ok"]
    api_version: Literal["2"]
    database: Literal["ok"]


class UnhealthyResponse(StrictModel):
    status: Literal["error"]
    api_version: Literal["2"]
    database: Literal["error"]


def _pydantic_error(error: DomainError) -> PydanticCustomError:
    return PydanticCustomError(error.code, error.message, error.details)


def _validated(operation: Callable[[], T]) -> T:
    try:
        return operation()
    except DomainError as error:
        raise _pydantic_error(error) from error
