"""
Implements `labtasker queue xxx`
"""

from typing import Optional

import typer
from typing_extensions import Annotated

from labtasker.client.core.api import (
    create_queue,
    delete_queue,
    get_queue,
    update_queue,
)
from labtasker.client.core.cli_utils import parse_metadata
from labtasker.client.core.config import requires_client_config
from labtasker.client.core.logging import stdout_console

app = typer.Typer()


@app.command()
@requires_client_config
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
        help='Optional metadata as a JSON string (e.g., \'{"key": "value"}\').',
    ),
):
    """
    Create a queue.
    """
    metadata = parse_metadata(metadata)
    stdout_console.print(
        create_queue(
            queue_name=queue_name,
            password=password,
            metadata=metadata,
        )
    )


@app.command()
@requires_client_config
def get():
    """Get current queue info."""
    stdout_console.print(get_queue())


@app.command()
@requires_client_config
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
        help='Optional metadata update as a JSON string (e.g., \'{"key": "value"}\').',
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
    stdout_console.print(
        f"Updating queue with:\n"
        f"  New Queue Name: {new_queue_name or 'No change'}\n"
        f"  New Password: {'******' if new_password else 'No change'}\n"
        f"  Metadata: {parsed_metadata or 'No change'}"
    )

    updated_queue = update_queue(
        new_queue_name=new_queue_name,
        new_password=new_password,
        metadata_update=parsed_metadata,
    )
    stdout_console.print(updated_queue)


@app.command()
@requires_client_config
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
