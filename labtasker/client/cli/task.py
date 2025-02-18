"""
Implements `labtasker task xxx`
"""

from functools import partial
from typing import Optional

import click
import typer
from httpx import HTTPStatusError
from pydantic import ValidationError

from labtasker.client.core.api import (
    delete_task,
    ls_tasks,
    report_task_status,
    submit_task,
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
def submit(
    task_name: Optional[str] = typer.Option(None, help="Name of the task."),
    args: Optional[str] = typer.Option(
        None,
        help='Arguments for the task as a python dict string (e.g., \'{"key": "value"}\').',
    ),
    metadata: Optional[str] = typer.Option(
        None,
        help='Optional metadata as a python dict string (e.g., \'{"key": "value"}\').',
    ),
    cmd: Optional[str] = typer.Option(
        None,
        help="Command to execute for the task.",
    ),
    heartbeat_timeout: Optional[float] = typer.Option(
        60,
        help="Heartbeat timeout for the task.",
    ),
    task_timeout: Optional[int] = typer.Option(
        None,
        help="Task execution timeout.",
    ),
    max_retries: Optional[int] = typer.Option(
        3,
        help="Maximum number of retries for the task.",
    ),
    priority: Optional[int] = typer.Option(
        1,
        help="Priority of the task.",
    ),
):
    """
    Submit a new task to the queue.
    """
    args_dict = parse_metadata(args) if args else {}
    metadata_dict = parse_metadata(metadata) if metadata else {}

    task_id = submit_task(
        task_name=task_name,
        args=args_dict,
        metadata=metadata_dict,
        cmd=cmd,
        heartbeat_timeout=heartbeat_timeout,
        task_timeout=task_timeout,
        max_retries=max_retries,
        priority=priority,
    )
    stdout_console.print(f"Task submitted with ID: {task_id}")


@app.command()
@requires_client_config
def report(
    task_id: str = typer.Argument(..., help="ID of the task to update."),
    status: str = typer.Argument(
        ..., help="New status for the task. One of `success`, `failed`, `cancelled`."
    ),
    summary: Optional[str] = typer.Option(
        None,
        help="Summary of the task status.",
    ),
):
    """
    Report the status of a task.
    """
    try:
        summary = parse_metadata(summary)
        report_task_status(task_id=task_id, status=status, summary=summary)
    except ValidationError as e:
        raise typer.BadParameter(e)
    stdout_console.print(f"Task {task_id} status updated to {status}.")


@app.command()
@requires_client_config
def ls(
    task_id: Optional[str] = typer.Option(
        None,
        help="Filter by task ID.",
    ),
    task_name: Optional[str] = typer.Option(
        None,
        help="Filter by task name.",
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
        help="Limit the number of tasks returned.",
    ),
    offset: int = typer.Option(
        0,
        help="Initial offset for pagination.",
    ),
):
    """List tasks in the queue."""
    extra_filter = parse_metadata(extra_filter)
    page_iter = pager_iterator(
        fetch_function=partial(
            ls_tasks,
            task_id=task_id,
            task_name=task_name,
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
def delete(
    task_id: str = typer.Argument(..., help="ID of the task to delete."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Confirm the operation."),
):
    """
    Delete a task.
    """
    if not yes:
        typer.confirm(
            f"Are you sure you want to delete task '{task_id}'?",
            abort=True,
        )
    try:
        delete_task(task_id=task_id)
        stdout_console.print(f"Task {task_id} deleted.")
    except HTTPStatusError as e:
        if e.response.status_code == 404:
            raise typer.BadParameter("Task not found")
        else:
            raise e
