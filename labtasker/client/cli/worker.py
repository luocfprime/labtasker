"""Manage workers (CRUD operations)."""

import sys
from functools import partial
from typing import List, Optional

import click
import typer
from pydantic import ValidationError
from starlette.status import HTTP_404_NOT_FOUND

from labtasker.api_models import Worker
from labtasker.client.core.api import (
    create_worker,
    delete_worker,
    get_queue,
    ls_workers,
    report_worker_status,
)
from labtasker.client.core.cli_utils import (
    LsFmtChoices,
    cli_utils_decorator,
    is_piped_io,
    ls_format_iter,
    pager_iterator,
    parse_filter,
    parse_metadata,
)
from labtasker.client.core.exceptions import LabtaskerHTTPStatusError
from labtasker.client.core.logging import set_verbose, stdout_console, verbose_print
from labtasker.client.core.utils import json_serializer

app = typer.Typer()


@app.callback(invoke_without_command=True)
def callback(
    ctx: typer.Context,
):
    if not ctx.invoked_subcommand:
        stdout_console.print(ctx.get_help())
        raise typer.Exit()


@app.command()
@cli_utils_decorator
def create(
    worker_name: Optional[str] = typer.Option(
        None,
        "--worker-name",
        "--name",
        help="Friendly name to identify this worker (optional).",
    ),
    metadata: Optional[str] = typer.Option(
        None,
        help='Additional worker metadata as a Python dictionary (e.g., \'{"type": "gpu"}\').',
    ),
    max_retries: Optional[int] = typer.Option(
        3,
        help="Maximum number of tolerated failures for a single worker.",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        "-q",
        help="Output only the worker ID, useful for scripting.",
    ),
):
    """
    Create a new worker for processing tasks.

    Workers are responsible for executing tasks from the queue.

    Example:
        labtasker worker create --name "gpu-worker-1" --metadata '{"gpu": "rtx3090"}'
    """
    metadata = parse_metadata(metadata)
    worker_id = create_worker(
        worker_name=worker_name,
        metadata=metadata,
        max_retries=max_retries,
    )

    if quiet:
        stdout_console.print(worker_id)
    else:
        stdout_console.print(f"Worker created with ID: {worker_id}")


@app.command()
@cli_utils_decorator
def ls(
    worker_id: Optional[str] = typer.Option(
        None,
        "--worker-id",
        "--id",
        help="Filter by worker ID.",
    ),
    worker_name: Optional[str] = typer.Option(
        None,
        "--worker-name",
        "--name",
        help="Filter by worker name.",
    ),
    extra_filter: Optional[str] = typer.Option(
        None,
        "--extra-filter",
        "-f",
        help='Optional mongodb filter as a dict string (e.g., \'{"$and": [{"metadata.tag": {"$in": ["a", "b"]}}, {"priority": 10}]}\'). '
        'Or a Python expression (e.g. \'metadata.tag in ["a", "b"] and priority == 10\')',
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        "-q",
        help="Only show worker IDs that match the query, rather than full entry. Useful when using in bash scripts.",
    ),
    ansi: bool = typer.Option(
        True,
        help="Enable ANSI colors.",
    ),
    pager: bool = typer.Option(
        True,
        help="Enable pagination.",
    ),
    limit: int = typer.Option(
        100,
        help="Limit the number of workers returned.",
    ),
    offset: int = typer.Option(
        0,
        help="Initial offset for pagination.",
    ),
    fmt: LsFmtChoices = typer.Option(
        "yaml",
        help="Output format. One of `yaml`, `jsonl`.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose output.",
        callback=set_verbose,
        is_eager=True,
    ),
):
    """
    List workers.
    """
    if quiet:
        if verbose:
            raise typer.BadParameter(
                "You can only specify one of the options --verbose and --quiet."
            )
        pager = False

    get_queue()  # validate auth and queue existence, prevent err swallowed by pager

    extra_filter = parse_filter(extra_filter)
    verbose_print(f"Parsed filter: {json_serializer(extra_filter, indent=4)}")

    page_iter = pager_iterator(
        fetch_function=partial(
            ls_workers,
            worker_id=worker_id,
            worker_name=worker_name,
            extra_filter=extra_filter,
        ),
        offset=offset,
        limit=limit,
    )

    if quiet:
        for item in page_iter:
            item: Worker
            stdout_console.print(item.worker_id)
        raise typer.Exit()  # exit directly without other printing

    if pager:
        click.echo_via_pager(
            ls_format_iter[fmt](
                page_iter,
                use_rich=False,
                ansi=ansi,
            )
        )
    else:
        for item in ls_format_iter[fmt](
            page_iter,
            use_rich=True,
            ansi=ansi,
        ):
            stdout_console.print(item)


@app.command()
@cli_utils_decorator
def report(
    worker_id: str = typer.Argument(..., help="ID of the worker to update."),
    status: str = typer.Argument(
        ..., help="New status for the worker. One of `active`, `suspended`, `crashed`."
    ),
):
    """
    Update the status of a worker. Can be used to revive crashed workers or manually suspend active workers.
    """
    try:
        report_worker_status(worker_id=worker_id, status=status)
    except ValidationError as e:
        raise typer.BadParameter(e)
    stdout_console.print(f"Worker {worker_id} status updated to {status}.")


@app.command()
@cli_utils_decorator
def delete(
    worker_ids: List[str] = typer.Argument(
        ... if not is_piped_io() else None, help="IDs of the worker to delete."
    ),
    cascade_update: bool = typer.Option(
        True,
        help="Whether to cascade set the worker id of relevant tasks to None",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Confirm the operation."),
):
    """
    Delete a worker by worker_id.
    """
    if worker_ids is None:  # read from stdin to support piping
        worker_ids = [line.strip() for line in sys.stdin.readlines() if line.strip()]
    if not yes:
        typer.confirm(
            f"Are you sure you want to delete worker '{worker_ids}'?",
            abort=True,
        )
    try:
        for worker_id in worker_ids:
            delete_worker(worker_id=worker_id, cascade_update=cascade_update)
            stdout_console.print(f"Worker {worker_id} deleted.")
    except LabtaskerHTTPStatusError as e:
        if e.response.status_code == HTTP_404_NOT_FOUND:
            raise typer.BadParameter("Worker not found")
        else:
            raise e
