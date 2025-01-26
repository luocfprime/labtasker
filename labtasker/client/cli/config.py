"""
Implements `labtasker config`
"""

from pathlib import Path
from typing import Optional

import typer
from typing_extensions import Annotated

from labtasker.constants import LABTASKER_CLIENT_CONFIG_PATH

app = typer.Typer()


@app.callback()
def config(
    api_base_url: Annotated[
        Optional[str],
        typer.Option(
            prompt=True,
            envvar="API_BASE_URL",
            help="Base URL of the LabTasker API in http string.",
        ),
    ] = None,
    queue_name: Annotated[
        Optional[str],
        typer.Option(
            prompt=True,
            envvar="QUEUE_NAME",
            help="Base URL of the LabTasker API in http string.",
        ),
    ] = None,
    password: Annotated[
        Optional[str],
        typer.Option(
            prompt=True,
            confirmation_prompt=True,
            hide_input=True,
            envvar="PASSWORD",
            help="Base URL of the LabTasker API in http string.",
        ),
    ] = None,
):
    typer.echo(f"Configuring client at {LABTASKER_CLIENT_CONFIG_PATH}")
    typer.echo(f"API Base URL: {api_base_url}")
    typer.echo(f"Queue Name: {queue_name}")
    typer.echo(f"Password: {password}")
