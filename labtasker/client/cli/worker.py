"""
Implements `labtasker worker xxx`
"""

from functools import partial
from typing import Optional

import click
import typer
from httpx import HTTPStatusError
from pydantic import ValidationError

from labtasker.client.core.api import (
    create_worker,
    delete_worker,
    ls_worker,
    report_worker_status,
)
from labtasker.client.core.cli_utils import (
    ls_jsonl_format_iter,
    pager_iterator,
    parse_metadata,
)
from labtasker.client.core.config import requires_client_config
from labtasker.client.core.logging import stdout_console

app = typer.Typer()


@app.command()
@requires_client_config
def create(
    worker_name: Optional[str] = typer.Option(
        None,
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
    stdout_console.print(f"Worker created with ID: {worker_id}")


@app.command()
@requires_client_config
def ls(
    worker_id: Optional[str] = typer.Option(
        None,
        help="Filter by worker ID.",
    ),
    worker_name: Optional[str] = typer.Option(
        None,
        help="Filter by worker name.",
    ),
    extra_filter: Optional[str] = typer.Option(
        None,
        help='Optional mongodb filter as a dict string (e.g., \'{"key": "value"}\').',
    ),
    paging: bool = typer.Option(
        False,
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
):
    """
    List workers.
    """
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
    if paging:
        click.echo_via_pager(
            ls_jsonl_format_iter(
                page_iter,
                use_rich=False,
            )
        )
    else:
        for item in ls_jsonl_format_iter(
            page_iter,
            use_rich=True,
        ):
            stdout_console.print(item)


@app.command()
@requires_client_config
def report(
    worker_id: str = typer.Argument(..., help="ID of the worker to update."),
    status: str = typer.Argument(
        ..., help="New status for the worker. One of `active`, `suspended`, `failed`."
    ),
):
    """
    Update the status of a worker.
    """
    try:
        report_worker_status(worker_id=worker_id, status=status)
    except ValidationError as e:
        raise typer.BadParameter(e)
    stdout_console.print(f"Worker {worker_id} status updated to {status}.")


@app.command()
@requires_client_config
def delete(
    worker_id: str = typer.Argument(..., help="ID of the worker to delete."),
    cascade_update: bool = typer.Option(
        True,
        help="Whether to cascade set the worker id of relevant tasks to None",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Confirm the operation."),
):
    """
    Delete a worker.
    """
    if not yes:
        typer.confirm(
            f"Are you sure you want to delete worker '{worker_id}'?",
            abort=True,
        )
    try:
        delete_worker(worker_id=worker_id, cascade_update=cascade_update)
        stdout_console.print(f"Worker {worker_id} deleted.")
    except HTTPStatusError as e:
        if e.response.status_code == 404:
            raise typer.BadParameter("Worker not found")
        else:
            raise e
