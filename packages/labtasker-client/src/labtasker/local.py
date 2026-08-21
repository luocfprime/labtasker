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
    directory: Path
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
            "Local mode requires POSIX Unix-domain sockets; configure a URL.",
            {"source": "default", "field": "url"},
        )


def local_paths(directory: Path | None = None) -> LocalPaths:
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
    )


def ensure_local_server(paths: LocalPaths, *, emit: Callable[[str], None]) -> LocalEnsureResult:
    require_local_capabilities()
    if socket_health(paths):
        return LocalEnsureResult(started=False, pid=None, server_version=None)
    if importlib.util.find_spec("labtasker_server") is None:
        raise ConfigError(
            "invalid_config",
            "Local mode requires labtasker-server; install labtasker or configure a URL.",
            {"source": "default", "field": "url"},
        )

    emit(f"requesting local daemon ensure directory={paths.directory} socket={paths.socket}")
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "labtasker_server",
                "_ensure-daemon",
                "--directory",
                str(paths.directory),
            ],
            cwd=paths.directory,
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
            retry_after_seconds=_optional_number(payload, "retry_after_seconds"),
        )
    if not socket_health(paths):
        raise _local_transport_error(
            paths,
            state="unhealthy",
            message="The local Server coordinator returned before its socket was healthy.",
        )

    pid = payload.get("pid")
    version = payload.get("version")
    started = payload.get("started")
    return LocalEnsureResult(
        started=started is True,
        pid=pid if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0 else None,
        server_version=version if isinstance(version, str) else None,
    )


def socket_transport(paths: LocalPaths) -> httpx.HTTPTransport:
    return httpx.HTTPTransport(uds=str(paths.socket))


def socket_health(paths: LocalPaths, *, timeout: float = 0.2) -> bool:
    try:
        with httpx.Client(
            transport=socket_transport(paths),
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
        payload = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    return {str(key): value for key, value in payload.items()}


def _optional_number(payload: dict[str, object] | None, field: str) -> float | None:
    if payload is None:
        return None
    value = payload.get(field)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _local_transport_error(
    paths: LocalPaths,
    *,
    state: str,
    message: str,
    retry_after_seconds: float | None = None,
) -> TransportError:
    details: dict[str, object] = {
        "state": state,
        "directory": str(paths.directory),
        "database": str(paths.database),
        "socket": str(paths.socket),
        "log": str(paths.log),
    }
    if retry_after_seconds is not None:
        details["retry_after_seconds"] = retry_after_seconds
    return TransportError(message, details)
