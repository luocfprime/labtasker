from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from labtasker import APIError, Client, TaskArg, TaskError, finish, loop, task_info
from labtasker.command_worker import run_command_worker


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


@pytest.mark.skipif(os.name != "posix", reason="Command Workers require POSIX process groups")
def test_real_python_and_command_workers(
    server_url: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LABTASKER_URL", server_url)
    monkeypatch.setenv("LABTASKER_TOKEN", "secret")
    with Client(url=server_url, token="secret") as client:
        client.submit_task(
            {"value": 4},
            name="python worker",
            routes=["python"],
            task_id="t_PYTHONWORKER",
        )
        client.submit_task(
            {"value": "hello world"},
            name="command worker",
            routes=["command"],
            task_id="t_COMMANDWORKR",
        )
        client.submit_task(
            {},
            name="command failure",
            routes=["failure"],
            max_attempts=2,
            task_id="t_COMMANDFAILX",
        )

    attempts: list[int] = []

    @loop(route="python", idle_timeout=0)
    def python_worker(value: int = TaskArg()) -> None:
        attempts.append(task_info().attempt)
        if task_info().attempt == 1:
            raise TaskError("retry once")
        finish({"doubled": value * 2})

    python_worker()
    assert attempts == [1, 2]

    command_script = (
        "import labtasker,sys; "
        "assert labtasker.task_info().run_dir.is_absolute(); "
        "labtasker.finish({'echo':sys.argv[1]})"
    )
    run_command_worker(
        [sys.executable, "-c", command_script, "%{value}"],
        route="command",
        idle_timeout=0,
    )
    run_command_worker(
        [sys.executable, "-c", "raise SystemExit(7)"],
        route="failure",
        idle_timeout=0,
    )

    with Client(url=server_url, token="secret") as client:
        python_task = client.get_task("t_PYTHONWORKER")
        command_task = client.get_task("t_COMMANDWORKR")
        failed_task = client.get_task("t_COMMANDFAILX")
    assert python_task.status == "succeeded"
    assert python_task.attempt == 2
    assert python_task.result == {"doubled": 8}
    assert python_task.last_error is not None
    assert python_task.last_error.type == "TaskError"
    assert command_task.status == "succeeded"
    assert command_task.result == {"echo": "hello world"}
    assert failed_task.status == "failed"
    assert failed_task.attempt == 2
    assert failed_task.last_error is not None
    assert failed_task.last_error.type == "CommandProcessError"

    command_runs = list(
        (tmp_path / ".labtasker/runs/default/command-worker__t_COMMANDWORKR").glob("*")
    )
    assert len(command_runs) == 1
    assert (command_runs[0] / "result.json").read_text().strip() == '{\n  "echo": "hello world"\n}'
