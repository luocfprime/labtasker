from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from labtasker_server.app import create_app
from labtasker_server.config import ServerSettings
from labtasker_server.database import Database
from labtasker_server.schemas import TaskCreate
from labtasker_server.services.tasks import TaskService

BASE = "/api/v2/queues/default"
W1 = "w_ABCDEFGHIJKL"
W2 = "w_BCDEFGHIJKLM"


def test_grouped_count_expands_membership_after_selection_and_pages(client: TestClient) -> None:
    for i, routes in enumerate([["a", "b"], ["a"], ["c"]]):
        assert client.put(f"{BASE}/tasks/t_{i:012}", json={"routes": routes}).status_code == 201
    client.post(f"{BASE}/tasks/claim", json={"route": "a", "run_id": "r_ABCDEFGHIJKL"})
    query = {"group_by": "routes,status", "limit": 1, "filter": '"a" in routes'}
    pages = []
    while True:
        response = client.get(f"{BASE}/tasks/count", params=query)
        assert response.status_code == 200, response.text
        page = response.json()
        assert page["count"] == 2
        pages.extend(page["items"])
        if page["next_cursor"] is None:
            break
        query["cursor"] = page["next_cursor"]
        query["limit"] = 2
    assert pages == [
        {"key": {"routes": "a", "status": "pending"}, "count": 1},
        {"key": {"routes": "a", "status": "running"}, "count": 1},
        {"key": {"routes": "b", "status": "running"}, "count": 1},
    ]
    assert client.get(f"{BASE}/tasks/count").json() == {"count": 3}
    empty = client.get(
        f"{BASE}/tasks/count", params={"status": "failed", "group_by": "status"}
    ).json()
    assert empty == {"group_by": ["status"], "count": 0, "items": [], "next_cursor": None}


@pytest.mark.parametrize(
    "query",
    [
        {"group_by": ""},
        {"group_by": "routes, status"},
        {"group_by": "routes,routes"},
        {"group_by": "last_route"},
        {"group_by": "status,"},
        {"limit": 100},
        {"cursor": "abc"},
        [("group_by", "routes"), ("group_by", "status")],
    ],
)
def test_count_rejects_invalid_grouping(client: TestClient, query: object) -> None:
    response = client.get(f"{BASE}/tasks/count", params=query)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_group_cursor_binds_selection_order_and_resource(client: TestClient) -> None:
    client.put(f"{BASE}/tasks/t_ABCDEFGHIJKL", json={"routes": ["a", "b"]})
    cursor = client.get(
        f"{BASE}/tasks/count", params={"group_by": "routes,status", "limit": 1}
    ).json()["next_cursor"]
    for url, params in [
        (f"{BASE}/tasks/count", {"group_by": "status,routes"}),
        (f"{BASE}/tasks/count", {"group_by": "routes,status", "status": "pending"}),
        (f"{BASE}/workers/count", {"group_by": "route,status"}),
        (f"{BASE}/tasks", {}),
    ]:
        response = client.get(url, params={**params, "cursor": cursor})
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "invalid_cursor"


def test_presence_is_advisory_expires_without_cleanup_and_can_reappear(tmp_path: Path) -> None:
    now = [1_700_000_000_000_000]
    app = create_app(ServerSettings(database=tmp_path / "test.db"), now_us=lambda: now[0])
    with TestClient(app) as client:
        payload = {"route": "a", "status": "busy", "task_id": "t_ABCDEFGHIJKL"}
        assert client.put(f"{BASE}/workers/{W1}", json=payload).status_code == 204
        observation = client.get(f"{BASE}/workers").json()["items"][0]
        assert observation["task_id"] == "t_ABCDEFGHIJKL"  # no Task/FK required
        assert client.get(f"{BASE}/tasks/count").json() == {"count": 0}
        assert client.get(f"{BASE}/workers/count", params={"group_by": "route,status"}).json()[
            "items"
        ] == [{"key": {"route": "a", "status": "busy"}, "count": 1}]
        now[0] += 300_000_000
        assert client.get(f"{BASE}/workers").json()["items"] == []
        assert client.get(f"{BASE}/workers/count").json() == {"count": 0}
        app.state.worker_service.expire()
        assert client.put(f"{BASE}/workers/{W1}", json=payload).status_code == 204
        assert client.delete(f"{BASE}/workers/{W1}").status_code == 204
        assert client.delete(f"{BASE}/workers/{W1}").status_code == 204
        # A late observation is deliberately allowed to re-create the row.
        assert client.put(f"{BASE}/workers/{W1}", json=payload).status_code == 204
        assert client.delete("/api/v2/queues/default").status_code == 204
        assert client.put(f"{BASE}/workers/{W1}", json=payload).status_code == 404


def test_worker_filter_language_and_ordered_pages(client: TestClient) -> None:
    for worker_id, status, task_id in [(W2, "busy", "t_ABCDEFGHIJKL"), (W1, "idle", None)]:
        assert (
            client.put(
                f"{BASE}/workers/{worker_id}",
                json={"route": "a", "status": status, "task_id": task_id},
            ).status_code
            == 204
        )
    first = client.get(f"{BASE}/workers", params={"limit": 1}).json()
    assert first["items"][0]["id"] == W1
    assert (
        client.get(f"{BASE}/workers", params={"cursor": first["next_cursor"]}).json()["items"][0][
            "id"
        ]
        == W2
    )
    expressions = {
        'route in ["a", "b"] and status == "idle"': 1,
        "task_id != None": 1,
        "exists(task_id)": 2,
        "missing(task_id)": 0,
        'queue == "default" and expires_at > "2020-01-01T00:00:00Z"': 2,
        'last_seen_at >= "2020-01-01T00:00:00Z"': 2,
        f'id == "{W1}" or status == "busy"': 2,
    }
    for expression, count in expressions.items():
        response = client.get(f"{BASE}/workers/count", params={"filter": expression})
        assert response.status_code == 200, response.text
        assert response.json() == {"count": count}
    for expression in ['status == "pending"', "metadata.x == 1", "expires_at > 1", '"a" in route']:
        response = client.get(f"{BASE}/workers/count", params={"filter": expression})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_filter"
    assert (
        client.get(
            f"{BASE}/workers", params={"cursor": first["next_cursor"], "filter": 'status == "idle"'}
        ).status_code
        == 422
    )


def test_observation_validation_and_route_identity(client: TestClient) -> None:
    path = f"{BASE}/workers/{W1}"
    for body in [
        {"route": "a", "status": "running", "task_id": None},
        {"route": "a", "status": "idle"},
        {"route": "a", "status": "busy", "task_id": "bad"},
    ]:
        response = client.put(path, json=body)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_request"
    payload = {"route": "a", "status": "idle", "task_id": None}
    assert client.put(path, json=payload).status_code == 204
    assert client.put(path, json={**payload, "route": "b"}).status_code == 409
    assert client.put(f"{BASE}/workers/not-an-id", json=payload).status_code == 422


def test_worker_migration_preserves_existing_tasks_and_is_repeatable(tmp_path: Path) -> None:
    path = tmp_path / "upgrade.db"
    db = Database(path)
    db.initialize()
    TaskService(db).create("default", "t_ABCDEFGHIJKL", TaskCreate(routes=["a", "b"]))
    config = Config()
    config.set_main_option(
        "script_location",
        str(
            Path(__file__).parents[2] / "packages/labtasker-server/src/labtasker_server/migrations"
        ),
    )
    with db.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0001_initial")
    assert "workers" not in inspect(db.engine).get_table_names()
    db.dispose()
    upgraded = Database(path)
    try:
        upgraded.initialize()
        upgraded.initialize()
        assert "workers" in inspect(upgraded.engine).get_table_names()
        assert TaskService(upgraded).get("default", "t_ABCDEFGHIJKL").routes == ["a", "b"]
    finally:
        upgraded.dispose()


def test_concurrent_observation_upserts_do_not_duplicate_or_mutate_tasks(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from labtasker_server.schemas import WorkerReport
    from labtasker_server.services.workers import WorkerService

    database = Database(tmp_path / "concurrent.db")
    try:
        database.initialize()
        task_service = TaskService(database)
        before, _ = task_service.create("default", "t_ABCDEFGHIJKL", TaskCreate(routes=["a"]))
        service = WorkerService(database)
        payload = WorkerReport(route="a", status="busy", task_id=before.id)
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(service.report, "default", W1, payload) for _ in range(8)]
            for future in futures:
                future.result(timeout=5)
        assert service.count("default") == 1
        assert task_service.get("default", before.id) == before
        service.withdraw("default", W1)
        assert task_service.get("default", before.id) == before
    finally:
        database.dispose()


def test_openapi_observation_schemas_and_count_union(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    models = schema["components"]["schemas"]
    assert set(models["WorkerReport"]["required"]) == {"route", "status", "task_id"}
    assert models["WorkerReport"]["additionalProperties"] is False
    assert models["WorkerReport"]["properties"]["status"]["enum"] == ["idle", "busy"]
    assert set(models["WorkerObservation"]["required"]) == {
        "id",
        "queue",
        "route",
        "status",
        "task_id",
        "last_seen_at",
        "expires_at",
    }
    for resource in ["tasks", "workers"]:
        operation = schema["paths"][f"/api/v2/queues/{{queue}}/{resource}/count"]["get"]
        result = operation["responses"]["200"]["content"]["application/json"]["schema"]
        assert {item["$ref"].rsplit("/", 1)[-1] for item in result["anyOf"]} == {
            "CountResponse",
            "GroupCountPage",
        }
        assert {"group_by", "limit", "cursor"} <= {p["name"] for p in operation["parameters"]}


@pytest.mark.parametrize(
    "fields", [["routes"], ["status"], ["routes", "status"], ["status", "routes"]]
)
@pytest.mark.parametrize("selection", [{}, {"status": "pending"}, {"filter": '"b" not in routes'}])
def test_task_group_pages_match_independent_membership_counts(
    client: TestClient, fields: list[str], selection: dict[str, str]
) -> None:
    from collections import Counter

    definitions = [["a", "b"], ["A", "a"], ["b"], ["c"], ["a", "b"], ["c"]]
    for i, routes in enumerate(definitions):
        response = client.put(f"{BASE}/tasks/t_{i:012}", json={"routes": routes})
        assert response.status_code == 201
    client.post(f"{BASE}/tasks/t_{0:012}/cancel")
    client.post(f"{BASE}/tasks/claim", json={"route": "c", "run_id": "r_ABCDEFGHIJKL"})
    client.put("/api/v2/queues/other")
    client.put("/api/v2/queues/other/tasks/t_ABCDEFGHIJKL", json={"routes": ["a"]})
    tasks = client.get(f"{BASE}/tasks", params=selection).json()["items"]
    expected = Counter()
    for task in tasks:
        for route in task["routes"] if "routes" in fields else [None]:
            expected[tuple(route if field == "routes" else task["status"] for field in fields)] += 1
    cursor = None
    actual = []
    while True:
        params = {**selection, "group_by": ",".join(fields), "limit": 1}
        if cursor is not None:
            params["cursor"] = cursor
        response = client.get(f"{BASE}/tasks/count", params=params)
        assert response.status_code == 200, response.text
        page = response.json()
        assert page["count"] == len(tasks)
        actual.extend(
            (tuple(item["key"][f] for f in fields), item["count"]) for item in page["items"]
        )
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert actual == sorted(expected.items())


def test_long_filter_cursor_round_trips_through_http(client: TestClient) -> None:
    client.put(f"{BASE}/tasks/t_ABCDEFGHIJKL", json={"routes": ["a", "b"]})
    selection = {"group_by": "routes", "limit": 1, "filter": 'status == "pending"' + "\t" * 7000}
    first = client.get(f"{BASE}/tasks/count", params=selection)
    assert first.status_code == 200, first.text
    second = client.get(
        f"{BASE}/tasks/count", params={**selection, "cursor": first.json()["next_cursor"]}
    )
    assert second.status_code == 200, second.text
    assert second.json()["items"] == [{"key": {"routes": "b"}, "count": 1}]
