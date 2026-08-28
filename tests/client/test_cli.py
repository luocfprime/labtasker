from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from labtasker.cli import app
from labtasker.errors import APIError
from labtasker.models import Queue, Task

runner = CliRunner()


def task() -> Task:
    return Task.model_validate_json(
        json.dumps(
            {
                "id": "t_ABCDEFGHIJKL",
                "queue": "default",
                "status": "pending",
                "name": None,
                "args": {"seed": 1},
                "metadata": {},
                "priority": 0,
                "attempt": 0,
                "max_attempts": 3,
                "routes": ["default"],
                "result": {},
                "last_error": None,
                "last_route": None,
                "created_at": "2026-08-20T12:00:00Z",
                "updated_at": "2026-08-20T12:00:00Z",
                "started_at": None,
                "finished_at": None,
            }
        ),
        strict=True,
    )


class FakeClient:
    last_submit: dict[str, Any] | None = None

    def __enter__(self) -> FakeClient:
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def submit_task(self, args: dict[str, object], **kwargs: object) -> Task:
        FakeClient.last_submit = {"args": args, **kwargs}
        return task()

    def get_task(self, task_id: str, *, queue: str | None = None) -> Task:
        return task()

    def create_queue(self, name: str) -> Queue:
        return Queue(name=name)

    def list_queues(self) -> list[Queue]:
        return [Queue(name="default")]

    def delete_task(self, task_id: str, *, queue: str | None = None) -> None:
        pass

    def delete_queue(self, name: str, *, cascade: bool = False) -> None:
        pass


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeClient.last_submit = None
    monkeypatch.setattr("labtasker.cli.Client", FakeClient)


def test_config_show_is_read_only_formatted_json(tmp_path: Path) -> None:
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0
    assert result.stderr == ""
    parsed = json.loads(result.stdout)
    assert parsed == {
        "mode": "local",
        "directory": str(tmp_path),
        "database": str(tmp_path / ".labtasker/server.db"),
        "socket": parsed["socket"],
        "url": None,
        "queue": "default",
        "token_configured": False,
    }
    assert parsed["socket"].startswith(f"/tmp/labtasker-{os.geteuid()}/")
    assert not (tmp_path / ".labtasker").exists()


def test_config_show_rejects_unrepresentable_bearer_token_without_traceback() -> None:
    result = runner.invoke(
        app,
        ["config", "show"],
        env={"LABTASKER_URL": "http://server.test", "LABTASKER_TOKEN": "秘密"},
    )
    assert result.exit_code == 1
    error = json.loads(result.stdout)
    assert error["error"]["code"] == "invalid_config"
    assert error["error"]["details"] == {"source": "environment", "field": "token"}
    assert "Traceback" not in result.stderr
    assert result.stderr == ""


def test_submit_parses_one_strict_json_object_and_repeated_routes(fake_client: None) -> None:
    result = runner.invoke(
        app,
        [
            "task",
            "submit",
            "--args",
            '{"text":"30","steps":30,"enabled":true}',
            "--metadata",
            '{"group":"a"}',
            "--route",
            "old",
            "--route",
            "new",
            "--queue",
            "experiments",
        ],
    )
    assert result.exit_code == 0
    assert json.loads(result.stdout)["id"] == "t_ABCDEFGHIJKL"
    assert FakeClient.last_submit == {
        "args": {"text": "30", "steps": 30, "enabled": True},
        "name": None,
        "metadata": {"group": "a"},
        "priority": 0,
        "max_attempts": 3,
        "routes": ["old", "new"],
        "task_id": None,
        "queue": "experiments",
    }


@pytest.mark.parametrize(
    "value",
    [
        "[]",
        '{"x":NaN}',
        '{"x":1,"x":2}',
        '{"x":9223372036854775808}',
    ],
)
def test_invalid_json_is_a_usage_error_without_network(fake_client: None, value: str) -> None:
    result = runner.invoke(app, ["task", "submit", "--args", value])
    assert result.exit_code == 2
    assert result.stdout == ""
    assert FakeClient.last_submit is None
    assert "--args must be one strict JSON object" in result.stderr


@pytest.mark.parametrize(
    "argv",
    [
        ["task", "submit"],
        ["task", "get", "t_ABCDEFGHIJKL"],
        ["task", "list"],
        ["task", "count"],
        ["task", "update", "t_ABCDEFGHIJKL", "--changes", '{"priority":1}'],
        [
            "task",
            "update",
            "--filter",
            'status == "pending"',
            "--changes",
            '{"priority":1}',
        ],
        ["task", "cancel", "t_ABCDEFGHIJKL"],
        ["task", "requeue", "t_ABCDEFGHIJKL"],
        ["task", "delete", "t_ABCDEFGHIJKL"],
        ["queue", "create", "demo"],
        ["queue", "list"],
        ["queue", "delete", "demo", "--cascade"],
    ],
    ids=[
        "task-submit",
        "task-get",
        "task-list",
        "task-count",
        "task-update-one",
        "task-update-filter",
        "task-cancel",
        "task-requeue",
        "task-delete",
        "queue-create",
        "queue-list",
        "queue-delete",
    ],
)
def test_every_finite_client_command_writes_handled_error_json_to_stdout(
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
) -> None:
    def fail(_operation: object) -> None:
        raise APIError(409, "operation_conflict", "Cannot perform operation.", {})

    monkeypatch.setattr("labtasker.cli._with_client", fail)
    result = runner.invoke(app, argv)
    assert result.exit_code == 1
    assert json.loads(result.stdout) == {
        "error": {
            "code": "operation_conflict",
            "message": "Cannot perform operation.",
            "details": {},
        }
    }
    assert result.stderr == ""


def test_delete_success_writes_no_stdout(fake_client: None) -> None:
    task_result = runner.invoke(app, ["task", "delete", "t_ABCDEFGHIJKL"])
    queue_result = runner.invoke(app, ["queue", "delete", "default", "--cascade"])
    assert task_result.exit_code == queue_result.exit_code == 0
    assert task_result.stdout == queue_result.stdout == ""


def test_update_requires_exactly_one_selection_form(fake_client: None) -> None:
    neither = runner.invoke(app, ["task", "update", "--changes", '{"priority":1}'])
    both = runner.invoke(
        app,
        [
            "task",
            "update",
            "t_ABCDEFGHIJKL",
            "--filter",
            'status == "pending"',
            "--changes",
            '{"priority":1}',
        ],
    )
    assert neither.exit_code == both.exit_code == 2
    assert "provide exactly one" in neither.stderr
    assert "provide exactly one" in both.stderr


def test_loop_requires_separator_command_and_preserves_every_argv_element(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def run(argv: list[str], **kwargs: object) -> None:
        calls.append((argv, kwargs))

    monkeypatch.setattr("labtasker.cli.run_command_worker", run)
    result = runner.invoke(
        app,
        [
            "loop",
            "--route",
            "gpu",
            "--idle-timeout",
            "0",
            "--force-stop-timeout",
            "2.5",
            "--",
            "python",
            "train.py",
            "--flag",
            "%{value}",
            "hello world",
        ],
    )
    assert result.exit_code == 0
    assert calls == [
        (
            ["python", "train.py", "--flag", "%{value}", "hello world"],
            {
                "route": "gpu",
                "queue": None,
                "idle_timeout": 0.0,
                "force_stop_timeout": 2.5,
            },
        )
    ]

    for missing_separator in (["loop"], ["loop", "python", "train.py"]):
        missing = runner.invoke(app, missing_separator)
        assert missing.exit_code == 2
        assert "COMMAND is required after --" in missing.stderr

    help_result = runner.invoke(app, ["loop", "--help"])
    assert help_result.exit_code == 0
    assert "Usage: root loop [OPTIONS] -- COMMAND [ARG...]" in help_result.stdout


def test_loop_static_template_error_is_usage_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def invalid(*_: object, **__: object) -> None:
        from labtasker.command_template import compile_argv

        compile_argv(["%{broken"])

    monkeypatch.setattr("labtasker.cli.run_command_worker", invalid)
    result = runner.invoke(app, ["loop", "--", "echo", "%{broken"])
    assert result.exit_code == 2
    assert "unterminated placeholder" in result.stderr


def test_loop_platform_error_is_a_clean_worker_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unsupported(*_: object, **__: object) -> None:
        raise NotImplementedError(
            "Command Workers require POSIX process-group support; "
            "platform 'win32' is not supported."
        )

    monkeypatch.setattr("labtasker.cli.run_command_worker", unsupported)
    result = runner.invoke(app, ["loop", "--", "python", "worker.py"])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == (
        "Command Workers require POSIX process-group support; platform 'win32' is not supported.\n"
    )
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (
            ["--help"],
            [
                "Submit, inspect, and execute Labtasker v2 Tasks.",
                "Submit, inspect, update, and control Tasks.",
                "Create, list, and delete Queue namespaces.",
            ],
        ),
        (
            ["task", "submit", "--help"],
            [
                "JSON types are preserved exactly",
                "--args <str>",
                "Task arguments as one strict JSON object.",
                "repeat for multiple routes",
                "labtasker task submit --name baseline",
            ],
        ),
        (
            ["task", "list", "--help"],
            [
                "List one page of Tasks",
                "combined with logical AND",
                "Opaque next_cursor from the same query",
                "metadata.group",
            ],
        ),
        (
            ["task", "update", "--help"],
            [
                "Provide exactly one of TASK_ID and --filter",
                "replaces every supplied field in full",
                "Running Tasks cannot be updated",
                "one atomic Server operation",
                'status == "pending"',
            ],
        ),
        (
            ["loop", "--help"],
            [
                "Usage: root loop [OPTIONS] -- COMMAND [ARG...]",
                "never invokes a shell",
                "%{object.field}",
                "Seconds without an eligible Task before normal exit",
                "wait forever if omitted",
            ],
        ),
        (
            ["config", "show", "--help"],
            [
                "effective URL, Queue, and non-secret token presence",
                ".labtasker/config.toml",
                "token value is never printed",
            ],
        ),
    ],
)
def test_help_explains_semantics_constraints_and_examples(
    arguments: list[str],
    expected: list[str],
) -> None:
    result = runner.invoke(app, arguments)
    assert result.exit_code == 0
    assert result.stderr == ""
    normalized_output = " ".join(result.stdout.split())
    for snippet in expected:
        assert " ".join(snippet.split()) in normalized_output


@pytest.mark.parametrize(
    "command",
    [
        ["task", "get"],
        ["task", "count"],
        ["task", "cancel"],
        ["task", "requeue"],
        ["task", "delete"],
        ["queue", "create"],
        ["queue", "list"],
        ["queue", "delete"],
    ],
)
def test_every_leaf_help_has_a_specific_description(command: list[str]) -> None:
    result = runner.invoke(app, [*command, "--help"])
    assert result.exit_code == 0
    assert result.stderr == ""
    description = next(
        line.strip()
        for line in result.stdout.splitlines()
        if line.startswith("  ") and "--help" not in line
    )
    assert description.endswith(".")
