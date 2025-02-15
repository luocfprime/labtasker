import sys
from contextlib import contextmanager
from pathlib import Path

from loguru import logger  # noqa
from rich.console import Console

stdout_console = Console(markup=True)
stderr_console = Console(markup=True, stderr=True)


@contextmanager
def log_to_file(
    file_path: Path, capture_stdout: bool = True, capture_stderr: bool = True, **kwargs
):
    """Temporarily redirect log to a file

    Args:
        file_path: Path to log file
        capture_stdout:
        capture_stderr:
        **kwargs: Logger extra kwargs
    """
    log_file = open(file_path, "a")

    original_stdout = None
    original_stderr = None

    # Redirect stdout and stderr to log file
    if capture_stdout:
        original_stdout = sys.stdout
        stdout_console.file = log_file
    if capture_stderr:
        original_stderr = sys.stderr
        stderr_console.file = log_file

    handler_id = logger.add(log_file, **kwargs)

    try:
        yield
    finally:
        # Restore stdout and stderr
        if capture_stdout:
            sys.stdout = original_stdout
        if capture_stderr:
            sys.stderr = original_stderr

        # Remove loguru handler and close the file
        logger.remove(handler_id)
        log_file.close()
