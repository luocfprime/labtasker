"""
Worker related CRUD operations.
"""

from functools import partial
from typing import Optional

import click
import typer
from pydantic import ValidationError
from starlette.status import HTTP_404_NOT_FOUND

from labtasker.api_models import Worker
from labtasker.client.core.api import (
    create_worker,
    delete_worker,
    get_queue,
    ls_worker,
    report_worker_status,
)
from labtasker.client.core.cli_utils import (
    LsFmtChoices,
    cli_utils_decorator,
    ls_format_iter,
    pager_iterator,
    parse_metadata,
)
from labtasker.client.core.exceptions import LabtaskerHTTPStatusError
from labtasker.client.core.logging import stdout_console

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
        help="Name of the worker.",
    ),
    metadata: Optional[str] = typer.Option(
        None,
        help='Optional metadata as a python dict string (e.g., \'{"key": "value"}\').',
    ),
    max_retries: Optional[int] = typer.Option(
        3,
        help="Maximum number of retries for the worker.",
    ),
    quiet: bool = typer.Option(
        False,
        help="Only show worker ID string, rather than full response. Useful when using in bash scripts.",
    ),
):
    """
    Create a new worker.
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
        help='Optional mongodb filter as a dict string (e.g., \'{"key": "value"}\').',
    ),
    quiet: bool = typer.Option(
        False,
        help="Only show worker IDs that match the query, rather than full entry. Useful when using in bash scripts.",
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
):
    """
    List workers.
    """
    if quiet and pager:
        raise typer.BadParameter("--quiet and --pager cannot be used together.")

    get_queue()  # validate auth and queue existence, prevent err swallowed by pager

    extra_filter = parse_metadata(extra_filter)
    page_iter = pager_iterator(
        fetch_function=partial(
            ls_worker,
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
            )
        )
    else:
        for item in ls_format_iter[fmt](
            page_iter,
            use_rich=True,
        ):
            stdout_console.print(item)


@app.command()
@cli_utils_decorator
def report(
    worker_id: str = typer.Argument(..., help="ID of the worker to update."),
    status: str = typer.Argument(
        ..., help="New status for the worker. One of `active`, `suspended`, `failed`."
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
    worker_id: str = typer.Argument(..., help="ID of the worker to delete."),
    cascade_update: bool = typer.Option(
        True,
        help="Whether to cascade set the worker id of relevant tasks to None",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Confirm the operation."),
):
    """
    Delete a worker by worker_id.
    """
    if not yes:
        typer.confirm(
            f"Are you sure you want to delete worker '{worker_id}'?",
            abort=True,
        )
    try:
        delete_worker(worker_id=worker_id, cascade_update=cascade_update)
        stdout_console.print(f"Worker {worker_id} deleted.")
    except LabtaskerHTTPStatusError as e:
        if e.response.status_code == HTTP_404_NOT_FOUND:
            raise typer.BadParameter("Worker not found")
        else:
            raise e
