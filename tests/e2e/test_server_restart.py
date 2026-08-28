from __future__ import annotations

import os
import socket
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
import uvicorn

from labtasker import APIError, Client, TransportError
from labtasker.command_worker import run_command_worker
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


def test_terminal_tasks_remain_identical_after_server_restart(tmp_path: Path) -> None:
    database = tmp_path / "terminal-persistence.db"
    port = unused_port()
    clock = Clock()
    url = f"http://127.0.0.1:{port}"

    with running_server(database, port, clock), Client(url=url, token=TOKEN) as client:
        client.submit_task({}, task_id="t_PERSISTSUCC1", routes=["persist"])
        succeeded_claim = client._claim(route="persist", run_id="r_PERSISTSUCC1", queue="default")
        assert succeeded_claim is not None
        client._complete(
            task_id=succeeded_claim.task.id,
            run_id=succeeded_claim.run_id,
            result={"score": 1},
            queue="default",
        )

        client.submit_task({}, task_id="t_PERSISTFAIL1", routes=["persist-fail"], max_attempts=1)
        failed_claim = client._claim(route="persist-fail", run_id="r_PERSISTFAIL1", queue="default")
        assert failed_claim is not None
        client._fail(
            task_id=failed_claim.task.id,
            run_id=failed_claim.run_id,
            error_type="ModelError",
            message="out of memory",
            traceback=None,
            queue="default",
        )

        client.submit_task({}, task_id="t_PERSISTCANC1")
        client.cancel_task("t_PERSISTCANC1")
        before = {
            task_id: client.get_task(task_id).model_dump(mode="json")
            for task_id in ("t_PERSISTSUCC1", "t_PERSISTFAIL1", "t_PERSISTCANC1")
        }

    with running_server(database, port, clock), Client(url=url, token=TOKEN) as client:
        after = {task_id: client.get_task(task_id).model_dump(mode="json") for task_id in before}

    assert after == before


@pytest.mark.skipif(os.name != "posix", reason="Command Workers require POSIX process groups")
def test_partitioned_command_worker_is_stopped_after_another_run_takes_over(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "partition.db"
    marker = tmp_path / "old-child.pid"
    port = unused_port()
    clock = Clock()
    url = f"http://127.0.0.1:{port}"
    old_run_id = "r_OLDPARTITION"
    new_run_id = "r_NEWPARTITION"
    partitioned = threading.Event()
    heartbeat_blocked = threading.Event()
    release_heartbeat = threading.Event()
    original_heartbeat = Client._heartbeat
    generated_run_ids = iter((old_run_id, "r_AFTERPART001"))

    def gated_heartbeat(self: Client, **kwargs: object) -> object:
        if kwargs.get("run_id") == old_run_id and partitioned.is_set():
            heartbeat_blocked.set()
            if not release_heartbeat.wait(3):
                raise TimeoutError("Test did not restore the heartbeat path.")
        return original_heartbeat(self, **kwargs)  # type: ignore[arg-type]

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LABTASKER_URL", url)
    monkeypatch.setenv("LABTASKER_TOKEN", TOKEN)
    monkeypatch.setattr("labtasker.worker.HEARTBEAT_INTERVAL_SECONDS", 0.02)
    monkeypatch.setattr(
        "labtasker.command_worker._generate_run_id", lambda: next(generated_run_ids)
    )
    monkeypatch.setattr(Client, "_heartbeat", gated_heartbeat)

    worker_errors: list[BaseException] = []
    child_script = (
        "import os,sys,time; open(sys.argv[1], 'w').write(str(os.getpid())); time.sleep(30)"
    )

    def run_old_worker() -> None:
        try:
            run_command_worker(
                [sys.executable, "-c", child_script, str(marker)],
                route="partition",
                idle_timeout=0,
                force_stop_timeout=0.2,
            )
        except BaseException as error:
            worker_errors.append(error)

    with running_server(database, port, clock):
        with Client(url=url, token=TOKEN) as client:
            client.submit_task(
                {},
                task_id="t_NETPARTITION",
                routes=["partition"],
                max_attempts=2,
            )
        worker = threading.Thread(target=run_old_worker)
        worker.start()
        deadline = time.monotonic() + 3
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert marker.exists(), "The old command child did not start."
        old_child_pid = int(marker.read_text())
        partitioned.set()
        assert heartbeat_blocked.wait(2)

    clock.advance(HEARTBEAT_TIMEOUT_US)

    try:
        with running_server(database, port, clock), Client(url=url, token=TOKEN) as client:
            expired = client.get_task("t_NETPARTITION")
            assert expired.status == "pending"
            assert expired.last_error is not None
            assert expired.last_error.type == "HeartbeatTimeout"

            replacement = client._claim(
                route="partition",
                run_id=new_run_id,
                queue="default",
            )
            assert replacement is not None
            assert replacement.task.attempt == 2

            release_heartbeat.set()
            worker.join(timeout=3)
            assert not worker.is_alive()
            assert worker_errors == []
            with pytest.raises(ProcessLookupError):
                os.kill(old_child_pid, 0)

            client._complete(
                task_id=replacement.task.id,
                run_id=replacement.run_id,
                result={"replacement": True},
                queue="default",
            )
            final = client.get_task(replacement.task.id)
    finally:
        release_heartbeat.set()
        if worker.is_alive():
            worker.join(timeout=1)
        if worker.is_alive():
            os.kill(old_child_pid, 9)
            worker.join(timeout=1)

    assert final.status == "succeeded"
    assert final.attempt == 2
    assert final.result == {"replacement": True}
    assert final.last_error is not None
    assert final.last_error.type == "HeartbeatTimeout"
