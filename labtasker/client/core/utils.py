import json
import os
import subprocess
import sys
import threading
from functools import partial, wraps
from typing import Any, Callable, Optional

import httpx
import pexpect
from pydantic_core import to_jsonable_python

from labtasker.api_models import BaseResponseModel
from labtasker.client.core.config import get_client_config
from labtasker.client.core.exceptions import (
    LabtaskerConnectError,
    LabtaskerConnectTimeout,
    LabtaskerHTTPStatusError,
    LabtaskerNetworkError,
)
from labtasker.client.core.logging import stderr_console, stdout_console
from labtasker.client.core.paths import get_labtasker_client_config_path
from labtasker.client.core.query_transpiler import transpile_query

server_notification_prefix = {
    "info": "[bold dodger_blue1]INFO(notification):[/bold dodger_blue1] ",
    "warning": "[bold orange1]WARNING(notification):[/bold orange1] ",
    "error": "[bold red]ERROR(notification):[/bold red] ",
}

server_notification_level = {
    "low": 0,
    "medium": 1,
    "high": 2,
}

transpile_query_safe = partial(
    transpile_query,
    allowed_fields=[
        "task_id",
        "queue_id",
        "status",
        "task_name",
        "created_at",
        "start_time",
        "last_heartbeat",
        "last_modified",
        "heartbeat_timeout",
        "task_timeout",
        "max_retries",
        "retries",
        "priority",
        "metadata",
        "args",
        "cmd",
        "summary",
        "worker_id",
        "worker_name",
    ],
)


def json_serializer(obj: Any, **kwargs) -> str:
    return json.dumps(to_jsonable_python(obj), **kwargs)


def display_server_notifications(
    func: Optional[Callable[..., "BaseResponseModel"]] = None, /
):
    def decorator(function: Callable[..., "BaseResponseModel"]):
        @wraps(function)
        def wrapped(*args, **kwargs):
            resp = function(*args, **kwargs)

            level = "medium"
            if get_labtasker_client_config_path().exists():
                level = get_client_config().display_server_notifications_level

            enabled = level != "none"

            if not enabled:
                return resp

            notifications = resp.notification or []
            for n in notifications:
                if (
                    server_notification_level[n.level]
                    < server_notification_level[level]
                ):  # skip if level is lower than the config
                    continue
                out = stdout_console if n.type == "info" else stderr_console
                out.print(
                    server_notification_prefix[n.type] + n.details,
                )

            return resp

        return wrapped

    if func is not None:
        return decorator(func)

    return decorator


def cast_http_error(func: Optional[Callable] = None, /):
    def decorator(function: Callable):
        @wraps(function)
        def wrapped(*args, **kwargs):
            try:
                return function(*args, **kwargs)
            except httpx.HTTPStatusError as e:
                raise LabtaskerHTTPStatusError(
                    message=str(e), request=e.request, response=e.response
                ) from e
            except httpx.ConnectError as e:
                raise LabtaskerConnectError(message=str(e), request=e.request) from e
            except httpx.ConnectTimeout as e:
                raise LabtaskerConnectTimeout(message=str(e), request=e.request) from e
            except httpx.HTTPError as e:
                raise LabtaskerNetworkError(str(e)) from e

        return wrapped

    if func is not None:
        return decorator(func)

    return decorator


def raise_for_status(r: httpx.Response) -> httpx.Response:
    """
    Call the original raise_for_status but preserve detailed error information.

    Args:
        r: The httpx.Response object

    Returns:
        The original response if successful

    Raises:
        HTTPStatusError: Enhanced with more detailed error information
    """
    try:
        return r.raise_for_status()
    except httpx.HTTPStatusError as e:
        error_details = r.text
        enhanced_message = f"{str(e)}\nResponse details: {error_details}"
        raise httpx.HTTPStatusError(
            enhanced_message, request=e.request, response=e.response
        ) from None


def run_with_pty(cmd, shell_exec=None, use_shell=False):
    """Run a command with PTY support for interactive programs."""
    if use_shell:
        shell_exec = shell_exec or "/bin/sh"
        child = pexpect.spawn(shell_exec, ["-c", cmd], encoding="utf-8")
    else:
        child = pexpect.spawn(cmd[0], cmd[1:], encoding="utf-8")

    stream_child_output(child)

    return child.exitstatus


def run_with_subprocess(cmd, shell_exec=None, use_shell=False):
    """Run a command using standard subprocess approach with real-time output.

    This implementation uses threads to handle stdout and stderr streams separately,
    providing good cross-platform compatibility with improved real-time output.

    Args:
        cmd: Command to execute, either as a string or a list of arguments
        shell_exec: Shell executable to use (if any)
        use_shell: Whether to run the command through the shell

    Returns:
        The return code from the subprocess
    """

    def read_stream(stream, is_stdout):
        """Read from a stream in small chunks for more immediate output.

        This approach avoids line-buffering issues and ensures output appears
        in real-time even when the subprocess doesn't output complete lines.

        Args:
            stream: The stream to read from (process stdout or stderr)
            is_stdout: Boolean indicating if this is stdout (True) or stderr (False)
        """
        # Read in small chunks (64 bytes) instead of lines for more responsive output
        for chunk in iter(lambda: stream.read(64), b""):
            if is_stdout:
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
            else:
                sys.stderr.buffer.write(chunk)
                sys.stderr.buffer.flush()

    with subprocess.Popen(
        args=cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,  # Use binary mode for more direct control
        bufsize=0,  # Disable buffering for immediate output
        executable=shell_exec,
        shell=use_shell,
    ) as process:
        # Create threads to handle output streams
        stdout_thread = threading.Thread(
            target=read_stream, args=(process.stdout, True)
        )
        stderr_thread = threading.Thread(
            target=read_stream, args=(process.stderr, False)
        )

        # Set as daemon threads to avoid blocking when main process exits
        stdout_thread.daemon = True
        stderr_thread.daemon = True

        # Start the threads
        stdout_thread.start()
        stderr_thread.start()

        # Wait for process to complete
        process.wait()

        # Wait for output processing to complete
        # Use a timeout to prevent potential deadlocks
        stdout_thread.join(timeout=1.0)
        stderr_thread.join(timeout=1.0)

        return process.returncode


def check_pty_available(opt: bool) -> bool:
    if opt and os.name == "nt":
        stderr_console.print(
            "[bold orange1]Warning:[/bold orange1] PTY is not available on Windows. "
            "Disabling PTY support."
        )
        return False
    return opt


def stream_child_output(child) -> None:
    """Stream the output of a pexpect child in real-time, supporting progress bars."""
    try:
        while True:
            try:
                output = child.read_nonblocking(size=1024, timeout=0.1)
                if output:
                    # keep \r
                    sys.stdout.write(output)
                    sys.stdout.flush()
            except pexpect.TIMEOUT:
                continue
            except pexpect.EOF:
                break
    finally:
        child.close()
