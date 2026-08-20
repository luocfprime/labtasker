from __future__ import annotations

import logging
import os
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TextIO, cast

_ACTIVE_TEE: WorkerTee | None = None
_FORK_HOOK_INSTALLED = False


class _TeeStream:
    def __init__(self, original: TextIO, lock: threading.RLock) -> None:
        self._original = original
        self._lock = lock
        self._destination: TextIO | None = None

    def write(self, value: str) -> int:
        with self._lock:
            written = self._original.write(value)
            if self._destination is not None:
                self._destination.write(value)
            return written

    def flush(self) -> None:
        with self._lock:
            self._original.flush()
            if self._destination is not None:
                self._destination.flush()

    def set_destination(self, destination: TextIO | None) -> None:
        with self._lock:
            self._destination = destination

    def __getattr__(self, name: str) -> object:
        return getattr(self._original, name)


class WorkerTee:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._stdout: _TeeStream | None = None
        self._stderr: _TeeStream | None = None
        self._original_stdout: TextIO | None = None
        self._original_stderr: TextIO | None = None
        self._destination: TextIO | None = None

    def __enter__(self) -> WorkerTee:
        global _ACTIVE_TEE, _FORK_HOOK_INSTALLED
        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr
        self._stdout = _TeeStream(sys.stdout, self._lock)
        self._stderr = _TeeStream(sys.stderr, self._lock)
        sys.stdout = cast(TextIO, self._stdout)
        sys.stderr = cast(TextIO, self._stderr)
        if not _FORK_HOOK_INSTALLED and hasattr(os, "register_at_fork"):
            os.register_at_fork(after_in_child=_clear_tee_after_fork)
            _FORK_HOOK_INSTALLED = True
        _ACTIVE_TEE = self
        return self

    def __exit__(self, *_: object) -> None:
        global _ACTIVE_TEE
        self.clear_destination()
        if self._original_stdout is not None:
            sys.stdout = self._original_stdout
        if self._original_stderr is not None:
            sys.stderr = self._original_stderr
        if _ACTIVE_TEE is self:
            _ACTIVE_TEE = None

    @contextmanager
    def capture(self, path: Path) -> Iterator[None]:
        if self._destination is not None:
            raise RuntimeError("A Worker log destination is already active.")
        with path.open("a", encoding="utf-8", errors="backslashreplace") as destination:
            self._destination = destination
            if self._stdout is not None:
                self._stdout.set_destination(destination)
            if self._stderr is not None:
                self._stderr.set_destination(destination)
            try:
                yield
            finally:
                self.clear_destination()

    def clear_destination(self) -> None:
        if self._stdout is not None:
            self._stdout.set_destination(None)
        if self._stderr is not None:
            self._stderr.set_destination(None)
        if self._destination is not None:
            self._destination.flush()
            self._destination = None


def configure_worker_logger() -> logging.Logger:
    logger = logging.getLogger("labtasker")
    if not logger.hasHandlers():
        handler = logging.StreamHandler()
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        if logger.level == logging.NOTSET:
            logger.setLevel(logging.INFO)
    return logger


def _clear_tee_after_fork() -> None:
    if _ACTIVE_TEE is not None:
        _ACTIVE_TEE.clear_destination()
