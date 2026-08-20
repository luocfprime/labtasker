from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn

from labtasker import APIError, Client
from labtasker_server.app import create_app
from labtasker_server.config import ServerSettings


@pytest.fixture
def server_url(tmp_path: Path) -> Iterator[str]:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    app = create_app(
        ServerSettings(
            host="127.0.0.1",
            port=port,
            database=tmp_path / "server.db",
            token="secret",
        )
    )
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    if not server.started:
        pytest.fail("Uvicorn test Server did not start.")
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        assert not thread.is_alive()


def test_real_client_server_resource_workflow(server_url: str) -> None:
    with Client(url=server_url, token="secret") as client:
        assert [queue.name for queue in client.list_queues()] == ["default"]
        assert client.create_queue("experiments").name == "experiments"
        created = client.submit_task(
            {"seed": 1},
            name="baseline",
            metadata={"group": "a"},
            routes=["gpu-v2", "gpu-v1"],
            task_id="t_ABCDEFGHIJKL",
            queue="experiments",
        )
        assert created.id == "t_ABCDEFGHIJKL"
        assert created.routes == ["gpu-v1", "gpu-v2"]
        assert client.get_task(created.id, queue="experiments") == created
        assert client.count_tasks(queue="experiments", status="pending") == 1
        page = client.list_tasks(
            queue="experiments",
            filter='metadata.group == "a"',
        )
        assert [task.id for task in page.items] == [created.id]

        updated = client.update_task(
            created.id,
            {"args": {"seed": 2}, "routes": ["gpu-v2"]},
            queue="experiments",
        )
        assert updated.args == {"seed": 2}
        assert updated.routes == ["gpu-v2"]
        bulk = client.update_tasks(
            queue="experiments",
            filter='status == "pending"',
            changes={"priority": 10},
        )
        assert bulk.matched == bulk.updated == 1
        assert client.cancel_task(created.id, queue="experiments").status == "cancelled"
        assert client.requeue_task(created.id, queue="experiments").status == "pending"
        client.delete_task(created.id, queue="experiments")
        assert client.count_tasks(queue="experiments") == 0
        client.delete_queue("experiments")
        assert [queue.name for queue in client.list_queues()] == ["default"]


def test_real_server_authentication_error_is_preserved(server_url: str) -> None:
    with Client(url=server_url, token="wrong") as client, pytest.raises(APIError) as raised:
        client.list_queues()
    assert raised.value.status_code == 401
    assert raised.value.code == "unauthorized"
    assert raised.value.details == {}
