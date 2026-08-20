from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass

from labtasker_server.errors import DomainError, invalid
from labtasker_server.validation import (
    INT64_MAX,
    INT64_MIN,
    validate_task_id,
    validate_unicode_scalar,
)


@dataclass(frozen=True, slots=True)
class TaskSelection:
    queue: str
    status: str | None
    name: str | None
    filter: str | None
    order_by: str
    descending: bool


@dataclass(frozen=True, slots=True)
class CursorPosition:
    value: str | int | None
    task_id: str


def encode_cursor(selection: TaskSelection, position: CursorPosition) -> str:
    payload = {
        "v": 1,
        "selection": {
            "queue": selection.queue,
            "status": selection.status,
            "name": selection.name,
            "filter": selection.filter,
            "order_by": selection.order_by,
            "descending": selection.descending,
        },
        "position": {"value": position.value, "id": position.task_id},
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")


def decode_cursor(cursor: str, selection: TaskSelection) -> CursorPosition:
    try:
        if not cursor or len(cursor) > 16_384 or not cursor.isascii():
            raise ValueError
        padding = "=" * (-len(cursor) % 4)
        raw = base64.b64decode(cursor + padding, altchars=b"-_", validate=True)
        payload = json.loads(raw)
        if not isinstance(payload, dict) or set(payload) != {"v", "selection", "position"}:
            raise ValueError
        if payload["v"] != 1 or payload["selection"] != _selection_json(selection):
            raise ValueError
        position = payload["position"]
        if not isinstance(position, dict) or set(position) != {"value", "id"}:
            raise ValueError
        task_id = position["id"]
        value = position["value"]
        if not isinstance(task_id, str) or isinstance(value, (bool, float, list, dict)):
            raise ValueError
        validate_task_id(task_id)
        _validate_cursor_value(selection.order_by, value)
        return CursorPosition(value=value, task_id=task_id)
    except (
        UnicodeError,
        ValueError,
        TypeError,
        json.JSONDecodeError,
        binascii.Error,
        DomainError,
    ) as error:
        raise invalid(
            "invalid_cursor", "Cursor is malformed or does not match this request."
        ) from error


def _selection_json(selection: TaskSelection) -> dict[str, object]:
    return {
        "queue": selection.queue,
        "status": selection.status,
        "name": selection.name,
        "filter": selection.filter,
        "order_by": selection.order_by,
        "descending": selection.descending,
    }


def _validate_cursor_value(order_by: str, value: object) -> None:
    numeric_fields = {
        "priority",
        "attempt",
        "max_attempts",
        "created_at",
        "updated_at",
        "started_at",
        "finished_at",
    }
    nullable_fields = {"name", "last_route", "started_at", "finished_at"}
    if value is None:
        if order_by not in nullable_fields:
            raise ValueError
        return
    if order_by in numeric_fields:
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or not INT64_MIN <= value <= INT64_MAX
        ):
            raise ValueError
        return
    if not isinstance(value, str):
        raise ValueError
    validate_unicode_scalar(value, field="cursor.position.value")
