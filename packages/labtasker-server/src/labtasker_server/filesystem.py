from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

FilesystemClass = Literal["local", "shared", "unknown"]
DatabaseFilesystem = Literal["auto", "local", "shared"]
EffectiveDatabaseFilesystem = Literal["local", "shared"]

# Keep these sets deliberately conservative. Unknown filesystems use the shared
# strategy, so a missing local entry costs performance rather than correctness.
KNOWN_LOCAL_FILESYSTEMS = frozenset(
    {
        "apfs",
        "btrfs",
        "ext2",
        "ext3",
        "ext4",
        "f2fs",
        "hfs",
        "hfsplus",
        "jfs",
        "overlay",
        "tmpfs",
        "ufs",
        "xfs",
        "zfs",
    }
)
KNOWN_SHARED_FILESYSTEMS = frozenset(
    {
        "beegfs",
        "ceph",
        "cifs",
        "fuse.sshfs",
        "gpfs",
        "lustre",
        "nfs",
        "nfs4",
        "smbfs",
        "wekafs",
    }
)


@dataclass(frozen=True, slots=True)
class FilesystemDetection:
    filesystem_type: str | None
    classification: FilesystemClass
    inspected_path: Path


@dataclass(frozen=True, slots=True)
class ResolvedDatabaseFilesystem:
    requested: DatabaseFilesystem
    effective: EffectiveDatabaseFilesystem
    detection: FilesystemDetection | None

    @property
    def warning(self) -> str | None:
        if self.requested != "auto" or self.detection is None:
            return None
        if self.detection.classification != "unknown":
            return None
        kind = self.detection.filesystem_type or "unavailable"
        return (
            "database filesystem type "
            f"{kind!r} is unknown at {self.detection.inspected_path}; "
            "using the conservative shared strategy"
        )


def resolve_database_filesystem(
    path: Path,
    requested: DatabaseFilesystem,
) -> ResolvedDatabaseFilesystem:
    if requested in {"local", "shared"}:
        return ResolvedDatabaseFilesystem(requested, requested, None)
    detection = detect_filesystem(path)
    effective: EffectiveDatabaseFilesystem = (
        "local" if detection.classification == "local" else "shared"
    )
    return ResolvedDatabaseFilesystem(requested, effective, detection)


def detect_filesystem(path: Path) -> FilesystemDetection:
    inspected = nearest_existing_path(path)
    filesystem_type = _filesystem_type(inspected)
    normalized = filesystem_type.lower() if filesystem_type is not None else None
    if normalized in KNOWN_LOCAL_FILESYSTEMS:
        classification: FilesystemClass = "local"
    elif normalized in KNOWN_SHARED_FILESYSTEMS:
        classification = "shared"
    else:
        classification = "unknown"
    return FilesystemDetection(normalized, classification, inspected)


def nearest_existing_path(path: Path) -> Path:
    candidate = path.expanduser().absolute()
    while not candidate.exists():
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent
    return candidate.resolve()


def _filesystem_type(path: Path) -> str | None:
    if sys.platform.startswith("linux"):
        return _linux_mount_type(path)
    if sys.platform == "darwin":
        return _darwin_mount_type(path)
    return None


def _linux_mount_type(path: Path) -> str | None:
    try:
        lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    target = os.fsencode(path)
    best_length = -1
    best_type: str | None = None
    for line in lines:
        fields = line.split()
        try:
            separator = fields.index("-")
            mount_point = os.fsencode(_unescape_mountinfo(fields[4]))
            filesystem_type = fields[separator + 1]
        except (IndexError, ValueError):
            continue
        if (target == mount_point or target.startswith(mount_point.rstrip(b"/") + b"/")) and len(
            mount_point
        ) > best_length:
            best_length = len(mount_point)
            best_type = filesystem_type
    return best_type


def _unescape_mountinfo(value: str) -> str:
    for encoded, decoded in (("\\040", " "), ("\\011", "\t"), ("\\012", "\n"), ("\\134", "\\")):
        value = value.replace(encoded, decoded)
    return value


def _darwin_mount_type(path: Path) -> str | None:
    try:
        result = subprocess.run(
            ["mount"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    target = str(path)
    best_length = -1
    best_type: str | None = None
    for line in result.stdout.splitlines():
        try:
            _, mounted = line.split(" on ", 1)
            mount_point, options = mounted.rsplit(" (", 1)
            filesystem_type = options.rstrip(")").split(",", 1)[0]
        except ValueError:
            continue
        if (target == mount_point or target.startswith(mount_point.rstrip("/") + "/")) and len(
            mount_point
        ) > best_length:
            best_length = len(mount_point)
            best_type = filesystem_type
    return best_type
