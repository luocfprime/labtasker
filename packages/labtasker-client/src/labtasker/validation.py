from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Sequence
from typing import cast

from labtasker.errors import ConfigError
from labtasker.types import JSONValue, TaskOrderField, TaskStatus, TaskUpdate

INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1
MAX_JSON_DEPTH = 64
MAX_FILTER_BYTES = 8192
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
TASK_ID_RE = re.compile(r"^t_[A-Za-z0-9_-]{12}$")
RUN_ID_RE = re.compile(r"^r_[A-Za-z0-9_-]{12}$")
TASK_STATUSES = {"pending", "running", "succeeded", "failed", "cancelled"}
TASK_ORDER_FIELDS = {
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
}


class RequestValidationError(ValueError):
    pass


def validate_json_object(value: object, *, field: str) -> dict[str, JSONValue]:
    if not isinstance(value, dict):
        raise RequestValidationError(f"{field} must be a JSON object.")
    validate_json_value(value, field=field)
    return cast(dict[str, JSONValue], value)


def validate_json_value(value: object, *, field: str) -> None:
    active_containers: set[int] = set()

    def walk(current: object, depth: int, path: str) -> None:
        if isinstance(current, str):
            validate_unicode_scalar(current, field=path)
            return
        if current is None or isinstance(current, bool):
            return
        if isinstance(current, int):
            if not INT64_MIN <= current <= INT64_MAX:
                raise RequestValidationError(f"{path} is outside the signed 64-bit range.")
            return
        if isinstance(current, float):
            if not math.isfinite(current):
                raise RequestValidationError(f"{path} must be finite.")
            return
        if isinstance(current, dict):
            if depth >= MAX_JSON_DEPTH:
                raise RequestValidationError(f"{field} exceeds JSON depth {MAX_JSON_DEPTH}.")
            identity = id(current)
            if identity in active_containers:
                raise RequestValidationError(f"{field} contains a cycle.")
            active_containers.add(identity)
            try:
                for key, child in current.items():
                    if not isinstance(key, str):
                        raise RequestValidationError(f"{path} has a non-string object key.")
                    validate_unicode_scalar(key, field=f"{path}.<key>")
                    walk(child, depth + 1, f"{path}.{key}")
            finally:
                active_containers.remove(identity)
            return
        if isinstance(current, Sequence) and not isinstance(current, (str, bytes, bytearray)):
            if not isinstance(current, list):
                raise RequestValidationError(f"{path} must use JSON arrays, not Python sequences.")
            if depth >= MAX_JSON_DEPTH:
                raise RequestValidationError(f"{field} exceeds JSON depth {MAX_JSON_DEPTH}.")
            identity = id(current)
            if identity in active_containers:
                raise RequestValidationError(f"{field} contains a cycle.")
            active_containers.add(identity)
            try:
                for index, child in enumerate(current):
                    walk(child, depth + 1, f"{path}[{index}]")
            finally:
                active_containers.remove(identity)
            return
        raise RequestValidationError(f"{path} is not representable in strict JSON.")

    walk(value, 0, field)


def validate_unicode_scalar(value: str, *, field: str) -> str:
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise RequestValidationError(f"{field} contains a lone Unicode surrogate.")
    return value


def validate_identifier(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER_RE.fullmatch(value):
        raise RequestValidationError(f"{field} must match [A-Za-z0-9][A-Za-z0-9._-]{{0,127}}.")
    return value


def validate_task_id(value: object) -> str:
    if not isinstance(value, str) or not TASK_ID_RE.fullmatch(value):
        raise RequestValidationError("task_id must match t_[A-Za-z0-9_-]{12}.")
    return value


def validate_run_id(value: object) -> str:
    if not isinstance(value, str) or not RUN_ID_RE.fullmatch(value):
        raise RequestValidationError("run_id must match r_[A-Za-z0-9_-]{12}.")
    return value


def validate_task_name(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RequestValidationError("name must be a string or None.")
    validate_unicode_scalar(value, field="name")
    if len(value) > 256:
        raise RequestValidationError("name exceeds 256 Unicode code points.")
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise RequestValidationError("name contains a control character.")
    return value


def validate_int64(value: object, *, field: str, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RequestValidationError(f"{field} must be an integer.")
    if not INT64_MIN <= value <= INT64_MAX or (positive and value <= 0):
        qualifier = "a positive signed 64-bit integer" if positive else "a signed 64-bit integer"
        raise RequestValidationError(f"{field} must be {qualifier}.")
    return value


def validate_routes(value: object) -> list[str]:
    if not isinstance(value, list) or not value:
        raise RequestValidationError("routes must be a non-empty list of strings.")
    routes = [validate_identifier(route, field="route") for route in value]
    if len(routes) != len(set(routes)):
        raise RequestValidationError("routes must not contain duplicates.")
    return sorted(routes)


def validate_filter(value: object, *, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise RequestValidationError("filter must be a non-empty string.")
        return None
    if not isinstance(value, str) or (required and not value.strip()):
        raise RequestValidationError("filter must be a non-empty string.")
    if len(value.encode("utf-8")) > MAX_FILTER_BYTES:
        raise RequestValidationError(f"filter exceeds {MAX_FILTER_BYTES} bytes.")
    validate_unicode_scalar(value, field="filter")
    return value


def validate_status(value: object | None) -> TaskStatus | None:
    if value is None:
        return None
    if not isinstance(value, str) or value not in TASK_STATUSES:
        raise RequestValidationError("status is not a valid Task status.")
    return cast(TaskStatus, value)


def validate_order_field(value: object) -> TaskOrderField:
    if not isinstance(value, str) or value not in TASK_ORDER_FIELDS:
        raise RequestValidationError("order_by is not a supported Task field.")
    return cast(TaskOrderField, value)


def validate_task_update(changes: object) -> TaskUpdate:
    if not isinstance(changes, dict) or not changes:
        raise RequestValidationError("changes must be a non-empty object.")
    allowed = {"name", "args", "metadata", "priority", "max_attempts", "routes", "result"}
    unknown = set(changes) - allowed
    if unknown:
        raise RequestValidationError(f"changes contains unsupported fields: {sorted(unknown)!r}.")
    normalized: dict[str, object] = {}
    for field, value in changes.items():
        if field == "name":
            normalized[field] = validate_task_name(value)
        elif field in {"args", "metadata", "result"}:
            normalized[field] = validate_json_object(value, field=field)
        elif field == "priority":
            normalized[field] = validate_int64(value, field=field)
        elif field == "max_attempts":
            normalized[field] = validate_int64(value, field=field, positive=True)
        elif field == "routes":
            normalized[field] = validate_routes(value)
    return cast(TaskUpdate, normalized)


def invalid_config(message: str, *, source: str, field: str | None = None) -> ConfigError:
    details = {"source": source}
    if field is not None:
        details["field"] = field
    return ConfigError("invalid_config", message, details)
