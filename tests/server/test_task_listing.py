from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from labtasker_server.app import create_app
from labtasker_server.config import ServerSettings


class Clock:
    def __init__(self) -> None:
        self.value = 1_700_000_000_000_000

    def __call__(self) -> int:
        return self.value


def create_tasks(client: TestClient) -> None:
    definitions = [
        {"name": None, "priority": 0, "metadata": {"group": "a"}},
        {"name": "beta", "priority": 2, "metadata": {"group": "a"}},
        {"name": "alpha", "priority": 1, "metadata": {"group": "b"}},
        {"name": None, "priority": 2, "metadata": {"group": "b"}},
    ]
    for index, body in enumerate(definitions, start=1):
        response = client.put(
            f"/api/v2/queues/default/tasks/t_{index:012d}",
            json=body,
        )
        assert response.status_code == 201


def test_default_listing_uses_stable_keyset_pages(database_path: Path) -> None:
    app = create_app(ServerSettings(database=database_path), now_us=Clock())
    with TestClient(app) as client:
        create_tasks(client)
        first = client.get("/api/v2/queues/default/tasks", params={"limit": 2}).json()
        assert [item["id"] for item in first["items"]] == [
            "t_000000000004",
            "t_000000000003",
        ]
        assert isinstance(first["next_cursor"], str)

        second = client.get(
            "/api/v2/queues/default/tasks",
            params={"limit": 2, "cursor": first["next_cursor"]},
        ).json()
        assert [item["id"] for item in second["items"]] == [
            "t_000000000002",
            "t_000000000001",
        ]
        assert second["next_cursor"] is None

        ascending = client.get(
            "/api/v2/queues/default/tasks",
            params={"order_by": "created_at", "descending": "false"},
        ).json()
        assert [item["id"] for item in ascending["items"]] == [
            "t_000000000001",
            "t_000000000002",
            "t_000000000003",
            "t_000000000004",
        ]


def test_null_order_values_sort_last_in_both_directions(database_path: Path) -> None:
    app = create_app(ServerSettings(database=database_path), now_us=Clock())
    with TestClient(app) as client:
        create_tasks(client)
        ascending = client.get(
            "/api/v2/queues/default/tasks",
            params={"order_by": "name", "descending": "false"},
        ).json()
        descending = client.get(
            "/api/v2/queues/default/tasks",
            params={"order_by": "name", "descending": "true"},
        ).json()
        assert [(item["name"], item["id"]) for item in ascending["items"]] == [
            ("alpha", "t_000000000003"),
            ("beta", "t_000000000002"),
            (None, "t_000000000001"),
            (None, "t_000000000004"),
        ]
        assert [(item["name"], item["id"]) for item in descending["items"]] == [
            ("beta", "t_000000000002"),
            ("alpha", "t_000000000003"),
            (None, "t_000000000004"),
            (None, "t_000000000001"),
        ]


def test_list_and_count_share_and_combined_selection(database_path: Path) -> None:
    app = create_app(ServerSettings(database=database_path), now_us=Clock())
    with TestClient(app) as client:
        create_tasks(client)
        parameters = {
            "status": "pending",
            "name": "beta",
            "filter": 'metadata.group == "a" and priority >= 2',
        }
        page = client.get("/api/v2/queues/default/tasks", params=parameters)
        count = client.get("/api/v2/queues/default/tasks/count", params=parameters)
        assert page.status_code == count.status_code == 200
        assert [item["id"] for item in page.json()["items"]] == ["t_000000000002"]
        assert count.json() == {"count": 1}


def test_cursor_allows_limit_change_but_rejects_selection_change(database_path: Path) -> None:
    app = create_app(ServerSettings(database=database_path), now_us=Clock())
    with TestClient(app) as client:
        create_tasks(client)
        cursor = client.get(
            "/api/v2/queues/default/tasks",
            params={"limit": 1, "status": "pending"},
        ).json()["next_cursor"]
        changed_limit = client.get(
            "/api/v2/queues/default/tasks",
            params={"limit": 3, "status": "pending", "cursor": cursor},
        )
        assert changed_limit.status_code == 200
        assert len(changed_limit.json()["items"]) == 3

        for changed in (
            {"status": "failed"},
            {"order_by": "priority"},
            {"descending": "false"},
            {"filter": "priority >= 0"},
        ):
            response = client.get(
                "/api/v2/queues/default/tasks",
                params={"cursor": cursor, **changed},
            )
            assert response.status_code == 422
            assert response.json()["error"]["code"] == "invalid_cursor"


def test_malformed_cursor_and_invalid_list_inputs_are_explicit(client: TestClient) -> None:
    malformed = client.get(
        "/api/v2/queues/default/tasks",
        params={"cursor": "not-base64!"},
    )
    assert malformed.status_code == 422
    assert malformed.json()["error"]["code"] == "invalid_cursor"

    for parameters in (
        {"limit": 0},
        {"limit": 1001},
        {"status": "unknown"},
        {"order_by": "duration"},
    ):
        response = client.get("/api/v2/queues/default/tasks", params=parameters)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_request"


def test_empty_page_and_unknown_queue(client: TestClient) -> None:
    assert client.get("/api/v2/queues/default/tasks").json() == {
        "items": [],
        "next_cursor": None,
    }
    missing = client.get("/api/v2/queues/missing/tasks")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "queue_not_found"
