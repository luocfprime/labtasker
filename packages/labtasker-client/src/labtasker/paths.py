"""Shared object-only dot paths used by Python and command Workers."""

from __future__ import annotations

import re
from typing import Any

_PATH_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")


class PathError(ValueError):
    pass


def parse_path(value: str) -> tuple[str, ...]:
    if not isinstance(value, str) or not _PATH_RE.fullmatch(value):
        raise PathError(
            "path must contain dot-separated ASCII identifiers matching [A-Za-z_][A-Za-z0-9_]*"
        )
    return tuple(value.split("."))


def select_path(value: object, path: tuple[str, ...]) -> Any:
    current = value
    traversed: list[str] = []
    for segment in path:
        traversed.append(segment)
        if not isinstance(current, dict):
            parent = ".".join(traversed[:-1]) or "<root>"
            raise PathError(f"path {'.'.join(path)!r} cannot traverse non-object {parent!r}")
        if segment not in current:
            raise PathError(f"path {'.'.join(path)!r} is missing key {segment!r}")
        current = current[segment]
    return current
