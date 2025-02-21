"""
Implements top level cli (mainly callbacks and setup)
"""

from typing import Optional

import httpx
import typer
from typing_extensions import Annotated

from labtasker import __version__
from labtasker.client.core.api import health_check
from labtasker.client.core.config import requires_client_config
from labtasker.client.core.logging import stderr_console, stdout_console

app = typer.Typer(pretty_exceptions_show_locals=False)


def version_callback(value: bool):
    if value:
        stdout_console.print(f"Labtasker Version: {__version__}")
        raise typer.Exit()


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
@requires_client_config
def health():
    """Check server connection and server health."""
    try:
        stdout_console.print(health_check())
    except (httpx.ConnectError, httpx.HTTPStatusError) as e:
        stderr_console.print(e)
