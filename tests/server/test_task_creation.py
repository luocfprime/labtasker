from __future__ import annotations

from fastapi.testclient import TestClient

from labtasker_server.validation import INT64_MAX, INT64_MIN

TASK_URL = "/api/v2/queues/default/tasks/t_ABCDEFGHIJKL"


def nested_arrays(count: int) -> list[object] | int:
    value: list[object] | int = 0
    for _ in range(count):
        value = [value]
    return value


def test_task_creation_expands_defaults_and_sorts_routes(client: TestClient) -> None:
    response = client.put(
        TASK_URL,
        json={
            "name": "SDXL 实验 🧪",
            "args": {"seed": 7, "enabled": True, "scale": 1.5, "none": None},
            "metadata": {"group": "demo"},
            "priority": INT64_MIN,
            "max_attempts": INT64_MAX,
            "routes": ["sdxl-v2", "SDXL"],
        },
    )
    assert response.status_code == 201
    task = response.json()
    assert set(task) == {
        "id",
        "queue",
        "status",
        "name",
        "args",
        "metadata",
        "priority",
        "attempt",
        "max_attempts",
        "routes",
        "result",
        "last_error",
        "last_route",
        "created_at",
        "updated_at",
        "started_at",
        "finished_at",
    }
    assert task["status"] == "pending"
    assert task["attempt"] == 0
    assert task["result"] == {}
    assert task["routes"] == ["SDXL", "sdxl-v2"]
    assert task["started_at"] is None
    assert task["finished_at"] is None
    assert task["last_error"] is None
    assert task["last_route"] is None
    assert task["created_at"].endswith("Z")
    assert task["updated_at"] == task["created_at"]
    assert client.get(TASK_URL).json() == task


def test_task_creation_is_idempotent_for_normalized_request(client: TestClient) -> None:
    first = client.put(TASK_URL, json={"routes": ["z", "a"]})
    repeated = client.put(
        TASK_URL,
        json={
            "name": None,
            "args": {},
            "metadata": {},
            "priority": 0,
            "max_attempts": 3,
            "routes": ["a", "z"],
        },
    )
    conflict = client.put(TASK_URL, json={"args": {"changed": True}, "routes": ["a", "z"]})

    assert first.status_code == 201
    assert repeated.status_code == 200
    assert repeated.json() == first.json()
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "task_id_conflict"
    assert client.get(TASK_URL).json()["args"] == {}


def test_same_task_id_in_different_queues_is_independent(client: TestClient) -> None:
    client.put("/api/v2/queues/other")
    first = client.put(TASK_URL, json={"args": {"queue": 1}})
    second = client.put(
        "/api/v2/queues/other/tasks/t_ABCDEFGHIJKL",
        json={"args": {"queue": 2}},
    )
    assert first.status_code == second.status_code == 201
    assert first.json()["args"] == {"queue": 1}
    assert second.json()["args"] == {"queue": 2}


def test_unknown_queue_and_invalid_task_id_are_distinct(client: TestClient) -> None:
    unknown = client.put(
        "/api/v2/queues/missing/tasks/t_ABCDEFGHIJKL",
        json={},
    )
    invalid = client.put(
        "/api/v2/queues/default/tasks/r_ABCDEFGHIJKL",
        json={},
    )
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "queue_not_found"
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "invalid_task_id"


def test_task_numeric_fields_are_strict_signed_int64(client: TestClient) -> None:
    cases = [
        ({"priority": True}, "invalid_task"),
        ({"priority": INT64_MAX + 1}, "invalid_task"),
        ({"priority": INT64_MIN - 1}, "invalid_task"),
        ({"max_attempts": 0}, "invalid_task"),
        ({"max_attempts": 1.0}, "invalid_task"),
    ]
    for body, code in cases:
        response = client.put(TASK_URL, json=body)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == code


def test_task_json_numeric_domain_is_validated_recursively(client: TestClient) -> None:
    for body in (
        b'{"args":{"value":NaN}}',
        b'{"args":{"value":Infinity}}',
        b'{"args":{"value":9223372036854775808}}',
        b'{"args":{"value":-9223372036854775809}}',
    ):
        response = client.put(TASK_URL, content=body, headers={"Content-Type": "application/json"})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_task"


def test_json_depth_64_is_allowed_and_65_is_rejected(client: TestClient) -> None:
    accepted = client.put(TASK_URL, json={"args": {"value": nested_arrays(63)}})
    rejected = client.put(
        "/api/v2/queues/default/tasks/t_MNOPQRSTUVWX",
        json={"args": {"value": nested_arrays(64)}},
    )
    assert accepted.status_code == 201
    assert rejected.status_code == 422
    assert rejected.json()["error"] == {
        "code": "json_too_deep",
        "message": "JSON value is too deeply nested.",
        "details": {"max_depth": 64},
    }


def test_lone_unicode_surrogates_are_rejected(client: TestClient) -> None:
    response = client.put(
        TASK_URL,
        content=b'{"args":{"value":"\\ud800"}}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_task"


def test_task_name_and_routes_reject_ambiguous_values(client: TestClient) -> None:
    cases = [
        ({"name": "x" * 257}, "invalid_task_name"),
        ({"name": "line\nbreak"}, "invalid_task_name"),
        ({"routes": []}, "invalid_task"),
        ({"routes": ["same", "same"]}, "invalid_task"),
        ({"routes": ["with space"]}, "invalid_task"),
        ({"routes": ["x" * 129]}, "invalid_task"),
    ]
    for index, (body, code) in enumerate(cases):
        task_id = f"t_{index:012d}"
        response = client.put(
            f"/api/v2/queues/default/tasks/{task_id}",
            json=body,
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == code
