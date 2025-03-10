import contextlib
import contextvars
import io
import os
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
    " - <level>{message}</level>"
)


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

    def read(self, size: int = -1) -> str:
        return self.original_stream.read(size)

    def readlines(self, hint: int = -1) -> List[str]:
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

    def writelines(self, lines: Iterable[str]) -> None:
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

    def readline(self, size: Optional[int] = -1) -> str:
        return self.original_stream.readline(size)

    def __del__(self) -> None:
        # Don't close the original stream when this object is deleted
        # The original stream's lifecycle should be managed externally
        pass

    @property
    def closed(self) -> bool:
        return self.original_stream.closed

    def _checkClosed(self) -> None:
        if self.closed:
            raise ValueError("I/O operation on closed file")

    # Additional TextIOBase attributes that may be needed
    @property
    def encoding(self) -> str:
        return getattr(self.original_stream, "encoding", None)

    @property
    def errors(self) -> Optional[str]:
        return getattr(self.original_stream, "errors", None)

    @property
    def newlines(self) -> Optional[Union[str, tuple]]:
        return getattr(self.original_stream, "newlines", None)

    @property
    def buffer(self):
        return getattr(self.original_stream, "buffer", None)

    @property
    def line_buffering(self) -> bool:
        return getattr(self.original_stream, "line_buffering", False)

    # Forward any other attributes to the original stream
    def __getattr__(self, name):
        return getattr(self.original_stream, name)


def reset_logger():
    logger.remove()
    logger.add(
        sys.stderr,
        format=LOGGER_FORMAT,
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    )


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


def setup():
    """Initialize logger and tee stream. The order of execution cannot be reversed."""
    _ensure_tee_streams_setup()
    reset_logger()


setup()
