"""
Implements `labtasker config`
"""

import tempfile
from typing import IO, Optional

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
        None,
        help="Editor to use.",
    ),
):
    """Configure local client. Run `labtasker config` which opens the configuration file using system configured editor"""
    # 0. Check if labtasker root exists, if not, init
    if not get_labtasker_root().exists():
        typer.confirm(
            "Labtasker root directory not found. Initializing with default template?",
            abort=True,
        )
        init_labtasker_root()

    # 1. Open editor and edit configuration in a temp file
    with tempfile.NamedTemporaryFile(
        "w+b",
        prefix="labtasker.tmp.",
        suffix=".toml",
    ) as f:  # type: IO[bytes]

        # 1.1 Copy existing config if exists
        if get_labtasker_client_config_path().exists():
            with open(get_labtasker_client_config_path(), "rb") as f_existing:
                f.write(f_existing.read())

        # 1.2 Edit
        while True:
            try:
                # a. Edit
                f.seek(0)
                click.edit(filename=f.name, editor=editor)

                # b. Reload and validate
                f.seek(0)
                ClientConfig.model_validate(tomlkit.load(f))

                f.seek(0)
                updated_content = f.read()

                break
            except (
                tomlkit.exceptions.ParseError,
                pydantic.ValidationError,
            ) as e:
                stderr_console.print(
                    "[bold red]Error:[/bold red] error when parsing config.\n"
                    f"Detail: {str(e)}"
                )
                typer.confirm("Continue to edit?", abort=True)

    # 2. Save
    with open(get_labtasker_client_config_path(), "wb") as f_existing:
        f_existing.write(updated_content)

    stdout_console.print("[bold green]Configuration updated successfully.[/bold green]")
