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
from labtasker.constants import LABTASKER_CLIENT_CONFIG_PATH

app = typer.Typer(pretty_exceptions_show_locals=False)


def version_callback(value: bool):
    if value:
        print(f"Labtasker Version: {__version__}")
        raise typer.Exit()


def cli_requires_config(func, /, *, load_config: bool = True):
    @wraps(func)
    def wrapped(*args, **kwargs):
        if not LABTASKER_CLIENT_CONFIG_PATH.exists():  # check if config file exists
            stderr_console.print(
                f"Configuration at {LABTASKER_CLIENT_CONFIG_PATH} not found. Run `labtasker config` to initialize configuration."
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
