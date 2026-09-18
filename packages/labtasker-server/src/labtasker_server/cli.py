from __future__ import annotations

import json
import os
import signal
import socket
import stat
import time
from contextlib import suppress
from pathlib import Path
from typing import Annotated, Literal

import typer
import uvicorn

from labtasker_server import __version__
from labtasker_server.app import create_app
from labtasker_server.config import ServerSettings
from labtasker_server.database import DatabaseOwnershipError
from labtasker_server.filesystem import DatabaseFilesystem, resolve_database_filesystem
from labtasker_server.local import (
    DaemonConfig,
    LocalPaths,
    RuntimeMetadata,
    acquire_socket_lock,
    daemon_state,
    ensure_daemon,
    local_paths,
    make_metadata,
    metadata_owner_is_verified,
    read_metadata,
    remove_stopped_artifacts,
    write_metadata,
)
from labtasker_server.logging import uvicorn_log_config
from labtasker_server.ownership import (
    OwnershipLock,
    acquire_sidecar_lock,
    canonical_path,
    sidecar_path,
)

Connection = Literal["http", "socket"]
app = typer.Typer(
    help="Run and manage the Labtasker v2 Server.",
    add_completion=False,
    no_args_is_help=True,
    pretty_exceptions_enable=False,
    rich_markup_mode=None,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"labtasker-server {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the Server package version and exit.",
        ),
    ] = False,
) -> None:
    """Run and manage the Labtasker v2 Server."""


@app.command()
def serve(
    connection: Annotated[
        Connection,
        typer.Option(help="Required transport: HTTP TCP listener or Unix socket."),
    ],
    labtasker_root: Annotated[
        Path | None,
        typer.Option(help="Managed-daemon state and default database root."),
    ] = None,
    database: Annotated[
        Path | None,
        typer.Option(help="SQLite database file owned by this Server process."),
    ] = None,
    database_filesystem: Annotated[
        DatabaseFilesystem,
        typer.Option(help="SQLite strategy: detect automatically, local, or shared."),
    ] = "auto",
    host: Annotated[
        str | None,
        typer.Option(help="HTTP bind address; valid only with --connection http."),
    ] = None,
    port: Annotated[
        int | None,
        typer.Option(min=1, max=65535, help="HTTP port; valid only with --connection http."),
    ] = None,
    socket_path: Annotated[
        Path | None,
        typer.Option("--socket", help="Unix socket path; valid only with --connection socket."),
    ] = None,
    daemon: Annotated[
        bool,
        typer.Option(help="Run detached and manage the process by Labtasker root."),
    ] = False,
) -> None:
    """Initialize SQLite and run one foreground or detached Server."""
    config, settings = _resolve_serve_config(
        connection=connection,
        labtasker_root=labtasker_root,
        database=database,
        database_filesystem=database_filesystem,
        host=host,
        port=port,
        socket_path=socket_path,
    )
    try:
        if daemon:
            started, metadata = ensure_daemon(
                config,
                emit=lambda _: None,
            )
            action = "started" if started else "already running"
            typer.echo(f"[labtasker-server] {action} daemon pid={metadata.pid}", err=True)
        else:
            _run_foreground(config, settings)
    except (DatabaseOwnershipError, OSError, RuntimeError) as error:
        typer.echo(f"[labtasker-server] Server startup error: {error}", err=True)
        raise typer.Exit(1) from error


@app.command("_ensure-daemon", hidden=True)
def ensure_daemon_command(
    labtasker_root: Annotated[Path, typer.Option()],
) -> None:
    """Ensure one healthy managed-local daemon for an authorized Client request."""
    try:
        paths = local_paths(labtasker_root)
        resolved = resolve_database_filesystem(paths.database, "auto")
        if resolved.detection is None or resolved.detection.classification != "local":
            kind = (
                resolved.detection.filesystem_type
                if resolved.detection is not None
                else "unavailable"
            )
            raise RuntimeError(
                f"Automatic local startup requires known local storage; detected {kind!r}. "
                "Launch labtasker-server serve explicitly."
            )
        config = DaemonConfig(
            labtasker_root=paths.labtasker_root,
            database=paths.database,
            database_filesystem="local",
            connection="socket",
            host=None,
            port=None,
            socket=paths.socket,
            authentication_enabled=False,
            server_version=__version__,
        )
        started, metadata = ensure_daemon(
            config,
            emit=lambda message: typer.echo(f"[labtasker-server] {message}", err=True),
        )
    except (OSError, RuntimeError) as error:
        typer.echo(f"[labtasker-server] automatic local startup error: {error}", err=True)
        result = _status_payload(local_paths(labtasker_root))
        result.update({"ok": False, "message": str(error)})
        typer.echo(json.dumps(result, ensure_ascii=False))
        raise typer.Exit(1) from error
    result = _status_payload(paths)
    result.update(
        {
            "ok": True,
            "started": started,
            "pid": metadata.pid,
            "version": metadata.server_version,
        }
    )
    typer.echo(json.dumps(result, ensure_ascii=False))


@app.command("_daemon", hidden=True)
def daemon_command(
    labtasker_root: Annotated[Path, typer.Option()],
    database: Annotated[Path, typer.Option()],
    database_filesystem: Annotated[Literal["local", "shared"], typer.Option()],
    connection: Annotated[Connection, typer.Option()],
    root_lock_fd: Annotated[int, typer.Option()],
    readiness_fd: Annotated[int, typer.Option()],
    generation: Annotated[str, typer.Option()],
    started_at: Annotated[float, typer.Option()],
    host: Annotated[str | None, typer.Option()] = None,
    port: Annotated[int | None, typer.Option(min=1, max=65535)] = None,
    socket_path: Annotated[Path | None, typer.Option("--socket")] = None,
) -> None:
    """Run one private detached Server child."""
    config, settings = _resolve_serve_config(
        connection=connection,
        labtasker_root=labtasker_root,
        database=database,
        database_filesystem=database_filesystem,
        host=host,
        port=port,
        socket_path=socket_path,
    )
    paths = local_paths(config.labtasker_root)
    root_lock = _inherited_root_lock(config.labtasker_root, root_lock_fd)
    listener: socket.socket | None = None
    socket_lock: OwnershipLock | None = None
    application: object | None = None
    try:
        write_metadata(
            paths,
            make_metadata(
                config,
                generation=generation,
                role="daemon",
                listener_bound=False,
                pid=os.getpid(),
                started_at=started_at,
            ),
        )
        if config.connection == "socket":
            assert config.socket is not None
            socket_lock = acquire_socket_lock(config.socket)
        application = create_app(settings)
        listener = _bind_listener(config)
        write_metadata(
            paths,
            make_metadata(
                config,
                generation=generation,
                role="daemon",
                listener_bound=True,
                pid=os.getpid(),
                started_at=started_at,
            ),
        )
        os.write(readiness_fd, generation.encode("utf-8"))
        os.close(readiness_fd)
        readiness_fd = -1
        uvicorn.run(
            application,
            fd=listener.fileno(),
            log_level="info",
            log_config=uvicorn_log_config(),
        )
    except BaseException as error:
        typer.echo(f"[labtasker-server] daemon failed: {error}", err=True)
        raise
    finally:
        if readiness_fd >= 0:
            os.close(readiness_fd)
        if listener is not None:
            listener.close()
        _dispose_application(application)
        if config.socket is not None and socket_lock is not None:
            _unlink_owned_socket(config.socket)
        if socket_lock is not None:
            socket_lock.close()
        remove_stopped_artifacts(paths, generation=generation)
        root_lock.close()


@app.command()
def status(
    labtasker_root: Annotated[Path | None, typer.Option()] = None,
) -> None:
    """Print managed-daemon status as JSON without creating or cleaning state."""
    paths = local_paths(labtasker_root)
    typer.echo(json.dumps(_status_payload(paths), indent=2, ensure_ascii=False) + "\n", nl=False)


@app.command()
def stop(
    labtasker_root: Annotated[Path | None, typer.Option()] = None,
    force: Annotated[
        bool,
        typer.Option(help="Send SIGKILL after the 30-second graceful deadline."),
    ] = False,
) -> None:
    """Stop the verified daemon selected by exact Labtasker root."""
    paths = local_paths(labtasker_root)
    state = daemon_state(paths)
    if state == "stopped":
        _cleanup_stopped_root(paths)
        typer.echo("[labtasker-server] daemon is already stopped", err=True)
        return
    metadata = read_metadata(paths)
    if metadata is None or metadata.role != "daemon" or not metadata_owner_is_verified(metadata):
        typer.echo(
            "[labtasker-server] Server stop error: root owner is not a verified daemon.",
            err=True,
        )
        raise typer.Exit(1)
    with suppress(ProcessLookupError):
        os.kill(metadata.pid, signal.SIGTERM)
    if _wait_for_root_release(paths, timeout=30.0):
        _cleanup_generation(paths, metadata)
        typer.echo(f"[labtasker-server] stopped daemon pid={metadata.pid}", err=True)
        return
    if not force:
        typer.echo(
            "[labtasker-server] Server stop error: daemon did not stop within 30 seconds; "
            "retry with --force.",
            err=True,
        )
        raise typer.Exit(1)
    current = read_metadata(paths)
    if (
        current is None
        or current.generation != metadata.generation
        or not metadata_owner_is_verified(current)
    ):
        typer.echo(
            "[labtasker-server] Server stop error: daemon identity changed; refusing SIGKILL.",
            err=True,
        )
        raise typer.Exit(1)
    os.kill(current.pid, signal.SIGKILL)
    if not _wait_for_root_release(paths, timeout=5.0):
        typer.echo(
            "[labtasker-server] Server stop error: root ownership was not released.",
            err=True,
        )
        raise typer.Exit(1)
    _cleanup_generation(paths, current)
    typer.echo(f"[labtasker-server] stopped daemon pid={current.pid}", err=True)


@app.command()
def logs(
    labtasker_root: Annotated[Path | None, typer.Option()] = None,
) -> None:
    """Print the selected daemon's complete UTF-8 log."""
    path = local_paths(labtasker_root).log
    try:
        typer.echo(path.read_text(encoding="utf-8"), nl=False)
    except FileNotFoundError:
        return
    except (OSError, UnicodeError) as error:
        typer.echo(f"[labtasker-server] Server log error: {error}", err=True)
        raise typer.Exit(1) from error


def _resolve_serve_config(
    *,
    connection: Connection,
    labtasker_root: Path | None,
    database: Path | None,
    database_filesystem: DatabaseFilesystem,
    host: str | None,
    port: int | None,
    socket_path: Path | None,
) -> tuple[DaemonConfig, ServerSettings]:
    root = canonical_path(Path.cwd() / ".labtasker" if labtasker_root is None else labtasker_root)
    database_path = canonical_path(root / "server.db" if database is None else database)
    resolved = resolve_database_filesystem(database_path, database_filesystem)
    if resolved.warning is not None:
        typer.echo(f"[labtasker-server] warning: {resolved.warning}", err=True)
    if connection == "http":
        if socket_path is not None:
            raise typer.BadParameter("--socket is valid only with --connection socket")
        effective_host = "127.0.0.1" if host is None else host
        effective_port = 8000 if port is None else port
        try:
            settings = ServerSettings.from_values(
                host=effective_host,
                port=effective_port,
                database=database_path,
                database_filesystem=resolved.effective,
            )
        except ValueError as error:
            raise typer.BadParameter(str(error)) from error
        effective_socket = None
    else:
        if host is not None or port is not None:
            raise typer.BadParameter("--host and --port are valid only with --connection http")
        paths = local_paths(root)
        effective_socket = canonical_path(paths.socket if socket_path is None else socket_path)
        effective_host = None
        effective_port = None
        settings = ServerSettings(
            database=database_path,
            database_filesystem=resolved.effective,
            token=None,
        )
    config = DaemonConfig(
        labtasker_root=root,
        database=database_path,
        database_filesystem=resolved.effective,
        connection=connection,
        host=effective_host,
        port=effective_port,
        socket=effective_socket,
        authentication_enabled=settings.token is not None if connection == "http" else False,
        server_version=__version__,
    )
    return config, settings


def _run_foreground(config: DaemonConfig, settings: ServerSettings) -> None:
    socket_lock: OwnershipLock | None = None
    listener: socket.socket | None = None
    application: object | None = None
    try:
        if config.connection == "socket":
            assert config.socket is not None
            socket_lock = acquire_socket_lock(config.socket)
        application = create_app(settings)
        if config.connection == "http":
            assert config.host is not None and config.port is not None
            uvicorn.run(
                application,
                host=config.host,
                port=config.port,
                log_level="info",
                log_config=uvicorn_log_config(),
            )
        else:
            listener = _bind_listener(config)
            uvicorn.run(
                application,
                fd=listener.fileno(),
                log_level="info",
                log_config=uvicorn_log_config(),
            )
    finally:
        if listener is not None:
            listener.close()
        _dispose_application(application)
        if config.socket is not None and socket_lock is not None:
            _unlink_owned_socket(config.socket)
        if socket_lock is not None:
            socket_lock.close()


def _dispose_application(application: object | None) -> None:
    if application is None:
        return
    state = getattr(application, "state", None)
    database = getattr(state, "database", None)
    if database is not None:
        database.dispose()


def _bind_listener(config: DaemonConfig) -> socket.socket:
    if config.connection == "socket":
        assert config.socket is not None
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            listener.bind(str(config.socket))
            os.chmod(config.socket, 0o600)
            listener.listen(128)
        except BaseException:
            listener.close()
            raise
        return listener
    assert config.host is not None and config.port is not None
    addresses = socket.getaddrinfo(
        config.host,
        config.port,
        type=socket.SOCK_STREAM,
        flags=socket.AI_PASSIVE,
    )
    if not addresses:
        raise RuntimeError(f"Could not resolve HTTP bind address {config.host!r}.")
    family, kind, protocol, _, address = addresses[0]
    listener = socket.socket(family, kind, protocol)
    try:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(address)
        listener.listen(128)
    except BaseException:
        listener.close()
        raise
    return listener


def _inherited_root_lock(root: Path, fd: int) -> OwnershipLock:
    expected = sidecar_path("root", root)
    try:
        descriptor = os.fstat(fd)
        target = expected.stat()
    except OSError as error:
        raise RuntimeError("Inherited root lock is unavailable.") from error
    if (descriptor.st_dev, descriptor.st_ino) != (target.st_dev, target.st_ino):
        raise RuntimeError("Inherited root lock does not match the configured root.")
    os.set_inheritable(fd, False)
    return OwnershipLock(expected, fd)


def _status_payload(paths: LocalPaths) -> dict[str, object]:
    state = daemon_state(paths)
    metadata = read_metadata(paths)
    verified = metadata is not None and metadata_owner_is_verified(metadata)
    return {
        "state": state,
        "labtasker_root": str(paths.labtasker_root),
        "database": metadata.database if verified and metadata is not None else None,
        "database_filesystem": (
            metadata.database_filesystem if verified and metadata is not None else None
        ),
        "connection": metadata.connection if verified and metadata is not None else None,
        "host": metadata.host if verified and metadata is not None else None,
        "port": metadata.port if verified and metadata is not None else None,
        "socket": metadata.socket if verified and metadata is not None else None,
        "log": str(paths.log),
        "pid": metadata.pid if verified and metadata is not None else None,
        "version": metadata.server_version if verified and metadata is not None else None,
    }


def _wait_for_root_release(paths: LocalPaths, *, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if daemon_state(paths) == "stopped":
            return True
        time.sleep(0.05)
    return daemon_state(paths) == "stopped"


def _cleanup_stopped_root(paths: LocalPaths) -> None:
    try:
        root_lock = acquire_sidecar_lock("root", paths.labtasker_root)
    except BlockingIOError:
        return
    try:
        remove_stopped_artifacts(paths)
    finally:
        root_lock.close()


def _cleanup_generation(paths: LocalPaths, metadata: RuntimeMetadata) -> None:
    try:
        root_lock = acquire_sidecar_lock("root", paths.labtasker_root)
    except BlockingIOError:
        return
    try:
        remove_stopped_artifacts(paths, generation=metadata.generation)
    finally:
        root_lock.close()


def _unlink_owned_socket(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    effective_uid = os.geteuid() if hasattr(os, "geteuid") else os.getuid()
    if stat.S_ISSOCK(info.st_mode) and info.st_uid == effective_uid:
        path.unlink()
