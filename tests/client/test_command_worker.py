from __future__ import annotations

import errno
import io
import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import labtasker.execution as execution_module
from labtasker.command_template import TemplateSyntaxError
from labtasker.command_worker import (
    _CommandLog,
    _run_pipes,
    _run_pty,
    _start_drain,
    run_command_worker,
)
from labtasker.config import ResolvedConfig
from labtasker.errors import APIError, TransportError
from labtasker.execution import (
    RunControl,
    finish,
    report_progress,
    report_worker_telemetry,
    task_info,
)
from labtasker.models import ClaimResponse, Queue, Task

UTC = timezone.utc


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
        claims: list[ClaimResponse | Exception | None],
        *,
        token: str | None = None,
        heartbeat_error: APIError | None = None,
    ) -> None:
        self._configuration = ResolvedConfig(
            url="http://server",
            socket=None,
            managed_local=False,
            labtasker_root=Path.cwd() / ".labtasker",
            queue="default",
            token=token,
            auto_start_local_server=False,
            local=None,
        )
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
        outcome = self.claims.popleft() if self.claims else None
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def _repair_local_connection(self, _: TransportError) -> None:
        pass

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


def test_command_worker_metadata_is_validated_before_client_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "labtasker.command_worker.Client", lambda **_: pytest.fail("Client constructed")
    )
    with pytest.raises(ValueError, match="signed 64-bit"):
        run_command_worker(["echo"], metadata={"invalid": 2**63})


def test_command_worker_rejects_non_posix_before_client_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed = False

    def fail_client(**_: object) -> None:
        nonlocal constructed
        constructed = True

    monkeypatch.setattr("labtasker.command_worker.Client", fail_client)
    monkeypatch.setattr("labtasker.command_worker._POSIX_PROCESS_GROUPS", False)
    monkeypatch.setattr("labtasker.command_worker._PLATFORM", "win32")
    with pytest.raises(NotImplementedError, match="platform 'win32' is not supported"):
        run_command_worker(["python", "worker.py"], idle_timeout=0)
    assert not constructed


@pytest.mark.skipif(os.name != "posix", reason="Command Workers require POSIX process groups")
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


@pytest.mark.skipif(os.name != "posix", reason="Command Workers require POSIX process groups")
def test_command_worker_confirms_recovered_claim_before_child_start(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    marker = tmp_path / "child-started"
    client = FakeClient([TransportError("response lost"), make_claim(), None])
    install(monkeypatch, client)
    monkeypatch.setattr("labtasker.worker._claim_backoff_delay", lambda _: 0.0)
    confirmations = 0

    def heartbeat(**_: object) -> object:
        nonlocal confirmations
        assert not marker.exists()
        confirmations += 1
        return SimpleNamespace(lease_expires_at=datetime.now(UTC))

    monkeypatch.setattr(client, "_heartbeat", heartbeat)
    run_command_worker(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; Path(__import__('sys').argv[1]).touch()",
            str(marker),
        ],
        idle_timeout=0,
    )

    assert confirmations == 1
    assert marker.exists()


@pytest.mark.skipif(os.name != "posix", reason="Command Workers require POSIX process groups")
def test_command_worker_does_not_prepare_or_start_unconfirmed_claim(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    marker = tmp_path / "child-started"
    client = FakeClient([TransportError("response lost"), make_claim()])
    install(monkeypatch, client)
    monkeypatch.setattr("labtasker.worker._claim_backoff_delay", lambda _: 0.0)

    def reject_confirmation(**_: object) -> None:
        raise APIError(401, "unauthorized", "bad token", {})

    monkeypatch.setattr(client, "_heartbeat", reject_confirmation)
    monkeypatch.setattr(
        "labtasker.command_worker.LocalRunJournal.create",
        lambda **_: pytest.fail("journal must not be created before claim confirmation"),
    )

    with pytest.raises(APIError, match="bad token"):
        run_command_worker(
            [
                sys.executable,
                "-c",
                "from pathlib import Path; Path(__import__('sys').argv[1]).touch()",
                str(marker),
            ],
            idle_timeout=0,
        )

    assert not marker.exists()
    assert client.actions == []


@pytest.mark.skipif(os.name != "posix", reason="Command Workers require POSIX process groups")
def test_pipe_worker_preserves_invalid_utf8_in_log_and_relays_safely(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class TextOnlyDestination:
        def __init__(self) -> None:
            self.parts: list[str] = []

        def write(self, value: str) -> None:
            self.parts.append(value)

        def flush(self) -> None:
            pass

        def isatty(self) -> bool:
            return False

    client = FakeClient([make_claim(), None])
    install(monkeypatch, client)
    destination = TextOnlyDestination()
    monkeypatch.setattr(sys, "stdout", destination)
    script = "import sys; sys.stdout.buffer.write(b'valid\\n\\xff\\xfe\\n'); sys.stdout.flush()"

    run_command_worker([sys.executable, "-c", script], idle_timeout=0)

    assert "".join(destination.parts) == "valid\n\\xff\\xfe\n"
    assert client.actions == [("complete", "t_ABCDEFGHIJKL", {})]
    log = next(tmp_path.glob(".labtasker/runs/default/**/run.log")).read_bytes()
    assert log == b"valid\n\xff\xfe\n"


@pytest.mark.skipif(os.name != "posix", reason="pipe fd behavior is POSIX-specific")
def test_pipe_drain_relays_small_output_before_eof(tmp_path: Path) -> None:
    read_fd, write_fd = os.pipe()
    source = os.fdopen(read_fd, "rb")
    destination_buffer = io.BytesIO()
    destination = SimpleNamespace(buffer=destination_buffer)
    log_path = tmp_path / "run.log"
    try:
        with log_path.open("wb", buffering=0) as log:
            thread = _start_drain(source, destination, _CommandLog(log), "stdout")
            os.write(write_fd, b"ready\n")
            deadline = time.monotonic() + 1
            while destination_buffer.getvalue() != b"ready\n" and time.monotonic() < deadline:
                time.sleep(0.01)
            assert destination_buffer.getvalue() == b"ready\n"
            os.close(write_fd)
            write_fd = -1
            thread.join(timeout=1)
            assert not thread.is_alive()
    finally:
        source.close()
        if write_fd >= 0:
            os.close(write_fd)
    assert log_path.read_bytes() == b"ready\n"


@pytest.mark.skipif(os.name != "posix", reason="pipe fd behavior is POSIX-specific")
def test_pipe_drain_keeps_draining_after_destination_closes(tmp_path: Path) -> None:
    class ClosedDestination:
        def write(self, _: str) -> None:
            raise BrokenPipeError

        def flush(self) -> None:
            raise AssertionError("flush must not follow a failed write")

    payload_size = 2 * 1024 * 1024
    process = subprocess.Popen(
        [sys.executable, "-c", f"import sys; sys.stdout.buffer.write(b'x' * {payload_size})"],
        stdout=subprocess.PIPE,
    )
    assert process.stdout is not None
    log_path = tmp_path / "run.log"
    with log_path.open("wb", buffering=0) as log:
        thread = _start_drain(
            process.stdout,
            ClosedDestination(),
            _CommandLog(log),
            "stdout",
        )
        process.wait(timeout=3)
        thread.join(timeout=1)
    assert not thread.is_alive()
    assert process.returncode == 0
    assert log_path.stat().st_size == payload_size


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


@pytest.mark.skipif(os.name != "posix", reason="PTY execution is POSIX-specific")
@pytest.mark.parametrize("force_stop_timeout", [None, 0.1])
@pytest.mark.parametrize("relay_fails", [False, True])
def test_pty_cancellation_drains_cleanup_output_while_waiting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    force_stop_timeout: float | None,
    relay_fails: bool,
) -> None:
    import pty

    ready = tmp_path / "ready"
    log_path = tmp_path / "pty.log"
    outer_master, outer_slave = pty.openpty()
    stdin = os.fdopen(os.dup(outer_slave), "r", encoding="utf-8")
    stdout_bytes = io.BytesIO()
    stdout = io.TextIOWrapper(stdout_bytes, encoding="utf-8", write_through=True)
    if relay_fails:
        stdout.close()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)
    control = RunControl(force_stop_timeout=None, force_stop=lambda: None)
    finished = threading.Event()
    rescued = threading.Event()
    script = """
import os, signal, sys, time
from pathlib import Path
def cleanup(*_):
    for _ in range(256):
        os.write(1, b'x' * 1024)
    if sys.argv[2] == 'hang':
        time.sleep(30)
    sys.exit(0)
signal.signal(signal.SIGTERM, cleanup)
Path(sys.argv[1]).write_text(str(os.getpgrp()))
while True:
    time.sleep(.1)
"""

    def cancel_and_rescue() -> None:
        deadline = time.monotonic() + 5
        group_id: int | None = None
        while time.monotonic() < deadline:
            if ready.exists() and (text := ready.read_text()):
                group_id = int(text)
                control.revoke("cancel")
                break
            time.sleep(0.01)
        if not finished.wait(max(0, deadline - time.monotonic())):
            rescued.set()
            if group_id is not None:
                with suppress(ProcessLookupError):
                    os.killpg(group_id, signal.SIGKILL)

    rescuer = threading.Thread(target=cancel_and_rescue, daemon=True)
    rescuer.start()
    started = time.monotonic()
    try:
        process = _run_pty(
            [
                sys.executable,
                "-c",
                script,
                str(ready),
                "exit" if force_stop_timeout is None else "hang",
            ],
            dict(os.environ),
            log_path,
            control,
            force_stop_timeout,
        )
        assert not rescued.is_set(), "PTY cleanup blocked behind undrained output"
        if force_stop_timeout is None:
            assert process.returncode == 0
            assert log_path.read_bytes() == b"x" * (256 * 1024)
            if not relay_fails:
                assert stdout_bytes.getvalue() == log_path.read_bytes()
        else:
            assert process.returncode == -signal.SIGKILL
            assert time.monotonic() - started < 3
    finally:
        finished.set()
        rescuer.join(timeout=6)
        control.executor_done()
        stdin.close()
        os.close(outer_master)
        os.close(outer_slave)


@pytest.mark.skipif(os.name != "posix", reason="Command Workers require POSIX")
@pytest.mark.parametrize("mode", ["pipes", "pty"])
def test_command_keeps_draining_after_log_disk_fills(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    mode: str,
) -> None:
    import pty

    class FullDisk(io.BytesIO):
        attempts = 0

        def write(self, chunk: bytes) -> int:
            self.attempts += 1
            raise OSError(errno.ENOSPC, "No space left on device")

    sink = FullDisk()
    log_path = tmp_path / "run.log"
    original_open = Path.open
    monkeypatch.setattr(
        Path,
        "open",
        lambda path, *args, **kwargs: (
            sink if path == log_path else original_open(path, *args, **kwargs)
        ),
    )
    outer_master, outer_slave = pty.openpty()
    stdin = os.fdopen(os.dup(outer_slave), "r", encoding="utf-8")
    stdout_bytes, stderr_bytes = io.BytesIO(), io.BytesIO()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(
        sys, "stdout", io.TextIOWrapper(stdout_bytes, encoding="utf-8", write_through=True)
    )
    monkeypatch.setattr(
        sys, "stderr", io.TextIOWrapper(stderr_bytes, encoding="utf-8", write_through=True)
    )
    processes: list[subprocess.Popen[bytes]] = []
    original_popen = subprocess.Popen

    def launch(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        process = original_popen(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr("labtasker.command_worker.subprocess.Popen", launch)
    finished, rescued = threading.Event(), threading.Event()

    def rescue() -> None:
        if not finished.wait(5):
            rescued.set()
            if processes:
                with suppress(ProcessLookupError):
                    os.killpg(processes[0].pid, signal.SIGKILL)

    rescuer = threading.Thread(target=rescue, daemon=True)
    rescuer.start()
    control = RunControl(force_stop_timeout=None, force_stop=lambda: None)
    size = 1024 * 1024
    script = f"import os; os.write(1, b'x' * {size}); os.write(2, b'y' * {size})"
    try:
        run = _run_pipes if mode == "pipes" else _run_pty
        process = run([sys.executable, "-c", script], dict(os.environ), log_path, control, None)
        assert not rescued.is_set(), "child blocked after the log sink failed"
        assert process.returncode == 0
        assert sink.attempts == 1
        assert sum("Could not write command run.log" in r.message for r in caplog.records) == 1
        if mode == "pipes":
            assert stdout_bytes.getvalue() == b"x" * size
            assert stderr_bytes.getvalue() == b"y" * size
        else:
            assert stdout_bytes.getvalue() == b"x" * size + b"y" * size
    finally:
        finished.set()
        rescuer.join(timeout=6)
        control.executor_done()
        stdin.close()
        os.close(outer_master)
        os.close(outer_slave)


def test_command_log_retries_short_writes_without_losing_bytes() -> None:
    class ShortWriter(io.BytesIO):
        def write(self, chunk: bytes) -> int:
            return super().write(chunk[:3])

    stream = ShortWriter()
    sink = _CommandLog(stream)
    sink.write(b"complete-output")
    assert stream.getvalue() == b"complete-output"


@pytest.mark.parametrize("written", [0, None])
def test_command_log_disables_nonprogressing_sink_once(
    caplog: pytest.LogCaptureFixture, written: int | None
) -> None:
    class StuckWriter(io.BytesIO):
        attempts = 0

        def write(self, chunk):
            self.attempts += 1
            return written

    stream = StuckWriter()
    sink = _CommandLog(stream)
    sink.write(b"first")
    sink.write(b"second")
    assert stream.attempts == 1
    assert sum("Could not write command run.log" in r.message for r in caplog.records) == 1


@pytest.mark.skipif(os.name != "posix", reason="Command Workers require POSIX process groups")
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


@pytest.mark.skipif(os.name != "posix", reason="Command Workers require POSIX process groups")
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


@pytest.mark.skipif(os.name != "posix", reason="Command Workers require POSIX")
@pytest.mark.parametrize("action", ["complete", "fail"])
def test_command_terminal_retry_stops_after_heartbeat_confirms_loss(
    monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    from labtasker.errors import TransportError

    client = FakeClient([make_claim(), None])
    install(monkeypatch, client)
    monkeypatch.setattr("labtasker.worker.HEARTBEAT_INTERVAL_SECONDS", 0.001)
    monkeypatch.setattr("labtasker.worker.TERMINAL_BACKOFF_SECONDS", (0.0,))
    controls: list[RunControl] = []
    reporting = threading.Event()
    attempts = 0

    def make_control(**kwargs: Any) -> RunControl:
        control = RunControl(**kwargs)
        controls.append(control)
        return control

    def heartbeat(**_: object) -> None:
        if reporting.is_set():
            raise APIError(409, "stale_run", "revoked", {})

    def failed_report(**_: object) -> None:
        nonlocal attempts
        attempts += 1
        assert attempts == 1, "retried after confirmed ownership loss"
        reporting.set()
        deadline = time.monotonic() + 1
        while not controls[0].revoked and time.monotonic() < deadline:
            time.sleep(0.001)
        assert controls[0].revoked
        raise TransportError("terminal endpoint unavailable")

    monkeypatch.setattr("labtasker.command_worker.RunControl", make_control)
    monkeypatch.setattr(client, "_heartbeat", heartbeat)
    monkeypatch.setattr(client, f"_{action}", failed_report)
    run_command_worker(
        [sys.executable, "-c", "pass" if action == "complete" else "raise SystemExit(1)"],
        idle_timeout=0,
        max_consecutive_failures=1,
    )
    assert attempts == 1
    assert client.actions == []


@pytest.mark.skipif(os.name != "posix", reason="process-group behavior is POSIX-specific")
@pytest.mark.parametrize("launcher_exits", [False, True])
@pytest.mark.parametrize("force_stop_timeout", [0.1, None])
def test_revocation_kills_surviving_descendant_after_launcher_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    launcher_exits: bool,
    force_stop_timeout: float | None,
) -> None:
    ready = tmp_path / "descendant-ready"
    child_script = (
        "import os,signal,sys,time; from pathlib import Path; "
        + ("signal.signal(signal.SIGTERM, signal.SIG_IGN); " if force_stop_timeout else "")
        + "Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(30)"
    )
    launcher_script = (
        "import subprocess,sys,time; "
        "subprocess.Popen([sys.executable, '-c', sys.argv[1], sys.argv[2]]); "
        + ("sys.exit(0)" if launcher_exits else "time.sleep(30)")
    )
    processes: list[subprocess.Popen[bytes]] = []
    original_popen = subprocess.Popen

    def launch(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        process = original_popen(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr("labtasker.command_worker.subprocess.Popen", launch)
    control = RunControl(force_stop_timeout=None, force_stop=lambda: None)
    finished = threading.Event()
    timed_out = threading.Event()

    def revoke_and_rescue() -> None:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if (
                ready.exists()
                and processes
                and (not launcher_exits or processes[0].poll() is not None)
            ):
                control.revoke("cancel")
                break
            time.sleep(0.01)
        if not finished.wait(max(0, deadline - time.monotonic())):
            timed_out.set()
            if processes:
                with suppress(ProcessLookupError):
                    os.killpg(processes[0].pid, signal.SIGKILL)

    rescuer = threading.Thread(target=revoke_and_rescue, daemon=True)
    rescuer.start()
    try:
        process = _run_pipes(
            [sys.executable, "-c", launcher_script, child_script, str(ready)],
            dict(os.environ),
            tmp_path / "run.log",
            control,
            force_stop_timeout,
        )
        # Returning from pipe drainage proves the surviving child released its
        # inherited streams; waiting for the launcher alone cannot achieve this.
        assert control.revoked
        assert process.returncode == (0 if launcher_exits else -signal.SIGTERM)
        assert not timed_out.is_set(), "descendant survived the force-stop deadline"
    finally:
        finished.set()
        rescuer.join(timeout=6)
        control.executor_done()
        if processes:
            with suppress(ProcessLookupError):
                os.killpg(processes[0].pid, signal.SIGKILL)
            processes[0].wait(timeout=3)


@pytest.mark.parametrize("state, expected", [("Z", False), ("X", False), ("S", True)])
def test_linux_group_wait_ignores_zombies_but_waits_for_live_members(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, state: str, expected: bool
) -> None:
    from labtasker.command_worker import _process_group_alive

    process = tmp_path / "123"
    process.mkdir()
    # A process name may itself contain spaces and closing parentheses.
    (process / "stat").write_text(f"123 (worker ) child) {state} 1 456 456 0 0")
    monkeypatch.setattr("labtasker.command_worker._PLATFORM", "linux")
    monkeypatch.setattr("labtasker.command_worker.Path", lambda _: tmp_path)
    monkeypatch.setattr("labtasker.command_worker.os.killpg", lambda *_: None)
    assert _process_group_alive(456) is expected


def test_linux_group_wait_is_conservative_when_process_inspection_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from labtasker.command_worker import _process_group_alive

    monkeypatch.setattr("labtasker.command_worker._PLATFORM", "linux")
    monkeypatch.setattr("labtasker.command_worker.Path", lambda _: tmp_path / "unavailable")
    monkeypatch.setattr("labtasker.command_worker.os.killpg", lambda *_: None)
    assert _process_group_alive(456)


@pytest.mark.parametrize("state", ["Z", "S"])
def test_darwin_zombie_signal_permission_error_is_not_a_live_process_failure(
    monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    from labtasker.command_worker import _process_group_alive, _signal_process_group

    def denied(*_: object) -> None:
        raise PermissionError("Darwin zombie group")

    monkeypatch.setattr("labtasker.command_worker._PLATFORM", "darwin")
    monkeypatch.setattr("labtasker.command_worker.os.killpg", denied)
    monkeypatch.setattr(
        "labtasker.command_worker.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(stdout=f"456 {state}\n789 S\n"),
    )
    assert _process_group_alive(456) is (state == "S")
    if state == "Z":
        _signal_process_group(456, signal.SIGTERM)
    else:
        with pytest.raises(PermissionError):
            _signal_process_group(456, signal.SIGTERM)


def test_environment_context_loads_task_info_and_finish_without_import_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    claim = make_claim()
    from labtasker.journal import LocalRunJournal

    journal = LocalRunJournal.create(
        claim=claim,
        endpoint={
            "connection": "http",
            "managed_local": False,
            "url": "http://server",
            "socket": None,
            "labtasker_root": None,
            "database": None,
        },
        queue="default",
        route="default",
        labtasker_root=tmp_path / ".labtasker",
    )
    environment = {
        "LABTASKER_URL": "http://server",
        "LABTASKER_QUEUE": "default",
        "LABTASKER_TASK_ID": claim.task.id,
        "LABTASKER_RUN_ID": claim.run_id,
        "LABTASKER_ROUTE": "default",
        "LABTASKER_RUN_DIR": str(journal.run_dir),
        "LABTASKER_WORKER_ID": "w_ABCDEFGHIJKL",
    }
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    reported: list[dict[str, Any]] = []
    progress_reports: list[dict[str, Any]] = []
    telemetry_reports: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "labtasker.worker.report_complete_until_resolved",
        lambda _client, **kwargs: not reported.append(kwargs["result"]),
    )
    monkeypatch.setattr(
        "labtasker.worker.report_progress_once",
        lambda _client, **kwargs: not progress_reports.append(kwargs["progress"]),
    )
    monkeypatch.setattr(
        "labtasker.worker.report_worker_telemetry_once",
        lambda _client, **kwargs: not telemetry_reports.append(kwargs["telemetry"]),
    )
    assert task_info().run_dir == journal.run_dir
    assert report_progress({"step": 7})
    assert report_worker_telemetry({"gpu_utilization": 0.75})
    finish({"metric": 3})
    assert progress_reports == [{"step": 7}]
    assert telemetry_reports == [{"gpu_utilization": 0.75}]
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


@pytest.mark.parametrize("kind", ["exit", "startup", "binding"])
def test_command_failure_guard_stops_after_reporting(monkeypatch, kind):
    from labtasker.errors import FatalWorkerError

    client = FakeClient([make_claim(run_id=f"r_{i:012d}") for i in range(3)])
    install(monkeypatch, client)
    argv = {
        "exit": [sys.executable, "-c", "raise SystemExit(7)"],
        "startup": ["/definitely/missing/command"],
        "binding": [sys.executable, "%{missing}"],
    }[kind]
    with pytest.raises(FatalWorkerError, match="2 consecutive execution failures"):
        run_command_worker(argv, max_consecutive_failures=2)
    assert len(client.actions) == 2
    assert all(a[0] == "fail" for a in client.actions)
    assert len(client.claims) == 1


def test_command_success_resets_failure_guard(monkeypatch):
    from labtasker.errors import FatalWorkerError

    client = FakeClient(
        [
            make_claim(run_id=f"r_{i:012d}", args={"code": code})
            for i, code in enumerate([1, 0, 1, 1, 1])
        ]
    )
    install(monkeypatch, client)
    with pytest.raises(FatalWorkerError):
        run_command_worker(
            [sys.executable, "-c", "import sys; sys.exit(int(sys.argv[1]))", "%{code}"],
            max_consecutive_failures=2,
        )
    assert [a[0] for a in client.actions] == ["fail", "complete", "fail", "fail"]
    assert len(client.claims) == 1


@pytest.mark.parametrize("mode", ["stale", "retry"])
def test_command_reporting_does_not_inflate_or_reset_count(monkeypatch, mode):
    from labtasker.errors import FatalWorkerError, TransportError

    client = FakeClient([make_claim(run_id=f"r_{i:012d}") for i in range(4)])
    install(monkeypatch, client)
    monkeypatch.setattr("labtasker.worker.time.sleep", lambda _: None)
    original = client._fail
    calls = 0

    def report(**kwargs):
        nonlocal calls
        calls += 1
        if mode == "stale" and calls == 2:
            raise APIError(409, "stale_run", "revoked", {})
        if mode == "retry" and calls < 4:
            raise TransportError("unavailable")
        original(**kwargs)

    monkeypatch.setattr(client, "_fail", report)
    with pytest.raises(FatalWorkerError):
        run_command_worker(
            [sys.executable, "-c", "raise SystemExit(7)"], max_consecutive_failures=2
        )
    assert len(client.actions) == 2
    assert len(client.claims) == (1 if mode == "stale" else 2)


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "5", None])
def test_command_failure_limit_is_validated_before_client(monkeypatch, value):
    monkeypatch.setattr(
        "labtasker.command_worker.Client", lambda **_: pytest.fail("Client constructed")
    )
    with pytest.raises(ValueError, match="positive integer"):
        run_command_worker(["echo"], max_consecutive_failures=value)


def test_command_observation_failure_does_not_stop_tasks_or_charge_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    attempted = threading.Event()

    def failed(request: httpx.Request) -> httpx.Response:
        attempted.set()
        raise httpx.ConnectTimeout("observation offline", request=request)

    monkeypatch.setattr(
        "labtasker.observations._make_http_client",
        lambda config: httpx.Client(
            base_url="http://server/api/v2/", transport=httpx.MockTransport(failed)
        ),
    )
    client = FakeClient(
        [make_claim(), make_claim(task_id="t_BCDEFGHIJKLM", run_id="r_BCDEFGHIJKLM"), None]
    )
    install(monkeypatch, client)
    run_command_worker([sys.executable, "-c", "pass"], idle_timeout=0, max_consecutive_failures=1)
    assert attempted.is_set()
    assert [action[0] for action in client.actions] == ["complete", "complete"]
