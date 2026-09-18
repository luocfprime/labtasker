from __future__ import annotations

import errno
import logging
import os
import select
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import IO, Any

from labtasker.client import Client
from labtasker.command_template import (
    CompiledTemplate,
    TemplateBindingError,
    compile_argv,
    resolve_argv,
)
from labtasker.execution import RunControl, _validate_force_stop_timeout
from labtasker.journal import LocalRunJournal
from labtasker.models import ClaimResponse
from labtasker.observations import ObservationReporter
from labtasker.tee import configure_worker_logger
from labtasker.types import JSONValue
from labtasker.validation import validate_identifier, validate_json_object
from labtasker.worker import (
    POLL_INTERVAL_SECONDS,
    Heartbeat,
    _best_effort_unclaim,
    _ExecutionResult,
    _FailureGuard,
    _finish_journal,
    _generate_run_id,
    _guard_worker_topology,
    _journal_best_effort,
    _preflight,
    _report_until_resolved,
    _safe_diagnostic_text,
    _validate_idle_timeout,
)

logger = logging.getLogger("labtasker.command_worker")
_PLATFORM = sys.platform
_POSIX_PROCESS_GROUPS = os.name == "posix" and hasattr(os, "killpg")


def run_command_worker(
    argv: list[str],
    *,
    route: str = "default",
    queue: str | None = None,
    idle_timeout: float = 300.0,
    force_stop_timeout: float | None = None,
    max_consecutive_failures: int = 5,
    metadata: dict[str, JSONValue] | None = None,
    labtasker_root: Path | None = None,
    auto_start_local_server: bool = False,
) -> None:
    guard = _FailureGuard(max_consecutive_failures)
    templates = compile_argv(argv)
    normalized_route = validate_identifier(route, field="route")
    normalized_idle_timeout = _validate_idle_timeout(idle_timeout)
    normalized_force_stop_timeout = _validate_force_stop_timeout(force_stop_timeout)
    normalized_metadata = validate_json_object(
        {} if metadata is None else metadata, field="metadata"
    )
    _guard_command_worker_platform()
    _guard_worker_topology()
    configure_worker_logger()
    with Client(
        queue=queue,
        labtasker_root=labtasker_root,
        auto_start_local_server=auto_start_local_server,
    ) as client:
        queue_name = client._configuration.queue
        _preflight(client, queue_name)
        with ObservationReporter(
            client._configuration, normalized_route, normalized_metadata
        ) as observer:
            idle_deadline: float | None = None
            while True:
                claim = client._claim(
                    route=normalized_route,
                    run_id=_generate_run_id(),
                    queue=queue_name,
                )
                if claim is None:
                    now = time.monotonic()
                    if idle_deadline is None:
                        idle_deadline = now + normalized_idle_timeout
                    if now >= idle_deadline:
                        logger.info("Worker idle timeout reached; stopping normally.")
                        return
                    time.sleep(min(POLL_INTERVAL_SECONDS, idle_deadline - now))
                    continue
                idle_deadline = None
                observer.activity(claim.task.id)
                logger.info(
                    "Claimed Task %s as run %s (attempt %d, route %s).",
                    claim.task.id,
                    claim.run_id,
                    claim.task.attempt,
                    normalized_route,
                )
                result = _run_command_claim(
                    client,
                    templates,
                    claim=claim,
                    queue=queue_name,
                    route=normalized_route,
                    force_stop_timeout=normalized_force_stop_timeout,
                    worker_id=observer.id,
                )

                guard.observe(result, claim.task.id)
                observer.activity(None)


def _guard_command_worker_platform() -> None:
    if not _POSIX_PROCESS_GROUPS:
        raise NotImplementedError(
            "Command Workers require POSIX process-group support; "
            f"platform {_PLATFORM!r} is not supported."
        )


def _run_command_claim(
    client: Client,
    templates: tuple[CompiledTemplate, ...],
    *,
    claim: ClaimResponse,
    queue: str,
    route: str,
    force_stop_timeout: float | None,
    worker_id: str,
) -> _ExecutionResult:
    try:
        journal = LocalRunJournal.create(
            claim=claim,
            endpoint=client._configuration.endpoint_dict(),
            queue=queue,
            route=route,
            labtasker_root=client._configuration.labtasker_root,
        )
    except Exception:
        _best_effort_unclaim(client, claim, queue)
        raise

    control = RunControl(force_stop_timeout=None, force_stop=lambda: None)
    heartbeat = Heartbeat(
        client,
        queue=queue,
        task_id=claim.task.id,
        run_id=claim.run_id,
        control=control,
    )
    process: subprocess.Popen[bytes] | None = None
    heartbeat.start()
    try:
        try:
            resolved = resolve_argv(templates, claim.task.args)
        except TemplateBindingError as error:
            return _report_command_failure(
                client, journal, claim, queue, "TaskBindingError", str(error), control=control
            )
        environment = _command_environment(client, claim, journal, queue, route, worker_id)
        try:
            if _interactive_terminal():
                process = _run_pty(
                    resolved,
                    environment,
                    journal.log_path,
                    control,
                    force_stop_timeout,
                )
            else:
                process = _run_pipes(
                    resolved,
                    environment,
                    journal.log_path,
                    control,
                    force_stop_timeout,
                )
        except OSError as error:
            return _report_command_failure(
                client,
                journal,
                claim,
                queue,
                type(error).__name__,
                str(error),
                control=control,
            )
        if control.fatal_error is not None:
            raise control.fatal_error
        if control.revoked:
            _journal_best_effort(journal.revoked)
            return _ExecutionResult()
        try:
            journal = LocalRunJournal.open(journal.run_dir)
        except Exception:
            logger.warning("Could not reload command child journal.", exc_info=True)
        if journal.phase == "acknowledged" and journal.terminal_action == "complete":
            return _ExecutionResult(succeeded=True)
        if journal.phase == "reporting" and journal.terminal_action == "complete":
            result = journal.read_result()
            accepted = _report_command_complete(client, claim, queue, result, control=control)
            _finish_journal(journal, accepted)
            return _ExecutionResult(succeeded=accepted)
        if control.completed:
            return _ExecutionResult(succeeded=True)
        if process.returncode == 0:
            _journal_best_effort(lambda: journal.reporting("complete", {}))
            accepted = _report_command_complete(client, claim, queue, {}, control=control)
            _finish_journal(journal, accepted)
            return _ExecutionResult(succeeded=accepted)
        message = _returncode_message(process.returncode)
        return _report_command_failure(
            client, journal, claim, queue, "CommandProcessError", message, control=control
        )
    except KeyboardInterrupt:
        if control.active:
            _best_effort_unclaim(client, claim, queue)
        raise
    finally:
        control.executor_done()
        heartbeat.stop()


def _run_pipes(
    argv: list[str],
    environment: dict[str, str],
    log_path: Path,
    control: RunControl,
    force_stop_timeout: float | None,
) -> subprocess.Popen[bytes]:
    process = subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        close_fds=True,
        start_new_session=True,
    )
    assert process.stdout is not None
    assert process.stderr is not None
    try:
        with log_path.open("ab", buffering=0) as log:
            sink = _CommandLog(log)
            stdout_thread = _start_drain(process.stdout, sys.stdout, sink, "stdout")
            stderr_thread = _start_drain(process.stderr, sys.stderr, sink, "stderr")
            _wait_process(process, control, force_stop_timeout, (stdout_thread, stderr_thread))
            stdout_thread.join()
            stderr_thread.join()
    except BaseException:
        _terminate_process_group(process, force_stop_timeout)
        raise
    return process


class _CommandLog:
    def __init__(self, stream: IO[bytes]) -> None:
        self._stream = stream
        self._lock = threading.Lock()
        self._failed = False

    def write(self, chunk: bytes) -> None:
        with self._lock:
            if self._failed:
                return
            try:
                offset = 0
                while offset < len(chunk):
                    written = self._stream.write(chunk[offset:])
                    if written is None or written <= 0:
                        raise OSError("run.log write made no progress")
                    offset += written
            except (OSError, ValueError) as error:
                self._failed = True
                logger.warning(
                    "Could not write command run.log (%s); continuing without the local log.",
                    error,
                )


def _start_drain(
    source: IO[bytes],
    destination: object,
    log: _CommandLog,
    name: str,
) -> threading.Thread:
    def drain() -> None:
        relay = True
        while True:
            chunk = os.read(source.fileno(), 65536)
            if not chunk:
                return
            log.write(chunk)
            if relay:
                try:
                    _write_bytes(destination, chunk)
                except Exception:
                    # The child must never block on a full pipe merely because the
                    # caller closed or replaced its output stream. Keep draining and
                    # journaling after live relay becomes unavailable.
                    relay = False

    thread = threading.Thread(target=drain, name=f"labtasker-command-{name}", daemon=True)
    thread.start()
    return thread


def _run_pty(
    argv: list[str],
    environment: dict[str, str],
    log_path: Path,
    control: RunControl,
    force_stop_timeout: float | None,
) -> subprocess.Popen[bytes]:
    import pty
    import termios

    master, slave = pty.openpty()
    _copy_terminal_size(sys.stdin.fileno(), slave)
    process = subprocess.Popen(
        argv,
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env=environment,
        close_fds=True,
        start_new_session=True,
    )
    os.close(slave)
    try:
        with log_path.open("ab", buffering=0) as log, _raw_terminal(sys.stdin.fileno()):
            sink = _CommandLog(log)
            last_size: bytes | None = None
            output_open = True
            relay = True

            def drain_output() -> None:
                nonlocal output_open, relay
                remaining = 65536
                while output_open and remaining and select.select([master], [], [], 0)[0]:
                    try:
                        chunk = os.read(master, remaining)
                    except OSError as error:
                        if error.errno != errno.EIO:
                            raise
                        chunk = b""
                    if chunk:
                        sink.write(chunk)
                        if relay:
                            try:
                                _write_bytes(sys.stdout, chunk)
                            except Exception:
                                relay = False
                        remaining -= len(chunk)
                    else:
                        output_open = False

            while output_open or process.poll() is None:
                if control.revoked:
                    _terminate_process_group(process, force_stop_timeout, drain_output)
                size = _terminal_size(sys.stdin.fileno())
                if size is not None and size != last_size:
                    try:
                        import fcntl

                        fcntl.ioctl(master, termios.TIOCSWINSZ, size)
                    except OSError:
                        pass
                    last_size = size
                readers = [master]
                if process.poll() is None:
                    readers.append(sys.stdin.fileno())
                ready, _, _ = select.select(readers, [], [], 0.1)
                if master in ready:
                    drain_output()
                if sys.stdin.fileno() in ready:
                    chunk = os.read(sys.stdin.fileno(), 65536)
                    if chunk:
                        os.write(master, chunk)
            process.wait()
    except BaseException:
        _terminate_process_group(process, force_stop_timeout)
        raise
    finally:
        os.close(master)
    return process


def _wait_process(
    process: subprocess.Popen[bytes],
    control: RunControl,
    force_stop_timeout: float | None,
    output_threads: tuple[threading.Thread, threading.Thread],
) -> None:
    # A launcher can exit while its descendants still own the output pipes.
    # Continue observing cancellation until that remaining output has drained.
    while process.poll() is None or any(thread.is_alive() for thread in output_threads):
        if control.revoked:
            _terminate_process_group(process, force_stop_timeout)
            return
        if process.poll() is None:
            with suppress(subprocess.TimeoutExpired):
                process.wait(timeout=0.1)
        else:
            time.sleep(0.1)


def _terminate_process_group(
    process: subprocess.Popen[bytes],
    force_stop_timeout: float | None,
    drain_output: Callable[[], None] | None = None,
) -> None:
    deadline = None if force_stop_timeout is None else time.monotonic() + force_stop_timeout
    _signal_process_group(process.pid, signal.SIGTERM)
    # Waiting only for the launcher loses surviving ranks when SIGTERM makes
    # the launcher exit first. Reap it, but retain the group's original deadline.
    while True:
        # PTY output has no separate reader thread. Keep draining while a
        # cooperative signal handler writes cleanup output before exiting.
        if drain_output is not None:
            drain_output()
        process.poll()
        if not _process_group_alive(process.pid):
            break
        if deadline is not None and time.monotonic() >= deadline:
            _signal_process_group(process.pid, signal.SIGKILL)
            break
        time.sleep(0.01 if deadline is None else min(0.01, max(0, deadline - time.monotonic())))
    process.wait()


def _process_group_alive(group_id: int) -> bool:
    try:
        os.killpg(group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        if _PLATFORM != "darwin":
            raise
    if _PLATFORM == "darwin":
        # Darwin can report EPERM rather than ESRCH for a zombie-only group.
        # Its built-in ps exposes process states without depending on /proc.
        try:
            result = subprocess.run(
                ["/bin/ps", "-axo", "pgid=,stat="],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=True,
                timeout=1,
            )
            return any(
                int(fields[0]) == group_id and not fields[1].startswith("Z")
                for line in result.stdout.splitlines()
                if (fields := line.split())
            )
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            return True
    if _PLATFORM != "linux":
        return True
    # Linux containers may retain orphan zombies indefinitely when PID 1 does
    # not reap. They still satisfy killpg(0), but cannot execute or receive a
    # signal. Keep waiting for actual group members, including those that have
    # closed their output streams; on inspection errors remain conservative.
    try:
        for entry in Path("/proc").iterdir():
            if not entry.name.isdecimal():
                continue
            try:
                fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
            except FileNotFoundError:
                continue
            if int(fields[2]) == group_id and fields[0] not in {"Z", "X"}:
                return True
    except (OSError, ValueError, IndexError):
        return True
    return False


def _signal_process_group(group_id: int, requested_signal: signal.Signals) -> None:
    try:
        os.killpg(group_id, requested_signal)
    except ProcessLookupError:
        pass
    except PermissionError:
        if _process_group_alive(group_id):
            raise


def _command_environment(
    client: Client,
    claim: ClaimResponse,
    journal: LocalRunJournal,
    queue: str,
    route: str,
    worker_id: str,
) -> dict[str, str]:
    environment = dict(os.environ)
    environment.update(
        {
            "LABTASKER_QUEUE": queue,
            "LABTASKER_TASK_ID": claim.task.id,
            "LABTASKER_RUN_ID": claim.run_id,
            "LABTASKER_ROUTE": route,
            "LABTASKER_RUN_DIR": str(journal.run_dir),
            "LABTASKER_WORKER_ID": worker_id,
        }
    )
    configuration = client._configuration
    if configuration.url is not None:
        assert configuration.url is not None
        environment["LABTASKER_URL"] = configuration.url
        environment.pop("LABTASKER_SOCKET", None)
    else:
        assert configuration.socket is not None
        environment["LABTASKER_SOCKET"] = str(configuration.socket)
        environment.pop("LABTASKER_URL", None)
    environment.pop("LABTASKER_ROOT", None)
    environment.pop("LABTASKER_LOCAL_DIRECTORY", None)
    token = configuration.token
    if token is None or configuration.url is None:
        environment.pop("LABTASKER_TOKEN", None)
    else:
        environment["LABTASKER_TOKEN"] = token
    return environment


def _report_command_complete(
    client: Client,
    claim: ClaimResponse,
    queue: str,
    result: dict[str, JSONValue],
    *,
    control: RunControl | None = None,
) -> bool:
    return _report_until_resolved(
        lambda: client._complete(
            task_id=claim.task.id,
            run_id=claim.run_id,
            result=result,
            queue=queue,
        ),
        control=control,
    )


def _report_command_failure(
    client: Client,
    journal: LocalRunJournal,
    claim: ClaimResponse,
    queue: str,
    error_type: str,
    message: str,
    *,
    control: RunControl | None = None,
) -> _ExecutionResult:
    error_type = _safe_diagnostic_text(error_type)
    message = _safe_diagnostic_text(message)
    logger.error("%s: %s", error_type, message)
    payload: dict[str, JSONValue] = {
        "type": error_type,
        "message": message,
        "traceback": None,
    }
    _journal_best_effort(lambda: journal.reporting("fail", payload))
    accepted = _report_until_resolved(
        lambda: client._fail(
            task_id=claim.task.id,
            run_id=claim.run_id,
            error_type=error_type,
            message=message,
            traceback=None,
            queue=queue,
        ),
        control=control,
    )
    _finish_journal(journal, accepted)

    return _ExecutionResult(failure=error_type if accepted else None)


def _returncode_message(returncode: int) -> str:
    if returncode < 0:
        return f"Command terminated by signal {-returncode}."
    return f"Command exited with status {returncode}."


def _write_bytes(destination: Any, value: bytes) -> None:
    buffer = getattr(destination, "buffer", None)
    if buffer is not None:
        buffer.write(value)
        buffer.flush()
        return
    destination.write(value.decode("utf-8", errors="backslashreplace"))
    destination.flush()


def _interactive_terminal() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty() and sys.stderr.isatty()


def _terminal_size(descriptor: int) -> bytes | None:
    try:
        import fcntl
        import termios

        return fcntl.ioctl(descriptor, termios.TIOCGWINSZ, b"\0" * 8)
    except OSError:
        return None


def _copy_terminal_size(source: int, destination: int) -> None:
    import termios

    size = _terminal_size(source)
    if size is None:
        return
    try:
        import fcntl

        fcntl.ioctl(destination, termios.TIOCSWINSZ, size)
    except OSError:
        pass


@contextmanager
def _raw_terminal(descriptor: int) -> Iterator[None]:
    import termios
    import tty

    attributes = termios.tcgetattr(descriptor)
    tty.setraw(descriptor)
    try:
        yield
    finally:
        termios.tcsetattr(descriptor, termios.TCSADRAIN, attributes)
