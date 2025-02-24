import os
import sys
from contextlib import contextmanager
from pathlib import Path

from loguru import logger  # noqa
from rich.console import Console

stdout_console = Console(markup=True)
stderr_console = Console(markup=True, stderr=True)

LOGGER_FORMAT = (
    "<green>[{time:YYYY-MM-DD HH:mm:ss.SSS}]</green>"
    "[<level>{level: <8}</level>]"
    " - <level>{message}</level>"
)


class TeeStream:
    def __init__(self, original_stream, *streams):
        self.original_stream = original_stream  # original stream (e.g. sys.stdout)
        self.streams = streams  # other streams (e.g. open files)

    def write(self, data):
        self.original_stream.write(data)
        for stream in self.streams:
            stream.write(data)
            stream.flush()

    def flush(self):
        self.original_stream.flush()
        for stream in self.streams:
            stream.flush()

    def __getattr__(self, name):
        return getattr(self.original_stream, name)


def reset_logger():
    logger.remove()
    logger.add(
        sys.stderr,
        format=LOGGER_FORMAT,
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    )


@contextmanager
def log_to_file(
    file_path: Path,
    capture_stdout: bool = True,
    capture_stderr: bool = True,
    **kwargs,
):
    """Temporarily redirect log to a file.

    Args:
        file_path (Path): Path to the log file.
        capture_stdout (bool): Whether to redirect stdout to the log file.
        capture_stderr (bool): Whether to redirect stderr to the log file.
        **kwargs: Additional arguments for the `logger.add` method.
    """
    log_file = open(file_path, "a")

    # Create tee streams for stdout and stderr
    original_stdout = sys.stdout
    original_stderr = sys.stderr

    if capture_stdout:
        sys.stdout = TeeStream(original_stdout, log_file)
    if capture_stderr:
        sys.stderr = TeeStream(original_stderr, log_file)

    # Add a loguru handler to the file
    handler_id = logger.add(log_file, **kwargs)

    try:
        yield
    finally:
        # Restore original stdout and stderr
        if capture_stdout:
            sys.stdout = original_stdout
        if capture_stderr:
            sys.stderr = original_stderr

        # Remove the loguru handler and close the file
        logger.remove(handler_id)
        log_file.close()


reset_logger()  # initialize
