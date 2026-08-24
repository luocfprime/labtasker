from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
import uvicorn

from labtasker import APIError, Client, TransportError
from labtasker_server.app import create_app
from labtasker_server.config import ServerSettings
from labtasker_server.services.tasks import HEARTBEAT_TIMEOUT_US

TOKEN = "restart-secret"


class Clock:
    def __init__(self, value: int = 1_800_000_000_000_000) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value

    def advance(self, microseconds: int) -> None:
        self.value += microseconds


def unused_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@contextmanager
def running_server(database: Path, port: int, clock: Clock) -> Iterator[str]:
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(
                ServerSettings(
                    host="127.0.0.1",
                    port=port,
                    database=database,
                    token=TOKEN,
                ),
                now_us=clock,
            ),
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
        pytest.fail("Restart test Server did not start.")
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        assert not thread.is_alive()


def test_restart_within_lease_allows_same_client_and_run_to_finish(tmp_path: Path) -> None:
    database = tmp_path / "restart.db"
    port = unused_port()
    clock = Clock()
    url = f"http://127.0.0.1:{port}"
    with Client(url=url, token=TOKEN) as client:
        with running_server(database, port, clock):
            client.submit_task({}, task_id="t_SHORTRESTART", routes=["restart"])
            claim = client._claim(route="restart", run_id="r_SHORTRESTART", queue="default")
            assert claim is not None

        with pytest.raises(TransportError):
            client._heartbeat(
                task_id=claim.task.id,
                run_id=claim.run_id,
                queue="default",
            )
        clock.advance(HEARTBEAT_TIMEOUT_US - 1)

        with running_server(database, port, clock):
            renewed = client._heartbeat(
                task_id=claim.task.id,
                run_id=claim.run_id,
                queue="default",
            )
            assert renewed.lease_expires_at > claim.lease_expires_at
            client._complete(
                task_id=claim.task.id,
                run_id=claim.run_id,
                result={"recovered": True},
                queue="default",
            )
            task = client.get_task(claim.task.id)

    assert task.status == "succeeded"
    assert task.attempt == 1
    assert task.result == {"recovered": True}


def test_restart_after_lease_expiry_retries_and_fences_old_run(tmp_path: Path) -> None:
    database = tmp_path / "restart-expired.db"
    port = unused_port()
    clock = Clock()
    url = f"http://127.0.0.1:{port}"
    with Client(url=url, token=TOKEN) as client:
        with running_server(database, port, clock):
            client.submit_task(
                {},
                task_id="t_LONGRESTART1",
                routes=["restart"],
                max_attempts=2,
            )
            old_claim = client._claim(
                route="restart",
                run_id="r_LONGRESTART1",
                queue="default",
            )
            assert old_claim is not None

        clock.advance(HEARTBEAT_TIMEOUT_US)

        with running_server(database, port, clock):
            expired = client.get_task(old_claim.task.id)
            assert expired.status == "pending"
            assert expired.attempt == 1
            assert expired.last_error is not None
            assert expired.last_error.type == "HeartbeatTimeout"
            assert expired.last_error.run_id == old_claim.run_id

            new_claim = client._claim(
                route="restart",
                run_id="r_LONGRESTART2",
                queue="default",
            )
            assert new_claim is not None
            assert new_claim.task.attempt == 2

            for operation in (
                lambda: client._heartbeat(
                    task_id=old_claim.task.id,
                    run_id=old_claim.run_id,
                    queue="default",
                ),
                lambda: client._complete(
                    task_id=old_claim.task.id,
                    run_id=old_claim.run_id,
                    result={"stale": True},
                    queue="default",
                ),
            ):
                with pytest.raises(APIError) as raised:
                    operation()
                assert raised.value.status_code == 409
                assert raised.value.code == "run_finalized"
                assert raised.value.details == {"action": "heartbeat_expired"}

            client._complete(
                task_id=new_claim.task.id,
                run_id=new_claim.run_id,
                result={"new_run": True},
                queue="default",
            )
            final = client.get_task(new_claim.task.id)

    assert final.status == "succeeded"
    assert final.attempt == 2
    assert final.result == {"new_run": True}
