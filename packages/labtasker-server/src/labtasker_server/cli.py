from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
import uvicorn

from labtasker_server.app import create_app
from labtasker_server.config import ServerSettings

app = typer.Typer(
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
    host: Annotated[str, typer.Option(help="Address to bind.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(min=1, max=65535, help="TCP port.")] = 8000,
    database: Annotated[Path, typer.Option(help="SQLite database path.")] = Path(
        ".labtasker/server.db"
    ),
) -> None:
    """Run one Labtasker v2 Server process."""
    settings = ServerSettings.from_values(host=host, port=port, database=database)
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="info")
