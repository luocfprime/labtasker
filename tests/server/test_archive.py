from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError

from labtasker_server.database import Database
from labtasker_server.errors import DomainError
from labtasker_server.schemas import TaskCreate, TaskUpdate
from labtasker_server.services.tasks import TaskService

BASE = "/api/v2/queues/default/tasks"
A, B, C = (f"t_{number:012d}" for number in range(1, 4))
RUN = "r_000000000001"


def archived_task(client: TestClient, task_id: str = A) -> dict:
    assert client.put(f"{BASE}/{task_id}", json={"routes": ["old", "default"]}).status_code == 201
    assert client.post(f"{BASE}/{task_id}/cancel").status_code == 200
    response = client.patch(f"{BASE}/{task_id}", json={"archived": True})
    assert response.status_code == 200
    return response.json()


def test_archive_scope_applies_to_list_scalar_groups_and_bulk_update(client: TestClient) -> None:
    archived_task(client)
    assert client.put(f"{BASE}/{B}", json={}).status_code == 201
    assert [t["id"] for t in client.get(BASE).json()["items"]] == [B]
    assert client.get(f"{BASE}/count").json() == {"count": 1}
    assert client.get(f"{BASE}/count", params={"filter": "archived == True"}).json() == {"count": 0}
    for groups in ["status", "routes", "routes,status", "status,routes"]:
        page = client.get(f"{BASE}/count", params={"group_by": groups}).json()
        assert page["count"] == 1
        assert all(item["key"].get("routes", "default") == "default" for item in page["items"])
        included = client.get(
            f"{BASE}/count", params={"group_by": groups, "include_archived": "true"}
        ).json()
        assert included["count"] == 2
    changes = {"filter": 'status != "running"', "changes": {"priority": 9}}
    assert client.patch(BASE, json=changes).json() == {"matched": 1, "updated": 1}
    assert client.get(f"{BASE}/{A}").json()["priority"] == 0
    assert client.patch(BASE, json={**changes, "include_archived": True}).json() == {
        "matched": 2,
        "updated": 1,
    }
    restore = {"filter": "archived == True", "changes": {"archived": False}}
    assert client.patch(BASE, json=restore).json() == {"matched": 0, "updated": 0}
    assert client.patch(BASE, json={**restore, "include_archived": True}).json() == {
        "matched": 1,
        "updated": 1,
    }
    assert client.get(f"{BASE}/count").json() == {"count": 2}


def test_archive_keeps_id_addressing_idempotency_and_terminal_data(client: TestClient) -> None:
    archived = archived_task(client)
    repeated = client.patch(f"{BASE}/{A}", json={"archived": True}).json()
    assert repeated == archived
    changed = client.patch(f"{BASE}/{A}", json={"name": "retained"}).json()
    assert changed["archived"] is True
    replay = client.put(f"{BASE}/{A}", json={"routes": ["old", "default"]})
    assert replay.status_code == 200 and replay.json()["archived"] is True
    assert client.post(f"{BASE}/{A}/cancel").json()["archived"] is True
    restored = client.post(f"{BASE}/{A}/requeue").json()
    assert restored["status"] == "pending" and restored["archived"] is False
    assert restored["finished_at"] == archived["finished_at"]
    assert client.post(f"{BASE}/{A}/cancel").status_code == 200
    assert client.patch(f"{BASE}/{A}", json={"archived": True}).status_code == 200
    assert client.delete(f"{BASE}/{A}").status_code == 204


def test_archive_state_validation_and_bulk_rollback(client: TestClient) -> None:
    assert client.put(f"{BASE}/{A}", json={}).status_code == 201
    assert client.put(f"{BASE}/{B}", json={}).status_code == 201
    assert client.post(f"{BASE}/{B}/cancel").status_code == 200
    batch = client.patch(
        BASE, json={"filter": 'status != "running"', "changes": {"archived": True}}
    )
    assert batch.status_code == 409
    assert batch.json()["error"]["code"] == "update_conflict"
    assert batch.json()["error"]["details"]["field"] == "archived"
    assert client.get(f"{BASE}/{B}").json()["archived"] is False
    assert client.patch(f"{BASE}/{A}", json={"archived": True}).status_code == 409
    assert client.post(f"{BASE}/claim", json={"route": "default", "run_id": RUN}).status_code == 200
    assert (
        client.patch(f"{BASE}/{A}", json={"archived": False}).json()["error"]["code"]
        == "task_running"
    )
    response = client.patch(
        BASE, json={"filter": 'status != "pending"', "changes": {"archived": True}}
    )
    assert response.json() == {"matched": 1, "updated": 1}


@pytest.mark.parametrize("value", [None, 0, 1, "true", [], {}])
def test_archive_and_scope_require_boolean_json(client: TestClient, value: object) -> None:
    assert client.put(f"{BASE}/{A}", json={"archived": value}).status_code == 422
    assert client.put(f"{BASE}/{A}", json={}).status_code == 201
    assert client.patch(f"{BASE}/{A}", json={"archived": value}).status_code == 422
    response = client.patch(
        BASE,
        json={"filter": "priority == 0", "include_archived": value, "changes": {"priority": 1}},
    )
    assert response.status_code == 422 and response.json()["error"]["code"] == "invalid_update"


@pytest.mark.parametrize(
    "expression",
    [
        "archived == 1",
        "archived == None",
        "archived < True",
        "archived in [True, 1]",
        "archived",
        "not archived",
    ],
)
def test_archive_filter_rejects_invalid_boolean_operations(
    client: TestClient, expression: str
) -> None:
    response = client.get(BASE, params={"filter": expression, "include_archived": "true"})
    assert response.status_code == 422 and response.json()["error"]["code"] == "invalid_filter"


@pytest.mark.parametrize(
    "expression,expected",
    [
        ("archived == True", 1),
        ("archived != True", 0),
        ("archived in [False, True]", 1),
        ("archived not in [False]", 1),
        ("exists(archived)", 1),
        ("missing(archived)", 0),
    ],
)
def test_archive_boolean_filters(client: TestClient, expression: str, expected: int) -> None:
    archived_task(client)
    assert client.get(
        f"{BASE}/count", params={"filter": expression, "include_archived": "true"}
    ).json() == {"count": expected}


@pytest.mark.parametrize(
    "suffix,params", [("", {"limit": 1}), ("/count", {"group_by": "routes,status", "limit": 1})]
)
def test_archive_scope_is_bound_to_cursor(client: TestClient, suffix: str, params: dict) -> None:
    archived_task(client)
    for task_id in [B, C]:
        assert client.put(f"{BASE}/{task_id}", json={"routes": [task_id]}).status_code == 201
    page = client.get(BASE + suffix, params=params).json()
    assert page["next_cursor"]
    response = client.get(
        BASE + suffix, params={**params, "cursor": page["next_cursor"], "include_archived": "true"}
    )
    assert response.status_code == 422 and response.json()["error"]["code"] == "invalid_cursor"


def test_archived_success_still_satisfies_dependencies_and_deduplicates_complete(
    client: TestClient,
) -> None:
    assert client.put(f"{BASE}/{A}", json={}).status_code == 201
    assert client.post(f"{BASE}/claim", json={"route": "default", "run_id": RUN}).status_code == 200
    body = {"run_id": RUN, "result": {"score": 1}}
    assert client.post(f"{BASE}/{A}/complete", json=body).status_code == 204
    archived = client.patch(f"{BASE}/{A}", json={"archived": True}).json()
    assert client.post(f"{BASE}/{A}/complete", json=body).status_code == 204
    assert client.get(f"{BASE}/{A}").json() == archived
    assert client.post(f"{BASE}/{A}/heartbeat", json={"run_id": RUN}).status_code == 409
    assert client.put(f"{BASE}/{B}", json={"dependencies": [A]}).status_code == 201
    claimed = client.post(
        f"{BASE}/claim", json={"route": "default", "run_id": "r_000000000002"}
    ).json()
    assert claimed["task"]["id"] == B and claimed["task"]["archived"] is False


def test_archive_only_queue_is_not_empty(client: TestClient) -> None:
    archived_task(client)
    assert client.get(f"{BASE}/count").json() == {"count": 0}
    assert {"name": "default"} in client.get("/api/v2/queues").json()
    response = client.delete("/api/v2/queues/default")
    assert response.status_code == 409 and response.json()["error"]["code"] == "queue_not_empty"
    assert client.delete("/api/v2/queues/default?cascade=true").status_code == 204


def test_archive_migration_preserves_routes_hash_and_rolls_back_on_failure(
    database_path: Path,
) -> None:
    database = Database(database_path)
    database.initialize()
    config = Config()
    config.set_main_option(
        "script_location",
        str(
            Path(__file__).parents[2] / "packages/labtasker-server/src/labtasker_server/migrations"
        ),
    )
    request = TaskCreate(routes=["old", "default"], dependencies=[B])
    try:
        TaskService(database).create("default", A, request)
        with database.engine.begin() as connection:
            connection.execute(text("BEGIN IMMEDIATE"))
            config.attributes["connection"] = connection
            command.downgrade(config, "0005_task_dependencies")
    finally:
        database.dispose()
    database = Database(database_path)

    def fail_after_add(_connection, _cursor, statement, *_args):
        if statement.startswith("ALTER TABLE tasks ADD COLUMN archived"):
            raise RuntimeError("injected archive migration failure")

    event.listen(database.engine, "after_cursor_execute", fail_after_add)
    try:
        with pytest.raises(RuntimeError, match="injected archive"):
            database.initialize()
    finally:
        database.dispose()
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0005_task_dependencies",
        )
        assert "archived" not in {row[1] for row in connection.execute("PRAGMA table_info(tasks)")}
    database = Database(database_path)
    try:
        database.initialize()
        task, created = TaskService(database).create("default", A, request)
        assert not created and task.archived is False
        assert task.routes == ["default", "old"] and task.dependencies == [B]
        with (
            database.engine.begin() as connection,
            pytest.raises(IntegrityError, match="CHECK constraint failed"),
        ):
            connection.execute(text("UPDATE tasks SET archived=1"))
    finally:
        database.dispose()


def test_archive_racing_requeue_never_leaves_archived_pending(database_path: Path) -> None:
    first_db = Database(database_path)
    first_db.initialize()
    try:
        first, second = TaskService(first_db), TaskService(first_db)
        first.create("default", A, TaskCreate())
        first.cancel("default", A)
        barrier = Barrier(2)

        def archive():
            barrier.wait()
            try:
                return first.update_task("default", A, TaskUpdate(archived=True))
            except DomainError as error:
                return error

        def requeue():
            barrier.wait()
            return second.requeue("default", A)

        with ThreadPoolExecutor(max_workers=2) as pool:
            archive_future, requeue_future = pool.submit(archive), pool.submit(requeue)
            archive_future.result()
            requeue_future.result()
        task = first.get("default", A)
        assert task.status == "pending" and task.archived is False
    finally:
        first_db.dispose()


def test_archive_does_not_consume_workload_size_budget(database_path: Path) -> None:
    from labtasker_server.services.tasks import canonical_json
    from labtasker_server.validation import MAX_TASK_DATA_BYTES

    request = TaskCreate(args={"text": ""})
    stored = request.model_dump(exclude={"dependencies"}) | {"result": {}}
    request.args["text"] = "x" * (MAX_TASK_DATA_BYTES - len(canonical_json(stored).encode()))
    database = Database(database_path)
    try:
        database.initialize()
        service = TaskService(database)
        service.create("default", A, request)
        service.cancel("default", A)
        assert service.update_task("default", A, TaskUpdate(archived=True)).archived is True
    finally:
        database.dispose()


def test_archive_openapi_exposes_only_the_approved_surfaces(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    models = schema["components"]["schemas"]
    assert models["Task"]["properties"]["archived"]["type"] == "boolean"
    assert models["TaskUpdate"]["properties"]["archived"]["type"] == "boolean"
    assert "archived" not in models["TaskCreate"]["properties"]
    assert models["BulkUpdateRequest"]["properties"]["include_archived"]["default"] is False
    for path in ["/api/v2/queues/{queue}/tasks", "/api/v2/queues/{queue}/tasks/count"]:
        parameter = next(
            p for p in schema["paths"][path]["get"]["parameters"] if p["name"] == "include_archived"
        )
        assert parameter["in"] == "query" and parameter["schema"]["default"] is False
    assert all(
        p["name"] != "include_archived"
        for p in schema["paths"]["/api/v2/queues/{queue}/tasks/{task_id}"]["get"]["parameters"]
    )
