from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from labtasker_server.app import create_app
from labtasker_server.config import ServerSettings

TASK_1 = "t_000000000001"
TASK_2 = "t_000000000002"
TASK_3 = "t_000000000003"
RUN_1 = "r_000000000001"
RUN_2 = "r_000000000002"


class Clock:
    def __init__(self) -> None:
        self.value = 1_700_000_000_000_000

    def __call__(self) -> int:
        return self.value

    def advance(self) -> None:
        self.value += 1


def submit(client: TestClient, task_id: str, **body: object) -> dict[str, object]:
    response = client.put(f"/api/v2/queues/default/tasks/{task_id}", json=body)
    assert response.status_code == 201
    return response.json()


def claim(client: TestClient, run_id: str) -> None:
    response = client.post(
        "/api/v2/queues/default/tasks/claim",
        json={"route": "default", "run_id": run_id},
    )
    assert response.status_code == 200


def fail(client: TestClient, task_id: str, run_id: str) -> None:
    response = client.post(
        f"/api/v2/queues/default/tasks/{task_id}/fail",
        json={
            "run_id": run_id,
            "error": {"type": "Error", "message": "failed", "traceback": None},
        },
    )
    assert response.status_code == 204


def test_single_update_replaces_only_supplied_user_fields(database_path: Path) -> None:
    clock = Clock()
    app = create_app(ServerSettings(database=database_path), now_us=clock)
    with TestClient(app) as client:
        created = submit(
            client,
            TASK_1,
            name="before",
            args={"keep": 1, "remove": 2},
            metadata={"group": "a"},
            routes=["default"],
        )
        clock.advance()
        response = client.patch(
            f"/api/v2/queues/default/tasks/{TASK_1}",
            json={
                "name": None,
                "args": {"keep": 3},
                "priority": 10,
                "max_attempts": 5,
                "routes": ["new", "default"],
                "result": {"corrected": True},
            },
        )
        assert response.status_code == 200
        updated = response.json()
        assert updated["name"] is None
        assert updated["args"] == {"keep": 3}
        assert updated["metadata"] == {"group": "a"}
        assert updated["priority"] == 10
        assert updated["max_attempts"] == 5
        assert updated["routes"] == ["default", "new"]
        assert updated["result"] == {"corrected": True}
        assert updated["status"] == "pending"
        assert updated["created_at"] == created["created_at"]
        assert updated["updated_at"] != created["updated_at"]

        unchanged = client.patch(
            f"/api/v2/queues/default/tasks/{TASK_1}",
            json={"priority": 10},
        ).json()
        assert unchanged["updated_at"] == updated["updated_at"]


def test_update_validation_is_strict_and_operation_specific(client: TestClient) -> None:
    submit(client, TASK_1)
    cases = [
        {},
        {"status": "failed"},
        {"args": None},
        {"routes": None},
        {"routes": []},
        {"priority": None},
        {"max_attempts": 0},
        {"result": []},
    ]
    for changes in cases:
        response = client.patch(
            f"/api/v2/queues/default/tasks/{TASK_1}",
            json=changes,
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_update"


def test_running_task_rejects_update_but_terminal_task_allows_it(client: TestClient) -> None:
    submit(client, TASK_1)
    claim(client, RUN_1)
    running = client.patch(
        f"/api/v2/queues/default/tasks/{TASK_1}",
        json={"args": {"new": True}},
    )
    assert running.status_code == 409
    assert running.json()["error"]["code"] == "task_running"

    client.post(f"/api/v2/queues/default/tasks/{TASK_1}/cancel")
    terminal = client.patch(
        f"/api/v2/queues/default/tasks/{TASK_1}",
        json={"args": {"new": True}, "routes": ["archive"]},
    )
    assert terminal.status_code == 200
    assert terminal.json()["status"] == "cancelled"
    assert terminal.json()["args"] == {"new": True}
    assert terminal.json()["routes"] == ["archive"]


def test_pending_max_attempts_must_exceed_consumed_attempts(client: TestClient) -> None:
    submit(client, TASK_1, max_attempts=3)
    claim(client, RUN_1)
    fail(client, TASK_1, RUN_1)
    conflict = client.patch(
        f"/api/v2/queues/default/tasks/{TASK_1}",
        json={"max_attempts": 1},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "update_conflict"
    assert conflict.json()["error"]["details"]["field"] == "max_attempts"
    assert client.get(f"/api/v2/queues/default/tasks/{TASK_1}").json()["max_attempts"] == 3


def test_batch_update_counts_changes_and_excludes_running_tasks(client: TestClient) -> None:
    submit(client, TASK_1, metadata={"group": "a"}, priority=5)
    submit(client, TASK_2, metadata={"group": "a"}, priority=0)
    submit(client, TASK_3, metadata={"group": "b"}, priority=0)
    claim(client, RUN_1)

    response = client.patch(
        "/api/v2/queues/default/tasks",
        json={
            "filter": 'metadata.group == "a"',
            "changes": {"priority": 5, "routes": ["v2"]},
        },
    )
    assert response.status_code == 200
    assert response.json() == {"matched": 1, "updated": 1}
    assert client.get(f"/api/v2/queues/default/tasks/{TASK_1}").json()["routes"] == ["default"]
    assert client.get(f"/api/v2/queues/default/tasks/{TASK_2}").json()["routes"] == ["v2"]
    assert client.get(f"/api/v2/queues/default/tasks/{TASK_3}").json()["routes"] == ["default"]

    unchanged = client.patch(
        "/api/v2/queues/default/tasks",
        json={"filter": 'metadata.group == "b"', "changes": {"priority": 0}},
    )
    assert unchanged.json() == {"matched": 1, "updated": 0}


def test_batch_update_rolls_back_if_one_nonrunning_task_conflicts(client: TestClient) -> None:
    submit(client, TASK_1, max_attempts=3, priority=1)
    submit(client, TASK_2, max_attempts=3, priority=2)
    claim(client, RUN_1)
    fail(client, TASK_2, RUN_1)

    response = client.patch(
        "/api/v2/queues/default/tasks",
        json={"filter": 'status == "pending"', "changes": {"max_attempts": 1}},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "update_conflict"
    assert client.get(f"/api/v2/queues/default/tasks/{TASK_1}").json()["max_attempts"] == 3
    assert client.get(f"/api/v2/queues/default/tasks/{TASK_2}").json()["max_attempts"] == 3


def test_batch_update_requires_explicit_nonempty_filter(client: TestClient) -> None:
    submit(client, TASK_1)
    missing = client.patch(
        "/api/v2/queues/default/tasks",
        json={"changes": {"priority": 1}},
    )
    empty = client.patch(
        "/api/v2/queues/default/tasks",
        json={"filter": " ", "changes": {"priority": 1}},
    )
    assert missing.status_code == empty.status_code == 422
    assert missing.json()["error"]["code"] == "invalid_filter"
    assert empty.json()["error"]["code"] == "invalid_filter"
