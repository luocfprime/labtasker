from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from labtasker import Client, TransportError, finish, loop
from labtasker.command_worker import run_command_worker
from labtasker_server.local import LAUNCH_THROTTLE_SECONDS
from labtasker_server.local import local_paths as server_local_paths

LOCAL_ENVIRONMENT_NAMES = (
    "LABTASKER_URL",
    "LABTASKER_TOKEN",
    "LABTASKER_SOCKET",
    "LABTASKER_LOCAL_DIRECTORY",
    "LABTASKER_QUEUE",
)


def _local_environment() -> dict[str, str]:
    environment = dict(os.environ)
    for name in LOCAL_ENVIRONMENT_NAMES:
        environment.pop(name, None)
    return environment


def _server_command(directory: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "labtasker_server", *arguments],
        cwd=directory,
        env=_local_environment(),
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )


def _server_status(directory: Path) -> dict[str, object]:
    result = _server_command(directory, "status")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    return payload


def _kill_daemon_and_wait_for_backoff(directory: Path) -> int:
    running = _server_status(directory)
    pid = running["pid"]
    assert isinstance(pid, int)
    os.kill(pid, signal.SIGKILL)

    deadline = time.monotonic() + 5
    while True:
        if _server_status(directory)["state"] == "backoff":
            return pid
        assert time.monotonic() < deadline
        time.sleep(0.05)


def _expire_launch_backoff(directory: Path) -> None:
    paths = server_local_paths(directory)
    payload = json.loads(paths.metadata.read_text(encoding="utf-8"))
    payload["automatic_attempt_at"] = time.time() - LAUNCH_THROTTLE_SECONDS - 1
    paths.metadata.write_text(json.dumps(payload), encoding="utf-8")


@pytest.mark.skipif(os.name != "posix", reason="local mode requires POSIX")
def test_default_local_client_starts_daemon_and_command_child_reuses_it(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    for name in LOCAL_ENVIRONMENT_NAMES:
        monkeypatch.delenv(name, raising=False)

    try:
        with Client() as client:
            assert [queue.name for queue in client.list_queues()] == ["default"]
            created = client.submit_task(
                {"value": 7},
                routes=["command"],
                task_id="t_LOCALCOMMAND",
            )
            assert created.status == "pending"

        diagnostic = capfd.readouterr().err
        assert "[labtasker-server] created local daemon" in diagnostic
        assert "[labtasker] connected server=local transport=unix" in diagnostic
        assert f"directory={tmp_path}" in diagnostic
        assert f"database={tmp_path / '.labtasker/server.db'}" in diagnostic
        assert " pid=" in diagnostic
        assert " version=" in diagnostic

        run_command_worker(
            [
                sys.executable,
                "-c",
                "import labtasker; labtasker.finish({'value': 14})",
            ],
            route="command",
            idle_timeout=0,
        )
        with Client() as client:
            task = client.get_task("t_LOCALCOMMAND")
        assert task.status == "succeeded"
        assert task.result == {"value": 14}

        loop_result = subprocess.run(
            [
                sys.executable,
                "-m",
                "labtasker",
                "loop",
                "--idle-timeout",
                "0",
                "--",
                sys.executable,
                "-c",
                "pass",
            ],
            cwd=tmp_path,
            env=_local_environment(),
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert loop_result.returncode == 0, loop_result.stderr
        assert loop_result.stdout == ""
        assert re.search(
            r"(?m)^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z "
            r"INFO \[labtasker\] Worker idle timeout reached; stopping normally\.$",
            loop_result.stderr,
        )

        status = _server_command(tmp_path, "status")
        assert status.returncode == 0
        payload = json.loads(status.stdout)
        assert payload["state"] == "running"
        assert payload["directory"] == str(tmp_path)
        assert payload["database"] == str(tmp_path / ".labtasker/server.db")
        assert payload["pid"] is not None
        server_log = (tmp_path / ".labtasker/server.log").read_text()
        assert re.search(
            r"(?m)^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z "
            r"INFO \[labtasker-server\] ",
            server_log,
        )
    finally:
        stopped = _server_command(tmp_path, "stop")
        assert stopped.returncode == 0, stopped.stderr

    assert _server_command(tmp_path, "status").stdout.startswith('{\n  "state": "stopped"')


@pytest.mark.skipif(os.name != "posix", reason="local mode requires POSIX")
def test_concurrent_first_clients_elect_exactly_one_daemon(tmp_path: Path) -> None:
    script = (
        "from labtasker import Client; "
        "client=Client(); "
        "print(len(client.list_queues())); "
        "client.close()"
    )

    def invoke() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-c", script],
            cwd=tmp_path,
            env=_local_environment(),
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )

    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda _: invoke(), range(4)))
        outcomes = [(result.returncode, result.stdout) for result in results]
        assert (
            outcomes
            == [
                (0, "1\n"),
            ]
            * 4
        ), [result.stderr for result in results]
        diagnostics = "".join(result.stderr for result in results)
        assert diagnostics.count("[labtasker-server] created local daemon") == 1
        assert _server_command(tmp_path, "status").returncode == 0
    finally:
        stopped = _server_command(tmp_path, "stop")
        assert stopped.returncode == 0, stopped.stderr


@pytest.mark.skipif(os.name != "posix", reason="local mode requires POSIX")
def test_dead_daemon_is_throttled_and_explicit_start_recovers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    for name in LOCAL_ENVIRONMENT_NAMES:
        monkeypatch.delenv(name, raising=False)

    try:
        with Client() as client:
            assert len(client.list_queues()) == 1
        _kill_daemon_and_wait_for_backoff(tmp_path)

        with Client() as client, pytest.raises(TransportError) as raised:
            client.list_queues()
        assert raised.value.details["state"] == "backoff"
        assert raised.value.details["retry_after_seconds"] > 0

        restarted = _server_command(tmp_path, "start")
        assert restarted.returncode == 0, restarted.stderr
        assert "[labtasker-server] started local daemon" in restarted.stderr
        with Client() as client:
            assert len(client.list_queues()) == 1
    finally:
        stopped = _server_command(tmp_path, "stop")
        assert stopped.returncode == 0, stopped.stderr


@pytest.mark.skipif(os.name != "posix", reason="local mode requires POSIX")
def test_expired_backoff_allows_the_next_client_to_restart_automatically(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    for name in LOCAL_ENVIRONMENT_NAMES:
        monkeypatch.delenv(name, raising=False)

    try:
        with Client() as client:
            assert len(client.list_queues()) == 1
        old_pid = _kill_daemon_and_wait_for_backoff(tmp_path)
        _expire_launch_backoff(tmp_path)

        with Client() as client:
            assert [queue.name for queue in client.list_queues()] == ["default"]
        restarted = _server_status(tmp_path)
        assert restarted["state"] == "running"
        assert isinstance(restarted["pid"], int)
        assert restarted["pid"] != old_pid
    finally:
        stopped = _server_command(tmp_path, "stop")
        assert stopped.returncode == 0, stopped.stderr


@pytest.mark.skipif(os.name != "posix", reason="local mode requires POSIX")
def test_existing_client_recovers_when_daemon_dies_between_requests(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    for name in LOCAL_ENVIRONMENT_NAMES:
        monkeypatch.delenv(name, raising=False)

    try:
        with Client() as client:
            assert [queue.name for queue in client.list_queues()] == ["default"]
            old_pid = _kill_daemon_and_wait_for_backoff(tmp_path)
            _expire_launch_backoff(tmp_path)

            assert [queue.name for queue in client.list_queues()] == ["default"]

        restarted = _server_status(tmp_path)
        assert restarted["state"] == "running"
        assert isinstance(restarted["pid"], int)
        assert restarted["pid"] != old_pid
    finally:
        stopped = _server_command(tmp_path, "stop")
        assert stopped.returncode == 0, stopped.stderr


@pytest.mark.skipif(os.name != "posix", reason="local mode requires POSIX")
def test_local_python_worker_recovers_heartbeat_after_daemon_crash(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    for name in LOCAL_ENVIRONMENT_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("labtasker.worker.HEARTBEAT_INTERVAL_SECONDS", 0.05)

    handler_started = threading.Event()
    release_handler = threading.Event()
    worker_errors: list[BaseException] = []

    @loop(route="recovery", idle_timeout=0)
    def worker() -> None:
        handler_started.set()
        assert release_handler.wait(10), "Test did not release the Worker handler."
        finish({"recovered": True})

    def run_worker() -> None:
        try:
            worker()
        except BaseException as error:
            worker_errors.append(error)

    try:
        with Client() as client:
            client.submit_task(
                {},
                routes=["recovery"],
                task_id="t_LOCALRECOVER",
            )

        worker_thread = threading.Thread(target=run_worker)
        worker_thread.start()
        assert handler_started.wait(5), "Worker did not claim the Task."

        old_pid = _kill_daemon_and_wait_for_backoff(tmp_path)
        time.sleep(0.1)
        assert worker_thread.is_alive()
        _expire_launch_backoff(tmp_path)

        deadline = time.monotonic() + 5
        while True:
            status = _server_status(tmp_path)
            if status["state"] == "running" and status["pid"] != old_pid:
                break
            assert time.monotonic() < deadline
            time.sleep(0.05)

        release_handler.set()
        worker_thread.join(timeout=5)
        assert not worker_thread.is_alive()
        assert worker_errors == []

        with Client() as client:
            task = client.get_task("t_LOCALRECOVER")
        assert task.status == "succeeded"
        assert task.attempt == 1
        assert task.result == {"recovered": True}
    finally:
        release_handler.set()
        stopped = _server_command(tmp_path, "stop")
        assert stopped.returncode == 0, stopped.stderr


@pytest.mark.skipif(os.name != "posix", reason="local mode requires POSIX")
def test_terminal_report_retries_after_local_daemon_crash(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    for name in LOCAL_ENVIRONMENT_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("labtasker.worker.TERMINAL_BACKOFF_SECONDS", (0.01,))

    original_complete = Client._complete
    complete_attempts = 0

    def crash_once_then_complete(self: Client, **kwargs: object) -> None:
        nonlocal complete_attempts
        complete_attempts += 1
        if complete_attempts == 1:
            _kill_daemon_and_wait_for_backoff(tmp_path)
            try:
                original_complete(self, **kwargs)  # type: ignore[arg-type]
            except TransportError:
                _expire_launch_backoff(tmp_path)
                raise
            raise AssertionError("Terminal report unexpectedly succeeded during backoff.")
        original_complete(self, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Client, "_complete", crash_once_then_complete)

    try:
        with Client() as client:
            client.submit_task(
                {},
                routes=["terminal-recovery"],
                task_id="t_TERMINALRCVR",
            )

        @loop(route="terminal-recovery", idle_timeout=0)
        def worker() -> None:
            finish({"reported_after_restart": True})

        worker()

        assert complete_attempts == 2
        with Client() as client:
            task = client.get_task("t_TERMINALRCVR")
        assert task.status == "succeeded"
        assert task.attempt == 1
        assert task.result == {"reported_after_restart": True}
    finally:
        stopped = _server_command(tmp_path, "stop")
        assert stopped.returncode == 0, stopped.stderr


@pytest.mark.skipif(os.name != "posix", reason="local mode requires POSIX")
def test_explicit_stop_then_client_restarts_with_persisted_tasks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    for name in LOCAL_ENVIRONMENT_NAMES:
        monkeypatch.delenv(name, raising=False)

    try:
        with Client() as client:
            created = client.submit_task(
                {"persisted": True},
                task_id="t_STOPRESTART1",
            )
        old_pid = _server_status(tmp_path)["pid"]
        assert isinstance(old_pid, int)

        stopped = _server_command(tmp_path, "stop")
        assert stopped.returncode == 0, stopped.stderr
        assert _server_status(tmp_path)["state"] == "stopped"

        with Client() as client:
            recovered = client.get_task(created.id)
        restarted = _server_status(tmp_path)
        assert restarted["state"] == "running"
        assert isinstance(restarted["pid"], int)
        assert restarted["pid"] != old_pid
        assert recovered.args == {"persisted": True}
        assert recovered.status == "pending"
    finally:
        stopped = _server_command(tmp_path, "stop")
        assert stopped.returncode == 0, stopped.stderr
