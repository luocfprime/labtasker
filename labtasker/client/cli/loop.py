"""Implements `labtasker loop xxx`"""

import json
import subprocess
import sys
from collections import defaultdict
from typing import List, Optional

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
    stdout_console,
    verbose_print,
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
        "--command",
        "-c",
        help="Specify the command to run with shell=True. Supports the same argument interpolation the same way as the positional argument. Except you need to quote the entire command.",
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
    if cmd and option_cmd:
        raise typer.BadParameter(
            "Only one of [CMD] and [--command] can be specified. Please use one of them."
        )

    cmd = cmd if cmd else option_cmd
    if not cmd and not sys.stdin.isatty():
        # try reading multi-line cmd from stdin if shell mode
        cmd = sys.stdin.read()

    if not cmd:
        raise typer.BadParameter(
            "Command cannot be empty. Either specify via positional argument [CMD] or `--command`."
        )

    parsed_filter = parse_filter(extra_filter)
    verbose_print(f"Parsed filter: {json.dumps(parsed_filter, indent=4)}")

    if heartbeat_timeout is None:
        heartbeat_timeout = get_client_config().task.heartbeat_interval * 3

    # Generate required fields dict
    dummy_variable_table = InfiniteDefaultDict()
    try:
        _, queried_keys = cmd_interpolate(cmd, dummy_variable_table)
    except (CmdParserError, KeyError, TypeError) as e:
        raise typer.BadParameter(f"Command error with exception {e}")

    required_fields = list(queried_keys)

    logger.info(f"Got command: {cmd}")

    @loop_run(
        required_fields=required_fields,
        extra_filter=parsed_filter,
        worker_id=worker_id,
        eta_max=eta_max,
        heartbeat_timeout=heartbeat_timeout,
        pass_args_dict=True,
    )
    def run_cmd(args):
        # Interpolate command

        (
            interpolated_cmd,
            _,
        ) = cmd_interpolate(
            cmd,
            args,
        )
        logger.info(f"Prepared to run interpolated command: {interpolated_cmd}")

        shell = False
        if isinstance(interpolated_cmd, str):
            shell = True

        with subprocess.Popen(
            args=interpolated_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=shell,
        ) as process:
            while True:
                output = process.stdout.readline()
                error = process.stderr.readline()

                if output:
                    stdout_console.print(output.strip())
                if error:
                    stderr_console.print(error.strip())

                # Break loop when process completes and streams are empty
                if process.poll() is not None and not output and not error:
                    break

            process.wait()
            if process.returncode != 0:
                raise _LabtaskerJobFailed(
                    "Job process finished with non-zero exit code."
                )

        logger.info(f"Task {task_info().task_id} ended.")

    run_cmd()

    logger.info("Loop ended.")
