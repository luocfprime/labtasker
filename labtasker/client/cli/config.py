"""
Implements `labtasker config`
"""

import typer
from pydantic import HttpUrl, SecretStr, ValidationError
from typing_extensions import Annotated

from labtasker.client.cli.cli import app
from labtasker.client.core.config import (
    dump_client_config,
    init_config_with_default,
    update_client_config,
)
from labtasker.client.core.logging import stderr_console
from labtasker.constants import get_labtasker_client_config_path


@app.command()
def config(
    api_base_url: Annotated[
        str,
        typer.Option(
            prompt=True,
            envvar="API_BASE_URL",
            help="Base URL of the LabTasker API in http string.",
        ),
    ],
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
    heartbeat_interval: Annotated[
        int,
        typer.Option(
            prompt=True,
            envvar="HEARTBEAT_INTERVAL",
            help="Hearbeat interval in seconds.",
        ),
    ],
):
    init_config_with_default()

    try:
        update_client_config(
            api_base_url=HttpUrl(api_base_url),
            queue_name=queue_name,
            password=SecretStr(password),
            heartbeat_interval=heartbeat_interval,
        )
    except ValidationError as e:
        stderr_console.print(
            f"[bold red]Input validation error[/bold red], please check your input.\n"
            f"[bold orange1]Detail[/bold orange1]: {e}"
        )
        raise typer.Exit(-1)

    if not get_labtasker_client_config_path().exists():
        if not typer.confirm(
            f"Configuration at {get_labtasker_client_config_path()} not found, create?"
        ):
            raise typer.Exit()

        get_labtasker_client_config_path().parent.mkdir(parents=True, exist_ok=True)
    else:
        if not typer.confirm(
            f"Configuration at {get_labtasker_client_config_path()} already exists, overwrite?"
        ):
            raise typer.Exit()

    dump_client_config()

    return True
