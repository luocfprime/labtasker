from __future__ import annotations

import json
import os
import signal
import socket
import time
from contextlib import suppress
from pathlib import Path
from typing import Annotated

import typer
import uvicorn

from labtasker_server import __version__
from labtasker_server.app import create_app
from labtasker_server.config import ServerSettings
from labtasker_server.database import DatabaseOwnershipError
from labtasker_server.local import (
    database_identity,
    database_is_free,
    ensure_local_daemon,
    ensure_runtime_directory,
    has_runtime_artifacts,
    local_paths,
    make_metadata,
    metadata_matches_database,
    metadata_owner_is_verified,
    read_metadata,
    remove_generation_artifacts,
    remove_generation_socket,
    remove_stale_artifacts,
    require_local_capabilities,
    socket_health,
    startup_age,
    throttle_remaining,
    write_metadata,
)
from labtasker_server.logging import uvicorn_log_config

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

    \b
      labtasker-server serve
      LABTASKER_SERVER_TOKEN=secret labtasker-server serve \\
        --host 0.0.0.0 --database /data/labtasker.db
    """
    try:
        settings = ServerSettings.from_values(host=host, port=port, database=database)
    except ValueError as error:
        typer.echo(f"[labtasker-server] Server configuration error: {error}", err=True)
        raise typer.Exit(1) from error
    try:
        application = create_app(settings)
    except (DatabaseOwnershipError, OSError, RuntimeError) as error:
        typer.echo(f"[labtasker-server] Server startup error: {error}", err=True)
        raise typer.Exit(1) from error
    uvicorn.run(
        application,
        host=settings.host,
        port=settings.port,
        log_level="info",
        log_config=uvicorn_log_config(),
    )


@app.command()
def start() -> None:
    """Start the current directory's local daemon, or report the existing one."""
    try:
        paths = local_paths()
        started, metadata = ensure_local_daemon(
            paths.directory,
            bypass_throttle=True,
            server_version=__version__,
            emit=lambda message: typer.echo(f"[labtasker-server] {message}", err=True),
        )
    except (OSError, RuntimeError) as error:
        typer.echo(f"[labtasker-server] Local Server startup error: {error}", err=True)
        raise typer.Exit(1) from error
    action = "started" if started else "already running"
    pid = metadata.pid if metadata is not None else "unknown"
    typer.echo(
        f"[labtasker-server] {action} local daemon pid={pid} socket={paths.socket}",
        err=True,
    )


@app.command("_ensure-daemon", hidden=True)
def ensure_daemon(
    directory: Annotated[Path, typer.Option(hidden=True)],
) -> None:
    """Ensure one healthy local daemon for an automatic Client request."""
    try:
        paths = local_paths(directory)
        started, metadata = ensure_local_daemon(
            paths.directory,
            bypass_throttle=False,
            server_version=__version__,
            emit=lambda message: typer.echo(f"[labtasker-server] {message}", err=True),
        )
    except (OSError, RuntimeError) as error:
        typer.echo(f"[labtasker-server] automatic local startup error: {error}", err=True)
        try:
            result = _local_status(directory)
        except (OSError, RuntimeError):
            result = {
                "state": "unhealthy",
                "directory": str(directory.resolve()),
                "database": None,
                "socket": None,
                "log": None,
                "pid": None,
                "version": None,
                "retry_after_seconds": None,
            }
        result.update({"ok": False, "message": str(error)})
        typer.echo(json.dumps(result, ensure_ascii=False))
        raise typer.Exit(1) from error
    result = _local_status(paths.directory)
    result.update(
        {
            "ok": True,
            "started": started,
            "pid": metadata.pid if metadata is not None else result["pid"],
            "version": (metadata.server_version if metadata is not None else result["version"]),
        }
    )
    typer.echo(json.dumps(result, ensure_ascii=False))


@app.command()
def status() -> None:
    """Print the current directory's local daemon status as JSON."""
    try:
        paths = local_paths()
        result = _local_status(paths.directory)
    except (OSError, RuntimeError) as error:
        typer.echo(f"[labtasker-server] Local Server status error: {error}", err=True)
        raise typer.Exit(1) from error
    typer.echo(json.dumps(result, indent=2, ensure_ascii=False) + "\n", nl=False)


@app.command()
def stop(
    force: Annotated[
        bool,
        typer.Option(help="Send SIGKILL after the 30-second graceful deadline."),
    ] = False,
) -> None:
    """Stop the current directory's verified local daemon."""
    try:
        paths = local_paths()
    except RuntimeError as error:
        typer.echo(f"[labtasker-server] Local Server stop error: {error}", err=True)
        raise typer.Exit(1) from error
    metadata = read_metadata(paths)
    if database_is_free(paths):
        if has_runtime_artifacts(paths):
            try:
                remove_stale_artifacts(paths)
            except RuntimeError as error:
                typer.echo(f"[labtasker-server] Local Server stop error: {error}", err=True)
                raise typer.Exit(1) from error
        typer.echo("[labtasker-server] local daemon is already stopped", err=True)
        return
    if (
        metadata is None
        or metadata.role != "daemon"
        or not metadata_owner_is_verified(paths, metadata)
    ):
        typer.echo(
            "[labtasker-server] Local Server stop error: "
            "database owner is not a verified local daemon.",
            err=True,
        )
        raise typer.Exit(1)

    with suppress(ProcessLookupError):
        os.kill(metadata.pid, signal.SIGTERM)
    typer.echo(f"[labtasker-server] stopping local daemon pid={metadata.pid}", err=True)
    if _wait_for_exit(paths.directory, timeout=30.0):
        remove_generation_artifacts(paths, metadata.generation)
        typer.echo(f"[labtasker-server] stopped local daemon pid={metadata.pid}", err=True)
        return
    if not force:
        typer.echo(
            "[labtasker-server] Local Server stop error: daemon did not stop within "
            "30 seconds; retry with --force.",
            err=True,
        )
        raise typer.Exit(1)

    current = read_metadata(paths)
    if (
        current is None
        or current.generation != metadata.generation
        or not metadata_owner_is_verified(paths, current)
    ):
        typer.echo(
            "[labtasker-server] Local Server stop error: "
            "daemon identity changed; refusing SIGKILL.",
            err=True,
        )
        raise typer.Exit(1)
    os.kill(current.pid, signal.SIGKILL)
    typer.echo(f"[labtasker-server] force-stopping local daemon pid={current.pid}", err=True)
    if not _wait_for_exit(paths.directory, timeout=5.0):
        typer.echo(
            "[labtasker-server] Local Server stop error: database ownership was not released.",
            err=True,
        )
        raise typer.Exit(1)
    remove_generation_artifacts(paths, current.generation)
    typer.echo(f"[labtasker-server] stopped local daemon pid={current.pid}", err=True)


@app.command()
def logs() -> None:
    """Print the current directory's complete local Server log."""
    try:
        path = local_paths().log
        typer.echo(path.read_text(encoding="utf-8"), nl=False)
    except FileNotFoundError:
        return
    except (OSError, UnicodeError) as error:
        typer.echo(f"[labtasker-server] Local Server log error: {error}", err=True)
        raise typer.Exit(1) from error


@app.command("_daemon", hidden=True)
def daemon(
    directory: Annotated[Path, typer.Option(hidden=True)],
    database_fd: Annotated[int, typer.Option(hidden=True)],
    generation: Annotated[str, typer.Option(hidden=True)],
    automatic_attempt_at: Annotated[float, typer.Option(hidden=True)],
) -> None:
    """Run one private local daemon process."""
    paths = local_paths(directory)
    listener: socket.socket | None = None
    try:
        require_local_capabilities()
        ensure_runtime_directory(paths)
        metadata = make_metadata(
            paths,
            generation=generation,
            role="daemon",
            pid=os.getpid(),
            automatic_attempt_at=automatic_attempt_at,
            database_fd=database_fd,
            server_version=__version__,
        )
        write_metadata(paths, metadata)
        if database_identity(database_fd) != (
            metadata.database_device,
            metadata.database_inode,
        ):
            raise RuntimeError("Inherited database identity changed.")
        settings = ServerSettings(database=paths.database, token=None, database_fd=database_fd)
        application = create_app(settings)
        os.close(database_fd)
        database_fd = -1

        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(paths.socket))
        os.chmod(paths.socket, 0o600)
        uvicorn.run(
            application,
            fd=listener.fileno(),
            log_level="info",
            log_config=uvicorn_log_config(),
        )
    except BaseException as error:
        typer.echo(f"[labtasker-server] Local daemon failed: {error}", err=True)
        raise
    finally:
        if database_fd >= 0:
            os.close(database_fd)
        if listener is not None:
            listener.close()
        # Preserve the attempt metadata so an unexpected exit remains throttled.
        # An explicit successful stop removes the full generation itself.
        remove_generation_socket(paths, generation)


def _local_status(directory: Path) -> dict[str, object]:
    paths = local_paths(directory)
    metadata = read_metadata(paths)
    if socket_health(paths):
        state = "running"
        retry_after: float | None = None
    elif not database_is_free(paths):
        state = (
            "starting"
            if metadata is not None
            and metadata_owner_is_verified(paths, metadata)
            and startup_age(metadata) is not None
            else "unhealthy"
        )
        retry_after = None
    else:
        remaining = (
            throttle_remaining(metadata)
            if metadata is not None and metadata_matches_database(paths, metadata)
            else 0.0
        )
        if remaining > 0:
            state = "backoff"
            retry_after = round(remaining, 3)
        elif has_runtime_artifacts(paths):
            state = "stale"
            retry_after = None
        else:
            state = "stopped"
            retry_after = None
    verified = metadata is not None and metadata_owner_is_verified(paths, metadata)
    return {
        "state": state,
        "directory": str(paths.directory),
        "database": str(paths.database),
        "socket": str(paths.socket),
        "log": str(paths.log),
        "pid": metadata.pid if verified and metadata is not None else None,
        "version": metadata.server_version if verified and metadata is not None else None,
        "retry_after_seconds": retry_after,
    }


def _wait_for_exit(directory: Path, *, timeout: float) -> bool:
    paths = local_paths(directory)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if database_is_free(paths):
            return True
        time.sleep(0.05)
    return database_is_free(paths)
