from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text

from labtasker import Client, TransportError
from labtasker_server.database import Database
from labtasker_server.filesystem import detect_filesystem, resolve_database_filesystem
from labtasker_server.local import local_paths

TOKEN = "shared-storage-integration-token"
pytestmark = [
    pytest.mark.shared_storage_integration,
    pytest.mark.timeout(600),
]


@dataclass(frozen=True, slots=True)
class RunningServer:
    process: subprocess.Popen[str]
    url: str
    port: int
    database: Path
    log: Path


def _environment(*, token: bool = True) -> dict[str, str]:
    environment = dict(os.environ)
    for name in (
        "LABTASKER_URL",
        "LABTASKER_SOCKET",
        "LABTASKER_ROOT",
        "LABTASKER_TOKEN",
        "LABTASKER_SERVER_TOKEN",
        "ALL_PROXY",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "all_proxy",
        "http_proxy",
        "https_proxy",
    ):
        environment.pop(name, None)
    if token:
        environment["LABTASKER_SERVER_TOKEN"] = TOKEN
    return environment


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _server_command(database: Path, port: int, *, filesystem: str = "auto") -> list[str]:
    return [
        sys.executable,
        "-m",
        "labtasker_server",
        "serve",
        "--connection",
        "http",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--database",
        str(database),
        "--database-filesystem",
        filesystem,
    ]


def _wait_for_http_server(process: subprocess.Popen[str], url: str, log: Path) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        returncode = process.poll()
        if returncode is not None:
            output = log.read_text(encoding="utf-8", errors="replace")
            pytest.fail(f"shared-storage Server exited with {returncode}:\n{output}")
        try:
            response = httpx.get(f"{url}/health", timeout=1.0)
        except httpx.HTTPError:
            time.sleep(0.05)
            continue
        if response.status_code == 200:
            assert response.json() == {
                "status": "ok",
                "api_version": "2",
                "database": "ok",
            }
            return
        time.sleep(0.05)
    pytest.fail("shared-storage Server did not become healthy within 60 seconds")


@contextmanager
def _running_http_server(
    directory: Path,
    database: Path,
    *,
    filesystem: str = "auto",
) -> Iterator[RunningServer]:
    port = _free_port()
    log_path = directory / f"http-server-{port}.log"
    with log_path.open("w", encoding="utf-8") as log_stream:
        process = subprocess.Popen(
            _server_command(database, port, filesystem=filesystem),
            cwd=directory,
            env=_environment(),
            stdin=subprocess.DEVNULL,
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            text=True,
        )
        server = RunningServer(
            process=process,
            url=f"http://127.0.0.1:{port}",
            port=port,
            database=database,
            log=log_path,
        )
        try:
            _wait_for_http_server(process, server.url, log_path)
            yield server
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)


def _run_server_cli(directory: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "labtasker_server", *arguments],
        cwd=directory,
        env=_environment(token=False),
        capture_output=True,
        text=True,
        check=False,
        timeout=90,
    )


def _stress_task_count() -> int:
    raw = os.environ.get("LABTASKER_SHARED_STORAGE_STRESS_TASKS", "32")
    try:
        count = int(raw)
    except ValueError:
        pytest.fail("LABTASKER_SHARED_STORAGE_STRESS_TASKS must be an integer")
    if not 1 <= count <= 1000:
        pytest.fail("LABTASKER_SHARED_STORAGE_STRESS_TASKS must be between 1 and 1000")
    return count


def test_auto_profile_pragmas_transactions_and_reopen(shared_storage_case: Path) -> None:
    database_path = shared_storage_case / "profile.db"
    detection = detect_filesystem(database_path)
    resolution = resolve_database_filesystem(database_path, "auto")
    assert detection.classification in {"shared", "unknown"}
    assert resolution.effective == "shared"
    assert (resolution.warning is not None) is (detection.classification == "unknown")

    database = Database(database_path, filesystem="auto")
    database.initialize()
    try:
        assert database.filesystem.effective == "shared"
        assert database.engine.pool.size() == 1  # type: ignore[attr-defined]
        assert database.engine.pool._max_overflow == 0  # type: ignore[attr-defined]
        with database.read_session() as session:
            assert session.scalar(text("PRAGMA journal_mode")) == "delete"
            assert session.scalar(text("PRAGMA synchronous")) == 3
            assert session.scalar(text("PRAGMA foreign_keys")) == 1
            assert session.scalar(text("PRAGMA busy_timeout")) == 5000
        with database.write_session() as session:
            session.execute(text("INSERT INTO queues(name) VALUES ('persisted')"))
        with (
            pytest.raises(RuntimeError, match="rollback probe"),
            database.write_session() as session,
        ):
            session.execute(text("INSERT INTO queues(name) VALUES ('rolled-back')"))
            raise RuntimeError("rollback probe")
    finally:
        database.dispose()

    reopened = Database(database_path, filesystem="auto")
    reopened.initialize()
    try:
        with reopened.read_session() as session:
            names = session.scalars(text("SELECT name FROM queues ORDER BY name")).all()
            assert names == ["default", "persisted"]
            assert session.scalar(text("PRAGMA journal_mode")) == "delete"
    finally:
        reopened.dispose()
    assert not database_path.with_name(f"{database_path.name}-wal").exists()
    assert not database_path.with_name(f"{database_path.name}-shm").exists()


def test_http_task_worker_lifecycle_survives_restart(shared_storage_case: Path) -> None:
    database = shared_storage_case / "lifecycle.db"
    with _running_http_server(shared_storage_case, database) as server:
        with Client(url=server.url, token=TOKEN) as client:
            assert client._health().database == "ok"
            client.create_queue("lifecycle")

            task = client.submit_task(
                {"seed": 7},
                name="shared lifecycle",
                routes=["nfs"],
                task_id="t_NFSLIFE00001",
                queue="lifecycle",
            )
            claim = client._claim(
                route="nfs",
                run_id="r_NFSLIFE00001",
                queue="lifecycle",
            )
            assert claim is not None and claim.task.id == task.id
            assert (
                client._heartbeat(
                    task_id=task.id,
                    run_id=claim.run_id,
                    queue="lifecycle",
                ).lease_expires_at
                > claim.lease_expires_at
            )
            client._report_progress(
                task_id=task.id,
                run_id=claim.run_id,
                progress={"step": 1, "storage": "shared"},
                queue="lifecycle",
            )
            client._complete(
                task_id=task.id,
                run_id=claim.run_id,
                result={"score": 0.9},
                queue="lifecycle",
            )

            failed = client.submit_task(
                {},
                routes=["fail"],
                max_attempts=1,
                task_id="t_NFSFAIL00001",
                queue="lifecycle",
            )
            failed_claim = client._claim(
                route="fail",
                run_id="r_NFSFAIL00001",
                queue="lifecycle",
            )
            assert failed_claim is not None and failed_claim.task.id == failed.id
            client._fail(
                task_id=failed.id,
                run_id=failed_claim.run_id,
                error_type="SharedStorageProbe",
                message="expected failure path",
                traceback=None,
                queue="lifecycle",
            )

            managed = client.submit_task(
                {},
                routes=["management"],
                task_id="t_NFSMGMT00001",
                queue="lifecycle",
            )
            assert (
                client.update_task(
                    managed.id,
                    {"priority": 11},
                    queue="lifecycle",
                ).priority
                == 11
            )
            assert client.cancel_task(managed.id, queue="lifecycle").status == "cancelled"
            assert client.requeue_task(managed.id, queue="lifecycle").status == "pending"
            client.delete_task(managed.id, queue="lifecycle")

        headers = {"Authorization": f"Bearer {TOKEN}"}
        with httpx.Client(base_url=server.url, headers=headers, timeout=10) as raw:
            worker_path = "/api/v2/queues/lifecycle/workers/w_NFSWORK00001"
            assert (
                raw.put(
                    worker_path,
                    json={"route": "nfs", "status": "idle", "task_id": None},
                ).status_code
                == 204
            )
            assert (
                raw.post(
                    f"{worker_path}/telemetry",
                    json={"telemetry": {"filesystem": "shared", "healthy": True}},
                ).status_code
                == 204
            )
            assert raw.delete(worker_path).status_code == 204

    with (
        _running_http_server(shared_storage_case, database) as restarted,
        Client(url=restarted.url, token=TOKEN) as client,
    ):
        succeeded = client.get_task("t_NFSLIFE00001", queue="lifecycle")
        failed = client.get_task("t_NFSFAIL00001", queue="lifecycle")
        assert succeeded.status == "succeeded"
        assert succeeded.progress == {"step": 1, "storage": "shared"}
        assert succeeded.result == {"score": 0.9}
        assert failed.status == "failed"
        assert failed.last_error is not None
        assert failed.last_error.type == "SharedStorageProbe"
        assert client.count_workers(queue="lifecycle") == 0


def test_concurrent_http_writers_and_workers_are_stable(shared_storage_case: Path) -> None:
    database = shared_storage_case / "concurrency.db"
    task_count = _stress_task_count()
    task_ids = [f"t_NFS{index:09d}" for index in range(task_count)]

    with _running_http_server(shared_storage_case, database) as server:
        with Client(url=server.url, token=TOKEN) as client:
            client.create_queue("stress")

        def submit(index: int) -> str:
            with Client(url=server.url, token=TOKEN) as client:
                task_id = task_ids[index]
                created = client.submit_task(
                    {"index": index},
                    routes=["stress"],
                    task_id=task_id,
                    queue="stress",
                )
                updated = client.update_task(
                    task_id,
                    {"priority": index},
                    queue="stress",
                )
                assert created.id == updated.id == client.get_task(task_id, queue="stress").id
                return task_id

        with ThreadPoolExecutor(max_workers=min(8, task_count)) as executor:
            assert sorted(executor.map(submit, range(task_count))) == task_ids

        completed: list[str] = []
        completed_lock = threading.Lock()

        def consume(worker_index: int) -> None:
            claim_index = 0
            with Client(url=server.url, token=TOKEN) as client:
                while True:
                    claim = client._claim(
                        route="stress",
                        run_id=f"r_{worker_index:02d}{claim_index:010d}",
                        queue="stress",
                    )
                    claim_index += 1
                    if claim is None:
                        return
                    client._heartbeat(
                        task_id=claim.task.id,
                        run_id=claim.run_id,
                        queue="stress",
                    )
                    client._report_progress(
                        task_id=claim.task.id,
                        run_id=claim.run_id,
                        progress={"worker": worker_index},
                        queue="stress",
                    )
                    client._complete(
                        task_id=claim.task.id,
                        run_id=claim.run_id,
                        result={"worker": worker_index},
                        queue="stress",
                    )
                    with completed_lock:
                        completed.append(claim.task.id)

        worker_count = min(8, task_count)
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            list(executor.map(consume, range(worker_count)))

        with Client(url=server.url, token=TOKEN) as client:
            assert sorted(completed) == task_ids
            assert client.count_tasks(queue="stress", status="succeeded") == task_count
            page = client.list_tasks(
                queue="stress",
                status="succeeded",
                limit=1000,
            )
            assert sorted(task.id for task in page.items) == task_ids


def test_same_host_owner_exclusion_and_managed_auto_start_guard(
    shared_storage_case: Path,
) -> None:
    database = shared_storage_case / "ownership.db"
    with _running_http_server(shared_storage_case, database) as server:
        second_port = _free_port()
        second = subprocess.run(
            _server_command(database, second_port, filesystem="shared"),
            cwd=shared_storage_case,
            env=_environment(),
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert second.returncode == 1
        assert "already owns database" in second.stderr.lower()
        with Client(url=server.url, token=TOKEN) as client:
            assert [queue.name for queue in client.list_queues()] == ["default"]

    managed_root = shared_storage_case / "managed-auto-root"
    with (
        Client(labtasker_root=managed_root, auto_start_local_server=True) as client,
        pytest.raises(TransportError, match="known local storage"),
    ):
        client.list_queues()
    assert not managed_root.exists()


def test_shared_socket_daemon_is_idempotent_and_manageable(shared_storage_case: Path) -> None:
    root = shared_storage_case / "daemon-root"
    database = root / "server.db"
    command = (
        "serve",
        "--connection",
        "socket",
        "--daemon",
        "--labtasker-root",
        str(root),
        "--database",
        str(database),
        "--database-filesystem",
        "auto",
    )
    try:
        started = _run_server_cli(shared_storage_case, *command)
        assert started.returncode == 0, started.stderr
        status = _run_server_cli(
            shared_storage_case,
            "status",
            "--labtasker-root",
            str(root),
        )
        assert status.returncode == 0, status.stderr
        payload = json.loads(status.stdout)
        assert payload["state"] == "running"
        assert payload["database_filesystem"] == "shared"
        assert payload["connection"] == "socket"

        socket_path = local_paths(root).socket
        with Client(socket=socket_path) as client:
            task = client.submit_task(
                {"transport": "socket"},
                task_id="t_NFSSOCK00001",
            )
            assert client.get_task(task.id) == task

        repeated = _run_server_cli(shared_storage_case, *command)
        assert repeated.returncode == 0, repeated.stderr
        repeated_status = _run_server_cli(
            shared_storage_case,
            "status",
            "--labtasker-root",
            str(root),
        )
        assert json.loads(repeated_status.stdout)["pid"] == payload["pid"]
    finally:
        stopped = _run_server_cli(
            shared_storage_case,
            "stop",
            "--labtasker-root",
            str(root),
            "--force",
        )
        assert stopped.returncode == 0, stopped.stderr
