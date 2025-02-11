"""
Implements `labtasker queue xxx`
"""

from ast import literal_eval
from typing import Optional

import typer
from typing_extensions import Annotated

from labtasker.client.core.api import create_queue, delete_queue, get_queue
from labtasker.client.core.config import requires_client_config
from labtasker.client.core.logging import stderr_console, stdout_console

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
    if metadata:
        try:
            metadata = literal_eval(metadata)
            assert isinstance(metadata, dict)
        except (ValueError, AssertionError, SyntaxError) as e:
            stderr_console.print("Error: Metadata must be a valid dict JSON string.")
            stderr_console.print(e)
            raise typer.Exit(code=1)

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
def update(): ...


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
