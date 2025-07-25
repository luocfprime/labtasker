"""Implements `labtasker loop xxx`"""

import os
import subprocess
import sys
import threading
from collections import defaultdict
from pathlib import Path
from typing import List, Optional

import pexpect
import typer
from typing_extensions import Annotated

from labtasker.client.cli.cli import app
from labtasker.client.core.cli_utils import (
    cli_utils_decorator,
    eta_max_validation,
    parse_filter,
)
from labtasker.client.core.cmd_parser import cmd_interpolate
from labtasker.client.core.config import get_client_config
from labtasker.client.core.context import task_info
from labtasker.client.core.exceptions import CmdParserError, _LabtaskerJobFailed
from labtasker.client.core.job_runner import loop_run
from labtasker.client.core.logging import (
    logger,
    set_verbose,
    stderr_console,
    verbose_print,
)
from labtasker.client.core.utils import json_serializer


class InfiniteDefaultDict(defaultdict):

    def __getitem__(self, key):
        if key not in self:
            self[key] = InfiniteDefaultDict()
        return super().__getitem__(key)

    def get(self, key, default=None):
        if key not in self:
            self[key] = InfiniteDefaultDict()
        return super().get(key, default)


def _check_pty_available(opt: bool) -> bool:
    if opt and os.name == "nt":
        stderr_console.print(
            "[bold orange1]Warning:[/bold orange1] PTY is not available on Windows. "
            "Disabling PTY support."
        )
        return False
    return opt


def _stream_child_output(child) -> None:
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


def _run_with_pty(cmd, shell_exec=None, use_shell=False):
    """Run a command with PTY support for interactive programs."""
    if use_shell:
        shell_exec = shell_exec or "/bin/sh"
        child = pexpect.spawn(shell_exec, ["-c", cmd], encoding="utf-8")
    else:
        child = pexpect.spawn(cmd[0], cmd[1:], encoding="utf-8")

    _stream_child_output(child)

    return child.exitstatus


def _run_with_subprocess(cmd, shell_exec=None, use_shell=False):
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


@app.command()
@cli_utils_decorator
def loop(
    cmd: Annotated[
        List[str],
        typer.Argument(
            ...,
            help="Command to run. Supports argument interpolation using %(arg_name) syntax. Example: `python main.py '%(input_file)' '%(output_dir)'`",
        ),
    ] = None,
    option_cmd: str = typer.Option(
        None,
        "--command",
        "--cmd",
        "-c",
        help="Specify the command to run with shell=True. Supports the same argument interpolation the same way as the positional argument. Except you need to quote the entire command.",
    ),
    script_path: Optional[Path] = typer.Option(
        None,
        exists=True,
        readable=True,
        help="Path to a script file that contains the command to execute. The script will run with '%(...)' placeholders replaced by the retrieved task arguments.",
    ),
    executable: Optional[str] = typer.Option(
        None,
        "--executable",
        help="Specify the shell executable to run the command with.",
    ),
    extra_filter: Optional[str] = typer.Option(
        None,
        "--extra-filter",
        "-f",
        help='Filter tasks using MongoDB query syntax (e.g., \'{"metadata.tag": {"$in": ["a", "b"]}}\') or Python expression (e.g., \'metadata.tag in ["a", "b"] and priority == 10\').',
    ),
    worker_id: Optional[str] = typer.Option(
        None,
        help="Assign a specific worker ID to run the tasks under.",
    ),
    eta_max: Optional[str] = typer.Option(
        None,
        callback=eta_max_validation,
        help="Maximum estimated time for task completion (e.g. '1h', '1h30m', '50s'). After which the task will be considered timed out.",
    ),
    heartbeat_timeout: Optional[float] = typer.Option(
        None,
        help="Time in seconds before a task is considered stalled if no heartbeat is received.",
    ),
    use_pty: bool = typer.Option(
        os.name == "posix",  # enabled by default on POSIX systems
        callback=_check_pty_available,
        help="Use pseudo terminal on POSIX systems for better interactive program support.",
    ),
    verbose: bool = typer.Option(  # noqa
        False,
        "--verbose",
        "-v",
        help="Enable verbose output.",
        callback=set_verbose,
        is_eager=True,
    ),
):
    """Process tasks from the queue by repeatedly running a command with task arguments.

    The command uses template syntax to insert task arguments. For example:

    labtasker loop -- python process.py --input '%(input_file)' --output '%(output_dir)'

    This will fetch tasks with 'input_file' and 'output_dir' arguments and run the command
    with those values substituted. Tasks are processed until the queue is empty.
    """
    # Ensure only one of [CMD], [--command], or [--script-path] is specified
    cmd_sources = [cmd, option_cmd, script_path]
    cmd_sources = list(filter(None, cmd_sources))  # Remove None values dynamically
    if len(cmd_sources) > 1:
        raise typer.BadParameter(
            "Only one of [CMD], [--command], or [--script-path] can be specified. Choose one."
        )

    # 1. Assign from cmd or option_cmd
    input_cmd = cmd or option_cmd

    # 2. Assign from script_path if provided
    if script_path and input_cmd is None:
        with open(script_path, "r") as f:
            input_cmd = f.read().strip()

    # 3. Try reading from stdin if shell mode is enabled
    if not input_cmd and not sys.stdin.isatty():
        input_cmd = sys.stdin.read().strip()

    # Final validation: ensure a command is present
    if not input_cmd:
        raise typer.BadParameter(
            "Command cannot be empty. Specify via positional argument [CMD] or `--command` or `--script-path`."
        )

    parsed_filter = parse_filter(extra_filter)
    verbose_print(f"Parsed filter: {json_serializer(parsed_filter, indent=4)}")

    if heartbeat_timeout is None:
        heartbeat_timeout = get_client_config().task.heartbeat_interval * 3

    # Generate required fields dict
    dummy_variable_table = InfiniteDefaultDict()
    try:
        _, queried_keys = cmd_interpolate(input_cmd, dummy_variable_table)
    except (CmdParserError, KeyError, TypeError) as e:
        raise typer.BadParameter(f"Command error with exception {e}")

    required_fields = list(queried_keys)

    logger.info(f"Got command: {input_cmd}")

    @loop_run(
        required_fields=required_fields,
        extra_filter=parsed_filter,
        worker_id=worker_id,
        eta_max=eta_max,
        heartbeat_timeout=heartbeat_timeout,
        pass_args_dict=True,
    )
    def run_cmd(args):
        interpolated_cmd, _ = cmd_interpolate(input_cmd, args)
        logger.info(f"Prepared to run interpolated command: {interpolated_cmd}")

        use_shell = isinstance(interpolated_cmd, str)

        try:
            if use_pty:
                # Use pexpect with PTY on POSIX systems
                exit_code = _run_with_pty(interpolated_cmd, executable, use_shell)
            else:
                # Standard subprocess approach for non-PTY execution
                exit_code = _run_with_subprocess(
                    interpolated_cmd, executable, use_shell
                )

            if exit_code != 0:
                raise _LabtaskerJobFailed(
                    f"Job process finished with non-zero exit code: {exit_code}"
                )

        except Exception as e:
            raise _LabtaskerJobFailed(f"Error running command: {str(e)}")

        logger.info(f"Task {task_info().task_id} ended.")

    run_cmd()

    logger.info("Loop ended.")
