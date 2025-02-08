"""
Implements top level cli (mainly callbacks and setup)
"""

from functools import wraps
from typing import Optional

import typer
from typing_extensions import Annotated

from labtasker import __version__
from labtasker.client.core.api import health_check
from labtasker.client.core.config import load_client_config
from labtasker.client.core.logging import stderr_console, stdout_console
from labtasker.constants import get_labtasker_client_config_path

app = typer.Typer(pretty_exceptions_show_locals=False)


def version_callback(value: bool):
    if value:
        print(f"Labtasker Version: {__version__}")
        raise typer.Exit()


def cli_requires_config(func, /, *, load_config: bool = True):
    @wraps(func)
    def wrapped(*args, **kwargs):
        if (
            not get_labtasker_client_config_path().exists()
        ):  # check if config file exists
            stderr_console.print(
                f"Configuration at {get_labtasker_client_config_path()} not found. Run `labtasker config` to initialize configuration."
            )
            raise typer.Exit(-1)
        # load config
        if load_config:
            load_client_config()
        return func(*args, **kwargs)

    return wrapped


@app.callback()
def callback(
    version: Annotated[
        Optional[bool],
        typer.Option(
            ..., "--version", callback=version_callback, help="Print Labtasker version."
        ),
    ] = None,
): ...


@app.command()
@cli_requires_config
def health():
    stdout_console.print(health_check())
