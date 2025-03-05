"""
Task queue related CRUD operations.
"""

from typing import Callable, Optional

import typer
from starlette.status import HTTP_409_CONFLICT
from typing_extensions import Annotated

from labtasker.client.core.api import (
    create_queue,
    delete_queue,
    get_queue,
    update_queue,
)
from labtasker.client.core.cli_utils import (
    cli_utils_decorator,
    handle_http_err,
    parse_metadata,
)
from labtasker.client.core.config import get_client_config
from labtasker.client.core.logging import stderr_console, stdout_console

app = typer.Typer()


def handle_queue_create_conflict_err(func: Optional[Callable] = None, /):
    """Handles queue create conflict and prints human-readable message."""

    def error_409_handler(e):
        stderr_console.print(f"[bold red]Error:[/bold red] Queue already exists.")
        raise typer.Abort()

    return handle_http_err(
        func, status_code=HTTP_409_CONFLICT, err_handler=error_409_handler
    )


@app.callback(invoke_without_command=True)
def callback(
    ctx: typer.Context,
):
    if not ctx.invoked_subcommand:
        stdout_console.print(ctx.get_help())
        raise typer.Exit()


@app.command()
@cli_utils_decorator
@handle_queue_create_conflict_err
def create(
    queue_name: Annotated[
        str,
        typer.Option(
            prompt=True,
            envvar="QUEUE_NAME",
            help="Queue name for current experiment.",
        ),
    ],
    password: Annotated[
        str,
        typer.Option(
            prompt=True,
            confirmation_prompt=True,
            hide_input=True,
            envvar="PASSWORD",
            help="Password for current queue.",
        ),
    ],
    metadata: Optional[str] = typer.Option(
        None,
        help='Optional metadata as a python dict string (e.g., \'{"key": "value"}\').',
    ),
    quiet: bool = typer.Option(
        False,
        help="Only show queue ID string, rather than full response. Useful when using in bash scripts.",
    ),
):
    """
    Create a queue.
    """
    metadata = parse_metadata(metadata)
    resp = create_queue(
        queue_name=queue_name,
        password=password,
        metadata=metadata,
    )
    stdout_console.print(resp.queue_id if quiet else resp)


@app.command()
@cli_utils_decorator
@handle_queue_create_conflict_err
def create_from_config(
    metadata: Optional[str] = typer.Option(
        None,
        help='Optional metadata as a python dict string (e.g., \'{"key": "value"}\').',
    ),
    quiet: bool = typer.Option(
        False,
        help="Only show queue ID string, rather than full response. Useful when using in bash scripts.",
    ),
):
    """
    Create a queue from config in `.labtasker/client.toml`.
    """
    metadata = parse_metadata(metadata)
    config = get_client_config()
    resp = create_queue(
        queue_name=config.queue.queue_name,
        password=config.queue.password.get_secret_value(),
        metadata=metadata,
    )
    stdout_console.print(resp.queue_id if quiet else resp)


@app.command()
@cli_utils_decorator
def get(
    quiet: bool = typer.Option(False, help="Only show queue ID string."),
):
    """Get current queue info."""
    resp = get_queue()
    stdout_console.print(resp.queue_id if quiet else resp)


@app.command()
@cli_utils_decorator
def update(
    new_queue_name: Optional[str] = typer.Option(
        None,
        help="New name for the queue.",
    ),
    new_password: Optional[str] = typer.Option(
        None,
        prompt=True,
        confirmation_prompt=True,
        hide_input=True,
        prompt_required=False,  # only trigger interactive prompt when `--new-password` is provided
        help="New password for the queue.",
    ),
    metadata: Optional[str] = typer.Option(
        None,
        help='Optional metadata update as a python dict string (e.g., \'{"label": "test"}\'). '
        "The updated metadata will be merged with the oringinal metadata."
        "If you want to unset the metadata entirely, specify via `--metadata '{}'`",
    ),
    quiet: bool = typer.Option(
        False,
        help="Suppress the output. Execution result is only available via status code.",
    ),
):
    """
    Update the current queue.
    If you do not wish to expose password in command (e.g. `labtasker queue update --new-password my-pass --new-queue-name my-name`),
    omit the content of `--new-password` and an interactive prompt will show up (i.e. labtasker queue update --new-password  --new-queue-name my-name).
    """
    # Parse metadata
    parsed_metadata = parse_metadata(metadata)

    # Proceed with the update logic
    if not quiet:
        if metadata is None:
            metadata_update_mode = "No change"
        elif metadata == {}:
            metadata_update_mode = "Reset to {}"
        else:
            metadata_update_mode = "Update"

        stdout_console.print(
            f"Updating queue with:\n"
            f"  New Queue Name: {new_queue_name or 'No change'}\n"
            f"  New Password: {'******' if new_password else 'No change'}\n"
            f"  Metadata ({metadata_update_mode}): {parsed_metadata}",
        )

    updated_queue = update_queue(
        new_queue_name=new_queue_name,
        new_password=new_password,
        metadata_update=parsed_metadata,
    )

    if not quiet:
        stdout_console.print(updated_queue)


@app.command()
@cli_utils_decorator
def delete(
    cascade: bool = typer.Option(False, help="Delete all tasks in the queue."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Confirm the operation."),
):
    """Delete current queue."""
    if not yes:
        typer.confirm(
            f"Are you sure you want to delete current queue '{get_queue().queue_name}' with cascade={cascade}?",
            abort=True,
        )
    delete_queue(cascade_delete=cascade)
    stdout_console.print("Queue deleted.")
