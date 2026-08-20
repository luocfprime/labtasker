from __future__ import annotations

import io
import json
import os
import sys
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import labtasker.execution as execution_module
from labtasker.command_template import TemplateSyntaxError
from labtasker.command_worker import _run_pty, run_command_worker
from labtasker.errors import APIError
from labtasker.execution import RunControl, finish, task_info
from labtasker.models import ClaimResponse, Queue, Task


def make_claim(
    *,
    args: dict[str, Any] | None = None,
    task_id: str = "t_ABCDEFGHIJKL",
    run_id: str = "r_ABCDEFGHIJKL",
) -> ClaimResponse:
    task = Task.model_validate(
        {
            "id": task_id,
            "queue": "default",
            "status": "running",
            "name": "command-test",
            "args": {} if args is None else args,
            "metadata": {},
            "priority": 0,
            "attempt": 1,
            "max_attempts": 3,
            "routes": ["default"],
            "result": {},
            "last_error": None,
            "last_route": "default",
            "created_at": datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
            "updated_at": datetime(2026, 8, 20, 12, 1, tzinfo=UTC),
            "started_at": datetime(2026, 8, 20, 12, 1, tzinfo=UTC),
            "finished_at": None,
        },
        strict=True,
    )
    return ClaimResponse(
        task=task,
        run_id=run_id,
        lease_expires_at=datetime(2026, 8, 20, 12, 6, tzinfo=UTC),
    )


class FakeClient:
    def __init__(
        self,
        claims: list[ClaimResponse | None],
        *,
        token: str | None = None,
        heartbeat_error: APIError | None = None,
    ) -> None:
        self.configuration = SimpleNamespace(url="http://server", queue="default", token=token)
        self.claims = deque(claims)
        self.heartbeat_error = heartbeat_error
        self.actions: list[tuple[str, str, object]] = []

    def __enter__(self) -> FakeClient:
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def list_queues(self) -> list[Queue]:
        return [Queue(name="default")]

    def _health(self) -> object:
        return SimpleNamespace(status="ok", api_version="2", database="ok")

    def _claim(self, **_: object) -> ClaimResponse | None:
        return self.claims.popleft() if self.claims else None

    def _heartbeat(self, **_: object) -> object:
        if self.heartbeat_error is not None:
            raise self.heartbeat_error
        return SimpleNamespace(lease_expires_at=datetime.now(UTC))

    def _complete(self, *, task_id: str, result: object, **_: object) -> None:
        self.actions.append(("complete", task_id, result))

    def _fail(
        self,
        *,
        task_id: str,
        error_type: str,
        message: str,
        traceback: str | None,
        **_: object,
    ) -> None:
        self.actions.append(
            ("fail", task_id, {"type": error_type, "message": message, "traceback": traceback})
        )

    def _unclaim(self, *, task_id: str, **_: object) -> None:
        self.actions.append(("unclaim", task_id, None))


@pytest.fixture(autouse=True)
def reset_context() -> None:
    execution_module._ACTIVE_CONTEXT = None
    execution_module._ENV_CONTEXT = None


def install(monkeypatch: pytest.MonkeyPatch, client: FakeClient) -> None:
    monkeypatch.setattr("labtasker.command_worker.Client", lambda **_: client)


def test_command_template_is_validated_before_client_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed = False

    def fail_client(**_: object) -> None:
        nonlocal constructed
        constructed = True

    monkeypatch.setattr("labtasker.command_worker.Client", fail_client)
    with pytest.raises(TemplateSyntaxError, match="unterminated"):
        run_command_worker(["%{bad"], idle_timeout=0)
    assert not constructed


def test_pipe_worker_preserves_argv_environment_streams_and_null_stdin(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeClient([make_claim(args={"text": "hello world", "obj": {"b": 2, "a": 1}}), None])
    install(monkeypatch, client)
    monkeypatch.setenv("LABTASKER_TOKEN", "must-not-leak")
    script = (
        "import json,os,sys; "
        "print(json.dumps({'args':sys.argv[1:],'token':os.getenv('LABTASKER_TOKEN'),"
        "'task':os.environ['LABTASKER_TASK_ID'],'stdin':sys.stdin.read()})); "
        "print('stderr-line', file=sys.stderr)"
    )
    run_command_worker(
        [sys.executable, "-c", script, "%{text}", "%{obj}"],
        idle_timeout=0,
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out.strip())
    assert payload == {
        "args": ["hello world", '{"a":1,"b":2}'],
        "token": None,
        "task": "t_ABCDEFGHIJKL",
        "stdin": "",
    }
    assert captured.err.strip() == "stderr-line"
    assert client.actions == [("complete", "t_ABCDEFGHIJKL", {})]
    log = next(tmp_path.glob(".labtasker/runs/default/**/run.log")).read_bytes()
    assert b"hello world" in log
    assert b"stderr-line" in log


@pytest.mark.skipif(os.name != "posix", reason="PTY execution is POSIX-specific")
def test_pty_worker_gives_child_one_terminal_and_captures_combined_raw_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import pty

    outer_master, outer_slave = pty.openpty()
    stdin = os.fdopen(os.dup(outer_slave), "r", encoding="utf-8", closefd=True)
    stdout_bytes = io.BytesIO()
    stdout = io.TextIOWrapper(stdout_bytes, encoding="utf-8", write_through=True)
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)
    log_path = tmp_path / "pty.log"
    control = RunControl(force_stop_timeout=None, force_stop=lambda: None)
    script = (
        "import os,sys; "
        "print(f'tty={os.isatty(0)},{os.isatty(1)},{os.isatty(2)}'); "
        "print('stderr-line', file=sys.stderr)"
    )
    try:
        process = _run_pty(
            [sys.executable, "-c", script],
            dict(os.environ),
            log_path,
            control,
            None,
        )
    finally:
        control.executor_done()
        stdin.close()
        os.close(outer_master)
        os.close(outer_slave)
    assert process.returncode == 0
    assert b"tty=True,True,True" in log_path.read_bytes()
    assert b"stderr-line" in log_path.read_bytes()
    assert b"tty=True,True,True" in stdout_bytes.getvalue()


def test_nonzero_and_binding_or_spawn_failure_are_task_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient([make_claim(), None])
    install(monkeypatch, client)
    # Different failures are exercised through separate static command definitions.
    run_command_worker([sys.executable, "-c", "raise SystemExit(7)"], idle_timeout=0)
    assert client.actions[0][0] == "fail"
    assert client.actions[0][2] == {
        "type": "CommandProcessError",
        "message": "Command exited with status 7.",
        "traceback": None,
    }

    binding_client = FakeClient(
        [
            make_claim(
                task_id="t_MNOPQRSTUVWX",
                run_id="r_MNOPQRSTUVWX",
                args={},
            ),
            None,
        ]
    )
    install(monkeypatch, binding_client)
    run_command_worker([sys.executable, "%{missing}"], idle_timeout=0)
    assert binding_client.actions[0][2]["type"] == "TaskBindingError"  # type: ignore[index]

    spawn_client = FakeClient([make_claim(task_id="t_ZYXWVUTSRQPO", run_id="r_ZYXWVUTSRQPO"), None])
    install(monkeypatch, spawn_client)
    run_command_worker(["/definitely/missing/labtasker-command"], idle_timeout=0)
    assert spawn_client.actions[0][2]["type"] == "FileNotFoundError"  # type: ignore[index]


def test_parent_takes_over_persisted_finish_payload_after_child_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient([make_claim(), None])
    install(monkeypatch, client)
    script = """
import json, os
from pathlib import Path
run_dir = Path(os.environ["LABTASKER_RUN_DIR"])
(run_dir / "result.json").write_text(json.dumps({"score": 0.75}))
record = json.loads((run_dir / "run.json").read_text())
record["phase"] = "reporting"
record["terminal_action"] = "complete"
(run_dir / "run.json").write_text(json.dumps(record))
raise SystemExit(9)
"""
    run_command_worker([sys.executable, "-c", script], idle_timeout=0)
    assert client.actions == [("complete", "t_ABCDEFGHIJKL", {"score": 0.75})]


@pytest.mark.skipif(os.name != "posix", reason="process-group behavior is POSIX-specific")
def test_confirmed_revocation_terminates_command_group_and_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient(
        [make_claim(), None],
        heartbeat_error=APIError(409, "stale_run", "stale", {}),
    )
    install(monkeypatch, client)
    monkeypatch.setattr("labtasker.worker.HEARTBEAT_INTERVAL_SECONDS", 0.01)
    started = time.monotonic()
    run_command_worker(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        idle_timeout=0,
        force_stop_timeout=0.2,
    )
    assert time.monotonic() - started < 3
    assert client.actions == []


def test_environment_context_loads_task_info_and_finish_without_import_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    claim = make_claim()
    from labtasker.journal import LocalRunJournal

    journal = LocalRunJournal.create(
        claim=claim,
        server_url="http://server",
        queue="default",
        route="default",
        cwd=tmp_path,
    )
    environment = {
        "LABTASKER_URL": "http://server",
        "LABTASKER_QUEUE": "default",
        "LABTASKER_TASK_ID": claim.task.id,
        "LABTASKER_RUN_ID": claim.run_id,
        "LABTASKER_ROUTE": "default",
        "LABTASKER_RUN_DIR": str(journal.run_dir),
    }
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    reported: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "labtasker.worker.report_complete_until_resolved",
        lambda _client, **kwargs: not reported.append(kwargs["result"]),
    )
    assert task_info().run_dir == journal.run_dir
    finish({"metric": 3})
    assert reported == [{"metric": 3}]
    assert json.loads(journal.result_path.read_text()) == {"metric": 3}
    assert json.loads(journal.run_path.read_text())["phase"] == "acknowledged"


def test_ordinary_config_environment_is_not_mistaken_for_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LABTASKER_URL", "http://server")
    monkeypatch.setenv("LABTASKER_QUEUE", "default")
    with pytest.raises(RuntimeError, match="No active"):
        task_info()
