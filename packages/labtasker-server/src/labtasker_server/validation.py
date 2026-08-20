from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import TypeAlias

from pydantic import JsonValue as PydanticJSONValue

from labtasker_server.errors import invalid

JSONValue: TypeAlias = PydanticJSONValue

INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1
MAX_JSON_DEPTH = 64
MAX_TASK_DATA_BYTES = 1_048_576
MAX_FILTER_BYTES = 8192
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
TASK_ID_RE = re.compile(r"^t_[A-Za-z0-9_-]{12}$")
RUN_ID_RE = re.compile(r"^r_[A-Za-z0-9_-]{12}$")


def validate_unicode_scalar(value: str, *, field: str) -> str:
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise invalid("invalid_request", "String contains a lone Unicode surrogate.", field=field)
    return value


def validate_json_value(value: object, *, field: str, max_depth: int = MAX_JSON_DEPTH) -> None:
    active_containers: set[int] = set()

    def walk(current: object, depth: int, path: str) -> None:
        if isinstance(current, str):
            validate_unicode_scalar(current, field=path)
            return
        if current is None or isinstance(current, bool):
            return
        if isinstance(current, int):
            if not INT64_MIN <= current <= INT64_MAX:
                raise invalid(
                    "invalid_request",
                    "Integer is outside the signed 64-bit range.",
                    field=path,
                )
            return
        if isinstance(current, float):
            if not math.isfinite(current):
                raise invalid("invalid_request", "Number must be finite.", field=path)
            return

        if isinstance(current, Mapping):
            if depth >= max_depth:
                raise invalid(
                    "json_too_deep",
                    "JSON value is too deeply nested.",
                    max_depth=max_depth,
                )
            identity = id(current)
            if identity in active_containers:
                raise invalid("invalid_request", "JSON value contains a cycle.", field=path)
            active_containers.add(identity)
            try:
                for key, child in current.items():
                    if not isinstance(key, str):
                        raise invalid(
                            "invalid_request",
                            "JSON object keys must be strings.",
                            field=path,
                        )
                    validate_unicode_scalar(key, field=f"{path}.<key>")
                    walk(child, depth + 1, f"{path}.{key}")
            finally:
                active_containers.remove(identity)
            return

        if isinstance(current, Sequence) and not isinstance(current, (str, bytes, bytearray)):
            if depth >= max_depth:
                raise invalid(
                    "json_too_deep",
                    "JSON value is too deeply nested.",
                    max_depth=max_depth,
                )
            identity = id(current)
            if identity in active_containers:
                raise invalid("invalid_request", "JSON value contains a cycle.", field=path)
            active_containers.add(identity)
            try:
                for index, child in enumerate(current):
                    walk(child, depth + 1, f"{path}[{index}]")
            finally:
                active_containers.remove(identity)
            return

        raise invalid(
            "invalid_request",
            "Value is not representable in strict JSON.",
            field=path,
            python_type=type(current).__name__,
        )

    walk(value, 0, field)


def validate_json_object(value: dict[str, JSONValue], *, field: str) -> dict[str, JSONValue]:
    validate_json_value(value, field=field)
    return value


def validate_identifier(value: str, *, kind: str) -> str:
    if not IDENTIFIER_RE.fullmatch(value):
        raise invalid(
            "invalid_request",
            f"{kind} must match [A-Za-z0-9][A-Za-z0-9._-]{{0,127}}.",
            field=kind.lower(),
        )
    return value


def validate_task_id(value: str) -> str:
    if not TASK_ID_RE.fullmatch(value):
        raise invalid("invalid_task_id", "Task ID has an invalid format.", task_id=value)
    return value


def validate_run_id(value: str) -> str:
    if not RUN_ID_RE.fullmatch(value):
        raise invalid("invalid_request", "Run ID has an invalid format.", field="run_id")
    return value


def validate_task_name(value: str | None) -> str | None:
    if value is None:
        return None
    validate_unicode_scalar(value, field="name")
    if len(value) > 256:
        raise invalid("invalid_task_name", "Task name exceeds 256 Unicode code points.")
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise invalid("invalid_task_name", "Task name contains a control character.")
    return value


def canonical_routes(routes: list[str]) -> list[str]:
    if not routes:
        raise invalid("invalid_request", "Routes must be a non-empty array.", field="routes")
    validated = [validate_identifier(route, kind="Route") for route in routes]
    if len(validated) != len(set(validated)):
        raise invalid("invalid_request", "Routes must not contain duplicates.", field="routes")
    return sorted(validated)
