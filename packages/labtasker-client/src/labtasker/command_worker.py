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
from collections.abc import Iterator
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
from labtasker.tee import configure_worker_logger
from labtasker.types import JSONValue
from labtasker.validation import validate_identifier
from labtasker.worker import (
    POLL_INTERVAL_SECONDS,
    Heartbeat,
    _best_effort_unclaim,
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


def run_command_worker(
    argv: list[str],
    *,
    route: str = "default",
    queue: str | None = None,
    idle_timeout: float = 300.0,
    force_stop_timeout: float | None = None,
) -> None:
    templates = compile_argv(argv)
    normalized_route = validate_identifier(route, field="route")
    normalized_idle_timeout = _validate_idle_timeout(idle_timeout)
    normalized_force_stop_timeout = _validate_force_stop_timeout(force_stop_timeout)
    _guard_worker_topology()
    configure_worker_logger()
    with Client(queue=queue) as client:
        queue_name = client.configuration.queue
        _preflight(client, queue_name)
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
            logger.info(
                "Claimed Task %s as run %s (attempt %d, route %s).",
                claim.task.id,
                claim.run_id,
                claim.task.attempt,
                normalized_route,
            )
            _run_command_claim(
                client,
                templates,
                claim=claim,
                queue=queue_name,
                route=normalized_route,
                force_stop_timeout=normalized_force_stop_timeout,
            )


def _run_command_claim(
    client: Client,
    templates: tuple[CompiledTemplate, ...],
    *,
    claim: ClaimResponse,
    queue: str,
    route: str,
    force_stop_timeout: float | None,
) -> None:
    try:
        journal = LocalRunJournal.create(
            claim=claim,
            server_url=client.configuration.url,
            queue=queue,
            route=route,
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
            _report_command_failure(client, journal, claim, queue, "TaskBindingError", str(error))
            return
        environment = _command_environment(client, claim, journal, queue, route)
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
            _report_command_failure(
                client,
                journal,
                claim,
                queue,
                type(error).__name__,
                str(error),
            )
            return
        if control.fatal_error is not None:
            raise control.fatal_error
        if control.revoked:
            _journal_best_effort(journal.revoked)
            return
        try:
            journal = LocalRunJournal.open(journal.run_dir)
        except Exception:
            logger.warning("Could not reload command child journal.", exc_info=True)
        if journal.phase == "acknowledged" and journal.terminal_action == "complete":
            return
        if journal.phase == "reporting" and journal.terminal_action == "complete":
            result = journal.read_result()
            accepted = _report_command_complete(client, claim, queue, result)
            _finish_journal(journal, accepted)
            return
        if control.completed:
            return
        if process.returncode == 0:
            _journal_best_effort(lambda: journal.reporting("complete", {}))
            accepted = _report_command_complete(client, claim, queue, {})
            _finish_journal(journal, accepted)
            return
        message = _returncode_message(process.returncode)
        _report_command_failure(client, journal, claim, queue, "CommandProcessError", message)
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
        start_new_session=os.name == "posix",
    )
    assert process.stdout is not None
    assert process.stderr is not None
    lock = threading.Lock()
    try:
        with log_path.open("ab", buffering=0) as log:
            stdout_thread = _start_drain(process.stdout, sys.stdout, log, lock, "stdout")
            stderr_thread = _start_drain(process.stderr, sys.stderr, log, lock, "stderr")
            _wait_process(process, control, force_stop_timeout)
            stdout_thread.join()
            stderr_thread.join()
    except BaseException:
        _terminate_process_group(process, force_stop_timeout)
        raise
    return process


def _start_drain(
    source: IO[bytes],
    destination: object,
    log: IO[bytes],
    lock: threading.Lock,
    name: str,
) -> threading.Thread:
    def drain() -> None:
        while True:
            chunk = source.read(65536)
            if not chunk:
                return
            with lock:
                log.write(chunk)
            _write_bytes(destination, chunk)

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
            last_size: bytes | None = None
            output_open = True
            while output_open or process.poll() is None:
                if control.revoked and process.poll() is None:
                    _terminate_process_group(process, force_stop_timeout)
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
                    try:
                        chunk = os.read(master, 65536)
                    except OSError as error:
                        if error.errno != errno.EIO:
                            raise
                        chunk = b""
                    if chunk:
                        log.write(chunk)
                        _write_bytes(sys.stdout, chunk)
                    else:
                        output_open = False
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
) -> None:
    while process.poll() is None:
        if control.revoked:
            _terminate_process_group(process, force_stop_timeout)
            return
        with suppress(subprocess.TimeoutExpired):
            process.wait(timeout=0.1)


def _terminate_process_group(
    process: subprocess.Popen[bytes],
    force_stop_timeout: float | None,
) -> None:
    if process.poll() is not None:
        return
    if os.name == "posix":
        os.killpg(process.pid, signal.SIGTERM)
    else:
        process.terminate()
    if force_stop_timeout is None:
        process.wait()
        return
    try:
        process.wait(timeout=force_stop_timeout)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait()


def _command_environment(
    client: Client,
    claim: ClaimResponse,
    journal: LocalRunJournal,
    queue: str,
    route: str,
) -> dict[str, str]:
    environment = dict(os.environ)
    environment.update(
        {
            "LABTASKER_URL": client.configuration.url,
            "LABTASKER_QUEUE": queue,
            "LABTASKER_TASK_ID": claim.task.id,
            "LABTASKER_RUN_ID": claim.run_id,
            "LABTASKER_ROUTE": route,
            "LABTASKER_RUN_DIR": str(journal.run_dir),
        }
    )
    token = client.configuration.token
    if token is None:
        environment.pop("LABTASKER_TOKEN", None)
    else:
        environment["LABTASKER_TOKEN"] = token
    return environment


def _report_command_complete(
    client: Client,
    claim: ClaimResponse,
    queue: str,
    result: dict[str, JSONValue],
) -> bool:
    return _report_until_resolved(
        lambda: client._complete(
            task_id=claim.task.id,
            run_id=claim.run_id,
            result=result,
            queue=queue,
        )
    )


def _report_command_failure(
    client: Client,
    journal: LocalRunJournal,
    claim: ClaimResponse,
    queue: str,
    error_type: str,
    message: str,
) -> None:
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
        )
    )
    _finish_journal(journal, accepted)


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
    return os.name == "posix" and sys.stdin.isatty() and sys.stdout.isatty() and sys.stderr.isatty()


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
