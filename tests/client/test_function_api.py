from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

import labtasker.api as api


class RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def _record(self, name: str, args: tuple[object, ...], kwargs: dict[str, object]) -> Any:
        self.calls.append((name, args, kwargs))
        return name

    def submit_task(self, *args: object, **kwargs: object) -> Any:
        return self._record("submit_task", args, kwargs)

    def get_task(self, *args: object, **kwargs: object) -> Any:
        return self._record("get_task", args, kwargs)

    def list_tasks(self, *args: object, **kwargs: object) -> Any:
        return self._record("list_tasks", args, kwargs)

    def count_tasks(self, *args: object, **kwargs: object) -> Any:
        return self._record("count_tasks", args, kwargs)

    def update_task(self, *args: object, **kwargs: object) -> Any:
        return self._record("update_task", args, kwargs)

    def update_tasks(self, *args: object, **kwargs: object) -> Any:
        return self._record("update_tasks", args, kwargs)

    def cancel_task(self, *args: object, **kwargs: object) -> Any:
        return self._record("cancel_task", args, kwargs)

    def requeue_task(self, *args: object, **kwargs: object) -> Any:
        return self._record("requeue_task", args, kwargs)

    def delete_task(self, *args: object, **kwargs: object) -> Any:
        return self._record("delete_task", args, kwargs)

    def create_queue(self, *args: object, **kwargs: object) -> Any:
        return self._record("create_queue", args, kwargs)

    def list_queues(self, *args: object, **kwargs: object) -> Any:
        return self._record("list_queues", args, kwargs)

    def delete_queue(self, *args: object, **kwargs: object) -> Any:
        return self._record("delete_queue", args, kwargs)


@pytest.fixture
def recording_client(monkeypatch: pytest.MonkeyPatch) -> RecordingClient:
    client = RecordingClient()
    monkeypatch.setattr(api, "_default_client", client)
    return client


def test_function_first_surface_is_only_a_thin_client_facade(
    recording_client: RecordingClient,
) -> None:
    assert (
        api.submit_task(
            {"seed": 3},
            name="demo",
            metadata={"group": "a"},
            priority=2,
            max_attempts=4,
            routes=["gpu"],
            task_id="t_ABCDEFGHIJKL",
            queue="experiments",
        )
        == "submit_task"
    )
    assert api.get_task("t_ABCDEFGHIJKL", queue="experiments") == "get_task"
    assert (
        api.list_tasks(
            status="pending",
            name="demo",
            filter="priority >= 2",
            order_by="priority",
            descending=False,
            limit=8,
            cursor="cursor",
            queue="experiments",
        )
        == "list_tasks"
    )
    assert api.count_tasks(status="pending", name="demo", queue="experiments") == "count_tasks"
    assert api.update_task("t_ABCDEFGHIJKL", {"priority": 4}, queue="experiments") == "update_task"
    assert (
        api.update_tasks(
            filter='status == "pending"',
            changes={"routes": ["gpu-v2"]},
            queue="experiments",
        )
        == "update_tasks"
    )
    assert api.cancel_task("t_ABCDEFGHIJKL", queue="experiments") == "cancel_task"
    assert api.requeue_task("t_ABCDEFGHIJKL", queue="experiments") == "requeue_task"
    assert api.delete_task("t_ABCDEFGHIJKL", queue="experiments") is None
    assert api.create_queue("experiments") == "create_queue"
    assert api.list_queues() == "list_queues"
    assert api.delete_queue("experiments", cascade=True) is None

    assert [name for name, _, _ in recording_client.calls] == [
        "submit_task",
        "get_task",
        "list_tasks",
        "count_tasks",
        "update_task",
        "update_tasks",
        "cancel_task",
        "requeue_task",
        "delete_task",
        "create_queue",
        "list_queues",
        "delete_queue",
    ]
    assert recording_client.calls[0] == (
        "submit_task",
        ({"seed": 3},),
        {
            "name": "demo",
            "metadata": {"group": "a"},
            "priority": 2,
            "max_attempts": 4,
            "routes": ["gpu"],
            "task_id": "t_ABCDEFGHIJKL",
            "queue": "experiments",
        },
    )


def test_default_client_is_constructed_lazily_once_across_threads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed: list[RecordingClient] = []

    def construct() -> RecordingClient:
        client = RecordingClient()
        constructed.append(client)
        return client

    monkeypatch.setattr(api, "_default_client", None)
    monkeypatch.setattr(api, "Client", construct)
    with ThreadPoolExecutor(max_workers=8) as executor:
        clients = list(executor.map(lambda _: api._client(), range(32)))
    assert len(constructed) == 1
    assert all(client is constructed[0] for client in clients)
