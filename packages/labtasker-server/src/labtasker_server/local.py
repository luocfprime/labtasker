from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
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
from typing import Literal, cast

try:
    import fcntl
except ImportError:  # pragma: no cover - local mode is rejected off POSIX
    fcntl = None  # type: ignore[assignment]

LOCAL_GITIGNORE = "*\n!.gitignore\n"
LAUNCH_THROTTLE_SECONDS = 10.0
STARTUP_WAIT_SECONDS = 30.0
STARTUP_PUBLICATION_SECONDS = 1.0
HEALTH_POLL_SECONDS = 0.05
METADATA_VERSION = 1


@dataclass(frozen=True, slots=True)
class LocalPaths:
    directory: Path
    database: Path
    log: Path
    runtime_directory: Path
    socket: Path
    metadata: Path


@dataclass(frozen=True, slots=True)
class RuntimeMetadata:
    metadata_version: int
    generation: str
    role: Literal["coordinator", "daemon"]
    pid: int
    process_start_marker: str
    directory: str
    database: str
    database_device: int
    database_inode: int
    automatic_attempt_at: float
    server_version: str | None


def require_local_capabilities() -> None:
    if os.name != "posix" or fcntl is None or not hasattr(socket, "AF_UNIX"):
        raise RuntimeError("Local mode requires POSIX flock and Unix-domain sockets.")


def local_paths(directory: Path | None = None) -> LocalPaths:
    require_local_capabilities()
    canonical = (Path.cwd() if directory is None else directory).resolve()
    digest = hashlib.sha256(os.fsencode(canonical)).hexdigest()
    runtime_directory = Path("/tmp") / f"labtasker-{os.geteuid()}"
    local_directory = canonical / ".labtasker"
    return LocalPaths(
        directory=canonical,
        database=local_directory / "server.db",
        log=local_directory / "server.log",
        runtime_directory=runtime_directory,
        socket=runtime_directory / f"{digest}.sock",
        metadata=runtime_directory / f"{digest}.json",
    )


def ensure_local_storage(paths: LocalPaths) -> None:
    paths.database.parent.mkdir(parents=True, exist_ok=True)
    try:
        with (paths.database.parent / ".gitignore").open(
            "x", encoding="utf-8", newline="\n"
        ) as stream:
            stream.write(LOCAL_GITIGNORE)
    except FileExistsError:
        pass


def ensure_runtime_directory(paths: LocalPaths) -> None:
    with suppress(FileExistsError):
        paths.runtime_directory.mkdir(mode=0o700)
    info = paths.runtime_directory.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) & 0o077
    ):
        raise RuntimeError(
            f"Runtime directory must be an owner-only real directory: {paths.runtime_directory}"
        )


def try_acquire_database(paths: LocalPaths, *, create: bool = True) -> int | None:
    require_local_capabilities()
    if create:
        ensure_local_storage(paths)
    elif not paths.database.exists():
        return os.open(os.devnull, os.O_RDONLY)
    flags = os.O_RDWR | (os.O_CREAT if create else 0)
    fd = os.open(paths.database, flags, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    return fd


def database_is_free(paths: LocalPaths) -> bool:
    fd = try_acquire_database(paths, create=False)
    if fd is None:
        return False
    os.close(fd)
    return True


def database_identity(fd: int) -> tuple[int, int]:
    info = os.fstat(fd)
    return info.st_dev, info.st_ino


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
    paths: LocalPaths,
    *,
    generation: str,
    role: Literal["coordinator", "daemon"],
    pid: int,
    automatic_attempt_at: float,
    database_fd: int,
    server_version: str | None,
) -> RuntimeMetadata:
    marker = process_start_marker(pid)
    if marker is None:
        raise RuntimeError(f"Could not determine process identity for PID {pid}.")
    device, inode = database_identity(database_fd)
    return RuntimeMetadata(
        metadata_version=METADATA_VERSION,
        generation=generation,
        role=role,
        pid=pid,
        process_start_marker=marker,
        directory=str(paths.directory),
        database=str(paths.database),
        database_device=device,
        database_inode=inode,
        automatic_attempt_at=automatic_attempt_at,
        server_version=server_version,
    )


def write_metadata(paths: LocalPaths, metadata: RuntimeMetadata) -> None:
    ensure_runtime_directory(paths)
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
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
            return None
        raw = json.loads(paths.metadata.read_text(encoding="utf-8"))
        metadata = RuntimeMetadata(**raw)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    if (
        not isinstance(metadata.metadata_version, int)
        or isinstance(metadata.metadata_version, bool)
        or metadata.metadata_version != METADATA_VERSION
        or not isinstance(metadata.generation, str)
        or not metadata.generation
        or not isinstance(metadata.role, str)
        or metadata.role not in {"coordinator", "daemon"}
        or not isinstance(metadata.pid, int)
        or isinstance(metadata.pid, bool)
        or metadata.pid <= 0
        or not isinstance(metadata.process_start_marker, str)
        or not metadata.process_start_marker
        or not isinstance(metadata.directory, str)
        or metadata.directory != str(paths.directory)
        or not isinstance(metadata.database, str)
        or metadata.database != str(paths.database)
        or not isinstance(metadata.database_device, int)
        or isinstance(metadata.database_device, bool)
        or not isinstance(metadata.database_inode, int)
        or isinstance(metadata.database_inode, bool)
        or not isinstance(metadata.automatic_attempt_at, (int, float))
        or isinstance(metadata.automatic_attempt_at, bool)
        or not math.isfinite(metadata.automatic_attempt_at)
        or not (metadata.server_version is None or isinstance(metadata.server_version, str))
    ):
        return None
    return metadata


def metadata_matches_database(paths: LocalPaths, metadata: RuntimeMetadata) -> bool:
    try:
        info = paths.database.stat()
    except OSError:
        return False
    return (metadata.database_device, metadata.database_inode) == (info.st_dev, info.st_ino)


def metadata_owner_is_verified(paths: LocalPaths, metadata: RuntimeMetadata) -> bool:
    return (
        metadata_matches_database(paths, metadata)
        and process_start_marker(metadata.pid) == metadata.process_start_marker
    )


def throttle_remaining(metadata: RuntimeMetadata | None, *, now: float | None = None) -> float:
    if metadata is None:
        return 0.0
    current = time.time() if now is None else now
    age = current - metadata.automatic_attempt_at
    if age < 0 or age >= LAUNCH_THROTTLE_SECONDS:
        return 0.0
    return LAUNCH_THROTTLE_SECONDS - age


def startup_age(metadata: RuntimeMetadata | None, *, now: float | None = None) -> float | None:
    if metadata is None:
        return None
    current = time.time() if now is None else now
    age = current - metadata.automatic_attempt_at
    return age if 0 <= age < STARTUP_WAIT_SECONDS else None


def socket_health(paths: LocalPaths, *, timeout: float = 0.2) -> bool:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(timeout)
            connection.connect(str(paths.socket))
            connection.sendall(
                b"GET /health HTTP/1.1\r\nHost: labtasker\r\nConnection: close\r\n\r\n"
            )
            response = bytearray()
            while len(response) <= 65536:
                chunk = connection.recv(8192)
                if not chunk:
                    break
                response.extend(chunk)
    except OSError:
        return False
    head, separator, body = bytes(response).partition(b"\r\n\r\n")
    if not separator or not head.startswith(b"HTTP/1.1 200"):
        return False
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    normalized = cast(dict[str, object], payload)
    return normalized == {"status": "ok", "api_version": "2", "database": "ok"}


def wait_for_health(paths: LocalPaths, *, deadline: float) -> bool:
    while time.monotonic() < deadline:
        if socket_health(paths):
            return True
        time.sleep(HEALTH_POLL_SECONDS)
    return socket_health(paths)


def ensure_local_daemon(
    directory: Path,
    *,
    bypass_throttle: bool,
    server_version: str,
    emit: Callable[[str], None],
) -> tuple[bool, RuntimeMetadata | None]:
    """Ensure one healthy local daemon and return whether this call started it."""
    require_local_capabilities()
    paths = local_paths(directory)
    ensure_runtime_directory(paths)
    if socket_health(paths):
        return False, read_metadata(paths)

    database_fd = try_acquire_database(paths)
    if database_fd is None:
        publication_deadline = time.monotonic() + STARTUP_PUBLICATION_SECONDS
        while True:
            metadata = read_metadata(paths)
            age = startup_age(metadata)
            if (
                metadata is not None
                and metadata_owner_is_verified(paths, metadata)
                and age is not None
            ):
                emit(f"waiting for local daemon pid={metadata.pid} socket={paths.socket}")
                deadline = time.monotonic() + max(0.0, STARTUP_WAIT_SECONDS - age)
                if wait_for_health(paths, deadline=deadline):
                    return False, read_metadata(paths) or metadata
                break
            if socket_health(paths):
                return False, read_metadata(paths)
            if time.monotonic() >= publication_deadline:
                break
            time.sleep(HEALTH_POLL_SECONDS)
        raise RuntimeError(f"Database is owned but local socket is unavailable: {paths.database}")

    try:
        if socket_health(paths):
            return False, read_metadata(paths)
        previous = read_metadata(paths)
        remaining = 0.0 if bypass_throttle else throttle_remaining(previous)
        if remaining > 0:
            raise RuntimeError(
                f"Automatic launch is throttled for {remaining:.1f}s; log={paths.log}"
            )
        remove_stale_artifacts(paths)
        process = _spawn_local_daemon(
            paths,
            database_fd=database_fd,
            server_version=server_version,
        )
    finally:
        os.close(database_fd)

    emit(f"created local daemon pid={process.pid} database={paths.database} socket={paths.socket}")
    if not wait_for_health(paths, deadline=time.monotonic() + STARTUP_WAIT_SECONDS):
        raise RuntimeError(f"Daemon did not become healthy within 30 seconds; log={paths.log}")
    return True, read_metadata(paths)


def _spawn_local_daemon(
    paths: LocalPaths,
    *,
    database_fd: int,
    server_version: str,
) -> subprocess.Popen[bytes]:
    generation = secrets.token_urlsafe(18)
    attempt_at = time.time()
    write_metadata(
        paths,
        make_metadata(
            paths,
            generation=generation,
            role="coordinator",
            pid=os.getpid(),
            automatic_attempt_at=attempt_at,
            database_fd=database_fd,
            server_version=server_version,
        ),
    )
    paths.log.parent.mkdir(parents=True, exist_ok=True)
    with paths.log.open("ab", buffering=0) as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "labtasker_server",
                "_daemon",
                "--directory",
                str(paths.directory),
                "--database-fd",
                str(database_fd),
                "--generation",
                generation,
                "--automatic-attempt-at",
                str(attempt_at),
            ],
            cwd=paths.directory,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            pass_fds=(database_fd,),
        )
    write_metadata(
        paths,
        make_metadata(
            paths,
            generation=generation,
            role="daemon",
            pid=process.pid,
            automatic_attempt_at=attempt_at,
            database_fd=database_fd,
            server_version=server_version,
        ),
    )
    return process


def remove_stale_artifacts(paths: LocalPaths) -> None:
    for path, expected in ((paths.socket, stat.S_ISSOCK), (paths.metadata, stat.S_ISREG)):
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if info.st_uid != os.geteuid() or not expected(info.st_mode):
            raise RuntimeError(f"Refusing to remove unverified runtime artifact: {path}")
        path.unlink()


def remove_generation_artifacts(paths: LocalPaths, generation: str) -> None:
    metadata = read_metadata(paths)
    if metadata is None or metadata.generation != generation:
        return
    try:
        info = paths.socket.lstat()
    except FileNotFoundError:
        pass
    else:
        if info.st_uid == os.geteuid() and stat.S_ISSOCK(info.st_mode):
            paths.socket.unlink()
    with suppress(FileNotFoundError):
        paths.metadata.unlink()


def remove_generation_socket(paths: LocalPaths, generation: str) -> None:
    metadata = read_metadata(paths)
    if metadata is None or metadata.generation != generation:
        return
    try:
        info = paths.socket.lstat()
    except FileNotFoundError:
        return
    if info.st_uid == os.geteuid() and stat.S_ISSOCK(info.st_mode):
        paths.socket.unlink()


def has_runtime_artifacts(paths: LocalPaths) -> bool:
    return paths.socket.exists() or paths.metadata.exists()
