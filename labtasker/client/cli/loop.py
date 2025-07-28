"""Implements `labtasker loop xxx`"""

import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import List, Optional

import typer
from typing_extensions import Annotated

from labtasker.client.cli.cli import app
from labtasker.client.core.cli_utils import (
    cli_utils_decorator,
    eta_max_validation,
    is_piped_io,
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
    verbose_print,
)
from labtasker.client.core.utils import (
    check_pty_available,
    json_serializer,
    run_with_pty,
    run_with_subprocess,
)


class InfiniteDefaultDict(defaultdict):

    def __getitem__(self, key):
        if key not in self:
            self[key] = InfiniteDefaultDict()
        return super().__getitem__(key)

    def get(self, key, default=None):
        if key not in self:
            self[key] = InfiniteDefaultDict()
        return super().get(key, default)


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
        callback=check_pty_available,
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
    if not input_cmd and is_piped_io():
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
                exit_code = run_with_pty(interpolated_cmd, executable, use_shell)
            else:
                # Standard subprocess approach for non-PTY execution
                exit_code = run_with_subprocess(interpolated_cmd, executable, use_shell)

            if exit_code != 0:
                raise _LabtaskerJobFailed(
                    f"Job process finished with non-zero exit code: {exit_code}"
                )

        except Exception as e:
            raise _LabtaskerJobFailed(f"Error running command: {str(e)}")

        logger.info(f"Task {task_info().task_id} ended.")

    run_cmd()

    logger.info("Loop ended.")
