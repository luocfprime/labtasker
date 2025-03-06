"""
Implements `labtasker config`
"""

import os
import tempfile
from pathlib import Path
from typing import Optional

import click
import pydantic
import tomlkit
import tomlkit.exceptions
import typer

from labtasker.client.cli.cli import app
from labtasker.client.core.config import ClientConfig, init_labtasker_root
from labtasker.client.core.logging import stderr_console, stdout_console
from labtasker.client.core.paths import (
    get_labtasker_client_config_path,
    get_labtasker_root,
)


@app.command()
def config(
    editor: Optional[str] = typer.Option(
        None, help="Editor to use for editing the configuration file."
    ),
):
    """
    Configure the local client. Opens the configuration file for editing using the specified or system-configured editor.
    """
    # 0. Check if Labtasker root exists, if not, initialize it
    if not get_labtasker_root().exists():
        typer.confirm(
            "Labtasker root directory not found. Would you like to initialize it with default templates?",
            abort=True,
        )
        init_labtasker_root()

    # 1. Create a temporary file and prepare it for editing
    temp_file_path = None
    try:
        # Create a temporary file
        fd, temp_file_path = tempfile.mkstemp(prefix="labtasker.tmp.", suffix=".toml")
        os.close(fd)  # Close the file descriptor to avoid locking issues
        temp_file_path = Path(temp_file_path)

        # 1.1 Copy existing configuration to the temporary file (if it exists)
        config_path = get_labtasker_client_config_path()
        if config_path.exists():
            with open(config_path, "rb") as existing_config, open(
                temp_file_path, "wb"
            ) as temp_file:
                temp_file.write(existing_config.read())

        # 1.2 Open the temporary file in the editor and validate changes
        while True:
            try:
                # a. Open the file in the specified or system-configured editor
                click.edit(filename=str(temp_file_path), editor=editor)

                # b. Reload and validate the updated configuration
                with open(temp_file_path, "r", encoding="utf-8") as temp_file:
                    updated_config = tomlkit.load(temp_file)
                    ClientConfig.model_validate(updated_config)

                # If validation passes, read the updated content
                with open(temp_file_path, "rb") as temp_file:
                    updated_content = temp_file.read()

                break  # Exit the loop when editing and validation succeed

            except (tomlkit.exceptions.ParseError, pydantic.ValidationError) as e:
                # Handle errors during parsing or validation
                stderr_console.print(
                    f"[bold red]Error:[/bold red] Invalid configuration file.\n"
                    f"Details: {str(e)}"
                )
                if not typer.confirm("Would you like to continue editing?", abort=True):
                    raise typer.Abort()

        # 2. Save the updated configuration back to the original file
        with open(config_path, "wb") as config_file:
            config_file.write(updated_content)

        stdout_console.print(
            "[bold green]Configuration updated successfully.[/bold green]"
        )

    finally:
        # Cleanup: Delete the temporary file
        if temp_file_path and temp_file_path.exists():
            temp_file_path.unlink()
