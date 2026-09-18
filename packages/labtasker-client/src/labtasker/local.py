from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import socket
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from labtasker.errors import ConfigError, TransportError

COORDINATOR_TIMEOUT_SECONDS = 35.0


@dataclass(frozen=True, slots=True)
class LocalPaths:
    labtasker_root: Path
    database: Path
    log: Path
    runtime_directory: Path
    socket: Path


@dataclass(frozen=True, slots=True)
class LocalEnsureResult:
    started: bool
    pid: int | None
    server_version: str | None


def require_local_capabilities() -> None:
    if os.name != "posix" or not hasattr(socket, "AF_UNIX"):
        raise ConfigError(
            "invalid_config",
            "Managed local mode requires POSIX Unix-domain sockets; configure a URL.",
            {"source": "managed_local", "field": "socket"},
        )


def local_paths(labtasker_root: Path) -> LocalPaths:
    require_local_capabilities()
    root = labtasker_root.expanduser().resolve()
    digest = hashlib.sha256(os.fsencode(root)).hexdigest()
    effective_uid = os.geteuid() if hasattr(os, "geteuid") else os.getuid()
    runtime_directory = (Path("/tmp") / f"labtasker-{effective_uid}").resolve()
    return LocalPaths(
        labtasker_root=root,
        database=root / "server.db",
        log=root / "server.log",
        runtime_directory=runtime_directory,
        socket=runtime_directory / f"root-{digest}.sock",
    )


def ensure_local_server(paths: LocalPaths, *, emit: Callable[[str], None]) -> LocalEnsureResult:
    require_local_capabilities()
    if socket_health(paths.socket):
        return LocalEnsureResult(started=False, pid=None, server_version=None)
    if importlib.util.find_spec("labtasker_server") is None:
        raise ConfigError(
            "invalid_config",
            "Automatic local startup requires labtasker-server; install labtasker or "
            "configure an existing URL/socket.",
            {"source": "managed_local", "field": "auto_start_local_server"},
        )

    emit(
        f"requesting local daemon ensure labtasker_root={paths.labtasker_root} "
        f"socket={paths.socket}"
    )
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "labtasker_server",
                "_ensure-daemon",
                "--labtasker-root",
                str(paths.labtasker_root),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            check=False,
            timeout=COORDINATOR_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise _local_transport_error(
            paths,
            state="starting",
            message="The local Server coordinator did not finish within 35 seconds.",
        ) from error
    except OSError as error:
        raise _local_transport_error(
            paths,
            state="stopped",
            message="The local Server coordinator could not be started.",
        ) from error

    payload = _parse_coordinator_result(result.stdout)
    if result.returncode != 0 or payload is None or payload.get("ok") is not True:
        state = payload.get("state") if payload is not None else None
        message = payload.get("message") if payload is not None else None
        raise _local_transport_error(
            paths,
            state=state if isinstance(state, str) else "unhealthy",
            message=(
                message
                if isinstance(message, str)
                else "The local Server coordinator failed without a valid result."
            ),
        )
    if not socket_health(paths.socket):
        raise _local_transport_error(
            paths,
            state="unhealthy",
            message="The local Server coordinator returned before its socket was healthy.",
        )

    pid = payload.get("pid")
    version = payload.get("version")
    return LocalEnsureResult(
        started=payload.get("started") is True,
        pid=pid if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0 else None,
        server_version=version if isinstance(version, str) else None,
    )


def socket_transport(path: Path) -> httpx.HTTPTransport:
    return httpx.HTTPTransport(uds=str(path))


def socket_health(path: Path, *, timeout: float = 0.2) -> bool:
    try:
        with httpx.Client(
            transport=socket_transport(path),
            base_url="http://labtasker",
            timeout=timeout,
        ) as client:
            response = client.get("/health")
        return response.status_code == 200 and response.json() == {
            "status": "ok",
            "api_version": "2",
            "database": "ok",
        }
    except (httpx.HTTPError, ValueError):
        return False


def _parse_coordinator_result(output: str) -> dict[str, object] | None:
    try:
        payload: object = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    return {str(key): value for key, value in payload.items()}


def _local_transport_error(
    paths: LocalPaths,
    *,
    state: str,
    message: str,
) -> TransportError:
    return TransportError(
        message,
        {
            "state": state,
            "labtasker_root": str(paths.labtasker_root),
            "database": str(paths.database),
            "socket": str(paths.socket),
            "log": str(paths.log),
        },
    )
