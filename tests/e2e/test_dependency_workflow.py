from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from labtasker import Client, finish, loop, task_info
from labtasker.cli import app


def test_dependency_cli_python_worker_and_user_result_lookup(
    server_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LABTASKER_URL", server_url)
    monkeypatch.setenv("LABTASKER_TOKEN", "secret")
    predecessor = "t_ABCDEFGHIJKL"
    result = CliRunner().invoke(
        app,
        [
            "task",
            "submit",
            "--route",
            "aggregate",
            "--dependency",
            predecessor,
            "--dependency",
            predecessor,
        ],
    )
    assert result.exit_code == 0, result.output
    downstream = json.loads(result.stdout)
    assert downstream["dependencies"] == [predecessor, predecessor]
    with Client(url=server_url, token="secret") as client:
        client.submit_task(task_id=predecessor, routes=["prepare"])

    @loop(route="aggregate", idle_timeout=0)
    def aggregate() -> None:
        info = task_info()
        assert info.dependencies == [predecessor, predecessor]
        with Client(url=server_url, token="secret") as client:
            finish(
                {"total": sum(client.get_task(dep).result["value"] for dep in info.dependencies)}
            )

    @loop(route="prepare", idle_timeout=0)
    def prepare() -> None:
        finish({"value": 7})

    aggregate()  # User chooses to start this Worker again when prerequisites succeed.
    with Client(url=server_url, token="secret") as client:
        assert client.get_task(downstream["id"]).attempt == 0
    prepare()
    aggregate()
    with Client(url=server_url, token="secret") as client:
        task = client.get_task(downstream["id"])
        assert task.status == "succeeded"
        assert task.result == {"total": 14}
    result = CliRunner().invoke(
        app,
        [
            "task",
            "update",
            downstream["id"],
            "--changes",
            '{"dependencies":[]}',
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["dependencies"] == []
