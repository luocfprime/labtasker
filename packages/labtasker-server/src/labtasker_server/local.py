from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
import select
import socket
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from labtasker_server.filesystem import EffectiveDatabaseFilesystem
from labtasker_server.ownership import (
    OwnershipLock,
    acquire_sidecar_lock,
    canonical_path,
    ensure_runtime_directory,
    require_socket_capability,
    runtime_directory,
    sidecar_is_locked,
)

LOCAL_GITIGNORE = "*\n!.gitignore\n"
STARTUP_WAIT_SECONDS = 30.0
HEALTH_POLL_SECONDS = 0.05
METADATA_VERSION = 2
Connection = Literal["http", "socket"]


@dataclass(frozen=True, slots=True)
class LocalPaths:
    labtasker_root: Path
    database: Path
    log: Path
    runtime_directory: Path
    socket: Path
    metadata: Path


@dataclass(frozen=True, slots=True)
class DaemonConfig:
    labtasker_root: Path
    database: Path
    database_filesystem: EffectiveDatabaseFilesystem
    connection: Connection
    host: str | None
    port: int | None
    socket: Path | None
    authentication_enabled: bool
    server_version: str

    def comparable(self) -> dict[str, object]:
        return {
            "labtasker_root": str(self.labtasker_root),
            "database": str(self.database),
            "database_filesystem": self.database_filesystem,
            "connection": self.connection,
            "host": self.host,
            "port": self.port,
            "socket": str(self.socket) if self.socket is not None else None,
            "authentication_enabled": self.authentication_enabled,
            "server_version": self.server_version,
        }


@dataclass(frozen=True, slots=True)
class RuntimeMetadata:
    metadata_version: int
    generation: str
    role: Literal["coordinator", "daemon"]
    listener_bound: bool
    pid: int
    process_start_marker: str
    started_at: float
    labtasker_root: str
    database: str
    database_filesystem: EffectiveDatabaseFilesystem
    connection: Connection
    host: str | None
    port: int | None
    socket: str | None
    log: str
    authentication_enabled: bool
    server_version: str

    def comparable(self) -> dict[str, object]:
        return {
            "labtasker_root": self.labtasker_root,
            "database": self.database,
            "database_filesystem": self.database_filesystem,
            "connection": self.connection,
            "host": self.host,
            "port": self.port,
            "socket": self.socket,
            "authentication_enabled": self.authentication_enabled,
            "server_version": self.server_version,
        }


def local_paths(labtasker_root: Path | None = None) -> LocalPaths:
    require_socket_capability()
    root = canonical_path(Path.cwd() / ".labtasker" if labtasker_root is None else labtasker_root)
    digest = hashlib.sha256(os.fsencode(root)).hexdigest()
    runtime = runtime_directory()
    return LocalPaths(
        labtasker_root=root,
        database=root / "server.db",
        log=root / "server.log",
        runtime_directory=runtime,
        socket=runtime / f"root-{digest}.sock",
        metadata=runtime / f"root-{digest}.json",
    )


def ensure_labtasker_root(paths: LocalPaths) -> None:
    paths.labtasker_root.mkdir(parents=True, exist_ok=True)
    try:
        with (paths.labtasker_root / ".gitignore").open(
            "x", encoding="utf-8", newline="\n"
        ) as stream:
            stream.write(LOCAL_GITIGNORE)
    except FileExistsError:
        pass


def process_start_marker(pid: int) -> str | None:
    proc_stat = Path(f"/proc/{pid}/stat")
    try:
        suffix = proc_stat.read_text(encoding="utf-8").rsplit(")", 1)[1].split()
        return f"proc:{suffix[19]}"
    except (OSError, IndexError):
        pass
    try:
        result = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            check=False,
            capture_output=True,
            text=True,
            timeout=1,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    marker = result.stdout.strip()
    return f"ps:{marker}" if result.returncode == 0 and marker else None


def make_metadata(
    config: DaemonConfig,
    *,
    generation: str,
    role: Literal["coordinator", "daemon"],
    listener_bound: bool = False,
    pid: int,
    started_at: float,
) -> RuntimeMetadata:
    marker = process_start_marker(pid)
    if marker is None:
        raise RuntimeError(f"Could not determine process identity for PID {pid}.")
    paths = local_paths(config.labtasker_root)
    return RuntimeMetadata(
        metadata_version=METADATA_VERSION,
        generation=generation,
        role=role,
        listener_bound=listener_bound,
        pid=pid,
        process_start_marker=marker,
        started_at=started_at,
        labtasker_root=str(config.labtasker_root),
        database=str(config.database),
        database_filesystem=config.database_filesystem,
        connection=config.connection,
        host=config.host,
        port=config.port,
        socket=str(config.socket) if config.socket is not None else None,
        log=str(paths.log),
        authentication_enabled=config.authentication_enabled,
        server_version=config.server_version,
    )


def write_metadata(paths: LocalPaths, metadata: RuntimeMetadata) -> None:
    ensure_runtime_directory()
    fd, temporary = tempfile.mkstemp(prefix=f".{paths.metadata.name}.", dir=paths.runtime_directory)
    try:
        os.fchmod(fd, 0o600)
        payload = (json.dumps(asdict(metadata), sort_keys=True) + "\n").encode()
        with os.fdopen(fd, "wb", closefd=True) as stream:
            fd = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, paths.metadata)
    finally:
        if fd >= 0:
            os.close(fd)
        with suppress(FileNotFoundError):
            os.unlink(temporary)


def read_metadata(paths: LocalPaths) -> RuntimeMetadata | None:
    try:
        info = paths.metadata.lstat()
        effective_uid = os.geteuid() if hasattr(os, "geteuid") else os.getuid()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != effective_uid:
            return None
        raw = json.loads(paths.metadata.read_text(encoding="utf-8"))
        metadata = RuntimeMetadata(**raw)
    except (OSError, ValueError, TypeError, RecursionError, OverflowError):
        return None
    if not _valid_metadata(paths, metadata):
        return None
    return metadata


def metadata_owner_is_verified(metadata: RuntimeMetadata) -> bool:
    return process_start_marker(metadata.pid) == metadata.process_start_marker


def metadata_matches(config: DaemonConfig, metadata: RuntimeMetadata) -> bool:
    return metadata.comparable() == config.comparable()


def metadata_differences(
    config: DaemonConfig, metadata: RuntimeMetadata
) -> dict[str, tuple[object, object]]:
    desired = config.comparable()
    observed = metadata.comparable()
    return {
        key: (observed[key], desired[key]) for key in desired if observed.get(key) != desired[key]
    }


def daemon_state(paths: LocalPaths) -> Literal["running", "starting", "unhealthy", "stopped"]:
    if not sidecar_is_locked("root", paths.labtasker_root):
        return "stopped"
    metadata = read_metadata(paths)
    if metadata is None or not metadata_owner_is_verified(metadata):
        return "unhealthy"
    if metadata.role == "daemon" and metadata.listener_bound and metadata_health(metadata):
        return "running"
    age = time.time() - metadata.started_at
    if 0 <= age < STARTUP_WAIT_SECONDS:
        return "starting"
    return "unhealthy"


def metadata_health(metadata: RuntimeMetadata) -> bool:
    if metadata.connection == "socket" and metadata.socket is not None:
        return socket_health(Path(metadata.socket))
    if metadata.connection == "http" and metadata.host is not None and metadata.port is not None:
        return http_health(metadata.host, metadata.port)
    return False


def socket_health(path: Path, *, timeout: float = 0.2) -> bool:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(timeout)
            connection.connect(str(path))
            return _send_health_request(connection)
    except OSError:
        return False


def http_health(host: str, port: int, *, timeout: float = 0.2) -> bool:
    health_host = _health_host(host)
    try:
        with socket.create_connection((health_host, port), timeout=timeout) as connection:
            return _send_health_request(connection)
    except OSError:
        return False


def wait_for_health(config: DaemonConfig, *, deadline: float) -> bool:
    while time.monotonic() < deadline:
        if config_health(config):
            return True
        time.sleep(HEALTH_POLL_SECONDS)
    return config_health(config)


def config_health(config: DaemonConfig) -> bool:
    if config.connection == "socket":
        assert config.socket is not None
        return socket_health(config.socket)
    assert config.host is not None and config.port is not None
    return http_health(config.host, config.port)


def ensure_daemon(
    config: DaemonConfig,
    *,
    emit: Callable[[str], None],
) -> tuple[bool, RuntimeMetadata]:
    paths = local_paths(config.labtasker_root)
    deadline = time.monotonic() + STARTUP_WAIT_SECONDS
    try:
        root_lock = acquire_sidecar_lock("root", paths.labtasker_root)
    except BlockingIOError:
        return _observe_existing_daemon(config, paths, deadline=deadline, emit=emit)

    try:
        ensure_labtasker_root(paths)
        _cleanup_stale_runtime(paths)
        generation = secrets.token_urlsafe(18)
        started_at = time.time()
        write_metadata(
            paths,
            make_metadata(
                config,
                generation=generation,
                role="coordinator",
                pid=os.getpid(),
                started_at=started_at,
            ),
        )
        process, readiness_fd = _spawn_daemon(
            config,
            paths,
            root_lock=root_lock,
            generation=generation,
            started_at=started_at,
        )
    except BaseException:
        root_lock.close()
        raise
    root_lock.close()
    emit(f"started daemon pid={process.pid}")
    try:
        _wait_for_bind_confirmation(readiness_fd, generation, deadline=deadline)
    finally:
        os.close(readiness_fd)
    if not wait_for_health(config, deadline=deadline):
        raise RuntimeError(f"Daemon did not become healthy within 30 seconds; log={paths.log}")
    metadata = read_metadata(paths)
    if metadata is None or metadata.generation != generation:
        raise RuntimeError("Daemon became healthy without matching runtime metadata.")
    return True, metadata


def remove_stopped_artifacts(paths: LocalPaths, *, generation: str | None = None) -> None:
    metadata = read_metadata(paths)
    if generation is not None and (metadata is None or metadata.generation != generation):
        return
    socket_path = Path(metadata.socket) if metadata is not None and metadata.socket else None
    socket_lock: OwnershipLock | None = None
    try:
        if socket_path is not None:
            try:
                socket_lock = acquire_sidecar_lock("socket", socket_path)
            except BlockingIOError:
                return
            _remove_verified_stale_socket(socket_path)
        _remove_owned_regular_file(paths.metadata)
    finally:
        if socket_lock is not None:
            socket_lock.close()


def acquire_socket_lock(path: Path) -> OwnershipLock:
    require_socket_capability()
    lock = acquire_sidecar_lock("socket", path)
    try:
        _validate_socket_parent(path)
        _remove_verified_stale_socket(path)
    except BaseException:
        lock.close()
        raise
    return lock


def _observe_existing_daemon(
    config: DaemonConfig,
    paths: LocalPaths,
    *,
    deadline: float,
    emit: Callable[[str], None],
) -> tuple[bool, RuntimeMetadata]:
    while time.monotonic() < deadline:
        metadata = read_metadata(paths)
        if metadata is not None and metadata_owner_is_verified(metadata):
            if not metadata_matches(config, metadata):
                differences = metadata_differences(config, metadata)
                raise RuntimeError(
                    "Daemon configuration conflicts: "
                    f"{differences!r}. Stop it with 'labtasker-server stop "
                    f"--labtasker-root {paths.labtasker_root}' before retrying."
                )
            if metadata.role == "daemon" and metadata.listener_bound and config_health(config):
                return False, metadata
            emit(f"waiting for daemon pid={metadata.pid}")
        time.sleep(HEALTH_POLL_SECONDS)
    raise RuntimeError(
        f"Labtasker root is owned but its daemon is unhealthy: {paths.labtasker_root}"
    )


def _spawn_daemon(
    config: DaemonConfig,
    paths: LocalPaths,
    *,
    root_lock: OwnershipLock,
    generation: str,
    started_at: float,
) -> tuple[subprocess.Popen[bytes], int]:
    read_fd, write_fd = os.pipe()
    os.set_inheritable(root_lock.fd, True)
    os.set_inheritable(write_fd, True)
    command = [
        sys.executable,
        "-m",
        "labtasker_server",
        "_daemon",
        "--labtasker-root",
        str(config.labtasker_root),
        "--database",
        str(config.database),
        "--database-filesystem",
        config.database_filesystem,
        "--connection",
        config.connection,
        "--root-lock-fd",
        str(root_lock.fd),
        "--readiness-fd",
        str(write_fd),
        "--generation",
        generation,
        "--started-at",
        str(started_at),
    ]
    if config.connection == "http":
        assert config.host is not None and config.port is not None
        command.extend(["--host", config.host, "--port", str(config.port)])
    else:
        assert config.socket is not None
        command.extend(["--socket", str(config.socket)])
    paths.log.parent.mkdir(parents=True, exist_ok=True)
    try:
        with paths.log.open("ab", buffering=0) as log:
            process = subprocess.Popen(
                command,
                cwd=config.labtasker_root,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                pass_fds=(root_lock.fd, write_fd),
            )
    except BaseException:
        os.close(read_fd)
        os.close(write_fd)
        raise
    finally:
        os.set_inheritable(root_lock.fd, False)
    os.close(write_fd)
    return process, read_fd


def _wait_for_bind_confirmation(fd: int, generation: str, *, deadline: float) -> None:
    remaining = max(0.0, deadline - time.monotonic())
    readable, _, _ = select.select([fd], [], [], remaining)
    if not readable:
        raise RuntimeError("Daemon did not confirm listener binding within 30 seconds.")
    payload = os.read(fd, 4096).decode("utf-8", errors="replace").strip()
    if payload != generation:
        raise RuntimeError("Daemon listener confirmation was missing or invalid.")


def _send_health_request(connection: socket.socket) -> bool:
    connection.sendall(b"GET /health HTTP/1.1\r\nHost: labtasker\r\nConnection: close\r\n\r\n")
    response = bytearray()
    while len(response) <= 65536:
        chunk = connection.recv(8192)
        if not chunk:
            break
        response.extend(chunk)
    head, separator, body = bytes(response).partition(b"\r\n\r\n")
    if not separator or not head.startswith(b"HTTP/1.1 200"):
        return False
    try:
        payload: object = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return payload == {"status": "ok", "api_version": "2", "database": "ok"}


def _health_host(host: str) -> str:
    if host == "0.0.0.0":
        return "127.0.0.1"
    if host == "::":
        return "::1"
    return host


def _cleanup_stale_runtime(paths: LocalPaths) -> None:
    metadata = read_metadata(paths)
    if metadata is not None and metadata.socket is not None:
        socket_path = Path(metadata.socket)
        socket_lock = acquire_socket_lock(socket_path)
        socket_lock.close()
    _remove_owned_regular_file(paths.metadata)


def _remove_owned_regular_file(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    effective_uid = os.geteuid() if hasattr(os, "geteuid") else os.getuid()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != effective_uid:
        raise RuntimeError(f"Refusing to remove unverified runtime artifact: {path}")
    path.unlink()


def _remove_verified_stale_socket(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    effective_uid = os.geteuid() if hasattr(os, "geteuid") else os.getuid()
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != effective_uid:
        raise RuntimeError(f"Refusing to replace unverified socket path: {path}")
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(0.2)
            connection.connect(str(path))
    except ConnectionRefusedError:
        pass
    except FileNotFoundError:
        return
    except OSError as error:
        raise RuntimeError(
            f"Could not verify that socket is stale; refusing to replace it: {path}"
        ) from error
    else:
        raise RuntimeError(f"Socket already has a live listener: {path}")
    path.unlink()


def _validate_socket_parent(path: Path) -> None:
    parent = path.parent
    try:
        info = parent.lstat()
    except FileNotFoundError:
        parent.mkdir(parents=True, mode=0o700)
        info = parent.lstat()
    writable = stat.S_IMODE(info.st_mode) & 0o022
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or (writable and not stat.S_IMODE(info.st_mode) & stat.S_ISVTX)
    ):
        raise RuntimeError(f"Unix socket parent is unsafe: {parent}")


def _valid_metadata(paths: LocalPaths, metadata: RuntimeMetadata) -> bool:
    return bool(
        isinstance(metadata.metadata_version, int)
        and not isinstance(metadata.metadata_version, bool)
        and metadata.metadata_version == METADATA_VERSION
        and isinstance(metadata.generation, str)
        and metadata.generation
        and metadata.role in {"coordinator", "daemon"}
        and isinstance(metadata.listener_bound, bool)
        and isinstance(metadata.pid, int)
        and not isinstance(metadata.pid, bool)
        and metadata.pid > 0
        and isinstance(metadata.process_start_marker, str)
        and metadata.process_start_marker
        and isinstance(metadata.started_at, (int, float))
        and not isinstance(metadata.started_at, bool)
        and math.isfinite(metadata.started_at)
        and metadata.labtasker_root == str(paths.labtasker_root)
        and isinstance(metadata.database, str)
        and metadata.database_filesystem in {"local", "shared"}
        and metadata.connection in {"http", "socket"}
        and (metadata.host is None or isinstance(metadata.host, str))
        and (
            metadata.port is None
            or (
                isinstance(metadata.port, int)
                and not isinstance(metadata.port, bool)
                and 1 <= metadata.port <= 65535
            )
        )
        and (metadata.socket is None or isinstance(metadata.socket, str))
        and metadata.log == str(paths.log)
        and isinstance(metadata.authentication_enabled, bool)
        and isinstance(metadata.server_version, str)
        and metadata.server_version
    )
