import os
from enum import Enum
from pathlib import Path
from typing import Optional

import typer
import uvicorn

from labtasker.filtering import install_traceback_filter
from labtasker.server.config import get_server_config, init_server_config
from labtasker.server.database import DBService, set_db_service
from labtasker.server.embedded_db import MongoClient, ServerStore
from labtasker.server.logging import log_config

install_traceback_filter()

cli = typer.Typer(context_settings={"help_option_names": ["-h", "--help"]})


class DbMode(str, Enum):
    EMBEDDED = "embedded"
    EXTERNAL = "external"


@cli.callback(invoke_without_command=True)
def callback(ctx: typer.Context):
    if not ctx.invoked_subcommand:
        print(ctx.get_help())
        raise typer.Exit()


@cli.command()
def serve(
    host: str = typer.Option(
        "0.0.0.0", envvar="API_HOST", help="IP address of the server."
    ),
    port: int = typer.Option(9321, envvar="API_PORT", help="Port to listen to."),
    db_mode: DbMode = typer.Option(
        "embedded", case_sensitive=False, envvar="DB_MODE", help="Database mode."
    ),
    db_path: Path = typer.Option(
        Path("labtasker_db.json"),
        writable=True,
        readable=True,
        help="Path to the database persistence file.",
    ),
    env_file: Optional[Path] = typer.Option(
        None,
        help="Path to the server.env file to load.",
    ),
):
    """Create a local server with a Python emulated MongoDB.
    (It is recommended to use the docker compose instead of this.)
    """
    if db_mode == "embedded":
        # authentication is not needed, as we are using Python emulated embedded DB
        os.environ["DB_USER"] = "admin"
        os.environ["DB_PASSWORD"] = "admin"

    os.environ["API_HOST"] = host
    os.environ["API_PORT"] = str(port)

    init_server_config(env_file)
    config = get_server_config()

    if db_mode == "embedded":
        set_db_service(
            DBService(
                db_name=config.db_name,
                client=MongoClient(
                    _store=ServerStore(persistence_path=str(db_path)),
                ),
            )
        )
    else:
        set_db_service(DBService(db_name=config.db_name, uri=config.mongodb_uri))

    # import after set_db_service
    from labtasker.server.endpoints import app

    uvicorn.run(app, host=config.api_host, port=config.api_port, log_config=log_config)


def main():
    # Use this to invoke command to prevent typer overriding exception hook
    return typer.main.get_command(cli).main()


if __name__ == "__main__":
    main()
