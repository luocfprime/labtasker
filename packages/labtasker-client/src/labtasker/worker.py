from __future__ import annotations

import functools
import json
import logging
import math
import os
import secrets
import threading
import time
import traceback as traceback_module
from collections.abc import Callable
from typing import ParamSpec, TypeVar, cast

from labtasker.binding import CompiledBinding, compile_binding
from labtasker.client import Client
from labtasker.errors import (
    APIError,
    ConfigError,
    FatalWorkerError,
    TransientError,
    TransportError,
)
from labtasker.execution import (
    ExecutionContext,
    RunControl,
    _validate_force_stop_timeout,
    activate_context,
    active_context_present,
    deactivate_context,
)
from labtasker.journal import LocalRunJournal
from labtasker.models import ClaimResponse, TaskInfo
from labtasker.tee import WorkerTee, configure_worker_logger
from labtasker.types import JSONValue
from labtasker.validation import RequestValidationError, validate_identifier

P = ParamSpec("P")
R = TypeVar("R")
HEARTBEAT_INTERVAL_SECONDS = 60.0
POLL_INTERVAL_SECONDS = 1.0
TERMINAL_BACKOFF_SECONDS = (0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0)
MAX_REQUEST_BYTES = 1024 * 1024
logger = logging.getLogger("labtasker.worker")


class Heartbeat:
    def __init__(
        self,
        client: Client,
        *,
        queue: str,
        task_id: str,
        run_id: str,
        control: RunControl,
    ) -> None:
        self._client = client
        self._queue = queue
        self._task_id = task_id
        self._run_id = run_id
        self._control = control
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name=f"labtasker-heartbeat-{run_id}",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join()

    def _run(self) -> None:
        while not self._stop.wait(HEARTBEAT_INTERVAL_SECONDS):
            try:
                self._client._heartbeat(
                    task_id=self._task_id,
                    run_id=self._run_id,
                    queue=self._queue,
                )
            except APIError as error:
                if _retryable_api_error(error):
                    logger.warning("Heartbeat Server error; retrying: %s", error.message)
                    continue
                if error.code == "run_finalized" and error.details.get("action") == "complete":
                    self._control.complete()
                elif error.code in {"run_finalized", "stale_run"}:
                    self._control.revoke(str(error.details.get("action", error.code)))
                else:
                    self._control.fail(error)
                return
            except TransportError as error:
                logger.warning("Heartbeat transport error; retrying: %s", error)


def loop(
    *,
    route: str = "default",
    queue: str | None = None,
    idle_timeout: float = 300.0,
    force_stop_timeout: float | None = None,
) -> Callable[[Callable[P, R]], Callable[P, None]]:
    normalized_route = validate_identifier(route, field="route")
    normalized_idle_timeout = _validate_idle_timeout(idle_timeout)
    normalized_force_stop_timeout = _validate_force_stop_timeout(force_stop_timeout)

    def decorate(function: Callable[P, R]) -> Callable[P, None]:
        binding = compile_binding(function)

        @functools.wraps(function)
        def run(*args: P.args, **kwargs: P.kwargs) -> None:
            binding.validate_invocation(
                cast(tuple[object, ...], args),
                cast(dict[str, object], kwargs),
            )
            _run_python_worker(
                binding,
                cast(tuple[object, ...], args),
                cast(dict[str, object], kwargs),
                route=normalized_route,
                queue=queue,
                idle_timeout=normalized_idle_timeout,
                force_stop_timeout=normalized_force_stop_timeout,
            )

        return run

    return decorate


def _run_python_worker(
    binding: CompiledBinding,
    startup_args: tuple[object, ...],
    startup_kwargs: dict[str, object],
    *,
    route: str,
    queue: str | None,
    idle_timeout: float,
    force_stop_timeout: float | None,
) -> None:
    _guard_worker_topology()
    with Client(queue=queue) as client, WorkerTee() as tee:
        configure_worker_logger()
        queue_name = client.configuration.queue
        _preflight(client, queue_name)
        idle_deadline: float | None = None
        while True:
            claim = client._claim(route=route, run_id=_generate_run_id(), queue=queue_name)
            if claim is None:
                now = time.monotonic()
                if idle_deadline is None:
                    idle_deadline = now + idle_timeout
                if now >= idle_deadline:
                    logger.info("Worker idle timeout reached; stopping normally.")
                    return
                time.sleep(min(POLL_INTERVAL_SECONDS, idle_deadline - now))
                continue
            idle_deadline = None
            logger.info(
                "Claimed Task %s as run %s (attempt %d, route %s).",
                claim.task.id,
                claim.run_id,
                claim.task.attempt,
                route,
            )
            _run_python_claim(
                client,
                tee,
                binding,
                startup_args,
                startup_kwargs,
                claim=claim,
                queue=queue_name,
                route=route,
                force_stop_timeout=force_stop_timeout,
            )


def _run_python_claim(
    client: Client,
    tee: WorkerTee,
    binding: CompiledBinding,
    startup_args: tuple[object, ...],
    startup_kwargs: dict[str, object],
    *,
    claim: ClaimResponse,
    queue: str,
    route: str,
    force_stop_timeout: float | None,
) -> None:
    try:
        journal = LocalRunJournal.create(
            claim=claim,
            endpoint=client.configuration.endpoint_dict(),
            queue=queue,
            route=route,
        )
    except Exception:
        try:
            client._unclaim(task_id=claim.task.id, run_id=claim.run_id, queue=queue)
        except Exception:
            logger.exception("Could not return Task after local journal setup failed.")
        raise
    control = RunControl(force_stop_timeout=force_stop_timeout, force_stop=_force_stop_process)

    def report_complete(result: dict[str, JSONValue]) -> bool:
        accepted = report_complete_until_resolved(
            client,
            queue=queue,
            task_id=claim.task.id,
            run_id=claim.run_id,
            result=result,
        )
        if accepted:
            control.complete()
        else:
            control.revoke("stale_run")
        return accepted

    info = TaskInfo(
        **claim.task.model_dump(),
        run_id=claim.run_id,
        run_dir=journal.run_dir,
    )
    context = ExecutionContext(
        info=info,
        kind="python",
        journal=journal,
        reporter=report_complete,
        control=control,
    )
    heartbeat = Heartbeat(
        client,
        queue=queue,
        task_id=claim.task.id,
        run_id=claim.run_id,
        control=control,
    )
    activate_context(context)
    heartbeat.start()
    fatal: FatalWorkerError | None = None
    try:
        with tee.capture(journal.log_path):
            try:
                binding.invoke(claim.task.args, startup_args, startup_kwargs)
            except FatalWorkerError as error:
                fatal = error
                logger.critical("Fatal Worker failure for Task %s.", claim.task.id, exc_info=True)
                if control.active and not context.finished:
                    _report_failure(client, journal, claim, queue, error)
            except TransientError as error:
                logger.warning("%s: %s", type(error).__name__, error)
                if control.active and not context.finished:
                    _report_unclaim(client, journal, claim, queue)
            except Exception as error:
                logger.exception("Task %s failed.", claim.task.id)
                if control.active and not context.finished:
                    _report_failure(client, journal, claim, queue, error)
            else:
                if control.active and not context.finished:
                    _report_complete(client, journal, claim, queue, {})
    except KeyboardInterrupt:
        if control.active and not context.finished:
            _best_effort_unclaim(client, claim, queue)
        raise
    finally:
        control.executor_done()
        heartbeat.stop()
        deactivate_context(context)
    if fatal is not None:
        raise fatal
    if control.fatal_error is not None:
        raise control.fatal_error


def report_complete_until_resolved(
    client: Client,
    *,
    queue: str,
    task_id: str,
    run_id: str,
    result: dict[str, JSONValue],
) -> bool:
    return _report_until_resolved(
        lambda: client._complete(
            task_id=task_id,
            run_id=run_id,
            result=result,
            queue=queue,
        )
    )


def _report_complete(
    client: Client,
    journal: LocalRunJournal,
    claim: ClaimResponse,
    queue: str,
    result: dict[str, JSONValue],
) -> None:
    _journal_best_effort(lambda: journal.reporting("complete", result))
    accepted = report_complete_until_resolved(
        client,
        queue=queue,
        task_id=claim.task.id,
        run_id=claim.run_id,
        result=result,
    )
    _finish_journal(journal, accepted)


def _report_unclaim(
    client: Client,
    journal: LocalRunJournal,
    claim: ClaimResponse,
    queue: str,
) -> None:
    _journal_best_effort(lambda: journal.reporting("unclaim"))
    accepted = _report_until_resolved(
        lambda: client._unclaim(task_id=claim.task.id, run_id=claim.run_id, queue=queue)
    )
    _finish_journal(journal, accepted)


def _report_failure(
    client: Client,
    journal: LocalRunJournal,
    claim: ClaimResponse,
    queue: str,
    error: Exception,
) -> None:
    error_type, message, traceback = _failure_diagnostic(error, claim.run_id)
    payload: dict[str, JSONValue] = {
        "type": error_type,
        "message": message,
        "traceback": traceback,
    }
    _journal_best_effort(lambda: journal.reporting("fail", payload))
    accepted = _report_until_resolved(
        lambda: client._fail(
            task_id=claim.task.id,
            run_id=claim.run_id,
            error_type=error_type,
            message=message,
            traceback=traceback,
            queue=queue,
        )
    )
    _finish_journal(journal, accepted)


def _report_until_resolved(operation: Callable[[], None]) -> bool:
    attempt = 0
    while True:
        try:
            operation()
            return True
        except APIError as error:
            if error.code in {"stale_run", "run_finalized"}:
                return False
            if not _retryable_api_error(error):
                raise
            logger.warning("Terminal report Server error; retrying: %s", error.message)
        except TransportError as error:
            logger.warning("Terminal report transport error; retrying: %s", error)
        delay = TERMINAL_BACKOFF_SECONDS[min(attempt, len(TERMINAL_BACKOFF_SECONDS) - 1)]
        attempt += 1
        time.sleep(delay)


def _failure_diagnostic(error: Exception, run_id: str) -> tuple[str, str, str | None]:
    error_type = _safe_diagnostic_text(type(error).__name__)
    message = _safe_diagnostic_text(str(error))
    formatted = _safe_diagnostic_text(
        "".join(traceback_module.format_exception(type(error), error, error.__traceback__))
    )
    body = {
        "run_id": run_id,
        "error": {"type": error_type, "message": message, "traceback": formatted},
    }
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > MAX_REQUEST_BYTES:
        return (
            error_type,
            "Failure diagnostics exceeded the 1 MiB limit; see local run.log.",
            None,
        )
    return error_type, message, formatted


def _safe_diagnostic_text(value: str) -> str:
    return "".join(
        "\N{REPLACEMENT CHARACTER}" if 0xD800 <= ord(character) <= 0xDFFF else character
        for character in value
    )


def _finish_journal(journal: LocalRunJournal, accepted: bool) -> None:
    _journal_best_effort(journal.acknowledged if accepted else journal.revoked)


def _journal_best_effort(operation: Callable[[], None]) -> None:
    try:
        operation()
    except Exception:
        logger.warning("Could not update local run journal.", exc_info=True)


def _best_effort_unclaim(client: Client, claim: ClaimResponse, queue: str) -> None:
    try:
        client._unclaim(task_id=claim.task.id, run_id=claim.run_id, queue=queue)
    except Exception:
        logger.warning("Could not return interrupted Task; heartbeat recovery will apply.")


def _preflight(client: Client, queue: str) -> None:
    client._health()
    if queue not in {item.name for item in client.list_queues()}:
        raise ConfigError(
            "invalid_config",
            f"Queue {queue!r} does not exist.",
            {"queue": queue},
        )


def _guard_worker_topology() -> None:
    if active_context_present() or os.environ.get("LABTASKER_RUN_ID") is not None:
        raise ConfigError(
            "invalid_config",
            "A nested Worker cannot start inside an active Labtasker execution.",
            {},
        )
    world_size = os.environ.get("WORLD_SIZE")
    rank_present = os.environ.get("RANK") is not None or os.environ.get("LOCAL_RANK") is not None
    try:
        distributed = world_size is not None and int(world_size) > 1
    except ValueError:
        distributed = False
    if distributed and rank_present:
        raise ConfigError(
            "invalid_config",
            "Start labtasker loop outside torchrun or Accelerate, not inside each rank.",
            {"WORLD_SIZE": world_size},
        )


def _validate_idle_timeout(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RequestValidationError("idle_timeout must be a finite non-negative number.")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        raise RequestValidationError("idle_timeout must be a finite non-negative number.")
    return normalized


def _retryable_api_error(error: APIError) -> bool:
    return error.status_code >= 500 or error.code == "database_busy"


def _generate_run_id() -> str:
    return f"r_{secrets.token_urlsafe(9)}"


def _force_stop_process() -> None:
    os._exit(1)
