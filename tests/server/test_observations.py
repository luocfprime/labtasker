from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

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
                json={
                    "route": "a",
                    "status": status,
                    "task_id": task_id,
                    "metadata": {"node": "n1" if worker_id == W1 else "n2"},
                },
            ).status_code
            == 204
        )
    assert (
        client.post(
            f"{BASE}/workers/{W2}/telemetry",
            json={"telemetry": {"gpu": {"utilization": 0.25}, "tags": ["slow"]}},
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
        'metadata.node == "n1"': 1,
        "telemetry.gpu.utilization < 0.5": 1,
        '"slow" in telemetry.tags': 1,
        "missing(telemetry.gpu.utilization)": 1,
        'telemetry_updated_at > "2020-01-01T00:00:00Z"': 1,
    }
    for expression, count in expressions.items():
        response = client.get(f"{BASE}/workers/count", params={"filter": expression})
        assert response.status_code == 200, response.text
        assert response.json() == {"count": count}
    for expression in ['status == "pending"', "metadata == 1", "expires_at > 1", '"a" in route']:
        response = client.get(f"{BASE}/workers/count", params={"filter": expression})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_filter"
    for field in ["metadata.node", "telemetry.gpu"]:
        response = client.get(f"{BASE}/workers/count", params={"group_by": field})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_request"
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
    assert client.get(f"{BASE}/workers").json()["items"][0]["metadata"] == {}
    assert client.put(path, json={**payload, "route": "b"}).status_code == 409
    assert client.put(f"{BASE}/workers/not-an-id", json=payload).status_code == 422
    for body in [
        {**payload, "metadata": []},
        {**payload, "metadata": {"invalid": 2**63}},
        {**payload, "extra": True},
    ]:
        response = client.put(path, json=body)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_request"

    for body in [
        {},
        {"telemetry": []},
        {"telemetry": {"invalid": 2**63}},
        {"telemetry": {}, "extra": True},
    ]:
        response = client.post(f"{path}/telemetry", json=body)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_request"


def test_worker_telemetry_is_a_separate_nonrenewing_snapshot(tmp_path: Path) -> None:
    now = [1_700_000_000_000_000]
    app = create_app(ServerSettings(database=tmp_path / "telemetry.db"), now_us=lambda: now[0])
    with TestClient(app) as client:
        report = {
            "route": "train",
            "status": "idle",
            "task_id": None,
            "metadata": {"hostname": "node-7", "gpu_ids": ["GPU-a"]},
        }
        assert client.put(f"{BASE}/workers/{W1}", json=report).status_code == 204
        before = client.get(f"{BASE}/workers").json()["items"][0]
        assert before["metadata"] == report["metadata"]
        assert before["telemetry"] is None
        assert before["telemetry_updated_at"] is None

        now[0] += 10_000_000
        assert (
            client.post(
                f"{BASE}/workers/{W1}/telemetry",
                json={"telemetry": {"gpu_utilization": 0.75}},
            ).status_code
            == 204
        )
        after = client.get(f"{BASE}/workers").json()["items"][0]
        assert after["telemetry"] == {"gpu_utilization": 0.75}
        assert after["telemetry_updated_at"].endswith("Z")
        assert after["last_seen_at"] == before["last_seen_at"]
        assert after["expires_at"] == before["expires_at"]

        now[0] += 10_000_000
        refreshed_report = {**report, "status": "busy", "metadata": {"hostname": "node-8"}}
        assert client.put(f"{BASE}/workers/{W1}", json=refreshed_report).status_code == 204
        refreshed = client.get(f"{BASE}/workers").json()["items"][0]
        assert refreshed["metadata"] == {"hostname": "node-8"}
        assert refreshed["telemetry"] == after["telemetry"]
        assert refreshed["telemetry_updated_at"] == after["telemetry_updated_at"]

        now[0] += 10_000_000
        assert (
            client.post(f"{BASE}/workers/{W1}/telemetry", json={"telemetry": {}}).status_code == 204
        )
        replaced = client.get(f"{BASE}/workers").json()["items"][0]
        assert replaced["telemetry"] == {}
        assert replaced["telemetry_updated_at"] != after["telemetry_updated_at"]

        now[0] += 300_000_000
        response = client.post(f"{BASE}/workers/{W1}/telemetry", json={"telemetry": {}})
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "worker_not_found"

        missing = client.post(f"{BASE}/workers/{W2}/telemetry", json={"telemetry": {}})
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "worker_not_found"

        assert client.put("/api/v2/queues/temporary", json={}).status_code == 201
        assert client.delete("/api/v2/queues/temporary").status_code == 204
        absent_queue = client.post(
            f"/api/v2/queues/temporary/workers/{W1}/telemetry", json={"telemetry": {}}
        )
        assert absent_queue.status_code == 404
        assert absent_queue.json()["error"]["code"] == "queue_not_found"


def test_worker_observability_migration_preserves_existing_worker_rows(tmp_path: Path) -> None:
    path = tmp_path / "worker-upgrade.db"
    database = Database(path)
    database.initialize()
    config = Config()
    config.set_main_option(
        "script_location",
        str(
            Path(__file__).parents[2] / "packages/labtasker-server/src/labtasker_server/migrations"
        ),
    )
    try:
        with database.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "0003_task_progress")
            connection.execute(
                text(
                    "INSERT INTO workers "
                    "(queue_name, worker_id, route, status, task_id, "
                    "last_seen_at_us, expires_at_us) "
                    "VALUES ('default', :worker_id, 'train', 'busy', :task_id, 100, 500)"
                ),
                {"worker_id": W1, "task_id": "t_ABCDEFGHIJKL"},
            )
    finally:
        database.dispose()

    upgraded = Database(path)
    try:
        upgraded.initialize()
        with upgraded.read_session() as session:
            row = session.execute(
                text(
                    "SELECT route, status, task_id, metadata_json, telemetry_json, "
                    "telemetry_updated_at_us, last_seen_at_us, expires_at_us "
                    "FROM workers WHERE worker_id = :worker_id"
                ),
                {"worker_id": W1},
            ).one()
        assert tuple(row) == (
            "train",
            "busy",
            "t_ABCDEFGHIJKL",
            "{}",
            None,
            None,
            100,
            500,
        )
    finally:
        upgraded.dispose()


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

    from labtasker_server.schemas import WorkerReport, WorkerTelemetryReport
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
        telemetry_payloads = [
            WorkerTelemetryReport(telemetry={"rank": rank, "values": [rank]}) for rank in range(8)
        ]
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [
                pool.submit(service.report_telemetry, "default", W1, telemetry)
                for telemetry in telemetry_payloads
            ]
            for future in futures:
                future.result(timeout=5)
        observation = service.list("default").items[0]
        assert observation.telemetry in [payload.telemetry for payload in telemetry_payloads]
        assert observation.telemetry_updated_at is not None
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
        "metadata",
        "telemetry",
        "telemetry_updated_at",
        "last_seen_at",
        "expires_at",
    }
    assert set(models["WorkerTelemetryReport"]["required"]) == {"telemetry"}
    assert (
        schema["paths"]["/api/v2/queues/{queue}/workers/{id}/telemetry"]["post"]["responses"][
            "204"
        ]["description"]
        == "Successful Response"
    )
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
