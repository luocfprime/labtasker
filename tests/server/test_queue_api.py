from __future__ import annotations

from fastapi.testclient import TestClient


def test_queue_create_is_idempotent_and_list_is_sorted(client: TestClient) -> None:
    created = client.put("/api/v2/queues/zeta")
    repeated = client.put("/api/v2/queues/zeta")
    client.put("/api/v2/queues/Alpha")

    assert created.status_code == 201
    assert created.json() == {"name": "zeta"}
    assert repeated.status_code == 200
    assert repeated.json() == {"name": "zeta"}
    assert client.get("/api/v2/queues").json() == [
        {"name": "Alpha"},
        {"name": "default"},
        {"name": "zeta"},
    ]


def test_queue_delete_requires_cascade_when_tasks_exist(client: TestClient) -> None:
    client.put(
        "/api/v2/queues/default/tasks/t_ABCDEFGHIJKL",
        json={"args": {"seed": 1}},
    )
    conflict = client.delete("/api/v2/queues/default")
    assert conflict.status_code == 409
    assert conflict.json()["error"] == {
        "code": "queue_not_empty",
        "message": "Queue is not empty; use cascade to delete its Tasks.",
        "details": {"queue": "default", "tasks": 1},
    }

    deleted = client.delete("/api/v2/queues/default?cascade=true")
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert client.get("/api/v2/queues").json() == []
    assert (
        client.get("/api/v2/queues/default/tasks/t_ABCDEFGHIJKL").json()["error"]["code"]
        == "task_not_found"
    )


def test_queue_delete_and_invalid_name_errors_are_explicit(client: TestClient) -> None:
    missing = client.delete("/api/v2/queues/missing")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "queue_not_found"

    invalid = client.put("/api/v2/queues/-bad")
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "invalid_request"


def test_queue_identifier_boundary(client: TestClient) -> None:
    maximum = "q" * 128
    assert client.put(f"/api/v2/queues/{maximum}").status_code == 201
    assert client.put(f"/api/v2/queues/{maximum}x").status_code == 422
    assert client.put("/api/v2/queues/SDXL").status_code == 201
    assert client.put("/api/v2/queues/sdxl").status_code == 201
