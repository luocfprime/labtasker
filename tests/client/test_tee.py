from __future__ import annotations

import io
import logging
import os
import select
import signal
import threading
from pathlib import Path
from typing import cast

import pytest

import labtasker.execution as execution
from labtasker.tee import WorkerTee, _worker_log_formatter


def test_default_worker_log_format_has_utc_timestamp_level_and_component() -> None:
    record = logging.LogRecord(
        name="labtasker.worker",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Worker idle timeout reached; stopping normally.",
        args=(),
        exc_info=None,
    )
    record.created = 1_777_032_000.123
    record.msecs = 123.0

    assert _worker_log_formatter().format(record) == (
        "2026-04-24T12:00:00.123Z INFO [labtasker] Worker idle timeout reached; stopping normally."
    )


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires fork")
def test_fork_detaches_tee_and_context_without_waiting_for_parent_locks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    held = threading.Event()
    release = threading.Event()
    context = cast(execution.ExecutionContext, object())
    log_path = tmp_path / "run.log"
    read_fd, write_fd = os.pipe()
    parent_pid = os.getpid()

    class ForkSensitiveLog(io.TextIOWrapper):
        def flush(self) -> None:
            if os.getpid() != parent_pid:
                os.write(write_fd, b"unexpected-child-flush")
                return
            super().flush()

        def __del__(self) -> None:
            if os.getpid() != parent_pid:
                os.write(write_fd, b"unexpected-child-destructor")
                return
            super().__del__()

    monkeypatch.setattr("labtasker.tee.io.TextIOWrapper", ForkSensitiveLog)
    child: int | None = None
    execution.activate_context(context)
    try:
        with WorkerTee() as tee, tee.capture(log_path):
            print("parent-before", flush=True)

            def hold_parent_locks() -> None:
                with tee._lock, execution._CONTEXT_LOCK:
                    held.set()
                    release.wait()

            holder = threading.Thread(target=hold_parent_locks)
            holder.start()
            assert held.wait(2)
            try:
                child = os.fork()
                if child == 0:
                    # The at-fork callbacks must return even while another
                    # parent thread retains both locks. The child's ordinary
                    # output must no longer enter the parent's run journal.
                    try:
                        assert not execution.active_context_present()
                        assert tee._destination is None
                        print("child-output", flush=True)
                        os.write(write_fd, b"ok")
                    finally:
                        os._exit(0)
                assert select.select([read_fd], [], [], 3)[0], "fork child deadlocked"
                assert os.read(read_fd, 2) == b"ok"
                _, status = os.waitpid(child, 0)
                child = None
                assert os.waitstatus_to_exitcode(status) == 0
            finally:
                if child is not None:
                    os.kill(child, signal.SIGKILL)
                    os.waitpid(child, 0)
                release.set()
                holder.join(timeout=2)
            assert execution.active_context_present()
            print("parent-after", flush=True)
        assert log_path.read_text() == "parent-before\nparent-after\n"
    finally:
        execution.deactivate_context(context)
        os.close(read_fd)
        os.close(write_fd)


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires fork")
def test_fork_child_unwinding_capture_does_not_flush_parent_log_twice(tmp_path: Path) -> None:
    log_path = tmp_path / "run.log"
    read_fd, write_fd = os.pipe()
    child: int | None = None
    try:
        try:
            with WorkerTee() as tee, tee.capture(log_path):
                # Deliberately omit flush, including UTF-8 and a surrogate that
                # must retain the existing backslashreplace encoding behavior.
                print("parent-中文-\ud800")
                child = os.fork()
                if child == 0:
                    print("child-only")
                    raise SystemExit(0)
                assert select.select([read_fd], [], [], 3)[0], "child capture close deadlocked"
                assert os.read(read_fd, 2) == b"ok"
                _, status = os.waitpid(child, 0)
                child = None
                assert os.waitstatus_to_exitcode(status) == 0
                print("parent-after")
        except SystemExit:
            # The child has now performed normal context-manager unwinding,
            # including TextIOWrapper.close(), unlike the direct os._exit test.
            if child == 0:
                os.write(write_fd, b"ok")
                os._exit(0)
            raise
        assert log_path.read_text() == "parent-中文-\\ud800\nparent-after\n"
    finally:
        if child not in {None, 0}:
            os.kill(child, signal.SIGKILL)
            os.waitpid(child, 0)
        os.close(read_fd)
        os.close(write_fd)
