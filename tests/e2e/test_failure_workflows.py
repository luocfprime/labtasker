from __future__ import annotations

import json
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

from labtasker import (
    APIError,
    Client,
    FatalWorkerError,
    TransientError,
    TransportError,
    cancellation_requested,
    finish,
    loop,
    task_info,
)


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


def test_real_http_submit_retries_after_sqlite_busy(
    server_url: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    lock = sqlite3.connect(tmp_path / "server.db")
    lock.execute("BEGIN IMMEDIATE")
    statuses: list[int] = []
    try:
        with Client(url=server_url, token="secret") as client:
            request = client._http.request

            def observe_request(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
                response = request(*args, **kwargs)  # type: ignore[arg-type]
                statuses.append(response.status_code)
                if response.status_code == 503:
                    assert response.json()["error"]["code"] == "database_busy"
                    lock.rollback()
                return response

            monkeypatch.setattr(client._http, "request", observe_request)
            task = client.submit_task(
                {},
                task_id="t_DATABASEBUSY",
            )
    finally:
        if lock.in_transaction:
            lock.rollback()
        lock.close()

    assert statuses == [503, 201]
    assert task.id == "t_DATABASEBUSY"
    assert task.status == "pending"


def test_real_response_loss_replays_idempotent_submit_but_not_update(
    server_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submit_statuses: list[int] = []
    with Client(url=server_url, token="secret") as client:
        request = client._http.request

        def lose_first_submit_response(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            response = request(*args, **kwargs)  # type: ignore[arg-type]
            submit_statuses.append(response.status_code)
            if len(submit_statuses) == 1:
                raise httpx.ReadError("response lost after commit", request=response.request)
            return response

        monkeypatch.setattr(client._http, "request", lose_first_submit_response)
        submitted = client.submit_task(
            {"value": 1},
            task_id="t_RESPONSELOSS",
        )

    assert submit_statuses == [201, 200]
    assert submitted.id == "t_RESPONSELOSS"

    update_statuses: list[int] = []
    with Client(url=server_url, token="secret") as client:
        request = client._http.request

        def lose_update_response(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            response = request(*args, **kwargs)  # type: ignore[arg-type]
            update_statuses.append(response.status_code)
            raise httpx.ReadError("response lost after commit", request=response.request)

        monkeypatch.setattr(client._http, "request", lose_update_response)
        with pytest.raises(TransportError):
            client.update_task("t_RESPONSELOSS", {"priority": 9})

    assert update_statuses == [200]
    with Client(url=server_url, token="secret") as client:
        persisted = client.get_task("t_RESPONSELOSS")
        assert client.count_tasks(filter='id == "t_RESPONSELOSS"') == 1
    assert persisted.priority == 9


def test_multiple_real_http_workers_complete_each_task_exactly_once(server_url: str) -> None:
    task_ids = [f"t_{index:012d}" for index in range(40)]
    with Client(url=server_url, token="secret") as client:
        for task_id in task_ids:
            client.submit_task({}, task_id=task_id, routes=["parallel"])

    completed_ids: list[str] = []
    completed_lock = threading.Lock()

    def consume(worker_index: int) -> None:
        claim_index = 0
        with Client(url=server_url, token="secret") as client:
            while True:
                claim = client._claim(
                    route="parallel",
                    run_id=f"r_{worker_index:02d}{claim_index:010d}",
                    queue="default",
                )
                claim_index += 1
                if claim is None:
                    return
                client._complete(
                    task_id=claim.task.id,
                    run_id=claim.run_id,
                    result={"worker": worker_index},
                    queue="default",
                )
                with completed_lock:
                    completed_ids.append(claim.task.id)

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(consume, range(4)))

    assert Counter(completed_ids) == Counter({task_id: 1 for task_id in task_ids})
    with Client(url=server_url, token="secret") as client:
        tasks = client.list_tasks(status="succeeded", limit=100).items
    assert {task.id for task in tasks} == set(task_ids)
    assert all(task.attempt == 1 for task in tasks)


@pytest.mark.skipif(os.name != "posix", reason="signal interruption requires POSIX")
def test_sigint_unclaims_python_worker_for_replacement(
    server_url: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LABTASKER_URL", server_url)
    monkeypatch.setenv("LABTASKER_TOKEN", "secret")
    marker = tmp_path / "interrupt-worker-started"
    with Client(url=server_url, token="secret") as client:
        client.submit_task(
            {},
            routes=["interrupt"],
            task_id="t_INTERRUPT001",
            max_attempts=2,
        )

    script = """
import sys
import time
from pathlib import Path
from labtasker import loop

@loop(route="interrupt", idle_timeout=0)
def worker():
    Path(sys.argv[1]).write_text("started")
    time.sleep(30)

try:
    worker()
except KeyboardInterrupt:
    raise SystemExit(130)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(marker)],
        cwd=tmp_path,
        env=dict(os.environ),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 5
        while not marker.exists() and process.poll() is None:
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert marker.exists(), "Worker did not claim the Task."
        process.send_signal(signal.SIGINT)
        _, stderr = process.communicate(timeout=5)
        assert process.returncode == 130, stderr
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)

    with Client(url=server_url, token="secret") as client:
        returned = client.get_task("t_INTERRUPT001")
    assert returned.status == "pending"
    assert returned.attempt == 0

    replacement_attempts: list[int] = []

    @loop(route="interrupt", idle_timeout=0)
    def replacement() -> None:
        replacement_attempts.append(task_info().attempt)
        finish({"replacement": True})

    replacement()
    assert replacement_attempts == [1]
    with Client(url=server_url, token="secret") as client:
        completed = client.get_task("t_INTERRUPT001")
    assert completed.status == "succeeded"
    assert completed.result == {"replacement": True}


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
    assert json.loads(result.stdout) == {
        "error": {
            "code": "unauthorized",
            "message": "Authentication is required.",
            "details": {},
        }
    }
    diagnostic = result.stderr.splitlines()[0]
    assert diagnostic.startswith("[labtasker] connected server=remote transport=http url=")
    assert "{\n" not in result.stderr
    assert "Traceback" not in result.stderr
    assert "wrong" not in result.stderr


def test_real_cli_transport_failure_is_json_stdout_without_traceback(tmp_path: Path) -> None:
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
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "transport_error"
    assert payload["error"]["details"]["operation"] == "list_tasks"
    assert payload["error"]["details"]["url"] == f"http://127.0.0.1:{port}"
    assert "{\n" not in result.stderr
    assert "Traceback" not in result.stderr
