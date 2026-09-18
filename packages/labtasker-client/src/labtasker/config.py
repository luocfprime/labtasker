from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypedDict
from urllib.parse import urlsplit, urlunsplit

import httpx

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from labtasker.errors import ConfigError
from labtasker.local import LocalPaths, local_paths, require_local_capabilities
from labtasker.validation import RequestValidationError, invalid_config, validate_identifier

DEFAULT_QUEUE = "default"
CONFIG_FIELDS = {"url", "socket", "queue", "token"}


class EndpointRecord(TypedDict):
    connection: Literal["http", "socket"]
    managed_local: bool
    url: str | None
    socket: str | None
    labtasker_root: str | None
    database: str | None


@dataclass(frozen=True, slots=True)
class ResolvedConfig:
    url: str | None
    socket: Path | None
    managed_local: bool
    labtasker_root: Path
    queue: str
    token: str | None
    auto_start_local_server: bool
    local: LocalPaths | None

    def public_dict(self) -> dict[str, object]:
        return {
            "connection": "http" if self.url is not None else "socket",
            "managed_local": self.managed_local,
            "labtasker_root": str(self.labtasker_root),
            "database": str(self.local.database) if self.local is not None else None,
            "socket": str(self.socket) if self.socket is not None else None,
            "url": self.url,
            "queue": self.queue,
            "token_configured": self.url is not None and self.token is not None,
            "auto_start_local_server": self.auto_start_local_server,
        }

    def endpoint_dict(self) -> EndpointRecord:
        return {
            "connection": "http" if self.url is not None else "socket",
            "managed_local": self.managed_local,
            "url": self.url,
            "socket": str(self.socket) if self.socket is not None else None,
            "labtasker_root": str(self.labtasker_root) if self.managed_local else None,
            "database": str(self.local.database) if self.local is not None else None,
        }


def resolve_config(
    *,
    url: str | None = None,
    socket: str | Path | None = None,
    labtasker_root: str | Path | None = None,
    auto_start_local_server: bool = False,
    token: str | None = None,
    queue: str | None = None,
    cwd: Path | None = None,
    environment: dict[str, str] | None = None,
) -> ResolvedConfig:
    working_directory = (Path.cwd() if cwd is None else cwd).resolve()
    environment_values = os.environ if environment is None else environment
    root = _resolve_root(labtasker_root, working_directory, environment_values)
    file_values = _read_config_file(root)

    endpoint_url, endpoint_socket, managed_local = _resolve_endpoint(
        explicit_url=url,
        explicit_socket=socket,
        environment=environment_values,
        file_values=file_values,
        working_directory=working_directory,
    )
    effective_queue, queue_source = _first_value(
        (queue, "constructor"),
        (environment_values.get("LABTASKER_QUEUE"), "environment"),
        (file_values.get("queue"), str(root / "config.toml")),
        (DEFAULT_QUEUE, "default"),
    )
    effective_token, token_source = _first_value(
        (token, "constructor"),
        (environment_values.get("LABTASKER_TOKEN"), "environment"),
        (file_values.get("token"), str(root / "config.toml")),
        (None, "default"),
    )
    normalized_queue = _validate_queue(effective_queue, source=queue_source)
    normalized_token = _validate_token(effective_token, source=token_source)
    if not isinstance(auto_start_local_server, bool):
        raise invalid_config(
            "auto_start_local_server must be a Boolean.",
            source="constructor",
            field="auto_start_local_server",
        )
    if auto_start_local_server and not managed_local:
        raise invalid_config(
            "auto_start_local_server is valid only for the managed-local endpoint.",
            source="constructor",
            field="auto_start_local_server",
        )

    local: LocalPaths | None = None
    if managed_local:
        require_local_capabilities()
        local = local_paths(root)
        endpoint_socket = local.socket
    return ResolvedConfig(
        url=endpoint_url,
        socket=endpoint_socket,
        managed_local=managed_local,
        labtasker_root=root,
        queue=normalized_queue,
        token=normalized_token if endpoint_url is not None else None,
        auto_start_local_server=auto_start_local_server,
        local=local,
    )


def _resolve_root(
    explicit: str | Path | None,
    working_directory: Path,
    environment: Mapping[str, str],
) -> Path:
    environment_root = environment.get("LABTASKER_ROOT")
    selected, source = _first_value(
        (explicit, "constructor"),
        (environment_root, "environment"),
        (working_directory / ".labtasker", "default"),
    )
    if isinstance(selected, str) and not selected:
        raise invalid_config(
            "Labtasker root must be a non-empty path.", source=source, field="labtasker_root"
        )
    if not isinstance(selected, (str, Path)):
        raise invalid_config(
            "Labtasker root must be a filesystem path.",
            source=source,
            field="labtasker_root",
        )
    return Path(selected).expanduser().resolve()


def _resolve_endpoint(
    *,
    explicit_url: str | None,
    explicit_socket: str | Path | None,
    environment: Mapping[str, str],
    file_values: dict[str, str],
    working_directory: Path,
) -> tuple[str | None, Path | None, bool]:
    layers: list[tuple[object | None, object | None, str]] = [
        (explicit_url, explicit_socket, "constructor"),
        (
            environment.get("LABTASKER_URL"),
            environment.get("LABTASKER_SOCKET"),
            "environment",
        ),
        (file_values.get("url"), file_values.get("socket"), "config"),
    ]
    for url, socket_value, source in layers:
        if url is None and socket_value is None:
            continue
        if url is not None and socket_value is not None:
            raise invalid_config(
                "URL and socket are mutually exclusive in the selected endpoint layer.",
                source=source,
                field="endpoint",
            )
        if url is not None:
            return _validate_url(url, source=source), None, False
        return None, _validate_socket(socket_value, source, working_directory), False
    return None, None, True


def _read_config_file(root: Path) -> dict[str, str]:
    config_path = root / "config.toml"
    legacy_path = root / "client.toml"
    if not config_path.exists():
        if legacy_path.exists():
            raise ConfigError(
                "legacy_config_found",
                "A v1 client.toml was found; create the v2 flat config.toml manually.",
                {"source": str(legacy_path)},
            )
        return {}
    try:
        raw = config_path.read_bytes()
        parsed = tomllib.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise invalid_config(
            "The client configuration file could not be read or parsed.",
            source=str(config_path),
        ) from error
    if set(parsed) - CONFIG_FIELDS:
        raise invalid_config(
            f"Unknown configuration keys: {sorted(set(parsed) - CONFIG_FIELDS)!r}.",
            source=str(config_path),
        )
    values: dict[str, str] = {}
    for field, value in parsed.items():
        if not isinstance(value, str) or not value:
            raise invalid_config(
                f"Configuration field '{field}' must be a non-empty string.",
                source=str(config_path),
                field=field,
            )
        values[field] = value
    return values


def _validate_url(value: object, *, source: str) -> str:
    if not isinstance(value, str) or not value:
        raise invalid_config("URL must be a non-empty string.", source=source, field="url")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise invalid_config("URL is invalid.", source=source, field="url") from error
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise invalid_config(
            "URL must be an absolute HTTP(S) base URL without userinfo, query or fragment.",
            source=source,
            field="url",
        )
    normalized = urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))
    try:
        httpx.URL(normalized)
    except (httpx.InvalidURL, UnicodeError) as error:
        raise invalid_config("URL is invalid.", source=source, field="url") from error
    return normalized


def _validate_socket(value: object, source: str, working_directory: Path) -> Path:
    if not isinstance(value, (str, Path)) or not str(value):
        raise invalid_config(
            "Socket must be a non-empty filesystem path.", source=source, field="socket"
        )
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = working_directory / path
    return path.resolve()


def _validate_queue(value: object | None, *, source: str) -> str:
    try:
        return validate_identifier(value, field="queue")
    except RequestValidationError as error:
        raise invalid_config(str(error), source=source, field="queue") from error


def _validate_token(value: object | None, *, source: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise invalid_config("Token must be a non-empty string.", source=source, field="token")
    if any(not 0x21 <= ord(character) <= 0x7E for character in value):
        raise invalid_config(
            "Token must contain only visible ASCII characters.", source=source, field="token"
        )
    return value


def _first_value(*candidates: tuple[object | None, str]) -> tuple[object | None, str]:
    return next(
        ((candidate, source) for candidate, source in candidates if candidate is not None),
        (None, "default"),
    )
