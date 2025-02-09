"""
Implements `labtasker queue xxx`
"""

from typing import Any, Dict, Optional

import typer
from pydantic import HttpUrl, SecretStr, ValidationError
from typing_extensions import Annotated

from labtasker.client.core.api import create_queue
from labtasker.client.core.config import (
    dump_client_config,
    init_config_with_default,
    requires_client_config,
    update_client_config,
)
from labtasker.client.core.logging import stderr_console
from labtasker.constants import get_labtasker_client_config_path

app = typer.Typer()


@app.command()
@requires_client_config
def create(
    queue_name: str = typer.Argument(..., help="The name of the queue to create."),
    password: str = typer.Argument(..., help="The password for the queue."),
    metadata: Optional[str] = typer.Option(
        None,
        "--metadata",
        "-m",
        help='Optional metadata as a JSON string (e.g., \'{"key": "value"}\').',
    ),
):
    """
    Command to create a queue using the create_queue function.
    """
    ...
    # # Parse metadata if provided
    # metadata_dict: Optional[Dict[str, Any]] = None
    # if metadata:
    #     try:
    #         metadata_dict = json.loads(metadata)
    #     except json.JSONDecodeError:
    #         typer.echo("Error: Metadata must be a valid JSON string.", err=True)
    #         raise typer.Exit(code=1)
    #
    # # Create the queue
    # try:
    #     response: QueueCreateResponse = create_queue(
    #         queue_name=queue_name,
    #         password=password,
    #         metadata=metadata_dict,
    #         client=httpx.Client(),  # Optionally use a pre-configured HTTPX client
    #     )
    #     typer.echo(f"Queue created successfully: {response}")
    # except Exception as e:
    #     typer.echo(f"Failed to create queue: {e}", err=True)
    #     raise typer.Exit(code=1)
