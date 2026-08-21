from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
import uvicorn

from labtasker_server.app import create_app
from labtasker_server.config import ServerSettings

app = typer.Typer(
    help="Run the Labtasker v2 HTTP Server.",
    add_completion=False,
    no_args_is_help=True,
    pretty_exceptions_enable=False,
    rich_markup_mode=None,
)


@app.callback()
def main() -> None:
    """Run and manage the Labtasker v2 Server."""


@app.command()
def serve(
    host: Annotated[
        str,
        typer.Option(help="Address to bind; a non-loopback address requires a token."),
    ] = "127.0.0.1",
    port: Annotated[
        int,
        typer.Option(min=1, max=65535, help="TCP port to listen on."),
    ] = 8000,
    database: Annotated[
        Path,
        typer.Option(help="SQLite database file owned by this Server process."),
    ] = Path(".labtasker/server.db"),
) -> None:
    """Initialize the database and run one Labtasker v2 Server process.

    Authentication is optional on loopback. For any non-loopback bind, set the
    shared token with LABTASKER_SERVER_TOKEN; tokens are never accepted as a
    command-line option. Run only one Server process for each SQLite file.

    Examples:

    
      labtasker-server serve
      LABTASKER_SERVER_TOKEN=secret labtasker-server serve \\
        --host 0.0.0.0 --database /data/labtasker.db
    """
    try:
        settings = ServerSettings.from_values(host=host, port=port, database=database)
    except ValueError as error:
        typer.echo(f"Server configuration error: {error}", err=True)
        raise typer.Exit(1) from error
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="info")
