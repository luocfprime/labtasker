import contextlib
import contextvars
import io
import os
import re
import sys
import threading
import warnings
from pathlib import Path
from typing import Iterable, List, Optional, Union

from loguru import logger  # noqa
from rich.console import Console

stdout_console = Console(markup=True)
stderr_console = Console(markup=True, stderr=True)

LOGGER_FORMAT = (
    "<green>[{time:YYYY-MM-DD HH:mm:ss.SSS}]</green>"
    "[<level>{level: <8}</level>]"
    "[<cyan>{name}</cyan>]"
    " - <level>{message}</level>"
)

DEBUG_LOGGER_FORMAT = (
    "<green>[{time:YYYY-MM-DD HH:mm:ss.SSS}]</green>"
    "[<level>{level: <8}</level>]"
    "[<cyan>{name}</cyan>]"
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
)

_verbose = False
_logger_handle = None

# Context variable for original stdout/stderr
original_stdout_var = contextvars.ContextVar("original_stdout", default=sys.stdout)
original_stderr_var = contextvars.ContextVar("original_stderr", default=sys.stderr)

# Context variable for stdout tee destinations
stdout_tee_outputs_var = contextvars.ContextVar("stdout_tee_outputs", default=[])

# Context variable for stderr tee destinations
stderr_tee_outputs_var = contextvars.ContextVar("stderr_tee_outputs", default=[])

# Global tee stream instances
_stdout_tee_stream = None
_stderr_tee_stream = None
_setup_lock = threading.Lock()


class TeeStream(io.TextIOBase):
    """
    A stateless stream that duplicates writes to multiple destinations based on the current context.
    """

    def __init__(self, original_stream, outputs_var):
        super().__init__()
        self.original_stream = original_stream
        self.outputs_var = outputs_var
        self.lock = threading.RLock()

    def write(self, text):
        with self.lock:
            # Always write to original stream
            result = self.original_stream.write(text)

            # Write to all tee outputs in current context
            for output in self.outputs_var.get():
                if output != self.original_stream:  # Avoid duplicate writes
                    try:
                        output.write(text)
                    except ValueError as e:
                        if "I/O operation on closed file" in str(e):
                            warnings.warn(
                                "Attempted to write to a closed file",
                                RuntimeWarning,
                            )
                        else:
                            raise

            return result

    def flush(self):
        with self.lock:
            # Flush original stream
            self.original_stream.flush()

            # Flush all tee outputs in current context
            for output in self.outputs_var.get():
                if output != self.original_stream:
                    try:
                        if hasattr(output, "flush"):
                            output.flush()
                    except ValueError as e:
                        if "I/O operation on closed file" not in str(e):
                            raise

    # Standard file methods proxied to original stream
    def close(self) -> None:
        return self.original_stream.close()

    def fileno(self) -> int:
        return self.original_stream.fileno()

    def isatty(self) -> bool:
        return self.original_stream.isatty()

    def readable(self) -> bool:
        return self.original_stream.readable()

    def read(self, size: int = -1) -> str:  # type: ignore[override]
        return self.original_stream.read(size)

    def readlines(self, hint: int = -1) -> List[str]:  # type: ignore[override]
        return self.original_stream.readlines(hint)

    def seek(self, offset: int, whence: int = 0) -> int:
        return self.original_stream.seek(offset, whence)

    def seekable(self) -> bool:
        return self.original_stream.seekable()

    def tell(self) -> int:
        return self.original_stream.tell()

    def truncate(self, size: Optional[int] = None) -> int:
        if size is None:
            return self.original_stream.truncate()
        return self.original_stream.truncate(size)

    def writable(self) -> bool:
        return self.original_stream.writable()

    def writelines(self, lines: Iterable[str]) -> None:  # type: ignore[override]
        # First write to original stream
        self.original_stream.writelines(lines)

        # Then write to all tee outputs
        with self.lock:
            for output in self.outputs_var.get():
                if output != self.original_stream:
                    try:
                        output.writelines(lines)
                    except ValueError as e:
                        if "I/O operation on closed file" in str(e):
                            warnings.warn(
                                "Attempted to write to a closed file",
                                RuntimeWarning,
                            )
                        else:
                            raise

    def readline(self, size: Optional[int] = -1) -> str:  # type: ignore[override]
        return self.original_stream.readline(size)

    def __del__(self) -> None:
        # Don't close the original stream when this object is deleted
        # The original stream's lifecycle should be managed externally
        pass

    @property
    def closed(self) -> bool:  # type: ignore[override]
        return self.original_stream.closed

    def _checkClosed(self) -> None:
        if self.closed:
            raise ValueError("I/O operation on closed file")

    # Additional TextIOBase attributes that may be needed
    @property
    def encoding(self) -> str:  # type: ignore[override]
        return getattr(self.original_stream, "encoding", None)  # type: ignore[return-value]

    @property
    def errors(self) -> Optional[str]:  # type: ignore[override]
        return getattr(self.original_stream, "errors", None)

    @property
    def newlines(self) -> Optional[Union[str, tuple]]:  # type: ignore[override]
        return getattr(self.original_stream, "newlines", None)

    @property
    def buffer(self):  # type: ignore[override]
        return getattr(self.original_stream, "buffer", None)

    @property
    def line_buffering(self) -> bool:  # type: ignore[override]
        return getattr(self.original_stream, "line_buffering", False)

    # Forward any other attributes to the original stream
    def __getattr__(self, name):
        return getattr(self.original_stream, name)


class AnsiFilterStream(io.TextIOBase):
    """Filter stream that removes ANSI escape sequences"""

    def __init__(self, stream):
        self.stream = stream
        self.ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

    def write(self, text):
        cleaned = self.ansi_escape.sub("", text)
        return self.stream.write(cleaned)

    def flush(self):
        return self.stream.flush()

    # Standard file methods proxied to original stream
    def close(self) -> None:
        return self.stream.close()

    def fileno(self) -> int:
        return self.stream.fileno()

    def isatty(self) -> bool:
        return self.stream.isatty()

    def readable(self) -> bool:
        return self.stream.readable()

    def read(self, size: int = -1) -> str:  # type: ignore[override]
        return self.stream.read(size)

    def readlines(self, hint: int = -1) -> List[str]:  # type: ignore[override]
        return self.stream.readlines(hint)

    def seek(self, offset: int, whence: int = 0) -> int:
        return self.stream.seek(offset, whence)

    def seekable(self) -> bool:
        return self.stream.seekable()

    def tell(self) -> int:
        return self.stream.tell()

    def truncate(self, size: Optional[int] = None) -> int:
        if size is None:
            return self.stream.truncate()
        return self.stream.truncate(size)

    def writable(self) -> bool:
        return self.stream.writable()

    def writelines(self, lines: Iterable[str]) -> None:  # type: ignore[override]
        # First write to original stream
        self.stream.writelines(lines)

    def readline(self, size: Optional[int] = -1) -> str:  # type: ignore[override]
        return self.stream.readline(size)

    def __del__(self) -> None:
        self.stream.close()

    @property
    def closed(self) -> bool:  # type: ignore[override]
        return self.stream.closed

    def _checkClosed(self) -> None:
        if self.closed:
            raise ValueError("I/O operation on closed file")

    # Additional TextIOBase attributes that may be needed
    @property
    def encoding(self) -> str:  # type: ignore[override]
        return getattr(self.stream, "encoding", None)  # type: ignore[return-value]

    @property
    def errors(self) -> Optional[str]:  # type: ignore[override]
        return getattr(self.stream, "errors", None)

    @property
    def newlines(self) -> Optional[Union[str, tuple]]:  # type: ignore[override]
        return getattr(self.stream, "newlines", None)

    @property
    def buffer(self):  # type: ignore[override]
        return getattr(self.stream, "buffer", None)

    @property
    def line_buffering(self) -> bool:  # type: ignore[override]
        return getattr(self.stream, "line_buffering", False)

    # Forward other methods/properties to wrapped stream
    def __getattr__(self, name):
        return getattr(self.stream, name)


def reset_logger(reset_all: bool = False, debug: bool = False):
    """
    Reset logger configuration.

    Args:
        reset_all: If True, removes all logger handlers
        debug: If True, sets logger to DEBUG level with DEBUG format
    """
    global _logger_handle

    if _logger_handle:
        try:
            logger.remove(_logger_handle)
        except ValueError:  # _logger_handle not exist (could be removed by user)
            _logger_handle = None

    if reset_all:
        logger.remove()

    if debug:
        log_format = DEBUG_LOGGER_FORMAT
        log_level = "DEBUG"
    else:
        log_format = LOGGER_FORMAT
        log_level = os.environ.get("LOG_LEVEL", "INFO").upper()

    _logger_handle = logger.add(
        sys.stderr,
        format=log_format,
        level=log_level,
    )

    return _logger_handle


def _ensure_tee_streams_setup():
    """
    Ensure tee streams are set up for stdout and stderr.
    This is done only once per process.
    """
    global _stdout_tee_stream, _stderr_tee_stream

    if _stdout_tee_stream is None or _stderr_tee_stream is None:
        with _setup_lock:
            if _stdout_tee_stream is None:
                # Save the true original stdout
                true_original_stdout = sys.stdout
                original_stdout_var.set(true_original_stdout)
                # Create and set up stdout tee stream
                _stdout_tee_stream = TeeStream(
                    true_original_stdout, stdout_tee_outputs_var
                )
                sys.stdout = _stdout_tee_stream  # patch stdout

            if _stderr_tee_stream is None:
                # Save the true original stderr
                true_original_stderr = sys.stderr
                original_stderr_var.set(true_original_stderr)
                # Create and set up stderr tee stream
                _stderr_tee_stream = TeeStream(
                    true_original_stderr, stderr_tee_outputs_var
                )
                sys.stderr = _stderr_tee_stream  # patch stderr


@contextlib.contextmanager
def log_to_file(
    file_path: Path,
    capture_stdout: bool = True,
    capture_stderr: bool = True,
):
    """
    Context manager that redirects logs, stdout and/or stderr to a file
    while preserving the original outputs.

    Args:
        file_path (Path): Path to the log file
        capture_stdout (bool): Whether to capture standard output
        capture_stderr (bool): Whether to capture standard error
    """
    # Make sure tee streams are set up
    _ensure_tee_streams_setup()

    # Open log file
    log_file = open(file_path, "a", encoding="utf-8")
    if not log_file.isatty():
        log_file = AnsiFilterStream(log_file)  # type: ignore[assignment]

    # Add file to appropriate output streams
    stdout_token = None
    stderr_token = None

    if capture_stdout:
        # Get current stdout outputs and add the log file
        current_stdout_outputs = stdout_tee_outputs_var.get().copy()
        new_stdout_outputs = current_stdout_outputs + [log_file]
        stdout_token = stdout_tee_outputs_var.set(new_stdout_outputs)

    if capture_stderr:
        # Get current stderr outputs and add the log file
        current_stderr_outputs = stderr_tee_outputs_var.get().copy()
        new_stderr_outputs = current_stderr_outputs + [log_file]
        stderr_token = stderr_tee_outputs_var.set(new_stderr_outputs)

    try:
        yield log_file
    finally:
        # Restore original output settings using tokens
        if stdout_token is not None:
            stdout_tee_outputs_var.reset(stdout_token)

        if stderr_token is not None:
            stderr_tee_outputs_var.reset(stderr_token)

        # Close the log file
        try:
            log_file.close()
        except ValueError:
            pass  # File might already be closed


def _setup():
    """Initialize logger and tee stream. The order of execution cannot be reversed."""
    _ensure_tee_streams_setup()
    reset_logger(reset_all=True, debug=False)  # remove default loguru logger


def set_verbose(verbose: bool) -> bool:
    global _verbose
    _verbose = verbose
    reset_logger(debug=verbose)
    return verbose


def verbose_print(t, stderr: bool = False):
    if _verbose:
        console = stderr_console if stderr else stdout_console
        console.print(t)


_setup()
