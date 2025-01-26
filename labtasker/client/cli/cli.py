"""
Implements top level cli (mainly callbacks and setup)
"""

from typing import Optional

import typer
from typing_extensions import Annotated

from labtasker import __version__
from labtasker.constants import LABTASKER_CLIENT_CONFIG_PATH

app = typer.Typer()


def version_callback(value: bool):
    if value:
        print(f"Labtasker Version: {__version__}")
        raise typer.Exit()


@app.callback()
def callback(
    version: Annotated[
        Optional[bool],
        typer.Option(
            ..., "--version", callback=version_callback, help="Print Labtasker version."
        ),
    ] = None,
):
    if not LABTASKER_CLIENT_CONFIG_PATH.exists():  # check if config file exists
        if not typer.confirm(
            f"Client configuration file not found at {LABTASKER_CLIENT_CONFIG_PATH}, create?"
        ):
            typer.Exit()

        LABTASKER_CLIENT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        LABTASKER_CLIENT_CONFIG_PATH.touch()

    return True
