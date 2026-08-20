from __future__ import annotations

import os
import threading
import time
import warnings
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from labtasker.client import Client
from labtasker.errors import ConfigError
from labtasker.journal import LocalRunJournal
from labtasker.models import Task, TaskInfo
from labtasker.types import JSONValue
from labtasker.validation import RequestValidationError, validate_json_object

CompletionReporter = Callable[[dict[str, JSONValue]], bool]
ContextKind = Literal["python", "command"]


class RunControl:
    def __init__(
        self,
        *,
        force_stop_timeout: float | None,
        force_stop: Callable[[], None],
    ) -> None:
        self._condition = threading.Condition()
        self._force_stop_timeout = force_stop_timeout
        self._force_stop = force_stop
        self._revoked_at: float | None = None
        self._revoked_action: str | None = None
        self._fatal_error: Exception | None = None
        self._completed = False
        self._executor_done = False
        self._watchdog = threading.Thread(
            target=self._watch_force_stop,
            name="labtasker-force-stop",
            daemon=True,
        )
        self._watchdog.start()

    @property
    def revoked(self) -> bool:
        with self._condition:
            return self._revoked_at is not None

    @property
    def revoked_action(self) -> str | None:
        with self._condition:
            return self._revoked_action

    @property
    def completed(self) -> bool:
        with self._condition:
            return self._completed

    @property
    def fatal_error(self) -> Exception | None:
        with self._condition:
            return self._fatal_error

    @property
    def active(self) -> bool:
        with self._condition:
            return self._revoked_at is None and not self._completed

    def revoke(self, action: str) -> None:
        with self._condition:
            if self._completed or self._revoked_at is not None:
                return
            self._revoked_at = time.monotonic()
            self._revoked_action = action
            self._condition.notify_all()

    def fail(self, error: Exception) -> None:
        with self._condition:
            if self._completed or self._revoked_at is not None:
                return
            self._fatal_error = error
            self._revoked_at = time.monotonic()
            self._revoked_action = error.__class__.__name__
            self._condition.notify_all()

    def complete(self) -> None:
        with self._condition:
            if self._revoked_at is None:
                self._completed = True
            self._condition.notify_all()

    def executor_done(self) -> None:
        with self._condition:
            self._executor_done = True
            self._condition.notify_all()

    def set_force_stop_timeout(self, value: float | None) -> None:
        with self._condition:
            if self._completed:
                raise RuntimeError("The current run has already completed.")
            self._force_stop_timeout = value
            self._condition.notify_all()

    def _watch_force_stop(self) -> None:
        while True:
            with self._condition:
                if self._executor_done or self._completed:
                    return
                if self._revoked_at is None or self._force_stop_timeout is None:
                    self._condition.wait()
                    continue
                deadline = self._revoked_at + self._force_stop_timeout
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    self._condition.wait(remaining)
                    continue
            self._force_stop()
            return


class ExecutionContext:
    def __init__(
        self,
        *,
        info: TaskInfo,
        kind: ContextKind,
        journal: LocalRunJournal,
        reporter: CompletionReporter,
        control: RunControl | None,
    ) -> None:
        self.info = info
        self.kind = kind
        self.journal = journal
        self.reporter = reporter
        self.control = control
        self._lock = threading.Lock()
        self._finish_started = False
        self._finished = False

    @property
    def finished(self) -> bool:
        with self._lock:
            return self._finished

    def finish(self, result: dict[str, JSONValue]) -> None:
        with self._lock:
            if self._finish_started:
                raise RuntimeError("finish() has already been called for this execution.")
            self._finish_started = True
        _best_effort_journal(lambda: self.journal.reporting("complete", result))
        accepted = self.reporter(result)
        if not accepted:
            _best_effort_journal(self.journal.revoked)
            raise RuntimeError("The current run was revoked before finish() could complete it.")
        with self._lock:
            self._finished = True
        if self.control is not None:
            self.control.complete()
        _best_effort_journal(self.journal.acknowledged)


_CONTEXT_LOCK = threading.RLock()
_ACTIVE_CONTEXT: ExecutionContext | None = None
_ENV_CONTEXT: ExecutionContext | None = None
_FORK_HOOK_INSTALLED = False


def activate_context(context: ExecutionContext) -> None:
    global _ACTIVE_CONTEXT, _FORK_HOOK_INSTALLED
    with _CONTEXT_LOCK:
        if _ACTIVE_CONTEXT is not None:
            raise RuntimeError("A Labtasker execution context is already active.")
        if not _FORK_HOOK_INSTALLED and hasattr(os, "register_at_fork"):
            os.register_at_fork(after_in_child=_clear_after_fork)
            _FORK_HOOK_INSTALLED = True
        _ACTIVE_CONTEXT = context


def deactivate_context(context: ExecutionContext) -> None:
    global _ACTIVE_CONTEXT
    with _CONTEXT_LOCK:
        if _ACTIVE_CONTEXT is context:
            _ACTIVE_CONTEXT = None


def active_context_present() -> bool:
    with _CONTEXT_LOCK:
        return _ACTIVE_CONTEXT is not None


def task_info() -> TaskInfo:
    context = _get_context()
    if context is None:
        raise RuntimeError("No active Labtasker Task execution is available.")
    return context.info


def finish(
    result: dict[str, JSONValue] | None = None,
    *,
    skip_if_no_labtasker: bool = False,
) -> None:
    context = _get_context()
    if context is None:
        if skip_if_no_labtasker:
            return
        raise RuntimeError("No active Labtasker Task execution is available.")
    normalized = validate_json_object({} if result is None else result, field="result")
    context.finish(normalized)


def cancellation_requested() -> bool:
    context = _require_python_context()
    if context.finished or context.control is None:
        return False
    return context.control.revoked


def set_force_stop_timeout(seconds: float | None) -> None:
    context = _require_python_context()
    if context.finished or context.control is None:
        raise RuntimeError("The current run is no longer cancellable.")
    context.control.set_force_stop_timeout(_validate_force_stop_timeout(seconds))


def _require_python_context() -> ExecutionContext:
    context = _get_context()
    if context is None or context.kind != "python":
        raise RuntimeError("This function requires an active Python Worker execution.")
    return context


def _get_context() -> ExecutionContext | None:
    with _CONTEXT_LOCK:
        if _ACTIVE_CONTEXT is not None:
            return _ACTIVE_CONTEXT
    return _load_environment_context()


def _load_environment_context() -> ExecutionContext | None:
    global _ENV_CONTEXT
    with _CONTEXT_LOCK:
        if _ENV_CONTEXT is not None:
            return _ENV_CONTEXT
        names = {
            "url": "LABTASKER_URL",
            "queue": "LABTASKER_QUEUE",
            "task_id": "LABTASKER_TASK_ID",
            "run_id": "LABTASKER_RUN_ID",
            "route": "LABTASKER_ROUTE",
            "run_dir": "LABTASKER_RUN_DIR",
        }
        values = {field: os.environ.get(name) for field, name in names.items()}
        execution_fields = {"task_id", "run_id", "route", "run_dir"}
        present = {field for field, value in values.items() if value is not None}
        if not (present & execution_fields):
            return None
        if present != set(names):
            raise ConfigError(
                "invalid_config",
                "Inherited Labtasker execution context is incomplete.",
                {"missing": sorted(set(names) - present)},
            )
        run_dir = Path(values["run_dir"] or "")
        if not run_dir.is_absolute():
            raise ConfigError(
                "invalid_config",
                "LABTASKER_RUN_DIR must be absolute.",
                {"field": "LABTASKER_RUN_DIR"},
            )
        try:
            task = Task.model_validate_json((run_dir / "task.json").read_bytes(), strict=True)
            run_id = values["run_id"] or ""
            journal = LocalRunJournal.open(run_dir)
            if (
                task.id != values["task_id"]
                or task.queue != values["queue"]
                or journal.server_url != values["url"]
                or journal.queue != values["queue"]
                or journal.task_id != values["task_id"]
                or journal.run_id != run_id
                or journal.route != values["route"]
            ):
                raise ValueError("execution environment does not match the local journal")
            info = TaskInfo(**task.model_dump(), run_id=run_id, run_dir=journal.run_dir)
        except Exception as error:
            raise ConfigError(
                "invalid_config",
                "Inherited Labtasker execution context could not be loaded.",
                {"source": str(run_dir)},
            ) from error
        client = Client(
            url=values["url"],
            token=os.environ.get("LABTASKER_TOKEN"),
            queue=values["queue"],
        )

        def report(result: dict[str, JSONValue]) -> bool:
            from labtasker.worker import report_complete_until_resolved

            return report_complete_until_resolved(
                client,
                queue=values["queue"] or "",
                task_id=values["task_id"] or "",
                run_id=run_id,
                result=result,
            )

        _ENV_CONTEXT = ExecutionContext(
            info=info,
            kind="command",
            journal=journal,
            reporter=report,
            control=None,
        )
        return _ENV_CONTEXT


def _best_effort_journal(operation: Callable[[], None]) -> None:
    try:
        operation()
    except Exception as error:
        warnings.warn(
            f"Labtasker could not update the local run journal: {error}",
            RuntimeWarning,
            stacklevel=3,
        )


def _validate_force_stop_timeout(value: float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RequestValidationError(
            "force_stop_timeout must be a finite non-negative number or None"
        )
    normalized = float(value)
    if not 0 <= normalized < float("inf"):
        raise RequestValidationError(
            "force_stop_timeout must be a finite non-negative number or None"
        )
    return normalized


def _clear_after_fork() -> None:
    global _ACTIVE_CONTEXT, _ENV_CONTEXT
    _ACTIVE_CONTEXT = None
    _ENV_CONTEXT = None
