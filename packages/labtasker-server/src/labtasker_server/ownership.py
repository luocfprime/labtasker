"""Database-inode ownership, independent of SQLite transaction locks."""

from __future__ import annotations

import os
import struct
import sys

try:
    import fcntl
except ImportError:  # pragma: no cover - explicit HTTP remains best effort off POSIX
    fcntl = None  # type: ignore[assignment]


def lock_database(fd: int) -> None:
    if fcntl is None:
        return
    if sys.platform == "darwin":
        # Darwin flock overlaps SQLite's POSIX locks. An open-file-description
        # lock on byte zero survives dup/fork/exec without covering SQLite's
        # lock bytes at 0x40000000. Unlike process-owned lockf, closing another
        # SQLite connection cannot release ownership. Darwin struct flock is
        # off_t start, off_t len, pid_t pid, short type, short whence.
        # F_OFD_SETLK is 90 in Darwin's ABI; some Python builds omit its name.
        command = getattr(fcntl, "F_OFD_SETLK", 90)
        request = struct.pack("@qqihh", 0, 1, 0, fcntl.F_WRLCK, os.SEEK_SET)
        fcntl.fcntl(fd, command, request)
    else:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
