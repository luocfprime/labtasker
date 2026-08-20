from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from labtasker.models import Task


def task_payload() -> dict[str, object]:
    return {
        "id": "t_ABCDEFGHIJKL",
        "queue": "default",
        "status": "pending",
        "name": None,
        "args": {"seed": 1},
        "metadata": {},
        "priority": 0,
        "attempt": 0,
        "max_attempts": 3,
        "routes": ["default"],
        "result": {},
        "last_error": None,
        "last_route": None,
        "created_at": "2026-08-20T12:00:00.123456Z",
        "updated_at": "2026-08-20T12:00:00.123456Z",
        "started_at": None,
        "finished_at": None,
    }


def parse(payload: dict[str, object]) -> Task:
    return Task.model_validate_json(json.dumps(payload), strict=True)


def test_task_is_frozen_but_json_containers_remain_ordinary() -> None:
    payload = task_payload()
    payload["future_field"] = "ignored"
    task = parse(payload)
    assert task.created_at.tzinfo is not None
    assert task.model_dump(mode="json")["created_at"] == "2026-08-20T12:00:00.123456Z"
    with pytest.raises(ValidationError):
        task.name = "changed"
    task.args["seed"] = 2
    assert task.args == {"seed": 2}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "success"),
        ("priority", True),
        ("attempt", 1.0),
        ("max_attempts", 0),
        ("routes", ["z", "a"]),
        ("created_at", "2026-08-20T12:00:00"),
        ("created_at", "2026-08-20T13:00:00+01:00"),
    ],
)
def test_known_response_fields_are_strict(field: str, value: object) -> None:
    payload = task_payload()
    payload[field] = value
    with pytest.raises((ValidationError, ValueError)):
        parse(payload)


def test_missing_required_response_field_is_rejected() -> None:
    payload = task_payload()
    del payload["result"]
    with pytest.raises(ValidationError):
        parse(payload)
