"""Host-local ownership locks, independent of SQLite transaction locks."""

from __future__ import annotations

import hashlib
import os
import socket
import stat
import struct
import sys
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

try:
    import fcntl
except ImportError:  # pragma: no cover - validated before supported startup paths
    fcntl = None  # type: ignore[assignment]

LockKind = Literal["root", "socket", "db"]


@dataclass(slots=True)
class OwnershipLock:
    path: Path
    fd: int

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1


def runtime_directory() -> Path:
    effective_uid = os.geteuid() if hasattr(os, "geteuid") else os.getuid()
    return (Path("/tmp") / f"labtasker-{effective_uid}").resolve(strict=False)


def ensure_runtime_directory() -> Path:
    require_lock_capability()
    directory = runtime_directory()
    with suppress(FileExistsError):
        directory.mkdir(mode=0o700)
    info = directory.lstat()
    effective_uid = os.geteuid() if hasattr(os, "geteuid") else os.getuid()
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != effective_uid
        or stat.S_IMODE(info.st_mode) & 0o077
    ):
        raise RuntimeError(f"Runtime directory must be owner-only: {directory}")
    return directory


def canonical_path(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def sidecar_path(kind: LockKind, target: Path) -> Path:
    canonical = canonical_path(target)
    digest = hashlib.sha256(os.fsencode(canonical)).hexdigest()
    return runtime_directory() / f"{kind}-{digest}.lock"


def acquire_sidecar_lock(kind: LockKind, target: Path) -> OwnershipLock:
    directory = ensure_runtime_directory()
    path = sidecar_path(kind, target)
    if path.parent != directory:
        raise AssertionError("Ownership sidecar escaped the runtime directory.")
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        info = os.fstat(fd)
        effective_uid = os.geteuid() if hasattr(os, "geteuid") else os.getuid()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != effective_uid:
            raise RuntimeError(f"Ownership sidecar must be an owner-owned file: {path}")
        assert fcntl is not None
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BaseException:
        os.close(fd)
        raise
    os.set_inheritable(fd, False)
    return OwnershipLock(path, fd)


def sidecar_is_locked(kind: LockKind, target: Path) -> bool:
    """Inspect an existing sidecar without creating runtime state."""
    require_lock_capability()
    path = sidecar_path(kind, target)
    try:
        fd = os.open(path, os.O_RDWR)
    except FileNotFoundError:
        return False
    try:
        assert fcntl is not None
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        return False
    finally:
        os.close(fd)


def require_lock_capability() -> None:
    if os.name != "posix" or fcntl is None:
        raise RuntimeError("Server ownership requires POSIX advisory file locking.")


def require_socket_capability() -> None:
    require_lock_capability()
    if not hasattr(socket, "AF_UNIX"):
        raise RuntimeError("Unix-socket Server operation is unsupported on this platform.")


def lock_database(fd: int) -> None:
    """Acquire the transitional v2.5 database-inode lock."""
    require_lock_capability()
    assert fcntl is not None
    if sys.platform == "darwin":
        command = getattr(fcntl, "F_OFD_SETLK", 90)
        request = struct.pack("@qqihh", 0, 1, 0, fcntl.F_WRLCK, os.SEEK_SET)
        fcntl.fcntl(fd, command, request)
    else:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
