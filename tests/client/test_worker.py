from __future__ import annotations

import threading
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import labtasker.execution as execution_module
from labtasker.binding import TaskArg
from labtasker.errors import APIError, ConfigError, FatalWorkerError, TransientError, TransportError
from labtasker.execution import (
    ExecutionContext,
    RunControl,
    activate_context,
    cancellation_requested,
    deactivate_context,
    finish,
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
)


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
        self.configuration = SimpleNamespace(url="http://server", queue="default", token=None)
        self.claims = deque(claims)
        self.actions: list[tuple[str, str, object]] = []
        self.claim_run_ids: list[str] = []

    def __enter__(self) -> FakeClient:
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def list_queues(self) -> list[Queue]:
        return [Queue(name="default")]

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


def test_cooperative_api_and_finish_context(tmp_path: Path) -> None:
    claimed = make_claim()
    journal = LocalRunJournal.create(
        claim=claimed,
        server_url="http://server",
        queue="default",
        route="default",
        cwd=tmp_path,
    )
    control = RunControl(force_stop_timeout=None, force_stop=lambda: None)
    results: list[dict[str, Any]] = []
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
    )
    activate_context(context)
    try:
        assert task_info() == info
        assert not cancellation_requested()
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
    finally:
        context.control.executor_done()
        deactivate_context(context)


def test_context_functions_are_strict_outside_execution() -> None:
    with pytest.raises(RuntimeError, match="No active"):
        task_info()
    with pytest.raises(RuntimeError, match="No active"):
        finish()
    finish(skip_if_no_labtasker=True)
    with pytest.raises(RuntimeError, match="active Python"):
        cancellation_requested()


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
