"""
Implements `labtasker loop xxx`
"""

import shlex
import subprocess
from collections import defaultdict
from typing import Optional

import typer

import labtasker
import labtasker.client.core.context
from labtasker.client.cli.cli import app
from labtasker.client.core.cli_utils import eta_max_validation, parse_metadata
from labtasker.client.core.cmd_parser import CmdSyntaxError, cmd_interpolate
from labtasker.client.core.config import get_client_config, requires_client_config
from labtasker.client.core.job_runner import finish
from labtasker.client.core.job_runner import loop as loop_run
from labtasker.client.core.logging import logger, stderr_console, stdout_console
from labtasker.utils import keys_to_query_dict


def infinite_defaultdict():
    return defaultdict(infinite_defaultdict)


@app.command()
@requires_client_config
def loop(
    cmd: str = typer.Option(
        ...,
        "--cmd",
        "-c",
        help="Command to run. Support argument auto interpolation, formatted like %(arg1).",
    ),
    extra_filter: Optional[str] = typer.Option(
        None,
        help='Optional mongodb filter as a dict string (e.g., \'{"key": "value"}\').',
    ),
    worker_id: Optional[str] = typer.Option(
        None,
        help="Worker ID to run the command under.",
    ),
    eta_max: Optional[str] = typer.Option(
        None,
        callback=eta_max_validation,
        help="Maximum ETA for the task. (e.g. '1h', '1h30m', '50s')",
    ),
    heartbeat_timeout: float = typer.Option(
        get_client_config().heartbeat_interval * 3,
        help="Heartbeat timeout for the task in seconds.",
    ),
):
    extra_filter = parse_metadata(extra_filter)

    # Generate required fields dict
    dummy_variable_table = infinite_defaultdict()
    try:
        _, queried_keys = cmd_interpolate(cmd, dummy_variable_table)
    except (CmdSyntaxError, KeyError, TypeError) as e:
        raise typer.BadParameter(f"Command error with exception {e}")

    required_fields = keys_to_query_dict(list(queried_keys))

    @loop_run(
        required_fields=required_fields,
        extra_filter=extra_filter,
        worker_id=worker_id,
        eta_max=eta_max,
        heartbeat_timeout=heartbeat_timeout,
        pass_args_dict=True,
    )
    def run_cmd(args):
        # Interpolate command
        interpolated_cmd, _ = cmd_interpolate(cmd, args)
        logger.info(f"Running command: {cmd}")

        with subprocess.Popen(
            shlex.split(interpolated_cmd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ) as process:
            while True:
                output = process.stdout.readline()
                error = process.stderr.readline()

                if output:
                    stdout_console(output.strip())
                if error:
                    stderr_console(error.strip())

                # Break loop when process completes and streams are empty
                if process.poll() is not None and not output and not error:
                    break

            process.wait()
            if process.returncode != 0:
                finish("failed")
            else:
                finish("success")

        logger.info(f"Task {labtasker.client.core.context.task_info().task_id} ended.")

    run_cmd()

    logger.info("Loop finished.")
