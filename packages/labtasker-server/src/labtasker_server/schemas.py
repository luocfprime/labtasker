from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator
from pydantic_core import PydanticCustomError

from labtasker_server.errors import DomainError
from labtasker_server.validation import (
    INT64_MAX,
    INT64_MIN,
    JSONValue,
    canonical_routes,
    validate_json_object,
    validate_task_name,
)

TaskStatus = Literal["pending", "running", "succeeded", "failed", "cancelled"]
Int64 = Annotated[StrictInt, Field(ge=INT64_MIN, le=INT64_MAX)]
PositiveInt64 = Annotated[StrictInt, Field(ge=1, le=INT64_MAX)]


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


class ErrorItem(StrictModel):
    location: list[str | int]
    message: str


class ErrorBody(StrictModel):
    code: str
    message: str
    details: dict[str, JSONValue]


class ErrorEnvelope(StrictModel):
    error: ErrorBody


def _pydantic_error(error: DomainError) -> PydanticCustomError:
    return PydanticCustomError(error.code, error.message, error.details)
