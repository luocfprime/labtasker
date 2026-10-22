from __future__ import annotations

import json

import httpx
import pytest
from test_cli import FakeClient, runner
from test_client import mock_client, task_payload
from typer.testing import CliRunner

import labtasker.api as api
from labtasker.cli import app
from labtasker.models import BulkUpdateResult, Task, TaskInfo, TaskPage
from labtasker.validation import RequestValidationError


def test_archive_selectors_and_false_wire_omission() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "PATCH":
            return httpx.Response(200, json={"matched": 0, "updated": 0})
        if request.url.path.endswith("/count"):
            return httpx.Response(200, json={"count": 0})
        return httpx.Response(200, json={"items": [], "next_cursor": None})

    with mock_client(handler) as client:
        for included in [False, True]:
            client.list_tasks(include_archived=included)
            client.count_tasks(include_archived=included)
            client.update_tasks(
                filter="archived == True", changes={"archived": False}, include_archived=included
            )
    for request in requests[:3]:
        assert "include_archived" not in request.url.params
        if request.content:
            assert "include_archived" not in json.loads(request.content)
    assert all(r.url.params["include_archived"] == "true" for r in requests[3:5])
    assert json.loads(requests[5].content) == {
        "filter": "archived == True",
        "changes": {"archived": False},
        "include_archived": True,
    }
    assert Task.model_validate_json(json.dumps(task_payload())).archived is False
    assert "archived" in TaskInfo.model_fields


@pytest.mark.parametrize("value", [None, 0, 1, "true", [], {}])
def test_archive_client_rejects_wrong_types_before_network(value: object) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("invalid archive input reached the Server")

    with mock_client(handler) as client:
        for operation in [client.list_tasks, client.count_tasks]:
            with pytest.raises(RequestValidationError):
                operation(include_archived=value)
        with pytest.raises(RequestValidationError):
            client.update_tasks(
                filter="priority == 0", changes={"priority": 1}, include_archived=value
            )
        with pytest.raises(RequestValidationError):
            client.update_task("t_ABCDEFGHIJKL", {"archived": value})


def test_archive_function_api_forwards_all_count_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    class Recording:
        def list_tasks(self, **kwargs):
            calls.append(kwargs)

        def count_tasks(self, **kwargs):
            calls.append(kwargs)

        def update_tasks(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(api, "_default_client", Recording())
    api.list_tasks(include_archived=True)
    api.count_tasks(include_archived=True)
    api.count_tasks(include_archived=True, group_by=["routes", "status"])
    api.update_tasks(filter="archived == True", changes={"archived": False}, include_archived=True)
    assert len(calls) == 4 and all(call["include_archived"] is True for call in calls)


@pytest.mark.parametrize("command", ["list", "count", "update"])
def test_archive_cli_filter_scope(command: str, monkeypatch: pytest.MonkeyPatch) -> None:
    class ArchiveClient(FakeClient):
        def list_tasks(self, **kwargs):
            assert kwargs["include_archived"] is True
            return TaskPage(items=[], next_cursor=None)

        def count_tasks(self, **kwargs):
            assert kwargs["include_archived"] is True
            return 0

        def update_tasks(self, **kwargs):
            assert kwargs["include_archived"] is True
            assert kwargs["changes"] == {"archived": False}
            return BulkUpdateResult(matched=0, updated=0)

    monkeypatch.setattr("labtasker.cli.Client", ArchiveClient)
    args = ["task", command, "--include-archived"]
    if command == "update":
        args += ["--filter", "archived == True", "--changes", '{"archived":false}']
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    help_text = runner.invoke(app, ["task", command, "--help"]).stdout
    assert "--include-archived" in help_text and "--no-include-archived" not in help_text


def test_archive_cli_rejects_scope_for_id_update() -> None:
    result = CliRunner().invoke(
        app,
        [
            "task",
            "update",
            "t_ABCDEFGHIJKL",
            "--include-archived",
            "--changes",
            '{"archived":false}',
        ],
    )
    assert result.exit_code == 2 and "requires --filter" in result.stderr
