from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

import labtasker
from labtasker.cli import app
from labtasker.command_worker import run_command_worker


def test_grouped_counts_cross_http_python_and_cli(
    server_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LABTASKER_URL", server_url)
    monkeypatch.setenv("LABTASKER_TOKEN", "secret")
    with labtasker.Client(url=server_url, token="secret") as client:
        monkeypatch.setattr("labtasker.api._default_client", client)
        client.submit_task(routes=["a", "b"])
        client.submit_task(routes=["a"])
        page = labtasker.count_tasks(group_by=["routes", "status"])
        assert page.count == 2
        assert [item.count for item in page.items] == [2, 1]
        with httpx.Client(base_url=server_url, headers={"Authorization": "Bearer secret"}) as raw:
            path = "/api/v2/queues/default/workers/w_ABCDEFGHIJKL"
            response = raw.put(path, json={"route": "a", "status": "idle", "task_id": None})
            assert response.status_code == 204
            assert raw.get("/api/v2/queues/default/workers").status_code == 200
        assert labtasker.list_workers().items[0].id == "w_ABCDEFGHIJKL"
        assert labtasker.count_workers() == 1
        assert labtasker.count_workers(group_by=["status", "route"]).items[0].key == {
            "status": "idle",
            "route": "a",
        }
        runner = CliRunner()
        for resource, fields, expected in [
            ("task", "routes,status", page.model_dump(mode="json")),
            (
                "worker",
                "route,status",
                client.count_workers(group_by=["route", "status"]).model_dump(mode="json"),
            ),
        ]:
            result = runner.invoke(app, [resource, "count", "--group-by", fields])
            assert result.exit_code == 0, result.output
            assert json.loads(result.stdout) == expected
        result = runner.invoke(app, ["worker", "list", "--filter", 'status == "idle"'])
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["items"][0]["task_id"] is None


@pytest.mark.parametrize("kind", ["python", "command"])
def test_real_worker_stays_busy_after_finish_and_withdraws(
    server_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kind: str
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LABTASKER_URL", server_url)
    monkeypatch.setenv("LABTASKER_TOKEN", "secret")
    with labtasker.Client(url=server_url, token="secret") as client:
        task = client.submit_task(routes=["a"])
        if kind == "python":
            cleanup_verified = []

            @labtasker.loop(route="a", idle_timeout=0)
            def execute() -> None:
                labtasker.finish({"done": True})
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    observations = client.list_workers().items
                    if observations and observations[0].status == "busy":
                        assert observations[0].task_id == task.id
                        assert client.get_task(task.id).status == "succeeded"
                        cleanup_verified.append(True)
                        return
                    time.sleep(0.01)
                pytest.fail("busy observation missing during post-finish cleanup")

            execute()
            assert cleanup_verified == [True]
        else:
            script = """
import time
import labtasker
labtasker.finish({"done": True})
with labtasker.Client() as client:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        observations = client.list_workers().items
        if observations and observations[0].status == "busy":
            assert observations[0].task_id == labtasker.task_info().id
            assert client.get_task(labtasker.task_info().id).status == "succeeded"
            break
        time.sleep(0.01)
    else:
        raise AssertionError("busy observation missing during cleanup")
"""
            # Child exit after finish cannot change the Task; additionally record
            # successful cleanup so an assertion failure cannot hide behind finish.
            marker = tmp_path / "cleanup-ok"
            script += f"\nfrom pathlib import Path\nPath({str(marker)!r}).touch()\n"
            run_command_worker([sys.executable, "-c", script], route="a", idle_timeout=0)
            assert marker.exists()
        assert client.get_task(task.id).result == {"done": True}
        assert client.count_workers() == 0
