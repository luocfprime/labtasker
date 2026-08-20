from __future__ import annotations

from typing import Literal, TypeAlias, TypedDict

from pydantic import JsonValue as PydanticJSONValue

JSONValue: TypeAlias = PydanticJSONValue
TaskStatus: TypeAlias = Literal["pending", "running", "succeeded", "failed", "cancelled"]
TaskOrderField: TypeAlias = Literal[
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


class TaskUpdate(TypedDict, total=False):
    name: str | None
    args: dict[str, JSONValue]
    metadata: dict[str, JSONValue]
    priority: int
    max_attempts: int
    routes: list[str]
    result: dict[str, JSONValue]
