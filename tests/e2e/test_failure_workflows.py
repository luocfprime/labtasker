from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from labtasker import (
    APIError,
    Client,
    FatalWorkerError,
    TransientError,
    cancellation_requested,
    finish,
    loop,
    task_info,
)


def stderr_envelope(stderr: str) -> dict[str, Any]:
    start = stderr.find("{")
    assert start >= 0, stderr
    return json.loads(stderr[start:])  # type: ignore[no-any-return]


def test_real_submission_retry_is_idempotent_and_definition_change_conflicts(
    server_url: str,
) -> None:
    with Client(url=server_url, token="secret") as client:
        original = client.submit_task(
            {"config": {"left": 1, "right": 2}},
            routes=["old", "new"],
            task_id="t_RETRYCONF001",
        )
        updated = client.update_task(original.id, {"priority": 20})
        retried = client.submit_task(
            {"config": {"right": 2, "left": 1}},
            routes=["new", "old"],
            max_attempts=3,
            task_id=original.id,
        )
        assert retried == updated

        with pytest.raises(APIError) as raised:
            client.submit_task(
                original.args,
                routes=original.routes,
                max_attempts=4,
                task_id=original.id,
            )
    assert raised.value.status_code == 409
    assert raised.value.code == "task_id_conflict"


def test_real_python_worker_failure_levels(
    server_url: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LABTASKER_URL", server_url)
    monkeypatch.setenv("LABTASKER_TOKEN", "secret")
    with Client(url=server_url, token="secret") as client:
        client.submit_task(
            {},
            routes=["transient"],
            task_id="t_TRANSIENT001",
            max_attempts=1,
        )
        client.submit_task(
            {},
            routes=["fatal"],
            task_id="t_FATALWORKER1",
            max_attempts=2,
        )

    transient_attempts: list[int] = []

    @loop(route="transient", idle_timeout=0)
    def transient_worker() -> None:
        transient_attempts.append(task_info().attempt)
        if len(transient_attempts) == 1:
            raise TransientError("temporary storage outage")
        finish({"recovered": True})

    transient_worker()
    assert transient_attempts == [1, 1]

    @loop(route="fatal", idle_timeout=0)
    def fatal_worker() -> None:
        raise FatalWorkerError("model runtime is corrupted")

    with pytest.raises(FatalWorkerError, match="model runtime is corrupted"):
        fatal_worker()

    with Client(url=server_url, token="secret") as client:
        transient_task = client.get_task("t_TRANSIENT001")
        fatal_task = client.get_task("t_FATALWORKER1")
    assert transient_task.status == "succeeded"
    assert transient_task.attempt == 1
    assert transient_task.last_error is None
    assert transient_task.result == {"recovered": True}
    assert fatal_task.status == "pending"
    assert fatal_task.attempt == 1
    assert fatal_task.last_error is not None
    assert fatal_task.last_error.type == "FatalWorkerError"

    @loop(route="fatal", idle_timeout=0)
    def replacement_worker() -> None:
        finish({"replacement_worker": True})

    replacement_worker()
    with Client(url=server_url, token="secret") as client:
        recovered = client.get_task("t_FATALWORKER1")
    assert recovered.status == "succeeded"
    assert recovered.attempt == 2
    assert recovered.result == {"replacement_worker": True}


def test_real_cancellation_reaches_python_worker_and_fences_completion(
    server_url: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LABTASKER_URL", server_url)
    monkeypatch.setenv("LABTASKER_TOKEN", "secret")
    monkeypatch.setattr("labtasker.worker.HEARTBEAT_INTERVAL_SECONDS", 0.02)
    with Client(url=server_url, token="secret") as client:
        client.submit_task({}, routes=["cancel"], task_id="t_CANCELWORKER")

    started = threading.Event()
    observed_cancellation = threading.Event()
    worker_errors: list[BaseException] = []

    @loop(route="cancel", idle_timeout=0)
    def cancellable_worker() -> None:
        started.set()
        deadline = time.monotonic() + 3
        while not cancellation_requested() and time.monotonic() < deadline:
            time.sleep(0.005)
        if cancellation_requested():
            observed_cancellation.set()
        finish({"must_not_be_accepted": True})

    def run_worker() -> None:
        try:
            cancellable_worker()
        except BaseException as error:
            worker_errors.append(error)

    thread = threading.Thread(target=run_worker)
    thread.start()
    assert started.wait(2)
    with Client(url=server_url, token="secret") as client:
        cancelled = client.cancel_task("t_CANCELWORKER")
    thread.join(timeout=3)

    assert not thread.is_alive()
    assert worker_errors == []
    assert observed_cancellation.is_set()
    assert cancelled.status == "cancelled"
    with Client(url=server_url, token="secret") as client:
        final = client.get_task("t_CANCELWORKER")
    assert final.status == "cancelled"
    assert final.result == {}


def test_real_cli_authentication_failure_is_structured_and_does_not_leak_token(
    server_url: str,
    tmp_path: Path,
) -> None:
    environment = dict(os.environ)
    environment.update(
        {
            "LABTASKER_URL": server_url,
            "LABTASKER_TOKEN": "wrong",
            "LABTASKER_QUEUE": "default",
        }
    )
    result = subprocess.run(
        [sys.executable, "-m", "labtasker", "task", "list"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    diagnostic = result.stderr.splitlines()[0]
    assert diagnostic.startswith("[labtasker] connected server=remote transport=http url=")
    assert stderr_envelope(result.stderr) == {
        "error": {
            "code": "unauthorized",
            "message": "Authentication is required.",
            "details": {},
        }
    }
    assert "Traceback" not in result.stderr
    assert "wrong" not in result.stderr


def test_real_cli_transport_failure_has_no_stdout_or_traceback(tmp_path: Path) -> None:
    with socket.socket() as unavailable:
        unavailable.bind(("127.0.0.1", 0))
        port = unavailable.getsockname()[1]
        environment = dict(os.environ)
        environment.update(
            {
                "LABTASKER_URL": f"http://127.0.0.1:{port}",
                "LABTASKER_QUEUE": "default",
            }
        )
        environment.pop("LABTASKER_TOKEN", None)
        result = subprocess.run(
            [sys.executable, "-m", "labtasker", "task", "list"],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )

    assert result.returncode == 1
    assert result.stdout == ""
    payload = stderr_envelope(result.stderr)
    assert payload["error"]["code"] == "transport_error"
    assert payload["error"]["details"]["operation"] == "list_tasks"
    assert payload["error"]["details"]["url"] == f"http://127.0.0.1:{port}"
    assert "Traceback" not in result.stderr
