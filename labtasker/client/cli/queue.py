"""Manage task queues (CRUD operations)"""

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
        stderr_console.print("[bold red]Error:[/bold red] Queue already exists.")
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
            help="Name for the new queue (must be unique on the server).",
        ),
    ],
    password: Annotated[
        str,
        typer.Option(
            prompt=True,
            confirmation_prompt=True,
            hide_input=True,
            envvar="PASSWORD",
            help="Password to secure access to this queue. Will be prompted if not provided.",
        ),
    ],
    metadata: Optional[str] = typer.Option(
        None,
        help='Optional queue metadata as a Python dictionary (e.g., \'{"project": "image-processing", "team": "research"}\').',
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        "-q",
        help="Output only the queue ID, useful for scripting and automation.",
    ),
):
    """
    Create a new task queue on the Labtasker server.

    A queue provides isolation between different projects or users. Each queue requires a unique name and password.

    Examples:
        labtasker queue create                                # Interactive prompts
        labtasker queue create --queue-name "my-project"      # Password will be prompted
        labtasker queue create --queue-name "project-x" --metadata '{"department": "engineering"}'
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
        help='Optional queue metadata as a Python dictionary (e.g., \'{"project": "image-processing", "team": "research"}\').',
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        "-q",
        help="Output only the queue ID, useful for scripting and automation.",
    ),
):
    """
    Create a queue using settings from your configuration file.

    This command reads the queue name and password from your local
    configuration file (.labtasker/client.toml) and creates a new queue
    with those settings.

    Examples:
        labtasker queue create_from_config
        labtasker queue create_from_config --metadata '{"project": "automated-testing"}'
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
    quiet: bool = typer.Option(
        False, "--quiet", "-q", help="Only show queue ID string."
    ),
):
    """Get current queue info."""
    resp = get_queue()
    stdout_console.print(resp.queue_id if quiet else resp)


@app.command()
@cli_utils_decorator
def update(
    new_queue_name: Optional[str] = typer.Option(
        None,
        help="New name for the queue (leave unchanged if not specified).",
    ),
    new_password: Optional[str] = typer.Option(
        None,
        prompt=True,
        confirmation_prompt=True,
        hide_input=True,
        prompt_required=False,
        help="New password for the queue. Use flag without value to prompt securely.",
    ),
    metadata: Optional[str] = typer.Option(
        None,
        help="Update queue metadata as a Python dictionary. Examples:\n"
        '- Add/update fields: \'{"department": "research", "priority": "high"}\'\n'
        "- Remove all metadata: '{}'",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        "-q",
        help="Suppress output details (success/failure indicated by exit code).",
    ),
):
    """
    Update properties of the current queue.

    This command allows you to change the name, password, or metadata
    of the queue you're currently connected to. You can update any
    combination of these properties in a single command.

    For security, use --new-password without a value to be prompted
    interactively rather than typing the password in the command line.

    Examples:
        labtasker queue update --new-queue-name "renamed-project"
        labtasker queue update --new-password  # Will prompt securely
        labtasker queue update --metadata '{"status": "active", "owner": "team-a"}'
        labtasker queue update --metadata '{}'  # Remove all metadata
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
    cascade: bool = typer.Option(
        False,
        help="Also delete all tasks in the queue (cannot be undone).",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip confirmation prompt.",
    ),
):
    """Delete current queue."""
    if not yes:
        typer.confirm(
            f"Are you sure you want to delete current queue '{get_queue().queue_name}' with cascade={cascade}?",
            abort=True,
        )
    delete_queue(cascade_delete=cascade)
    stdout_console.print("Queue deleted.")
