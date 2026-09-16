from __future__ import annotations

import json
from collections import UserDict

import pytest
from pydantic import ValidationError

from labtasker.models import Task, WorkerObservation
from labtasker.validation import RequestValidationError, validate_json_object


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


def test_task_accepts_optional_progress_fields_from_newer_server() -> None:
    payload = task_payload()
    payload.update(
        {
            "progress": {"step": 12, "loss": 0.5},
            "progress_updated_at": "2026-08-20T12:01:00Z",
            "progress_attempt": 1,
        }
    )
    task = parse(payload)
    assert task.progress == {"step": 12, "loss": 0.5}
    assert task.progress_attempt == 1
    assert task.progress_updated_at is not None


def test_task_defaults_missing_additive_progress_fields_to_none() -> None:
    task = parse(task_payload())
    assert (task.progress, task.progress_updated_at, task.progress_attempt) == (None, None, None)


def test_worker_observation_accepts_observability_fields_and_old_defaults() -> None:
    payload = {
        "id": "w_ABCDEFGHIJKL",
        "queue": "default",
        "route": "train",
        "status": "busy",
        "task_id": "t_ABCDEFGHIJKL",
        "last_seen_at": "2026-08-20T12:00:00Z",
        "expires_at": "2026-08-20T12:05:00Z",
    }
    old = WorkerObservation.model_validate_json(json.dumps(payload), strict=True)
    assert (old.metadata, old.telemetry, old.telemetry_updated_at) == ({}, None, None)
    current = WorkerObservation.model_validate_json(
        json.dumps(
            {
                **payload,
                "metadata": {"hostname": "node-7"},
                "telemetry": {"gpu_utilization": 0.5},
                "telemetry_updated_at": "2026-08-20T12:01:00Z",
            }
        ),
        strict=True,
    )
    assert current.metadata == {"hostname": "node-7"}
    assert current.telemetry == {"gpu_utilization": 0.5}


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


def test_python_json_boundary_rejects_mapping_like_non_dict_containers() -> None:
    with pytest.raises(RequestValidationError, match="strict JSON"):
        validate_json_object({"nested": UserDict({"value": 1})}, field="args")
