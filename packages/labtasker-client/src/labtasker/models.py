from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from labtasker.types import JSONValue, TaskStatus
from labtasker.validation import (
    validate_identifier,
    validate_int64,
    validate_json_object,
    validate_routes,
    validate_run_id,
    validate_task_id,
    validate_task_name,
    validate_unicode_scalar,
)

UTC = timezone.utc


class ResponseModel(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)


class LastError(ResponseModel):
    type: str
    message: str
    traceback: str | None
    occurred_at: datetime
    attempt: int
    run_id: str

    @field_validator("type", "message", "traceback")
    @classmethod
    def validate_strings(cls, value: str | None, info: object) -> str | None:
        if value is None:
            return None
        return validate_unicode_scalar(value, field=getattr(info, "field_name", "last_error"))

    @field_validator("occurred_at")
    @classmethod
    def validate_time(cls, value: datetime) -> datetime:
        return _utc_datetime(value)

    @field_validator("attempt")
    @classmethod
    def validate_attempt(cls, value: int) -> int:
        return validate_int64(value, field="attempt")

    @field_validator("run_id")
    @classmethod
    def validate_run(cls, value: str) -> str:
        return validate_run_id(value)


class Task(ResponseModel):
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
    progress: dict[str, JSONValue] | None = None
    progress_updated_at: datetime | None = None
    progress_attempt: int | None = None
    last_error: LastError | None
    last_route: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return validate_task_id(value)

    @field_validator("queue")
    @classmethod
    def validate_queue(cls, value: str) -> str:
        return validate_identifier(value, field="queue")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        return validate_task_name(value)

    @field_validator("args", "metadata", "result", "progress")
    @classmethod
    def validate_objects(
        cls,
        value: dict[str, JSONValue] | None,
        info: object,
    ) -> dict[str, JSONValue] | None:
        if value is None:
            return None
        return validate_json_object(value, field=getattr(info, "field_name", "task"))

    @field_validator("priority", "attempt")
    @classmethod
    def validate_numbers(cls, value: int, info: object) -> int:
        return validate_int64(value, field=getattr(info, "field_name", "task"))

    @field_validator("progress_attempt")
    @classmethod
    def validate_progress_attempt(cls, value: int | None) -> int | None:
        if value is None:
            return None
        value = validate_int64(value, field="progress_attempt")
        if value < 0:
            raise ValueError("progress_attempt must be non-negative")
        return value

    @model_validator(mode="after")
    def validate_progress_fields(self) -> Task:
        fields = (self.progress, self.progress_updated_at, self.progress_attempt)
        if any(value is None for value in fields) and any(value is not None for value in fields):
            raise ValueError("progress fields must be all null or all present")
        return self

    @field_validator("max_attempts")
    @classmethod
    def validate_max_attempts(cls, value: int) -> int:
        return validate_int64(value, field="max_attempts", positive=True)

    @field_validator("routes")
    @classmethod
    def validate_task_routes(cls, value: list[str]) -> list[str]:
        routes = validate_routes(value)
        if value != routes:
            raise ValueError("routes must be sorted lexicographically")
        return routes

    @field_validator("last_route")
    @classmethod
    def validate_last_route(cls, value: str | None) -> str | None:
        return None if value is None else validate_identifier(value, field="last_route")

    @field_validator(
        "created_at",
        "updated_at",
        "started_at",
        "finished_at",
        "progress_updated_at",
    )
    @classmethod
    def validate_times(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc_datetime(value)


class TaskInfo(Task):
    run_id: str
    run_dir: Path

    @field_validator("run_id")
    @classmethod
    def validate_run(cls, value: str) -> str:
        return validate_run_id(value)

    @field_validator("run_dir")
    @classmethod
    def validate_run_dir(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("run_dir must be absolute")
        return value


class TaskPage(ResponseModel):
    items: list[Task]
    next_cursor: str | None


class ClaimResponse(ResponseModel):
    task: Task
    run_id: str
    lease_expires_at: datetime

    @field_validator("run_id")
    @classmethod
    def validate_run(cls, value: str) -> str:
        return validate_run_id(value)

    @field_validator("lease_expires_at")
    @classmethod
    def validate_lease_expires_at(cls, value: datetime) -> datetime:
        return _utc_datetime(value)


class HeartbeatResponse(ResponseModel):
    lease_expires_at: datetime

    @field_validator("lease_expires_at")
    @classmethod
    def validate_lease_expires_at(cls, value: datetime) -> datetime:
        return _utc_datetime(value)


class HealthResponse(ResponseModel):
    status: Literal["ok"]
    api_version: Literal["2"]
    database: Literal["ok"]


class Queue(ResponseModel):
    name: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return validate_identifier(value, field="queue")


class BulkUpdateResult(ResponseModel):
    matched: int
    updated: int

    @field_validator("matched", "updated")
    @classmethod
    def validate_count(cls, value: int, info: object) -> int:
        value = validate_int64(value, field=getattr(info, "field_name", "count"))
        if value < 0:
            raise ValueError("count must be non-negative")
        return value


class CountResponse(ResponseModel):
    count: int

    @field_validator("count")
    @classmethod
    def validate_count(cls, value: int) -> int:
        value = validate_int64(value, field="count")
        if value < 0:
            raise ValueError("count must be non-negative")
        return value


def _utc_datetime(value: datetime) -> datetime:
    offset = value.utcoffset()
    if value.tzinfo is None or offset is None:
        raise ValueError("timestamp must be timezone-aware")
    if offset.total_seconds() != 0:
        raise ValueError("timestamp must use UTC")
    return value.astimezone(UTC)


class CountGroup(ResponseModel):
    key: dict[str, str]
    count: int

    @model_validator(mode="after")
    def validate_group(self) -> CountGroup:
        if not self.key or self.count <= 0:
            raise ValueError("A count group must have a key and a positive count.")
        return self


class GroupCountPage(ResponseModel):
    group_by: list[str]
    count: int
    items: list[CountGroup]
    next_cursor: str | None

    @model_validator(mode="after")
    def validate_page(self) -> GroupCountPage:
        if not self.group_by or len(set(self.group_by)) != len(self.group_by) or self.count < 0:
            raise ValueError("Invalid grouping or total count.")
        seen: set[tuple[str, ...]] = set()
        for item in self.items:
            if set(item.key) != set(self.group_by) or item.count > self.count:
                raise ValueError("Group keys/count do not match the page.")
            key = tuple(item.key[field] for field in self.group_by)
            if key in seen:
                raise ValueError("Duplicate group key.")
            seen.add(key)
        return self


class WorkerObservation(ResponseModel):
    id: str
    queue: str
    route: str
    status: Literal["idle", "busy"]
    task_id: str | None
    last_seen_at: datetime
    expires_at: datetime

    @field_validator("id")
    @classmethod
    def validate_worker(cls, value: str) -> str:
        from labtasker.validation import validate_worker_id

        return validate_worker_id(value)

    @field_validator("queue", "route")
    @classmethod
    def validate_label(cls, value: str, info: object) -> str:
        return validate_identifier(value, field=getattr(info, "field_name", "Worker"))

    @field_validator("task_id")
    @classmethod
    def validate_task(cls, value: str | None) -> str | None:
        return None if value is None else validate_task_id(value)

    @field_validator("last_seen_at", "expires_at")
    @classmethod
    def validate_time(cls, value: datetime) -> datetime:
        return _utc_datetime(value)


class WorkerPage(ResponseModel):
    items: list[WorkerObservation]
    next_cursor: str | None
