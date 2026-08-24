from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from labtasker import Client, TransportError
from labtasker.command_worker import run_command_worker

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
        running = json.loads(_server_command(tmp_path, "status").stdout)
        assert isinstance(running["pid"], int)
        os.kill(running["pid"], signal.SIGKILL)

        deadline = time.monotonic() + 5
        while True:
            status = json.loads(_server_command(tmp_path, "status").stdout)
            if status["state"] == "backoff":
                break
            assert time.monotonic() < deadline
            time.sleep(0.05)

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
