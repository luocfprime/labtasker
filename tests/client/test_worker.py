from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
import warnings
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

import labtasker.execution as execution_module
from labtasker.binding import TaskArg
from labtasker.client import Client
from labtasker.config import ResolvedConfig
from labtasker.errors import (
    APIError,
    ConfigError,
    FatalWorkerError,
    TaskError,
    TransientError,
    TransportError,
)
from labtasker.execution import (
    ExecutionContext,
    RunControl,
    activate_context,
    cancellation_requested,
    deactivate_context,
    finish,
    report_progress,
    report_worker_telemetry,
    set_force_stop_timeout,
    task_info,
)
from labtasker.journal import LocalRunJournal
from labtasker.models import ClaimResponse, Queue, Task, TaskInfo
from labtasker.worker import (
    Heartbeat,
    _failure_diagnostic,
    _guard_worker_topology,
    loop,
    report_complete_until_resolved,
    report_progress_once,
    report_worker_telemetry_once,
)

UTC = timezone.utc


def make_claim(
    *,
    task_id: str = "t_ABCDEFGHIJKL",
    run_id: str = "r_ABCDEFGHIJKL",
    args: dict[str, Any] | None = None,
    attempt: int = 1,
) -> ClaimResponse:
    task = Task.model_validate(
        {
            "id": task_id,
            "queue": "default",
            "status": "running",
            "name": "worker-test",
            "args": {} if args is None else args,
            "metadata": {},
            "priority": 0,
            "attempt": attempt,
            "max_attempts": 3,
            "routes": ["default"],
            "result": {},
            "last_error": None,
            "last_route": "default",
            "created_at": datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
            "updated_at": datetime(2026, 8, 20, 12, attempt, tzinfo=UTC),
            "started_at": datetime(2026, 8, 20, 12, attempt, tzinfo=UTC),
            "finished_at": None,
        },
        strict=True,
    )
    return ClaimResponse(
        task=task,
        run_id=run_id,
        lease_expires_at=datetime(2026, 8, 20, 12, 10, tzinfo=UTC),
    )


class FakeClient:
    def __init__(self, claims: list[ClaimResponse | None]) -> None:
        self.configuration = ResolvedConfig(
            url="http://server", queue="default", token=None, local=None
        )
        self.claims = deque(claims)
        self.actions: list[tuple[str, str, object]] = []
        self.claim_run_ids: list[str] = []

    def __enter__(self) -> FakeClient:
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def list_queues(self) -> list[Queue]:
        return [Queue(name="default")]

    def _health(self) -> object:
        return SimpleNamespace(status="ok", api_version="2", database="ok")

    def _claim(self, *, route: str, run_id: str, queue: str) -> ClaimResponse | None:
        self.claim_run_ids.append(run_id)
        return self.claims.popleft() if self.claims else None

    def _heartbeat(self, **_: object) -> object:
        raise AssertionError("short unit executions must stop before the first heartbeat")

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
def reset_execution_context() -> None:
    execution_module._ACTIVE_CONTEXT = None
    execution_module._ENV_CONTEXT = None


def install_fake_client(monkeypatch: pytest.MonkeyPatch, client: FakeClient) -> None:
    monkeypatch.setattr("labtasker.worker.Client", lambda **_: client)


def test_python_loop_processes_multiple_tasks_and_journals_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = FakeClient(
        [
            make_claim(args={"prompt": "cat", "extra": 1}),
            make_claim(
                task_id="t_MNOPQRSTUVWX",
                run_id="r_MNOPQRSTUVWX",
                args={"prompt": "dog"},
                attempt=2,
            ),
            None,
        ]
    )
    install_fake_client(monkeypatch, client)
    observed: list[tuple[str, str, str]] = []

    @loop(idle_timeout=0)
    def handler(model: str, prompt: str = TaskArg()) -> None:
        info = task_info()
        observed.append((model, prompt, info.run_id))
        print(f"running {prompt}")

    handler("loaded")
    assert observed == [
        ("loaded", "cat", "r_ABCDEFGHIJKL"),
        ("loaded", "dog", "r_MNOPQRSTUVWX"),
    ]
    assert client.actions == [
        ("complete", "t_ABCDEFGHIJKL", {}),
        ("complete", "t_MNOPQRSTUVWX", {}),
    ]
    assert len(set(client.claim_run_ids)) == 3
    logs = list(tmp_path.glob(".labtasker/runs/default/**/run.log"))
    assert len(logs) == 2
    assert {path.read_text().strip() for path in logs} == {"running cat", "running dog"}


def test_journal_creation_failure_unclaims_before_worker_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient([make_claim()])
    install_fake_client(monkeypatch, client)

    def fail_journal(**_: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("labtasker.worker.LocalRunJournal.create", fail_journal)

    @loop(idle_timeout=0)
    def handler() -> None:
        raise AssertionError("Handler must not run without a journal.")

    with pytest.raises(OSError, match="disk full"):
        handler()
    assert client.actions == [("unclaim", "t_ABCDEFGHIJKL", None)]


@pytest.mark.parametrize("phase", ["reporting", "acknowledged"])
def test_mid_run_journal_failure_does_not_block_server_completion(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    phase: str,
) -> None:
    client = FakeClient([make_claim(), None])
    install_fake_client(monkeypatch, client)

    def fail_reporting(*_: object, **__: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(f"labtasker.journal.LocalRunJournal.{phase}", fail_reporting)

    @loop(idle_timeout=0)
    def handler() -> None:
        finish({"server_is_authoritative": True})

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        handler()

    assert client.actions == [("complete", "t_ABCDEFGHIJKL", {"server_is_authoritative": True})]
    assert "could not update the local run journal: disk full" in caplog.text


def test_finish_after_confirmed_revocation_does_not_report(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient([make_claim(), None])
    install_fake_client(monkeypatch, client)

    @loop(idle_timeout=0)
    def handler() -> None:
        context = execution_module._ACTIVE_CONTEXT
        assert context is not None and context.control is not None
        context.control.revoke("cancel")
        with pytest.raises(RuntimeError, match="revoked"):
            finish({"late": True})
        assert context.journal.phase == "running"

    handler()
    assert client.actions == []


@pytest.mark.parametrize(
    ("mode", "exit_code"),
    [("returned", 0), ("raised", 0), ("active", 1), ("finish-active", 1)],
)
def test_force_stop_only_applies_while_user_function_is_active(
    tmp_path: Path, mode: str, exit_code: int
) -> None:
    # Run the real watchdog/os._exit in an isolated process. Revocation is
    # synchronized to the terminal request, after normal/exceptional return,
    # or while inline code/finish() still occupies the executor.
    script = """
import sys, time
from types import SimpleNamespace
import labtasker.execution as execution
import labtasker.worker as worker
from labtasker.binding import compile_binding
from labtasker.config import ResolvedConfig
from labtasker.errors import TransportError
from labtasker.models import ClaimResponse
from labtasker.tee import WorkerTee
mode = sys.argv[1]
claim = ClaimResponse.model_validate_json(sys.argv[2])
worker.TERMINAL_BACKOFF_SECONDS = (1.0 if mode == 'finish-active' else 0.2,)
def report(**kwargs):
    execution._ACTIVE_CONTEXT.control.revoke('cancel')
    raise TransportError('terminal response lost')
client = SimpleNamespace(
    configuration=ResolvedConfig(url='http://server', queue='default', token=None, local=None),
    _complete=report, _fail=report, _heartbeat=lambda **kwargs: None,
)
def handler():
    if mode == 'raised':
        raise ValueError('workload failed')
    if mode == 'active':
        execution._ACTIVE_CONTEXT.control.revoke('cancel')
        time.sleep(2)
    if mode == 'finish-active':
        execution.finish({'score': 1})
with WorkerTee() as tee:
        worker._run_python_claim(
            client, tee, compile_binding(handler), (), {}, claim=claim,
            queue='default', route='default', force_stop_timeout=0.03,
            worker_id='w_ABCDEFGHIJKL',
        )
print('worker-survived')
"""
    result = subprocess.run(
        [sys.executable, "-c", script, mode, make_claim().model_dump_json()],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == exit_code, result.stderr
    assert ("worker-survived" in result.stdout) is (exit_code == 0)


def test_default_log_handler_disk_error_does_not_interrupt_finish_or_terminal_retry(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import labtasker.tee as tee_module

    client = FakeClient([make_claim(), None])
    install_fake_client(monkeypatch, client)
    monkeypatch.setattr("labtasker.worker.TERMINAL_BACKOFF_SECONDS", (0.0,))
    original = client._complete
    attempts = 0

    def complete(**kwargs: Any) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TransportError("offline")
        original(**kwargs)

    def fail_journal(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    class FullDisk:
        write = fail_journal
        flush = fail_journal

    monkeypatch.setattr(client, "_complete", complete)
    monkeypatch.setattr(LocalRunJournal, "reporting", fail_journal)

    @loop(idle_timeout=0)
    def handler() -> None:
        tee = tee_module._ACTIVE_TEE
        assert tee is not None and tee._stderr is not None
        destination = tee._stderr._destination
        stream_handler = logging.StreamHandler(sys.stderr)
        logger = logging.getLogger("labtasker.worker")
        logger.addHandler(stream_handler)
        tee._stderr._destination = FullDisk()  # type: ignore[assignment]
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error")
                finish({"score": 1})
        finally:
            tee._stderr._destination = destination
            logger.removeHandler(stream_handler)

    handler()
    assert attempts == 2
    assert client.actions == [("complete", "t_ABCDEFGHIJKL", {"score": 1})]
    diagnostics = capsys.readouterr().err
    assert "could not update the local run journal: disk full" in diagnostics
    assert "Terminal report transport error; retrying: offline" in diagnostics


@pytest.mark.parametrize("action", ["complete", "finish", "fail", "unclaim"])
def test_terminal_retry_stops_after_heartbeat_confirms_revocation(
    monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    client = FakeClient([make_claim(), None])
    install_fake_client(monkeypatch, client)
    monkeypatch.setattr("labtasker.worker.HEARTBEAT_INTERVAL_SECONDS", 0.001)
    monkeypatch.setattr("labtasker.worker.TERMINAL_BACKOFF_SECONDS", (0.0,))
    reporting = threading.Event()
    attempts = 0

    def heartbeat(**_: object) -> None:
        if reporting.is_set():
            raise APIError(409, "stale_run", "revoked", {})

    def failed_report(**_: object) -> None:
        nonlocal attempts
        attempts += 1
        assert attempts == 1, "retried after confirmed ownership loss"
        reporting.set()
        context = execution_module._ACTIVE_CONTEXT
        assert context is not None and context.control is not None
        deadline = time.monotonic() + 1
        while not context.control.revoked and time.monotonic() < deadline:
            time.sleep(0.001)
        assert context.control.revoked
        raise TransportError("terminal response lost")

    monkeypatch.setattr(client, "_heartbeat", heartbeat)
    monkeypatch.setattr(client, f"_{'complete' if action == 'finish' else action}", failed_report)

    @loop(idle_timeout=0, max_consecutive_failures=1)
    def handler() -> None:
        if action == "finish":
            finish({"result": 1})
        elif action == "fail":
            raise ValueError("workload error")
        elif action == "unclaim":
            raise TransientError("try again")

    handler()
    assert attempts == 1
    assert client.actions == []


def test_benign_completed_control_does_not_cancel_completion_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient([make_claim(), None])
    install_fake_client(monkeypatch, client)
    monkeypatch.setattr("labtasker.worker.TERMINAL_BACKOFF_SECONDS", (0.0,))
    original = client._complete
    attempts = 0

    def complete(**kwargs: Any) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            context = execution_module._ACTIVE_CONTEXT
            assert context is not None and context.control is not None
            context.control.complete()
            raise TransportError("accepted completion response lost")
        original(**kwargs)

    monkeypatch.setattr(client, "_complete", complete)

    @loop(idle_timeout=0)
    def handler() -> None:
        finish({"score": 1})

    handler()
    assert attempts == 2
    assert client.actions == [("complete", "t_ABCDEFGHIJKL", {"score": 1})]


def test_failure_levels_and_binding_error_continue_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient(
        [
            make_claim(args={"mode": "transient"}),
            make_claim(
                task_id="t_MNOPQRSTUVWX",
                run_id="r_MNOPQRSTUVWX",
                args={"mode": "failure"},
            ),
            make_claim(
                task_id="t_ZYXWVUTSRQPO",
                run_id="r_ZYXWVUTSRQPO",
                args={},
            ),
            None,
        ]
    )
    install_fake_client(monkeypatch, client)

    @loop(idle_timeout=0)
    def handler(mode: str = TaskArg()) -> None:
        if mode == "transient":
            raise TransientError("temporary")
        raise ValueError("broken")

    handler()
    assert [action[:2] for action in client.actions] == [
        ("unclaim", "t_ABCDEFGHIJKL"),
        ("fail", "t_MNOPQRSTUVWX"),
        ("fail", "t_ZYXWVUTSRQPO"),
    ]
    assert client.actions[1][2]["type"] == "ValueError"  # type: ignore[index]
    assert client.actions[2][2]["type"] == "BindingError"  # type: ignore[index]


def test_fatal_failure_reports_then_stops_but_post_finish_cannot_rewrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed = FakeClient([make_claim()])
    install_fake_client(monkeypatch, failed)

    @loop(idle_timeout=0)
    def fatal() -> None:
        raise FatalWorkerError("unsafe")

    with pytest.raises(FatalWorkerError, match="unsafe"):
        fatal()
    assert failed.actions[0][0] == "fail"

    completed = FakeClient([make_claim(task_id="t_MNOPQRSTUVWX", run_id="r_MNOPQRSTUVWX")])
    install_fake_client(monkeypatch, completed)

    @loop(idle_timeout=0)
    def finish_then_fatal() -> None:
        finish({"score": 1})
        raise FatalWorkerError("cleanup unsafe")

    with pytest.raises(FatalWorkerError, match="cleanup unsafe"):
        finish_then_fatal()
    assert completed.actions == [("complete", "t_MNOPQRSTUVWX", {"score": 1})]


def test_finish_is_not_control_flow_and_later_ordinary_error_does_not_rewrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient([make_claim(), None])
    install_fake_client(monkeypatch, client)
    after_finish: list[bool] = []

    @loop(idle_timeout=0)
    def handler() -> None:
        finish({"ok": True})
        after_finish.append(task_info().run_id == "r_ABCDEFGHIJKL")
        raise RuntimeError("bad shutdown")

    handler()
    assert after_finish == [True]
    assert client.actions == [("complete", "t_ABCDEFGHIJKL", {"ok": True})]


def test_keyboard_interrupt_best_effort_unclaims_and_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient([make_claim()])
    install_fake_client(monkeypatch, client)

    @loop(idle_timeout=0)
    def handler() -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        handler()
    assert client.actions == [("unclaim", "t_ABCDEFGHIJKL", None)]


def test_keyboard_interrupt_during_terminal_report_still_unclaims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class InterruptedClient(FakeClient):
        def _complete(self, **_: object) -> None:
            raise KeyboardInterrupt

    client = InterruptedClient([make_claim()])
    install_fake_client(monkeypatch, client)

    @loop(idle_timeout=0)
    def handler() -> None:
        pass

    with pytest.raises(KeyboardInterrupt):
        handler()
    assert client.actions == [("unclaim", "t_ABCDEFGHIJKL", None)]


def test_idle_zero_claims_once_and_unknown_queue_fails_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient([None])
    install_fake_client(monkeypatch, client)

    @loop(idle_timeout=0)
    def handler() -> None:
        raise AssertionError

    handler()
    assert len(client.claim_run_ids) == 1

    client.list_queues = lambda: [Queue(name="other")]  # type: ignore[method-assign]
    with pytest.raises(ConfigError, match="does not exist"):
        handler()


def test_terminal_report_retries_only_uncertain_and_server_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("labtasker.worker.time.sleep", lambda _: None)
    outcomes: deque[Exception | None] = deque(
        [
            TransportError("offline"),
            APIError(503, "database_busy", "busy", {}),
            None,
        ]
    )
    calls = 0

    class Reporter:
        def _complete(self, **_: object) -> None:
            nonlocal calls
            calls += 1
            outcome = outcomes.popleft()
            if outcome is not None:
                raise outcome

    assert report_complete_until_resolved(
        Reporter(),  # type: ignore[arg-type]
        queue="default",
        task_id="t_ABCDEFGHIJKL",
        run_id="r_ABCDEFGHIJKL",
        result={},
    )
    assert calls == 3

    for code, details in (("stale_run", {}), ("run_finalized", {"action": "fail"})):

        class StaleReporter:
            def __init__(self, error_code: str, error_details: dict[str, object]) -> None:
                self.error_code = error_code
                self.error_details = error_details

            def _complete(self, **_: object) -> None:
                raise APIError(409, self.error_code, "stale", self.error_details)

        assert not report_complete_until_resolved(
            StaleReporter(code, details),  # type: ignore[arg-type]
            queue="default",
            task_id="t_ABCDEFGHIJKL",
            run_id="r_ABCDEFGHIJKL",
            result={},
        )

    class InvalidReporter:
        def _complete(self, **_: object) -> None:
            raise APIError(422, "invalid_request", "bad", {})

    with pytest.raises(APIError, match="bad"):
        report_complete_until_resolved(
            InvalidReporter(),  # type: ignore[arg-type]
            queue="default",
            task_id="t_ABCDEFGHIJKL",
            run_id="r_ABCDEFGHIJKL",
            result={},
        )


def test_failure_diagnostic_has_bounded_fallback() -> None:
    normal = ValueError("bad")
    assert _failure_diagnostic(normal, "r_ABCDEFGHIJKL")[:2] == ("ValueError", "bad")
    huge = ValueError("x" * (1024 * 1024))
    assert _failure_diagnostic(huge, "r_ABCDEFGHIJKL") == (
        "ValueError",
        "Failure diagnostics exceeded the 1 MiB limit; see local run.log.",
        None,
    )
    invalid_unicode = ValueError("bad \ud800 text")
    assert _failure_diagnostic(invalid_unicode, "r_ABCDEFGHIJKL")[1] == "bad � text"


def test_run_control_cancellation_setter_uses_revocation_time() -> None:
    forced = threading.Event()
    control = RunControl(force_stop_timeout=None, force_stop=forced.set)
    control.revoke("cancel")
    time.sleep(0.01)
    control.set_force_stop_timeout(0)
    assert forced.wait(1)


def test_repeating_force_stop_setter_does_not_slide_revocation_deadline() -> None:
    forced = threading.Event()
    control = RunControl(force_stop_timeout=None, force_stop=forced.set)
    control.revoke("cancel")
    control.set_force_stop_timeout(0.08)
    time.sleep(0.04)
    control.set_force_stop_timeout(0.08)
    assert forced.wait(0.06)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (APIError(409, "stale_run", "stale", {}), "revoked"),
        (APIError(409, "run_finalized", "done", {"action": "complete"}), "completed"),
        (APIError(401, "unauthorized", "bad token", {}), "fatal"),
    ],
)
def test_heartbeat_distinguishes_completion_revocation_and_protocol_failure(
    monkeypatch: pytest.MonkeyPatch,
    error: APIError,
    expected: str,
) -> None:
    monkeypatch.setattr("labtasker.worker.HEARTBEAT_INTERVAL_SECONDS", 0.001)

    class HeartbeatClient:
        def _heartbeat(self, **_: object) -> None:
            raise error

    control = RunControl(force_stop_timeout=None, force_stop=lambda: None)
    heartbeat = Heartbeat(
        HeartbeatClient(),  # type: ignore[arg-type]
        queue="default",
        task_id="t_ABCDEFGHIJKL",
        run_id="r_ABCDEFGHIJKL",
        control=control,
    )
    heartbeat.start()
    deadline = time.monotonic() + 1
    while control.active and time.monotonic() < deadline:
        time.sleep(0.001)
    heartbeat.stop()
    if expected == "completed":
        assert control.completed
    elif expected == "revoked":
        assert control.revoked and control.fatal_error is None
    else:
        assert control.revoked and control.fatal_error is error
    control.executor_done()


def test_heartbeat_recovers_after_deep_error_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("labtasker.worker.HEARTBEAT_INTERVAL_SECONDS", 0.001)
    recovered = threading.Event()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                503, content=b'{"error":' + b"[" * 1100 + b"0" + b"]" * 1100 + b"}"
            )
        recovered.set()
        return httpx.Response(200, json={"lease_expires_at": "2026-09-09T12:00:00Z"})

    client = Client(url="http://server.test")
    client._http.close()
    client._http = httpx.Client(
        base_url="http://server.test/api/v2/", transport=httpx.MockTransport(handler)
    )
    control = RunControl(force_stop_timeout=None, force_stop=lambda: None)
    heartbeat = Heartbeat(
        client,
        queue="default",
        task_id="t_ABCDEFGHIJKL",
        run_id="r_ABCDEFGHIJKL",
        control=control,
    )
    heartbeat.start()
    try:
        assert recovered.wait(1), "invalid JSON stopped the heartbeat thread"
    finally:
        heartbeat.stop()
        control.executor_done()
        client.close()
    assert control.active and control.fatal_error is None
    assert len(requests) >= 2
    assert requests[0].content == requests[1].content


def test_terminal_report_recovers_after_deep_error_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("labtasker.worker.TERMINAL_BACKOFF_SECONDS", (0.0,))
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) < 5:
            return httpx.Response(
                503, content=b'{"error":' + b"[" * 1100 + b"0" + b"]" * 1100 + b"}"
            )
        return httpx.Response(204)

    client = Client(url="http://server.test")
    client._http.close()
    client._http = httpx.Client(
        base_url="http://server.test/api/v2/", transport=httpx.MockTransport(handler)
    )
    with client:
        assert report_complete_until_resolved(
            client,
            queue="default",
            task_id="t_ABCDEFGHIJKL",
            run_id="r_ABCDEFGHIJKL",
            result={"score": 1},
        )
    assert len(requests) == 5
    assert len({request.content for request in requests}) == 1


def test_cooperative_api_and_finish_context(tmp_path: Path) -> None:
    claimed = make_claim()
    journal = LocalRunJournal.create(
        claim=claimed,
        endpoint={
            "mode": "http",
            "url": "http://server",
            "socket": None,
            "directory": None,
            "database": None,
        },
        queue="default",
        route="default",
        cwd=tmp_path,
    )
    control = RunControl(force_stop_timeout=None, force_stop=lambda: None)
    results: list[dict[str, Any]] = []
    progress_reports: list[dict[str, Any]] = []
    telemetry_reports: list[dict[str, Any]] = []
    info = TaskInfo(
        **claimed.task.model_dump(),
        run_id=claimed.run_id,
        run_dir=journal.run_dir,
    )
    context = ExecutionContext(
        info=info,
        kind="python",
        journal=journal,
        reporter=lambda result: not results.append(result),
        control=control,
        progress_reporter=lambda progress: not progress_reports.append(progress),
        worker_telemetry_reporter=lambda telemetry: not telemetry_reports.append(telemetry),
    )
    activate_context(context)
    try:
        assert task_info() == info
        assert not cancellation_requested()
        assert report_progress({"step": 4, "loss": 0.5})
        assert progress_reports == [{"step": 4, "loss": 0.5}]
        assert report_worker_telemetry({"gpu_utilization": 0.5})
        assert telemetry_reports == [{"gpu_utilization": 0.5}]
        set_force_stop_timeout(2)
        control.revoke("cancel")
        assert cancellation_requested()
        control = RunControl(force_stop_timeout=None, force_stop=lambda: None)
        context.control = control
        finish({"score": 2})
        assert results == [{"score": 2}]
        assert not cancellation_requested()
        with pytest.raises(RuntimeError, match="no longer cancellable"):
            set_force_stop_timeout(None)
        with pytest.raises(RuntimeError, match="already been called"):
            finish({})
        with pytest.raises(RuntimeError, match="already completed"):
            report_progress({})
        assert report_worker_telemetry({"cleanup": True})
        assert telemetry_reports == [{"gpu_utilization": 0.5}, {"cleanup": True}]
    finally:
        context.control.executor_done()
        deactivate_context(context)


def test_context_functions_are_strict_outside_execution() -> None:
    with pytest.raises(RuntimeError, match="No active"):
        task_info()
    with pytest.raises(RuntimeError, match="No active"):
        finish()
    finish(skip_if_no_labtasker=True)
    assert not report_progress({}, skip_if_no_labtasker=True)
    assert not report_worker_telemetry({}, skip_if_no_labtasker=True)
    with pytest.raises(RuntimeError, match="active Python"):
        cancellation_requested()


def test_progress_transport_failure_is_best_effort_and_stale_run_revokes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class ProgressClient:
        def __init__(self, error: Exception) -> None:
            self.error = error

        def _report_progress(self, **_: object) -> None:
            raise self.error

    control = RunControl(force_stop_timeout=None, force_stop=lambda: None)
    assert not report_progress_once(
        ProgressClient(TransportError("offline")),  # type: ignore[arg-type]
        queue="default",
        task_id="t_ABCDEFGHIJKL",
        run_id="r_ABCDEFGHIJKL",
        progress={"step": 1},
        control=control,
    )
    assert control.active
    assert not report_progress_once(
        ProgressClient(APIError(409, "run_finalized", "cancelled", {"action": "cancel"})),  # type: ignore[arg-type]
        queue="default",
        task_id="t_ABCDEFGHIJKL",
        run_id="r_ABCDEFGHIJKL",
        progress={"step": 2},
        control=control,
    )
    assert control.revoked
    assert control.revoked_action == "cancel"
    assert "Progress report rejected; continuing Task: cancelled" in caplog.text
    control.executor_done()


def test_worker_telemetry_transport_failure_is_best_effort(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class TelemetryClient:
        def _report_worker_telemetry(self, **_: object) -> None:
            raise TransportError("offline")

    assert not report_worker_telemetry_once(
        TelemetryClient(),  # type: ignore[arg-type]
        queue="default",
        worker_id="w_ABCDEFGHIJKL",
        telemetry={"gpu_utilization": 0.5},
    )
    assert "Worker telemetry transport error; continuing Task" in caplog.text


def test_python_worker_metadata_is_validated_statically() -> None:
    with pytest.raises(ValueError, match="signed 64-bit"):
        loop(metadata={"invalid": 2**63})


@pytest.mark.parametrize("value", [True, -1, float("nan"), float("inf"), "1"])
def test_timeout_validation_is_static(value: object) -> None:
    with pytest.raises((ValueError, TypeError)):
        loop(idle_timeout=value)  # type: ignore[arg-type]
    with pytest.raises((ValueError, TypeError)):
        loop(force_stop_timeout=value)  # type: ignore[arg-type]


def test_distributed_and_nested_worker_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORLD_SIZE", "2")
    monkeypatch.setenv("LOCAL_RANK", "0")
    with pytest.raises(ConfigError, match="outside torchrun"):
        _guard_worker_topology()
    monkeypatch.delenv("WORLD_SIZE")
    monkeypatch.delenv("LOCAL_RANK")
    monkeypatch.setenv("LABTASKER_RUN_ID", "r_ABCDEFGHIJKL")
    with pytest.raises(ConfigError, match="nested Worker"):
        _guard_worker_topology()


@pytest.mark.parametrize("error_type", [ValueError, TaskError, TransientError])
def test_failure_guard_stops_before_next_claim(monkeypatch, error_type):
    client = FakeClient([make_claim(run_id=f"r_{i:012d}") for i in range(6)])
    install_fake_client(monkeypatch, client)

    @loop(idle_timeout=0)
    def handler():
        raise error_type("broken")

    with pytest.raises(FatalWorkerError, match="5 consecutive execution failures"):
        handler()
    assert len(client.actions) == 5
    assert len(client.claim_run_ids) == 5
    assert len(client.claims) == 1
    assert all(
        a[0] == ("unclaim" if error_type is TransientError else "fail") for a in client.actions
    )


@pytest.mark.parametrize("mode", ["success", "finish", "stale", "idle", "revoke"])
def test_failure_guard_reset_and_neutral_results(monkeypatch, mode):
    claims = [make_claim(run_id=f"r_{i:012d}", args={"index": i}) for i in range(5)]
    if mode == "idle":
        claims.insert(1, None)
    client = FakeClient(claims)
    install_fake_client(monkeypatch, client)
    monkeypatch.setattr("labtasker.worker.time.sleep", lambda _: None)
    original_fail = client._fail

    def report(**kwargs):
        if mode == "stale" and len(client.actions) == 1:
            client.actions.append(("stale", "", None))
            raise APIError(409, "stale_run", "revoked", {})
        original_fail(**kwargs)

    monkeypatch.setattr(client, "_fail", report)

    @loop(idle_timeout=1, max_consecutive_failures=2)
    def handler(index: int = TaskArg()):
        if index == 1 and mode == "revoke":
            execution_module._ACTIVE_CONTEXT.control.revoke("cancel")
        if index == 1 and mode == "success":
            return
        if index == 1 and mode == "finish":
            finish()
        raise ValueError("broken")

    with pytest.raises(FatalWorkerError):
        handler()
    assert len(client.actions) == (
        4 if mode in {"success", "finish"} else 3 if mode == "stale" else 2
    )


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "5", None])
def test_failure_limit_validated_before_client(monkeypatch, value):
    monkeypatch.setattr("labtasker.worker.Client", lambda **_: pytest.fail("Client constructed"))
    with pytest.raises(ValueError, match="positive integer"):
        loop(max_consecutive_failures=value)


def test_failure_report_retries_count_once(monkeypatch):
    client = FakeClient([make_claim(run_id=f"r_{i:012d}") for i in range(3)])
    install_fake_client(monkeypatch, client)
    monkeypatch.setattr("labtasker.worker.time.sleep", lambda _: None)
    calls = 0
    original = client._fail

    def report(**kwargs):
        nonlocal calls
        calls += 1
        if calls < 4:
            raise TransportError("unavailable")
        original(**kwargs)

    monkeypatch.setattr(client, "_fail", report)

    @loop(max_consecutive_failures=2)
    def handler():
        raise ValueError("broken")

    with pytest.raises(FatalWorkerError):
        handler()
    assert calls == 5
    assert len(client.claim_run_ids) == 2
    assert len(client.actions) == 2


def test_observation_network_failure_never_stops_healthy_loop_or_charges_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    attempted = threading.Event()

    def failed(request: httpx.Request) -> httpx.Response:
        attempted.set()
        raise httpx.ConnectTimeout("observation endpoint is offline", request=request)

    monkeypatch.setattr(
        "labtasker.observations._make_http_client",
        lambda config: httpx.Client(
            base_url="http://server/api/v2/", transport=httpx.MockTransport(failed)
        ),
    )
    client = FakeClient(
        [make_claim(), make_claim(task_id="t_BCDEFGHIJKLM", run_id="r_BCDEFGHIJKLM"), None]
    )
    install_fake_client(monkeypatch, client)
    executed = []

    @loop(idle_timeout=0, max_consecutive_failures=1)
    def handler() -> None:
        assert attempted.wait(2)
        executed.append(task_info().id)

    handler()
    assert len(executed) == 2
    assert [action[0] for action in client.actions] == ["complete", "complete"]
