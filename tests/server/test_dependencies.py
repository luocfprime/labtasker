from __future__ import annotations

import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import event, text

from labtasker_server.database import Database
from labtasker_server.errors import DomainError
from labtasker_server.schemas import TaskCreate, TaskUpdate
from labtasker_server.services.tasks import TaskService, canonical_json

A = "t_000000000001"
B = "t_000000000002"
C = "t_000000000003"
BASE = "/api/v2/queues/default/tasks"


def claim(client: TestClient, number: int, *, route: str = "default", queue: str = "default"):
    return client.post(
        f"/api/v2/queues/{queue}/tasks/claim",
        json={"route": route, "run_id": f"r_{number:012d}"},
    )


def complete(client: TestClient, task_id: str, number: int, *, queue: str = "default") -> None:
    response = client.post(
        f"/api/v2/queues/{queue}/tasks/{task_id}/complete",
        json={"run_id": f"r_{number:012d}", "result": {"value": number}},
    )
    assert response.status_code == 204


def test_forward_references_fanin_and_priority_do_not_block_other_tasks(client: TestClient) -> None:
    deps = [B, A, B]
    assert (
        client.put(f"{BASE}/{C}", json={"dependencies": deps, "priority": 100}).status_code == 201
    )
    assert claim(client, 1).status_code == 204
    assert client.put(f"{BASE}/{A}", json={}).json()["dependencies"] == []
    assert claim(client, 2).json()["task"]["id"] == A
    assert claim(client, 3).status_code == 204
    complete(client, A, 2)
    assert claim(client, 4).status_code == 204  # A succeeded, but B is missing.
    assert client.put(f"{BASE}/{B}", json={}).status_code == 201
    assert claim(client, 5).json()["task"]["id"] == B
    complete(client, B, 5)
    received = claim(client, 6).json()["task"]
    assert received["id"] == C
    assert received["dependencies"] == deps
    assert received["attempt"] == 1
    # Once claimed, deletion of a prerequisite does not revoke the current run.
    assert client.delete(f"{BASE}/{A}").status_code == 204
    assert claim(client, 6).json()["task"] == received
    complete(client, C, 6)


def test_cycles_self_reference_and_missing_ids_are_normal_pending(client: TestClient) -> None:
    for task_id, deps in [(A, [B]), (B, [A]), (C, [C])]:
        assert client.put(f"{BASE}/{task_id}", json={"dependencies": deps}).status_code == 201
    before = client.get(BASE).json()
    assert claim(client, 1).status_code == 204
    assert client.get(BASE).json() == before
    assert client.get("/health").status_code == 200
    assert client.delete(f"{BASE}/{A}").status_code == 204
    assert client.get(f"{BASE}/{B}").json()["dependencies"] == [A]
    assert claim(client, 2).status_code == 204
    assert client.patch(f"{BASE}/{B}", json={"dependencies": []}).status_code == 200
    assert claim(client, 3).json()["task"]["id"] == B
    rejected = client.patch(f"{BASE}/{B}", json={"dependencies": [C]})
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "task_running"
    # Bulk update excludes running Tasks and uses complete replacement.
    response = client.patch(
        BASE, json={"filter": 'status != "succeeded"', "changes": {"dependencies": []}}
    )
    assert response.status_code == 200
    assert response.json() == {"matched": 1, "updated": 1}
    assert claim(client, 4).json()["task"]["id"] == C


def test_queue_scope_deletion_id_reuse_and_original_creation_identity(client: TestClient) -> None:
    assert client.put("/api/v2/queues/other").status_code == 201
    assert client.put(f"/api/v2/queues/other/tasks/{A}", json={}).status_code == 201
    assert claim(client, 1, queue="other").status_code == 200
    complete(client, A, 1, queue="other")
    body = {"dependencies": [A], "routes": ["child"]}
    assert client.put(f"{BASE}/{B}", json=body).status_code == 201
    assert claim(client, 2, route="child").status_code == 204
    assert client.put(f"{BASE}/{A}", json={}).status_code == 201
    assert claim(client, 3).status_code == 200
    complete(client, A, 3)
    assert client.delete(f"{BASE}/{A}").status_code == 204
    assert claim(client, 4, route="child").status_code == 204
    assert client.put(f"{BASE}/{A}", json={}).status_code == 201
    assert claim(client, 5).status_code == 200
    complete(client, A, 5)
    assert claim(client, 6, route="child").json()["task"]["id"] == B
    complete(client, B, 6)
    assert client.patch(f"{BASE}/{B}", json={"dependencies": [C]}).status_code == 200
    assert client.put(f"{BASE}/{B}", json=body).status_code == 200
    assert client.put(f"{BASE}/{B}", json={**body, "dependencies": [C]}).status_code == 409
    assert client.delete("/api/v2/queues/default?cascade=true").status_code == 204


@pytest.mark.parametrize("state", ["failed", "cancelled"])
def test_failure_and_cancellation_wait_for_explicit_recovery(
    client: TestClient, state: str
) -> None:
    assert client.put(f"{BASE}/{A}", json={"max_attempts": 1}).status_code == 201
    assert client.put(f"{BASE}/{B}", json={"dependencies": [A], "priority": 10}).status_code == 201
    if state == "failed":
        assert claim(client, 1).json()["task"]["id"] == A
        response = client.post(
            f"{BASE}/{A}/fail",
            json={
                "run_id": "r_000000000001",
                "error": {"type": "Error", "message": "failed", "traceback": None},
            },
        )
        assert response.status_code == 204
    else:
        assert client.post(f"{BASE}/{A}/cancel").status_code == 200
    assert claim(client, 2).status_code == 204
    assert client.get(f"{BASE}/{B}").json()["attempt"] == 0
    assert client.post(f"{BASE}/{A}/requeue").status_code == 200
    assert claim(client, 3).json()["task"]["id"] == A
    complete(client, A, 3)
    assert claim(client, 4).json()["task"]["id"] == B


@pytest.mark.parametrize("value", [None, "t_000000000001", {}, [1], [True], ["bad"], [[A]]])
def test_invalid_dependencies_use_error_envelope(client: TestClient, value: object) -> None:
    response = client.put(f"{BASE}/{A}", json={"dependencies": value})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_task"
    assert client.put(f"{BASE}/{A}", json={}).status_code == 201
    response = client.patch(f"{BASE}/{A}", json={"dependencies": value})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_update"


def test_dependencies_share_stored_size_limit_and_openapi(client: TestClient) -> None:
    assert client.put(f"{BASE}/{A}", json={"args": {"large": "x" * 700_000}}).status_code == 201
    response = client.patch(f"{BASE}/{A}", json={"dependencies": [B] * 25_000})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "task_data_too_large"
    assert client.get(f"{BASE}/{A}").json()["dependencies"] == []
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    for name in ["Task", "TaskCreate", "TaskUpdate"]:
        field = schemas[name]["properties"]["dependencies"]
        assert field["type"] == "array"
        assert field["items"]["type"] == "string"


def test_large_dependency_list_and_retained_progress_share_size_budget(client: TestClient) -> None:
    assert client.put(f"{BASE}/{A}", json={}).status_code == 201
    assert claim(client, 1).status_code == 200
    complete(client, A, 1)
    dependencies = [A] * 20_000
    assert client.put(f"{BASE}/{B}", json={"dependencies": dependencies}).status_code == 201
    assert claim(client, 2).json()["task"]["id"] == B
    too_large = {"run_id": "r_000000000002", "result": {"large": "x" * 800_000}}
    response = client.post(f"{BASE}/{B}/complete", json=too_large)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "task_data_too_large"
    assert client.get(f"{BASE}/{B}").json()["status"] == "running"
    complete(client, B, 2)
    assert client.get("/health").status_code == 200

    assert client.put(f"{BASE}/{C}", json={}).status_code == 201
    assert claim(client, 3).status_code == 200
    assert (
        client.post(
            f"{BASE}/{C}/progress",
            json={
                "run_id": "r_000000000003",
                "progress": {"large": "x" * 800_000},
            },
        ).status_code
        == 204
    )
    assert client.post(f"{BASE}/{C}/cancel").status_code == 200
    response = client.patch(f"{BASE}/{C}", json={"dependencies": dependencies})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "task_data_too_large"
    assert client.get(f"{BASE}/{C}").json()["dependencies"] == []


@pytest.mark.parametrize("mutation", ["update", "delete"])
def test_dependency_mutation_racing_claim_is_atomic(database_path: Path, mutation: str) -> None:
    database = Database(database_path)
    database.initialize()
    first = TaskService(database)
    second = TaskService(database)
    barrier = Barrier(2)
    try:
        first.create("default", A, TaskCreate(routes=["parent"]))
        assert first.claim("default", "parent", "r_000000000001") is not None
        first.complete("default", A, "r_000000000001", {})
        first.create("default", B, TaskCreate(dependencies=[A]))

        def mutate():
            barrier.wait()
            try:
                if mutation == "update":
                    return second.update_task("default", B, TaskUpdate(dependencies=[C]))
                return second.delete("default", A)
            except DomainError as error:
                return error

        def take():
            barrier.wait()
            return first.claim("default", "default", "r_000000000002")

        with ThreadPoolExecutor(max_workers=2) as pool:
            write, read = pool.submit(mutate), pool.submit(take)
            outcome, claimed = write.result(), read.result()
        if mutation == "update":
            if claimed is None:
                assert not isinstance(outcome, DomainError)
                assert first.get("default", B).dependencies == [C]
            else:
                assert isinstance(outcome, DomainError) and outcome.code == "task_running"
                assert claimed.task.dependencies == [A]
        else:
            assert outcome is None
            assert first.get("default", B).dependencies == [A]
            if claimed is not None:
                first.complete("default", B, claimed.run_id, {})
            else:
                assert first.get("default", B).status == "pending"
    finally:
        database.dispose()


def test_migration_preserves_old_creation_hash_and_dependency_restart(database_path: Path) -> None:
    database = Database(database_path)
    database.initialize()
    config = Config()
    config.set_main_option(
        "script_location",
        str(
            Path(__file__).parents[2] / "packages/labtasker-server/src/labtasker_server/migrations"
        ),
    )
    request = TaskCreate(args={"seed": 1})
    original_data = request.model_dump(mode="json", exclude={"dependencies"})
    old_hash = hashlib.sha256(canonical_json(original_data).encode()).hexdigest()
    try:
        TaskService(database).create("default", A, request)
        with database.engine.begin() as connection:
            connection.execute(text("BEGIN IMMEDIATE"))
            config.attributes["connection"] = connection
            command.downgrade(config, "0004_worker_observability")
            assert connection.scalar(text("SELECT creation_hash FROM tasks")) == old_hash
    finally:
        database.dispose()

    # A failed migration must leave the file on the previous version, with data intact.
    database = Database(database_path)

    def fail_after_add(_connection, _cursor, statement, *_args):
        if statement.startswith("ALTER TABLE tasks ADD COLUMN dependencies_json"):
            raise RuntimeError("injected dependency migration failure")

    event.listen(database.engine, "after_cursor_execute", fail_after_add)
    try:
        with pytest.raises(RuntimeError, match="injected dependency"):
            database.initialize()
    finally:
        database.dispose()
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0004_worker_observability",
        )
        assert "dependencies_json" not in {
            column[1] for column in connection.execute("PRAGMA table_info(tasks)")
        }
        assert connection.execute("SELECT creation_hash FROM tasks").fetchone() == (old_hash,)
    database = Database(database_path)
    try:
        database.initialize()
        service = TaskService(database)
        task, created = service.create("default", A, request)
        assert not created and task.dependencies == []
        service.create("default", B, TaskCreate(dependencies=[C, A]))
    finally:
        database.dispose()
    database = Database(database_path)
    try:
        database.initialize()
        assert TaskService(database).get("default", B).dependencies == [C, A]
    finally:
        database.dispose()
